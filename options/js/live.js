/* Page 2: live option chain (Sensibull via local bridge, or simulated) + strategy builder */
(function () {
  'use strict';
  const { bs, fmt, esc, store, css, payoffChart, toast } = OD;
  const { UNDERLYINGS, BridgeFeed, SimFeed, chainStats, yearsToExpiry, ivDec } = Feeds;
  const $ = (id) => document.getElementById(id);

  // Opened from the bridge itself? Then the bridge is this origin.
  const servedByBridge = /^(127\.0\.0\.1|localhost)$/.test(location.hostname) && location.port;
  const defaultBridge = servedByBridge ? location.origin : 'http://127.0.0.1:8765';

  const S = {
    source: store.get('live.source', 'sensibull'),
    feed: null, sim: new SimFeed(),
    underlying: store.get('live.underlying', 'NIFTY'),
    expiry: null, chain: null, timer: null, busy: false, errors: 0,
    legs: store.get('live.legs', []),
    scrolledFor: null, loginPoll: null,
  };

  // ------------------------------------------------------------ setup
  $('underlying').innerHTML = Object.keys(UNDERLYINGS).map((u) => `<option ${u === S.underlying ? 'selected' : ''}>${u}</option>`).join('');
  $('bridge-url').value = store.get('live.bridge', defaultBridge);
  $('login-id').value = store.get('live.loginId', '');
  $('remember-id').checked = !!store.get('live.loginId');
  $('lot').value = store.get('live.lot.' + S.underlying, UNDERLYINGS[S.underlying].lot);

  function setPill(kind, text) {
    const p = $('feed-pill'); p.className = 'pill ' + kind; $('feed-pill-text').textContent = text;
  }
  function msg(html, kind = '') { $('conn-msg').innerHTML = kind ? `<span class="${kind}">${html}</span>` : html; }

  function setSource(src) {
    S.source = src; store.set('live.source', src);
    document.querySelectorAll('#source-seg button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.v === src));
    $('sensibull-panel').classList.toggle('hidden', src !== 'sensibull');
    $('sim-panel').classList.toggle('hidden', src !== 'sim');
    if (src === 'sim') { S.feed = S.sim; setPill('warn live', 'Simulated data'); startPolling(true); }
    else { S.feed = null; stopPolling(); S.chain = null; renderAll(); setPill('', 'Not connected'); connect(true); }
  }
  $('source-seg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setSource(b.dataset.v); });

  // ------------------------------------------------------------ bridge connection
  function bridge() { return new BridgeFeed($('bridge-url').value.trim() || defaultBridge); }
  function remember() {
    if ($('remember-id').checked) { store.set('live.loginId', $('login-id').value.trim()); store.set('live.bridge', $('bridge-url').value.trim()); }
    else { store.del('live.loginId'); store.del('live.bridge'); }
  }
  $('remember-id').addEventListener('change', remember);

  async function connect(quiet = false) {
    const b = bridge();
    if (!quiet) msg('Contacting bridge…');
    try {
      const st = await b.status();
      S.feed = b; remember();
      showLogin(st);
      msg(st.logged_in ? `Connected. Logged in to Sensibull${st.login_id ? ' as ' + esc(st.login_id) : ''}.` : 'Connected to the bridge. Streaming public Sensibull data. Log in to attach your session.', 'pos');
      startPolling(true);
      return true;
    } catch (e) {
      S.feed = null;
      setPill('bad', 'Bridge offline');
      msg(`${esc(e.message)} Start it with <code>python3 options/bridge/sensibull_bridge.py</code>, or switch to <b>Simulated</b> to explore the tools.`, quiet ? 'muted' : 'neg');
      return false;
    }
  }
  function showLogin(st) {
    $('logout-btn').classList.toggle('hidden', !st.logged_in);
    $('login-btn').textContent = st.logged_in ? 'Log in again' : 'Log in to Sensibull';
  }
  $('connect-btn').addEventListener('click', () => connect(false));

  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const loginId = $('login-id').value.trim(), secret = $('login-secret').value, token = $('session-token').value.trim();
    if (!loginId && !token) { msg('Enter your Sensibull login ID, or paste a session token under Advanced.', 'neg'); return; }
    if (!S.feed || S.feed.name !== 'sensibull') { if (!(await connect(false))) return; }
    remember();
    $('login-btn').disabled = true;
    msg(token ? 'Setting session token…' : 'Opening the Sensibull login window on your computer…');
    try {
      const r = await S.feed.login({ login_id: loginId, secret, session_token: token });
      $('login-secret').value = ''; $('session-token').value = '';
      if (r.pending) {
        msg(esc(r.message || 'Finish logging in (OTP / broker 2FA) in the browser window the bridge opened. This page will update automatically.'));
        pollLogin();
      } else { msg(esc(r.message || 'Logged in.'), 'pos'); showLogin({ logged_in: true }); }
    } catch (err) { msg(esc(err.message), 'neg'); }
    finally { $('login-btn').disabled = false; }
  });
  function pollLogin() {
    clearInterval(S.loginPoll);
    const started = Date.now();
    S.loginPoll = setInterval(async () => {
      try {
        const st = await S.feed.status();
        if (st.logged_in) { clearInterval(S.loginPoll); showLogin(st); msg(`Logged in to Sensibull${st.login_id ? ' as ' + esc(st.login_id) : ''}. Your session is held in the bridge's memory only.`, 'pos'); }
        else if (st.login_error) { clearInterval(S.loginPoll); msg(esc(st.login_error), 'neg'); }
        else if (st.login_state) msg(esc(st.login_state));
      } catch { /* keep trying */ }
      if (Date.now() - started > 6 * 60e3) { clearInterval(S.loginPoll); msg('Login timed out. Try again.', 'neg'); }
    }, 2000);
  }
  $('logout-btn').addEventListener('click', async () => {
    try { await S.feed.logout(); showLogin({ logged_in: false }); msg('Logged out. Session cleared from the bridge.'); } catch (e) { msg(esc(e.message), 'neg'); }
  });

  // ------------------------------------------------------------ polling
  function stopPolling() { clearTimeout(S.timer); S.timer = null; }
  function startPolling(now) {
    stopPolling();
    if (now) tick();
  }
  async function tick() {
    stopPolling();
    const feed = S.feed; if (!feed) return;
    if (!S.busy) {
      S.busy = true;
      try {
        const token = null;
        const chain = await feed.chain(S.underlying, token);
        if (feed !== S.feed) return;
        S.chain = chain; S.errors = 0;
        if (chain.lotSize && !store.get('live.lot.' + S.underlying)) $('lot').value = chain.lotSize;
        setPill(chain.source === 'sim' ? 'warn live' : 'ok live', chain.source === 'sim' ? 'Simulated data' : 'Live · Sensibull');
        renderAll();
      } catch (e) {
        S.errors++;
        setPill('bad', 'Feed error');
        if (S.source === 'sensibull') msg(esc(e.message), 'neg');
      } finally { S.busy = false; }
    }
    const ms = +$('poll').value;
    if (ms > 0) S.timer = setTimeout(tick, S.errors ? Math.min(ms * 2 ** S.errors, 60000) : ms);
  }
  $('poll').addEventListener('change', () => startPolling(true));
  $('underlying').addEventListener('change', () => {
    S.underlying = $('underlying').value; store.set('live.underlying', S.underlying);
    S.expiry = null; S.scrolledFor = null;
    $('lot').value = store.get('live.lot.' + S.underlying, UNDERLYINGS[S.underlying]?.lot || 1);
    startPolling(true);
  });
  $('expiry').addEventListener('change', () => { S.expiry = $('expiry').value; S.scrolledFor = null; renderAll(); });
  $('range').addEventListener('change', renderAll);
  $('lot').addEventListener('change', () => { store.set('live.lot.' + S.underlying, +$('lot').value); renderBuilder(); });

  // ------------------------------------------------------------ render
  const lot = () => Math.max(1, +$('lot').value || 1);
  function currentExp() {
    if (!S.chain || !S.chain.expiries.length) return null;
    return S.chain.expiries.find((e) => e.expiry === S.expiry) || S.chain.expiries[0];
  }

  function renderAll() {
    const c = S.chain;
    if (!c) {
      $('tiles').innerHTML = '<p class="muted small">Waiting for data…</p>';
      document.querySelector('#chain tbody').innerHTML = '';
      $('updated').textContent = '';
      renderBuilder();
      return;
    }
    const opts = c.expiries.map((e) => e.expiry);
    if (!opts.includes(S.expiry)) S.expiry = opts[0];
    const cur = [...$('expiry').options].map((o) => o.value).join();
    if (cur !== opts.join()) $('expiry').innerHTML = opts.map((x) => `<option value="${x}">${fmtDate(x)}</option>`).join('');
    $('expiry').value = S.expiry;
    $('updated').textContent = `${c.source === 'sim' ? 'Simulated' : 'Sensibull'} · updated ${new Date(c.updatedAt).toLocaleTimeString()}`;
    const exp = currentExp();
    renderTiles(c, exp); renderChain(c, exp); renderCharts(c, exp); renderBuilder();
  }
  const fmtDate = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });

  function renderTiles(c, exp) {
    const st = chainStats(exp, c.spot);
    const days = st.T * 365;
    const tile = (label, value, sub = '') => `<div class="tile"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
    $('tiles').innerHTML = [
      tile(esc(c.underlying) + ' spot', fmt.n(c.spot, 2)),
      tile('Future', isFinite(exp.future) ? fmt.n(exp.future, 2) : '-', isFinite(exp.future) ? `basis ${fmt.n(exp.future - c.spot, 1)}` : ''),
      tile('ATM IV', fmt.pct(st.atmIv), `ATM ${fmt.n(st.atmK, 0)}`),
      tile('Expected move', isFinite(st.move) ? '± ' + fmt.n(st.move, 0) : '-', '1σ to expiry'),
      tile('PCR (OI)', isFinite(st.pcr) ? st.pcr.toFixed(2) : '-', `P ${fmt.compact(st.peOi)} / C ${fmt.compact(st.ceOi)}`),
      tile('Max pain', st.maxPain ? fmt.n(st.maxPain, 0) : '-'),
      tile('Days to expiry', days < 1 ? (days * 24).toFixed(1) + ' h' : days.toFixed(1), fmtDate(exp.expiry)),
    ].join('');
  }

  function renderChain(c, exp) {
    const st = chainStats(exp, c.spot);
    const n = +$('range').value;
    const idx = exp.strikes.findIndex((s) => s.K === st.atmK);
    const rows = n >= 999 || idx < 0 ? exp.strikes : exp.strikes.slice(Math.max(0, idx - n), idx + n + 1);
    const maxOi = Math.max(1, ...rows.map((s) => Math.max(s.CE?.oi || 0, s.PE?.oi || 0)));
    const cell = (o, key, dp) => (o && isFinite(o[key]) ? (key === 'iv' ? (o.iv * 100).toFixed(1) : key === 'delta' ? o.delta.toFixed(2) : dp === 'c' ? fmt.compact(o[key]) : fmt.px(o[key])) : '-');
    const oiCell = (o, side) => `<td class="oi ${side}"><div class="bar" style="width:${(100 * (o?.oi || 0) / maxOi).toFixed(1)}%"></div><span>${cell(o, 'oi', 'c')}</span></td>`;
    const ltpCell = (o, type, K) => `<td><span class="ltp-cell">${type === 'C' ? btns(type, K) : ''}<span>${cell(o, 'ltp')}</span>${type === 'P' ? btns(type, K) : ''}</span></td>`;
    const btns = (type, K) => `<button class="bs-btn b" data-t="${type}" data-k="${K}" data-s="1" title="Buy ${K} ${type === 'C' ? 'CE' : 'PE'}">B</button><button class="bs-btn s" data-t="${type}" data-k="${K}" data-s="-1" title="Sell ${K} ${type === 'C' ? 'CE' : 'PE'}">S</button>`;
    document.querySelector('#chain tbody').innerHTML = rows.map((s) => {
      const ceItm = s.K < c.spot, peItm = s.K > c.spot;
      return `<tr class="${s.K === st.atmK ? 'atm' : ''}" data-k="${s.K}">
        ${oiCell(s.CE, 'ce')}<td class="${ceItm ? 'itm' : ''}">${cell(s.CE, 'volume', 'c')}</td><td class="${ceItm ? 'itm' : ''}">${cell(s.CE, 'iv')}</td><td class="${ceItm ? 'itm' : ''}">${cell(s.CE, 'delta')}</td>${ltpCell(s.CE, 'C', s.K).replace('<td>', `<td class="${ceItm ? 'itm' : ''}">`)}
        <td class="strike">${fmt.n(s.K, 0)}</td>
        ${ltpCell(s.PE, 'P', s.K).replace('<td>', `<td class="${peItm ? 'itm' : ''}">`)}<td class="${peItm ? 'itm' : ''}">${cell(s.PE, 'delta')}</td><td class="${peItm ? 'itm' : ''}">${cell(s.PE, 'iv')}</td><td class="${peItm ? 'itm' : ''}">${cell(s.PE, 'volume', 'c')}</td>${oiCell(s.PE, 'pe')}
      </tr>`;
    }).join('');
    const key = c.underlying + exp.expiry;
    if (S.scrolledFor !== key) {
      S.scrolledFor = key;
      const row = document.querySelector('#chain tr.atm'); const wrap = $('chain-wrap');
      if (row) wrap.scrollTop = row.offsetTop - wrap.clientHeight / 2 + row.clientHeight;
    }
  }
  document.querySelector('#chain').addEventListener('click', (e) => {
    const b = e.target.closest('.bs-btn'); if (!b) return;
    addLeg(b.dataset.t, +b.dataset.k, +b.dataset.s);
  });

  function renderCharts(c, exp) {
    if (!window.Chart) return;
    OD.chartDefaults();
    const st = chainStats(exp, c.spot);
    const idx = exp.strikes.findIndex((s) => s.K === st.atmK);
    const rows = idx < 0 ? exp.strikes : exp.strikes.slice(Math.max(0, idx - 15), idx + 16);
    const labels = rows.map((s) => s.K);
    const call = css('--call'), put = css('--put');
    const oiData = { labels, datasets: [
      { label: 'Call OI', data: rows.map((s) => s.CE?.oi || 0), backgroundColor: call, borderRadius: 3, borderSkipped: 'start', barPercentage: 0.9, categoryPercentage: 0.8 },
      { label: 'Put OI', data: rows.map((s) => s.PE?.oi || 0), backgroundColor: put, borderRadius: 3, borderSkipped: 'start', barPercentage: 0.9, categoryPercentage: 0.8 },
    ] };
    upsert('oi-chart', 'bar', oiData, {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 10, callback: function (v) { return fmt.n(this.getLabelForValue(v), 0); } } }, y: { ticks: { callback: (v) => fmt.compact(v) } } },
      plugins: { tooltip: { callbacks: { title: (it) => 'Strike ' + fmt.n(+it[0].label, 0), label: (it) => ` ${it.dataset.label}: ${fmt.compact(it.parsed.y)}` } } },
    });
    const ivData = { datasets: [
      { label: 'Call IV', data: rows.filter((s) => isFinite(s.CE?.iv)).map((s) => ({ x: s.K, y: s.CE.iv * 100 })), borderColor: call, backgroundColor: call, pointRadius: 2 },
      { label: 'Put IV', data: rows.filter((s) => isFinite(s.PE?.iv)).map((s) => ({ x: s.K, y: s.PE.iv * 100 })), borderColor: put, backgroundColor: put, pointRadius: 2 },
    ] };
    upsert('iv-chart', 'line', ivData, {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'nearest', axis: 'x', intersect: false },
      scales: { x: { type: 'linear', grid: { display: false }, ticks: { callback: (v) => fmt.n(v, 0) } }, y: { title: { display: true, text: 'IV %' } } },
      plugins: { spotLine: { x: c.spot, label: 'Spot' }, tooltip: { callbacks: { title: (it) => 'Strike ' + fmt.n(it[0].parsed.x, 0), label: (it) => ` ${it.dataset.label}: ${it.parsed.y.toFixed(1)}%` } } },
    });
  }
  function upsert(id, type, data, options) {
    const cv = $(id);
    if (cv._chart) { cv._chart.data = data; cv._chart.options = options; cv._chart.update(); return; }
    cv._chart = new Chart(cv, { type, data, options, plugins: [OD.spotLinePlugin] });
  }

  // ------------------------------------------------------------ strategy builder
  function quote(type, K, expiry) {
    const e = S.chain?.expiries.find((x) => x.expiry === expiry); if (!e) return null;
    const row = e.strikes.find((s) => s.K === K); if (!row) return null;
    return row[type === 'C' ? 'CE' : 'PE'];
  }
  function addLeg(type, K, side) {
    const exp = currentExp(); if (!exp) return;
    const q = quote(type, K, exp.expiry);
    if (!q || !isFinite(q.ltp)) { toast('No price for that strike yet', 'bad'); return; }
    S.legs.push({ id: Math.random().toString(36).slice(2, 8), type, K, side, lots: 1, entry: q.ltp, expiry: exp.expiry, underlying: S.underlying, iv: q.iv, at: Date.now() });
    saveLegs(); renderBuilder();
  }
  const saveLegs = () => store.set('live.legs', S.legs);
  $('clear-legs').addEventListener('click', () => { S.legs = S.legs.filter((l) => l.underlying !== S.underlying); saveLegs(); renderBuilder(); });
  $('legs').addEventListener('click', (e) => {
    const t = e.target; const id = t.closest('.leg')?.dataset.id; if (!id) return;
    const leg = S.legs.find((l) => l.id === id);
    if (t.classList.contains('x')) S.legs = S.legs.filter((l) => l.id !== id);
    else if (t.classList.contains('tag')) leg.side *= -1;
    else return;
    saveLegs(); renderBuilder();
  });
  $('legs').addEventListener('change', (e) => {
    const t = e.target; const id = t.closest('.leg')?.dataset.id; if (!id) return;
    const leg = S.legs.find((l) => l.id === id);
    if (t.name === 'lots') leg.lots = Math.max(1, Math.round(+t.value) || 1);
    if (t.name === 'entry') leg.entry = Math.max(0, +t.value || 0);
    saveLegs(); renderBuilder();
  });

  $('template').addEventListener('change', () => {
    const k = $('template').value; $('template').value = '';
    const exp = currentExp(); if (!k || !exp || !S.chain) return;
    const st = chainStats(exp, S.chain.spot); const spot = S.chain.spot;
    const strikes = exp.strikes.map((s) => s.K);
    const near = (x) => strikes.reduce((a, b) => (Math.abs(b - x) < Math.abs(a - x) ? b : a), strikes[0]);
    const m = isFinite(st.move) ? st.move : spot * 0.02;
    const T = {
      short_strangle: [['C', -1, spot + m], ['P', -1, spot - m]],
      iron_condor: [['P', 1, spot - 1.6 * m], ['P', -1, spot - m], ['C', -1, spot + m], ['C', 1, spot + 1.6 * m]],
      bull_put: [['P', -1, spot - 0.5 * m], ['P', 1, spot - 1.1 * m]],
      bear_call: [['C', -1, spot + 0.5 * m], ['C', 1, spot + 1.1 * m]],
      long_straddle: [['C', 1, st.atmK], ['P', 1, st.atmK]],
    }[k];
    T.forEach(([type, side, K]) => addLeg(type, near(K), side));
  });

  function renderBuilder() {
    const legs = S.legs.filter((l) => l.underlying === S.underlying);
    const L = lot(); const spot = S.chain?.spot;
    if (!legs.length) {
      $('legs').innerHTML = '<p class="small muted">No legs yet. Add them from the chain with B / S, or pick a template.</p>';
      $('strat-tiles').innerHTML = '';
      const cv = $('payoff'); if (cv._chart) { cv._chart.destroy(); cv._chart = null; }
      return;
    }
    let mtm = 0, net = 0, dSum = 0, tSum = 0, vSum = 0, gSum = 0;
    const now = Date.now();
    const rows = legs.map((l) => {
      const q = quote(l.type, l.K, l.expiry);
      const ltp = q && isFinite(q.ltp) ? q.ltp : NaN;
      const iv = q && isFinite(q.iv) ? q.iv : (l.iv || 0.15);
      const T = yearsToExpiry(l.expiry, now);
      const g = spot ? bs(l.type, spot, l.K, T, iv) : null;
      const pick = (k) => (q && isFinite(q[k]) ? q[k] : g ? g[k] : 0);
      const u = l.side * l.lots * L;
      if (isFinite(ltp)) mtm += u * (ltp - l.entry);
      net += -u * l.entry;
      dSum += u * pick('delta'); tSum += u * pick('theta'); vSum += u * pick('vega'); gSum += u * pick('gamma');
      const pnl = isFinite(ltp) ? u * (ltp - l.entry) : NaN;
      return `<div class="leg" data-id="${l.id}">
        <button class="tag ${l.side > 0 ? 'buy' : 'sell'}" title="Flip buy/sell">${l.side > 0 ? 'BUY' : 'SELL'}</button>
        <span><b>${fmt.n(l.K, 0)} ${l.type === 'C' ? 'CE' : 'PE'}</b> <span class="muted small">${fmtDate(l.expiry)}</span><br><span class="small muted">entry ${fmt.px(l.entry)} · LTP ${fmt.px(ltp)}</span></span>
        <label class="small muted">lots <input type="number" name="lots" min="1" step="1" value="${l.lots}"></label>
        <span class="num small ${fmt.cls(pnl)}">${fmt.rs(pnl)}</span>
        <button class="x" title="Remove leg" aria-label="Remove leg">×</button>
      </div>`;
    });
    $('legs').innerHTML = rows.join('');

    if (!spot) return;
    // Evaluate at the earliest expiry; later legs keep their remaining time value.
    const tFirst = Math.min(...legs.map((l) => yearsToExpiry(l.expiry, now)));
    const legIv = (l) => { const q = quote(l.type, l.K, l.expiry); return q && isFinite(q.iv) ? q.iv : (l.iv || 0.15); };
    const valueAt = (x, when) => legs.reduce((a, l) => {
      const Trem = Math.max(yearsToExpiry(l.expiry, now) - when, 0);
      const v = Trem <= 1e-9 ? (l.type === 'C' ? Math.max(x - l.K, 0) : Math.max(l.K - x, 0)) : bs(l.type, x, l.K, Trem, legIv(l)).price;
      return a + l.side * l.lots * L * (v - l.entry);
    }, 0);
    const lo = spot * 0.88, hi = spot * 1.12, N = 300;
    const exp = [], today = [];
    for (let i = 0; i <= N; i++) { const x = lo + (hi - lo) * i / N; exp.push({ x, y: valueAt(x, tFirst) }); today.push({ x, y: valueAt(x, 0) }); }
    payoffChart($('payoff'), [
      { label: 'At expiry', data: exp, color: css('--accent'), fill: true },
      { label: 'Today', data: today, color: css('--muted'), dashed: true, width: 1.5 },
    ], { spot, xLabel: `${S.underlying} at ${fmtDate(legs.reduce((a, l) => (yearsToExpiry(l.expiry, now) < yearsToExpiry(a, now) ? l.expiry : a), legs[0].expiry))}` });

    const ys = exp.map((p) => p.y);
    const sameExp = legs.every((l) => l.expiry === legs[0].expiry);
    let slopeHi = 0; for (const l of legs) if (l.type === 'C') slopeHi += l.side * l.lots;
    const y0 = sameExp ? valueAt(0.01, tFirst) : NaN;
    const maxP = sameExp && slopeHi > 0 ? Infinity : Math.max(...ys, isFinite(y0) ? y0 : -Infinity);
    const maxL = sameExp && slopeHi < 0 ? -Infinity : Math.min(...ys, isFinite(y0) ? y0 : Infinity);
    const be = []; for (let i = 1; i < exp.length; i++) if ((exp[i - 1].y < 0) !== (exp[i].y < 0)) { const t = exp[i - 1].y / (exp[i - 1].y - exp[i].y); be.push(exp[i - 1].x + t * (exp[i].x - exp[i - 1].x)); }
    const tile = (label, value, cls = '') => `<div class="tile"><div class="label">${label}</div><div class="value ${cls}">${value}</div></div>`;
    $('strat-tiles').innerHTML = [
      tile('Live P&amp;L', fmt.rs(mtm), fmt.cls(mtm)),
      tile(net >= 0 ? 'Net credit' : 'Net debit', fmt.rs(Math.abs(net))),
      tile('Max profit', fmt.rs(maxP), 'pos'),
      tile('Max loss', fmt.rs(maxL), 'neg'),
      tile('Breakeven', be.map((b) => fmt.n(b, 0)).join(' / ') || '-', 'wrap'),
      tile('Net Δ (units)', fmt.n(dSum, 1)),
      tile('Θ / day', fmt.rs(tSum), fmt.cls(tSum)),
      tile('Vega / 1%', fmt.rs(vSum)),
    ].join('');
    if (!sameExp) $('strat-tiles').insertAdjacentHTML('beforeend', '<p class="small muted" style="grid-column:1/-1">Mixed expiries: max profit and loss are measured within ±12% of spot at the first expiry.</p>');
  }

  document.addEventListener('od:theme', () => { ['payoff', 'oi-chart', 'iv-chart'].forEach((id) => { const c = $(id); if (c._chart) { c._chart.destroy(); c._chart = null; } }); renderAll(); });

  // ------------------------------------------------------------ boot
  if (servedByBridge && !store.get('live.bridge')) $('bridge-url').value = location.origin;
  setSource(S.source);
})();
