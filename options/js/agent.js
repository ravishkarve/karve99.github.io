/* Page 3: autoresearch loop for options strategies.
   program.md  -> the editable research program (textarea)
   train.py    -> the strategy config the agent edits (BT.SPACE)
   prepare.py  -> the fixed backtest harness (backtest.js)
   results.tsv -> the experiment log (results table / download) */
(function () {
  'use strict';
  const { fmt, esc, store, css, rng } = OD;
  const $ = (id) => document.getElementById(id);
  const SDK_URL = 'https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@0.128.0/+esm';
  // USD per million tokens (input, output)
  const PRICES = { 'claude-opus-5': [5, 25], 'claude-fable-5-1': [10, 50], 'claude-sonnet-5': [2, 10], 'claude-haiku-4-5': [1, 5] };
  const FALLBACK_MODELS = new Set(['claude-opus-5', 'claude-fable-5-1']);

  const DEFAULT_PROGRAM = `# program.md: options strategy research

You are an autonomous research agent. Find the options strategy on this
index that MAXIMISES RETURN (CAGR), subject to the risk limits below.

## The loop
1. Read the results log. Form ONE clear hypothesis.
2. Edit the strategy config to test it. Prefer small, attributable changes
   (one or two knobs), but switch structure when a line of attack is exhausted.
3. The harness backtests it on the train and validation periods.
4. If the score beats the best so far, the change is KEPT and becomes the
   new baseline. Otherwise it is DISCARDED.
5. Repeat forever. Never stop to ask the human.

## Rules
- Only the config changes. Data, pricing, costs and scoring are fixed.
- A run is discarded if max drawdown exceeds the limit or a period has too
  few trades.
- The test period is hidden from you. Do not try to guess it.
- Overfitting is the enemy. A tiny gain from an oddly specific setting is
  probably noise. When scores tie, prefer the simpler, more robust config.
- Explore broadly early (different structures, deltas, expiries, exits),
  then refine around what works.
- Position size (risk_per_trade) scales both return and drawdown. Use it
  deliberately.
- If ten or more runs in a row fail to improve, try something radically
  different.
`;

  // ------------------------------------------------------------ state
  const S = {
    ds: null, dsKey: '', dsDesc: store.get('agent.data', { kind: 'synthetic', seed: 42, years: 12, vrp: 0.1 }),
    results: [], running: false, stopReq: false, busy: false,
    usage: store.get('agent.usage', { in: 0, out: 0, usd: 0, calls: 0 }),
    stall: 0, claudeErrors: 0, client: null, clientKey: '',
  };
  const R = rng((Date.now() % 1e9) | 0);

  // ------------------------------------------------------------ program + settings
  $('program').value = store.get('agent.program', DEFAULT_PROGRAM);
  $('objective').value = store.get('agent.objective', 'robust');
  $('maxdd').value = String(store.get('agent.maxdd', 0.3));
  $('mintrades').value = store.get('agent.mintrades', 8);
  $('program').addEventListener('change', () => store.set('agent.program', $('program').value));
  $('program-reset').addEventListener('click', () => { $('program').value = DEFAULT_PROGRAM; store.set('agent.program', DEFAULT_PROGRAM); });
  for (const id of ['objective', 'maxdd', 'mintrades']) {
    $(id).addEventListener('change', () => {
      store.set('agent.' + id, id === 'objective' ? $(id).value : +$(id).value);
      if (S.results.length && confirm('Changing the scoring rules makes earlier scores incomparable. Re-score all experiments now?')) rescoreAll();
    });
  }
  const program = () => ({ text: $('program').value, objective: $('objective').value, maxDD: +$('maxdd').value, minTrades: Math.max(1, +$('mintrades').value || 1) });

  // proposer
  let proposer = store.get('agent.proposer', 'local');
  function setProposer(p) {
    proposer = p; store.set('agent.proposer', p);
    document.querySelectorAll('#proposer-seg button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.v === p));
    $('proposer-local').classList.toggle('hidden', p !== 'local');
    $('proposer-claude').classList.toggle('hidden', p !== 'claude');
  }
  $('proposer-seg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setProposer(b.dataset.v); });
  setProposer(proposer);
  $('api-key').value = store.get('agent.key', null) || store.sget('agent.key', '') || '';
  $('remember-key').checked = !!store.get('agent.key', null);
  $('model').value = store.get('agent.model', 'claude-opus-5');
  $('effort').value = store.get('agent.effort', 'high');
  $('budget').value = store.get('agent.budget', 5);
  const saveKey = () => {
    const k = $('api-key').value.trim();
    store.sset('agent.key', k);
    if ($('remember-key').checked) store.set('agent.key', k); else store.del('agent.key');
  };
  $('api-key').addEventListener('change', saveKey);
  $('remember-key').addEventListener('change', saveKey);
  for (const id of ['model', 'effort', 'budget']) $(id).addEventListener('change', () => store.set('agent.' + id, id === 'budget' ? +$(id).value : $(id).value));

  // ------------------------------------------------------------ data
  function setDataTab(kind) {
    document.querySelectorAll('#data-seg button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.v === kind));
    for (const k of ['synthetic', 'csv', 'bridge']) $('data-' + k).classList.toggle('hidden', k !== kind);
  }
  $('data-seg').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setDataTab(b.dataset.v); });

  function describe(ds) {
    const n = ds.close.length;
    const s = ds.splits;
    return `<b>${esc(ds.label)}</b>: ${n.toLocaleString()} days, ${ds.dates[0]} to ${ds.dates[n - 1]}.
      Train ${ds.dates[s.train[0]]} to ${ds.dates[s.train[1]]} · validation to ${ds.dates[s.val[1]]} · test (hidden) to ${ds.dates[s.test[1]]}.
      ${ds.ivProxied ? `<span class="muted">IV estimated from realised volatility on ${ds.ivProxied.toLocaleString()} days.</span>` : ''}`;
  }
  function useDataset(raw, desc) {
    const key = JSON.stringify({ label: raw.label, n: raw.close.length, first: raw.close[0], last: raw.close[raw.close.length - 1] });
    if (S.results.length && key !== S.dsKey) {
      if (!confirm('Switching data resets the experiment log, because scores on different data are not comparable. Continue?')) return false;
      clearResults();
    }
    S.ds = BT.prepare(raw); S.dsKey = key; S.dsDesc = desc;
    try { store.set('agent.data', desc); } catch { /* too large, ignore */ }
    $('data-info').innerHTML = describe(S.ds);
    return true;
  }
  const loadSynthetic = () => {
    const seed = Math.max(1, +$('seed').value | 0), years = Math.min(30, Math.max(4, +$('years').value | 0)), vrp = +$('vrp').value;
    return useDataset(BT.synthMarket(seed, years, vrp), { kind: 'synthetic', seed, years, vrp });
  };
  for (const id of ['seed', 'years', 'vrp']) $(id).addEventListener('change', () => { if (!loadSynthetic()) restoreSyntheticInputs(); });
  function restoreSyntheticInputs() { const d = S.dsDesc; if (d.kind === 'synthetic') { $('seed').value = d.seed; $('years').value = d.years; $('vrp').value = String(d.vrp); } }

  $('csv-file').addEventListener('change', async () => {
    const f = $('csv-file').files[0]; if (!f) return;
    try {
      const text = await f.text();
      const raw = BT.parseCSV(text, f.name);
      if (useDataset(raw, { kind: 'csv', name: f.name, text: text.length < 1.5e6 ? text : null })) log(`Loaded ${f.name}.`, 'ok');
    } catch (e) { $('data-info').innerHTML = `<span class="neg">${esc(e.message)}</span>`; }
  });

  $('bridge-url').value = store.get('live.bridge', /^(127\.0\.0\.1|localhost)$/.test(location.hostname) && location.port ? location.origin : 'http://127.0.0.1:8765');
  $('hist-source').value = store.get('agent.histSource', 'kite');
  $('bridge-load').addEventListener('click', async () => {
    const base = $('bridge-url').value.trim().replace(/\/+$/, '');
    $('data-info').textContent = 'Downloading NIFTY history through the bridge…';
    try {
      const src = $('hist-source').value; store.set('agent.histSource', src);
      const r = await fetch(base + (src === 'kite' ? '/api/history?source=kite&underlying=NIFTY&years=15' : '/api/history?symbol=%5ENSEI&iv=%5EINDIAVIX&range=max'));
      const d = await r.json();
      if (!r.ok || d.ok === false) throw new Error(d.error || 'HTTP ' + r.status);
      const raw = BT.fillIv({ dates: d.dates, close: d.close, iv: d.iv.map((x) => (x == null ? NaN : x)), label: `NIFTY 50 + India VIX (${d.source || (src === 'kite' ? 'Zerodha Kite' : 'Yahoo Finance')})`, synthetic: false });
      if (raw.close.length < 300) throw new Error('Not enough history returned');
      const csv = 'date,close,iv\n' + raw.dates.map((x, i) => `${x},${raw.close[i]},${raw.iv[i]}`).join('\n');
      if (useDataset(raw, { kind: 'csv', name: raw.label, text: csv })) log(`Loaded ${raw.close.length.toLocaleString()} days of NIFTY history from ${d.source || src}.`, 'ok');
    } catch (e) {
      $('data-info').innerHTML = `<span class="neg">${esc(e instanceof TypeError ? `Cannot reach the bridge at ${base}. Is it running?` : e.message)}</span>`;
    }
  });

  // ------------------------------------------------------------ log
  function log(msg, kind = '') {
    const el = $('log');
    const line = document.createElement('div');
    if (kind) line.className = kind;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    el.appendChild(line);
    while (el.childNodes.length > 400) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
  }

  // ------------------------------------------------------------ results
  function bestIdx() {
    let b = -1;
    S.results.forEach((r, i) => { if (r.status === 'keep' && (b < 0 || r.score > S.results[b].score)) b = i; });
    return b;
  }
  const best = () => { const i = bestIdx(); return i >= 0 ? S.results[i] : null; };
  const persist = () => {
    try { store.set('agent.results', { dsKey: S.dsKey, results: S.results }); } catch { /* quota */ }
    store.set('agent.usage', S.usage);
  };
  function clearResults() { S.results = []; S.stall = 0; persist(); renderAll(true); }
  function rescoreAll() {
    const p = program(); let bestScore = -Infinity;
    for (const r of S.results) {
      const ev = BT.evaluate(S.ds, r.config, p);
      Object.assign(r, { train: ev.train, val: ev.val, test: ev.test, score: ev.score, ok: ev.ok, reason: ev.reason });
      if (r.status !== 'crash') r.status = ev.ok && ev.score > bestScore + 1e-4 ? 'keep' : 'discard';
      if (r.status === 'keep') bestScore = ev.score;
    }
    persist(); renderAll(true); log('Re-scored all experiments with the new rules.');
  }

  // ------------------------------------------------------------ proposers
  const KNOBS = Object.keys(BT.SPACE).filter((k) => k !== 'structure');
  const WEIGHTS = { short_delta: 3, wing_delta: 2, dte: 3, profit_target: 2, stop_loss: 2, exit_dte: 2, risk_per_trade: 3, iv_rank_min: 1.5, iv_rank_max: 1, trend_filter: 1, sma_len: 1, cooldown: 0.5 };
  function randomConfig() {
    const c = {};
    for (const [k, s] of Object.entries(BT.SPACE)) c[k] = s.kind === 'enum' ? s.values[Math.floor(R() * s.values.length)] : s.min + R() * (s.max - s.min);
    c.iv_rank_min = Math.round(R() * 50); c.iv_rank_max = 100;
    return BT.clampConfig(c);
  }
  function mutate(base) {
    const c = { ...base };
    const changes = R() < 0.7 ? 1 : 2;
    if (R() < 0.12) c.structure = BT.STRUCTURES[Math.floor(R() * BT.STRUCTURES.length)];
    else {
      const total = KNOBS.reduce((a, k) => a + (WEIGHTS[k] || 1), 0);
      for (let n = 0; n < changes; n++) {
        let x = R() * total, k = KNOBS[0];
        for (const kk of KNOBS) { x -= WEIGHTS[kk] || 1; if (x <= 0) { k = kk; break; } }
        const s = BT.SPACE[k];
        if (s.kind === 'enum') c[k] = s.values[Math.floor(R() * s.values.length)];
        else c[k] = c[k] + R.gauss() * 0.15 * (s.max - s.min) * (S.stall > 25 ? 1.8 : 1);
      }
    }
    return BT.clampConfig(c);
  }
  function diffText(a, b) {
    if (!a) return 'baseline';
    const parts = [];
    for (const k of Object.keys(BT.SPACE)) if (a[k] !== b[k]) parts.push(`${k} ${a[k]} → ${b[k]}`);
    return parts.join(', ') || 'no change';
  }
  function proposeLocal() {
    const b = best(); const seen = new Set(S.results.map((r) => BT.configKey(r.config)));
    if (!b) return { config: { ...BT.DEFAULT_CONFIG }, description: 'baseline: default iron condor', rationale: 'Establish a baseline.' };
    let cfg, why;
    for (let tries = 0; tries < 30; tries++) {
      if (S.stall >= 40 && R() < 0.5) { cfg = randomConfig(); why = 'Random restart after a long stall, to escape a local optimum.'; }
      else { cfg = mutate(b.config); why = 'Local mutation of the best config.'; }
      if (!seen.has(BT.configKey(cfg))) break;
    }
    return { config: cfg, description: diffText(b.config, cfg), rationale: why };
  }

  // Claude proposer
  function responseSchema() {
    const props = {};
    for (const [k, s] of Object.entries(BT.SPACE)) props[k] = s.kind === 'enum' ? { type: 'string', enum: s.values } : { type: s.kind === 'int' ? 'integer' : 'number' };
    return {
      type: 'object',
      properties: {
        hypothesis: { type: 'string' },
        description: { type: 'string' },
        config: { type: 'object', properties: props, required: Object.keys(props), additionalProperties: false },
      },
      required: ['hypothesis', 'description', 'config'],
      additionalProperties: false,
    };
  }
  const pct = (v) => (isFinite(v) ? (v * 100).toFixed(2) : 'n/a');
  function buildPrompt() {
    const p = program(); const b = best();
    const space = Object.entries(BT.SPACE).map(([k, s]) => `- ${k}: ${s.kind === 'enum' ? 'one of ' + s.values.join(' | ') : `${s.kind} in [${s.min}, ${s.max}]`}. ${s.doc}`).join('\n');
    const H = BT.H;
    const recent = S.results.slice(-40).map((r) => [r.n, r.status, r.ok ? pct(r.score) : 'invalid', pct(r.train.cagr), pct(r.val.cagr), pct(r.train.maxDD), pct(r.val.maxDD), r.train.trades, r.val.trades, r.config.structure, (r.description || '').replace(/\s+/g, ' ').slice(0, 140), r.ok ? '' : r.reason].join('\t')).join('\n');
    const structStats = {};
    for (const r of S.results) { const s = r.config.structure; const o = structStats[s] || (structStats[s] = { n: 0, best: -Infinity }); o.n++; if (r.ok) o.best = Math.max(o.best, r.score); }
    const ss = Object.entries(structStats).map(([k, v]) => `${k}: ${v.n} runs, best score ${isFinite(v.best) ? pct(v.best) + '%' : 'none valid'}`).join('\n') || 'none yet';
    return `${p.text}

## Scoring (fixed)
objective: ${p.objective === 'robust' ? 'score = min(train CAGR, validation CAGR)' : 'score = validation CAGR'}
max drawdown limit: ${pct(p.maxDD)}% ${p.objective === 'robust' ? '(train and validation)' : '(validation)'}
min trades per period: ${p.minTrades}

## Harness (fixed, you cannot change it)
Data: ${S.ds.label}. Train ${S.ds.dates[S.ds.splits.train[0]]} to ${S.ds.dates[S.ds.splits.train[1]]}, validation to ${S.ds.dates[S.ds.splits.val[1]]}. Daily closes; one position at a time.
Options priced by Black-Scholes from the day's implied volatility with a fixed put skew. Strikes rounded to ${H.strikeStep}; lot ${H.lot} units; starting equity Rs ${H.capital.toLocaleString('en-IN')} per period.
Costs: Rs ${H.brokeragePerOrder}/leg/order, slippage ${H.slippagePct * 100}% of premium (min ${H.slippageMin}), STT ${H.sttSell * 100}% on sells, fees ${H.exchangeFees * 100}%.
Margin for naked shorts: ${H.nakedMargin * 100}% of notional (+${H.extraNakedMargin * 100}% per extra naked leg). Defined-risk positions are sized by max loss, longs by premium.

## Config knobs
${space}

## Best config so far (${b ? `experiment #${b.n}, score ${pct(b.score)}%` : 'none yet'})
${b ? JSON.stringify(b.config) : JSON.stringify(BT.DEFAULT_CONFIG) + ' (default, not yet run)'}
${b ? `train: CAGR ${pct(b.train.cagr)}%, maxDD ${pct(b.train.maxDD)}%, trades ${b.train.trades}, win ${pct(b.train.winRate)}%, sharpe ${b.train.sharpe.toFixed(2)}
validation: CAGR ${pct(b.val.cagr)}%, maxDD ${pct(b.val.maxDD)}%, trades ${b.val.trades}, win ${pct(b.val.winRate)}%, sharpe ${b.val.sharpe.toFixed(2)}` : ''}

## Structures tried
${ss}

## Results log (most recent ${Math.min(40, S.results.length)} of ${S.results.length}; percentages)
n\tstatus\tscore\ttrain_cagr\tval_cagr\ttrain_dd\tval_dd\ttrain_trades\tval_trades\tstructure\tdescription\tinvalid_reason
${recent || '(empty)'}

Propose the next single experiment. Do not repeat a config already in the log. Return JSON with:
- hypothesis: what you expect and why, in one or two sentences
- description: a short label for the change (for example "short_delta 0.16 -> 0.20")
- config: the complete config to run`;
  }

  async function getClient(key) {
    if (window.__anthropicClientFactory) return window.__anthropicClientFactory(key); // test hook
    if (S.client && S.clientKey === key) return S.client;
    let mod;
    try { mod = await import(SDK_URL); } catch (e) { throw new Error('Could not load the Anthropic SDK from the CDN: ' + e.message); }
    const Anthropic = mod.default || mod.Anthropic;
    S.client = new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true, maxRetries: 2 });
    S.clientKey = key;
    return S.client;
  }

  async function proposeClaude() {
    const key = $('api-key').value.trim();
    if (!key) throw new Error('Enter an Anthropic API key, or switch to Local search.');
    const cap = +$('budget').value || 0;
    if (cap && S.usage.usd >= cap) { const e = new Error(`Spend cap of $${cap} reached. Raise it to continue.`); e.fatal = true; throw e; }
    const client = await getClient(key);
    const model = $('model').value, effort = $('effort').value;
    const output_config = { format: { type: 'json_schema', schema: responseSchema() } };
    if (model !== 'claude-haiku-4-5') output_config.effort = effort;
    const params = {
      model, max_tokens: 16000, output_config,
      system: 'You are an autonomous quantitative research agent running an experiment loop on an options strategy backtester. Reply only with the requested JSON.',
      messages: [{ role: 'user', content: buildPrompt() }],
    };
    let resp;
    try {
      resp = FALLBACK_MODELS.has(model)
        ? await client.beta.messages.create({ ...params, betas: ['server-side-fallback-2026-07-01'], fallbacks: 'default' })
        : await client.messages.create(params);
    } catch (e) {
      const status = e && e.status;
      const err = new Error(status === 401 ? 'The API key was rejected (401).' : status === 429 ? 'Rate limited by the API (429). Retrying after a pause.' : `API error${status ? ' ' + status : ''}: ${e.message || e}`);
      err.fatal = status === 401 || status === 403 || status === 400;
      err.retryAfter = status === 429 ? 20000 : 0;
      throw err;
    }
    const u = resp.usage || {};
    const [pi, po] = PRICES[resp.model] || PRICES[model] || [5, 25];
    const inTok = (u.input_tokens || 0) + (u.cache_creation_input_tokens || 0) + (u.cache_read_input_tokens || 0);
    S.usage.in += inTok; S.usage.out += u.output_tokens || 0; S.usage.calls++;
    S.usage.usd += (inTok * pi + (u.output_tokens || 0) * po) / 1e6;
    if (resp.stop_reason === 'refusal') throw new Error('The model declined this request (refusal). Using local search for this step.');
    if (resp.stop_reason === 'max_tokens') throw new Error('The response hit max_tokens before finishing.');
    const text = (resp.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('');
    let out;
    try { out = JSON.parse(text); } catch { throw new Error('Could not parse the model\'s JSON reply.'); }
    const cfg = BT.clampConfig(out.config || {});
    const by = resp.model && resp.model !== model ? `${model} → ${resp.model}` : model;
    return { config: cfg, description: String(out.description || diffText(best()?.config, cfg)).slice(0, 200), rationale: String(out.hypothesis || '').slice(0, 600), by };
  }

  // ------------------------------------------------------------ one experiment
  async function experiment() {
    if (!S.ds) loadSynthetic();
    let prop, by = 'local';
    if (proposer === 'claude' && S.results.length) {
      try {
        prop = await proposeClaude(); by = prop.by || 'claude';
        S.claudeErrors = 0;
      } catch (e) {
        S.claudeErrors++;
        log(e.message, 'err');
        if (e.fatal || S.claudeErrors >= 5) { S.stopReq = true; if (!e.fatal) log('Stopping after repeated API errors.', 'err'); return; }
        if (e.retryAfter) await sleep(e.retryAfter);
        prop = proposeLocal(); by = 'local (fallback)';
      }
    } else prop = proposeLocal();
    const cfg = BT.clampConfig(prop.config);
    const dup = S.results.find((r) => BT.configKey(r.config) === BT.configKey(cfg));
    const n = S.results.length + 1;
    let ev, status;
    try {
      ev = BT.evaluate(S.ds, cfg, program());
      const b = best();
      status = ev.ok && (!b || ev.score > b.score + 1e-4) ? 'keep' : 'discard';
      if (dup) status = 'discard';
    } catch (e) {
      ev = { train: {}, val: {}, test: {}, score: -Infinity, ok: false, reason: 'crash: ' + e.message };
      status = 'crash';
    }
    const row = { n, ts: Date.now(), config: cfg, description: dup ? `duplicate of #${dup.n}` : prop.description, rationale: prop.rationale, by, status, score: ev.score, ok: ev.ok, reason: ev.reason, train: ev.train, val: ev.val, test: ev.test };
    S.results.push(row);
    S.stall = status === 'keep' ? 0 : S.stall + 1;
    const scoreTxt = ev.ok ? fmt.signPct(ev.score, 2) : 'invalid';
    log(`#${n} ${status.toUpperCase()} score ${scoreTxt} · ${cfg.structure} · ${row.description}${ev.ok ? '' : ' · ' + ev.reason}`, status === 'keep' ? 'ok' : status === 'crash' ? 'err' : '');
    if (prop.rationale && by !== 'local') log(`   hypothesis: ${prop.rationale}`);
    persist();
    renderAll(status === 'keep');
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function loop() {
    if (S.running) return;
    if (!S.ds) loadSynthetic();
    S.running = true; S.stopReq = false; setRunUi();
    log(`Loop started · proposer: ${proposer === 'claude' ? $('model').value : 'local search'}`);
    const maxRuns = +$('maxruns').value; let done = 0;
    while (!S.stopReq) {
      await experiment(); done++;
      if (maxRuns && done >= maxRuns) { log(`Reached ${maxRuns} experiments.`); break; }
      await sleep(Math.max(+$('delay').value, 16));
    }
    S.running = false; setRunUi(); log('Loop stopped.');
  }
  function setRunUi() {
    $('start').textContent = S.running ? '■ Stop loop' : '▶ Start loop';
    $('start').classList.toggle('danger', S.running);
    $('step').disabled = S.running;
    const p = $('run-pill'); p.className = 'pill ' + (S.running ? 'ok live' : '');
    $('run-pill-text').textContent = S.running ? 'Researching…' : 'Idle';
  }
  $('start').addEventListener('click', () => { if (S.running) { S.stopReq = true; log('Stopping after the current experiment…'); } else loop(); });
  $('step').addEventListener('click', async () => { if (S.busy || S.running) return; S.busy = true; $('step').disabled = true; await experiment(); S.busy = false; $('step').disabled = false; });
  $('reset').addEventListener('click', () => { if (S.running) return toastStop(); if (confirm('Clear all experiments and start over?')) { clearResults(); log('Reset.'); } });
  const toastStop = () => OD.toast('Stop the loop first');

  // ------------------------------------------------------------ rendering
  function renderAll(newBest = false) { renderTiles(); renderTable(); renderProgress(); if (newBest || !renderAll.did) { renderBest(); renderAll.did = true; } }

  function renderTiles() {
    const b = best(); const kept = S.results.filter((r) => r.status === 'keep').length;
    const valid = S.results.filter((r) => r.ok).length;
    const tile = (l, v, sub = '', cls = '') => `<div class="tile"><div class="label">${l}</div><div class="value ${cls}">${v}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
    $('run-tiles').innerHTML = [
      tile('Experiments', S.results.length.toLocaleString(), `${valid} valid · ${kept} kept`),
      tile('Best score', b ? fmt.signPct(b.score, 2) : '-', b ? `#${b.n} · ${b.config.structure}` : '', b ? fmt.cls(b.score) : ''),
      tile('Best · val CAGR', b ? fmt.signPct(b.val.cagr, 1) : '-', b ? `train ${fmt.signPct(b.train.cagr, 1)}` : '', b ? fmt.cls(b.val.cagr) : ''),
      tile('Best · test CAGR', b ? fmt.signPct(b.test.cagr, 1) : '-', 'hidden from agent', b ? fmt.cls(b.test.cagr) : ''),
      tile('Since last gain', S.stall.toLocaleString(), 'experiments'),
      tile('API spend', '$' + S.usage.usd.toFixed(3), `${S.usage.calls} calls · ${fmt.compact(S.usage.in + S.usage.out)} tokens`),
    ].join('');
  }

  function renderTable() {
    const rows = S.results.slice(-300).reverse();
    $('results').querySelector('tbody').innerHTML = rows.map((r) => `
      <tr class="${r.status === 'keep' ? 'kept' : ''}" title="${esc(r.rationale || '')}">
        <td>${r.n}</td>
        <td class="text"><span class="status-${r.status}">${r.status}</span>${r.ok ? '' : `<br><span class="small muted">${esc(r.reason)}</span>`}</td>
        <td class="${r.ok ? fmt.cls(r.score) : ''}">${r.ok ? fmt.signPct(r.score, 2) : '-'}</td>
        <td class="${fmt.cls(r.train.cagr)}">${fmt.signPct(r.train.cagr, 1)}</td>
        <td class="${fmt.cls(r.val.cagr)}">${fmt.signPct(r.val.cagr, 1)}</td>
        <td class="${fmt.cls(r.test.cagr)}">${fmt.signPct(r.test.cagr, 1)}</td>
        <td>${fmt.pct(r.val.maxDD, 1)}</td>
        <td>${r.val.trades ?? '-'}</td>
        <td class="text">${esc(r.config.structure)}</td>
        <td class="text small">${esc(r.description)}</td>
        <td class="text small muted">${esc(r.by)}</td>
      </tr>`).join('') || '<tr><td colspan="11" class="text muted">No experiments yet.</td></tr>';
  }

  function renderProgress() {
    if (!window.Chart) return;
    OD.chartDefaults();
    const kept = [], disc = [], line = []; let bestSoFar = null;
    for (const r of S.results) {
      if (!r.ok) continue;
      const pt = { x: r.n, y: r.score * 100 };
      (r.status === 'keep' ? kept : disc).push(pt);
      if (r.status === 'keep') bestSoFar = pt.y;
      if (bestSoFar !== null) line.push({ x: r.n, y: bestSoFar });
    }
    if (line.length && S.results.length) line.push({ x: S.results.length, y: bestSoFar });
    const accent = css('--accent'), faint = css('--faint');
    const data = { datasets: [
      { type: 'line', label: 'Best so far', data: line, borderColor: accent, stepped: 'before', borderWidth: 2, pointRadius: 0, order: 3 },
      { type: 'scatter', label: 'Discarded', data: disc, backgroundColor: OD.hexA(faint, 0.55), pointRadius: 3, pointHoverRadius: 5, order: 2 },
      { type: 'scatter', label: 'Kept', data: kept, backgroundColor: accent, borderColor: css('--surface'), borderWidth: 2, pointRadius: 6, pointHoverRadius: 8, order: 1 },
    ] };
    const byN = new Map(S.results.map((r) => [r.n, r]));
    const opts = {
      responsive: true, maintainAspectRatio: false, parsing: false,
      interaction: { mode: 'nearest', intersect: false, axis: 'xy' },
      scales: {
        x: { type: 'linear', title: { display: true, text: 'Experiment #' }, grid: { display: false }, ticks: { precision: 0 } },
        y: { title: { display: true, text: 'Score (CAGR %)' }, ticks: { callback: (v) => v.toFixed(1) + '%' } },
      },
      plugins: { tooltip: { callbacks: {
        title: (it) => `#${it[0].parsed.x}`,
        label: (it) => { const r = byN.get(it.parsed.x); return r ? ` ${r.status}: ${it.parsed.y.toFixed(2)}% · ${r.config.structure}` : ` ${it.parsed.y.toFixed(2)}%`; },
        afterLabel: (it) => { const r = byN.get(it.parsed.x); return r && it.dataset.label !== 'Best so far' ? ' ' + (r.description || '').slice(0, 80) : ''; },
      } } },
    };
    const cv = $('progress-chart');
    if (cv._chart) { cv._chart.data = data; cv._chart.options = opts; cv._chart.update(); }
    else cv._chart = new Chart(cv, { data, options: opts });
    const invalid = S.results.length - kept.length - disc.length;
    $('progress-note').textContent = invalid ? `${invalid} run${invalid === 1 ? '' : 's'} broke a risk rule and ${invalid === 1 ? 'is' : 'are'} not plotted` : '';
  }

  function renderBest() {
    const b = best();
    const cv = $('equity-chart');
    if (!b || !S.ds) {
      $('best-summary').innerHTML = '<p class="muted small">Start the loop to find one.</p>';
      if (cv._chart) { cv._chart.destroy(); cv._chart = null; }
      return;
    }
    const row = (k, label) => { const m = b[k]; return `<tr><td class="text">${label}</td><td class="${fmt.cls(m.cagr)}">${fmt.signPct(m.cagr, 1)}</td><td>${fmt.pct(m.maxDD, 1)}</td><td>${m.sharpe.toFixed(2)}</td><td>${m.trades}</td><td>${fmt.pct(m.winRate, 0)}</td><td>${fmt.pct(m.exposure, 0)}</td></tr>`; };
    $('best-summary').innerHTML = `
      <p>Experiment <b>#${b.n}</b> · score <b class="${fmt.cls(b.score)}">${fmt.signPct(b.score, 2)}</b> · found by ${esc(b.by)}</p>
      ${b.rationale && b.by !== 'local' ? `<p class="small muted">${esc(b.rationale)}</p>` : ''}
      <div class="table-wrap" style="margin-bottom:10px"><table class="data">
        <thead><tr><th class="text">Period</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>Trades</th><th>Win %</th><th>In market</th></tr></thead>
        <tbody>${row('train', 'Train')}${row('val', 'Validation')}${row('test', 'Test (hidden)')}</tbody>
      </table></div>
      <pre class="config-view">${esc(JSON.stringify(b.config, null, 2))}</pre>
      ${b.test.cagr < b.val.cagr - 0.05 ? '<div class="callout warn small"><p>Test return is well below validation. The search has probably overfitted.</p></div>' : ''}`;

    if (!window.Chart) return;
    OD.chartDefaults();
    const colors = { train: css('--call'), val: css('--put'), test: css('--series-3') };
    const names = { train: 'Train', val: 'Validation', test: 'Test' };
    const datasets = ['train', 'val', 'test'].map((k) => {
      const [a, z] = S.ds.splits[k];
      const r = BT.run(S.ds, b.config, a, z, { record: true });
      const step = Math.max(1, Math.floor(r.equity.length / 300));
      const pts = []; for (let i = 0; i < r.equity.length; i += step) pts.push({ x: a + i, y: r.equity[i] / 1e5 });
      pts.push({ x: a + r.equity.length - 1, y: r.equity[r.equity.length - 1] / 1e5 });
      return { label: names[k], data: pts, borderColor: colors[k], borderWidth: 2, pointRadius: 0, tension: 0 };
    });
    const opts = {
      responsive: true, maintainAspectRatio: false, parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      scales: {
        x: { type: 'linear', grid: { display: false }, ticks: { maxTicksLimit: 7, callback: (v) => (S.ds.dates[Math.round(v)] || '').slice(0, 7) } },
        y: { title: { display: true, text: 'Equity (₹ lakh)' } },
      },
      plugins: { tooltip: { callbacks: { title: (it) => S.ds.dates[Math.round(it[0].parsed.x)] || '', label: (it) => ` ${it.dataset.label}: ₹${it.parsed.y.toFixed(2)} L` } } },
    };
    if (cv._chart) { cv._chart.data.datasets = datasets; cv._chart.options = opts; cv._chart.update(); }
    else cv._chart = new Chart(cv, { type: 'line', data: { datasets }, options: opts });
  }

  // ------------------------------------------------------------ exports
  function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  $('download-tsv').addEventListener('click', () => {
    const head = ['n', 'status', 'score', 'train_cagr', 'val_cagr', 'test_cagr', 'train_maxdd', 'val_maxdd', 'test_maxdd', 'train_trades', 'val_trades', 'proposer', 'description', 'hypothesis', 'config'];
    const clean = (s) => String(s ?? '').replace(/[\t\n\r]+/g, ' ');
    const lines = S.results.map((r) => [r.n, r.status, r.ok ? r.score : '', r.train.cagr, r.val.cagr, r.test.cagr, r.train.maxDD, r.val.maxDD, r.test.maxDD, r.train.trades, r.val.trades, r.by, clean(r.description), clean(r.rationale), JSON.stringify(r.config)].join('\t'));
    download('results.tsv', [head.join('\t'), ...lines].join('\n') + '\n', 'text/tab-separated-values');
  });
  $('export-best').addEventListener('click', () => {
    const b = best(); if (!b) return OD.toast('No best strategy yet');
    download('best_strategy.json', JSON.stringify({ experiment: b.n, score: b.score, data: S.ds.label, config: b.config, train: b.train, validation: b.val, test: b.test }, null, 2), 'application/json');
  });

  document.addEventListener('od:theme', () => { ['progress-chart', 'equity-chart'].forEach((id) => { const c = $(id); if (c._chart) { c._chart.destroy(); c._chart = null; } }); renderAll(true); });

  // ------------------------------------------------------------ boot
  (function boot() {
    const d = S.dsDesc;
    let raw = null;
    try {
      if (d.kind === 'csv' && d.text) { raw = BT.parseCSV(d.text, d.name); setDataTab('csv'); }
    } catch { raw = null; }
    if (!raw) {
      const sd = d.kind === 'synthetic' ? d : { seed: 42, years: 12, vrp: 0.1 };
      $('seed').value = sd.seed; $('years').value = sd.years; $('vrp').value = String(sd.vrp);
      raw = BT.synthMarket(sd.seed, sd.years, sd.vrp);
      S.dsDesc = { kind: 'synthetic', ...sd };
      setDataTab('synthetic');
    }
    S.ds = BT.prepare(raw);
    S.dsKey = JSON.stringify({ label: raw.label, n: raw.close.length, first: raw.close[0], last: raw.close[raw.close.length - 1] });
    $('data-info').innerHTML = describe(S.ds);
    const saved = store.get('agent.results', null);
    if (saved && saved.dsKey === S.dsKey && Array.isArray(saved.results)) {
      S.results = saved.results.map((r) => ({ ...r, score: r.score === null ? -Infinity : r.score }));
      let st = 0; for (let i = S.results.length - 1; i >= 0 && S.results[i].status !== 'keep'; i--) st++; S.stall = st;
      if (S.results.length) log(`Restored ${S.results.length} experiments from your last session.`);
    }
    setRunUi(); renderAll(true);
    if (!S.results.length) log('Ready. Press Start to begin the research loop.');
  })();
})();
