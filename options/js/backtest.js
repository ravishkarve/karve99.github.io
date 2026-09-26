/* Backtest harness for the research agent - the fixed "prepare.py" of the loop.
   The agent may only change the strategy config; data, pricing, costs and the
   metric below are immutable, so every experiment is measured the same way. */
(function () {
  'use strict';
  const { bsPrice, strikeForDelta, rng } = OD;

  // ------------------------------------------------------------ immutable harness constants
  const H = Object.freeze({
    capital: 1000000,        // ₹10 lakh starting equity for every split
    lot: 75,                 // units per lot
    strikeStep: 50,          // strikes rounded to 50 points
    tradingDays: 252,
    brokeragePerOrder: 20,   // ₹ per leg per transaction
    sttSell: 0.001,          // 0.1% of premium on sell-side option turnover
    exchangeFees: 0.0005,    // exchange + GST + stamp duty, ~0.05% of premium turnover
    slippagePct: 0.01,       // 1% of option price per unit per leg, min 0.05
    slippageMin: 0.05,
    nakedMargin: 0.12,       // SPAN+exposure approx: 12% of notional per naked short leg
    extraNakedMargin: 0.03,  // +3% of notional for each additional naked leg (strangle, straddle)
    splits: [0.6, 0.2, 0.2], // train / validation / test (test is never shown to the agent)
  });

  // ------------------------------------------------------------ search space ("train.py" knobs)
  const STRUCTURES = ['short_put', 'short_call', 'short_strangle', 'short_straddle', 'iron_condor', 'iron_fly',
    'bull_put_spread', 'bear_call_spread', 'bull_call_spread', 'bear_put_spread',
    'long_call', 'long_put', 'long_straddle', 'long_strangle'];
  const SPACE = {
    structure: { kind: 'enum', values: STRUCTURES, doc: 'Option structure opened on each entry' },
    dte: { kind: 'int', min: 3, max: 60, doc: 'Calendar days to expiry when the position is opened' },
    short_delta: { kind: 'num', min: 0.05, max: 0.5, step: 0.01, doc: '|delta| of the core strikes (short legs; the long leg for long_* and debit spreads)' },
    wing_delta: { kind: 'num', min: 0.01, max: 0.3, step: 0.01, doc: '|delta| of the wing strikes (protection for credit spreads, the sold leg for debit spreads). Must be below short_delta' },
    profit_target: { kind: 'num', min: 0, max: 3, step: 0.05, doc: 'Close when P&L >= profit_target x entry premium. 0 = off' },
    stop_loss: { kind: 'num', min: 0, max: 5, step: 0.1, doc: 'Close when P&L <= -stop_loss x entry premium. 0 = off' },
    exit_dte: { kind: 'int', min: 0, max: 30, doc: 'Close when calendar days to expiry <= exit_dte. 0 = hold to expiry' },
    iv_rank_min: { kind: 'int', min: 0, max: 100, doc: 'Only enter when 1-year IV rank >= this' },
    iv_rank_max: { kind: 'int', min: 0, max: 100, doc: 'Only enter when 1-year IV rank <= this' },
    trend_filter: { kind: 'enum', values: ['none', 'above_sma', 'below_sma'], doc: 'Only enter when close is above / below its SMA' },
    sma_len: { kind: 'int', min: 5, max: 200, doc: 'SMA length in trading days for trend_filter' },
    risk_per_trade: { kind: 'num', min: 0.01, max: 0.6, step: 0.01, doc: 'Fraction of equity committed per trade: margin for naked shorts, max loss for defined risk, premium for longs' },
    cooldown: { kind: 'int', min: 0, max: 10, doc: 'Trading days to wait after a close before re-entering' },
  };
  const DEFAULT_CONFIG = Object.freeze({
    structure: 'iron_condor', dte: 30, short_delta: 0.16, wing_delta: 0.05, profit_target: 0.5, stop_loss: 2,
    exit_dte: 5, iv_rank_min: 0, iv_rank_max: 100, trend_filter: 'none', sma_len: 50, risk_per_trade: 0.1, cooldown: 0,
  });

  function clampConfig(c) {
    const out = {};
    for (const [k, s] of Object.entries(SPACE)) {
      let v = c && c[k] !== undefined ? c[k] : DEFAULT_CONFIG[k];
      if (s.kind === 'enum') v = s.values.includes(v) ? v : DEFAULT_CONFIG[k];
      else {
        v = Number(v); if (!isFinite(v)) v = DEFAULT_CONFIG[k];
        v = Math.min(s.max, Math.max(s.min, v));
        if (s.kind === 'int') v = Math.round(v);
        else v = Math.round(v / s.step) * s.step, v = +v.toFixed(4);
      }
      out[k] = v;
    }
    if (out.wing_delta >= out.short_delta) out.wing_delta = +Math.max(0.01, out.short_delta - 0.03).toFixed(2);
    if (out.iv_rank_min > out.iv_rank_max) [out.iv_rank_min, out.iv_rank_max] = [out.iv_rank_max, out.iv_rank_min];
    return out;
  }
  const configKey = (c) => JSON.stringify(Object.keys(SPACE).map((k) => c[k]));

  // ------------------------------------------------------------ data
  /** Synthetic index: Heston-style stochastic volatility with jumps.
      Implied vol = true instantaneous vol x (1 + vrp) + noise. */
  function synthMarket(seed = 42, years = 12, vrp = 0.1) {
    const r = rng(seed); const n = Math.round(years * 252); const dt = 1 / 252;
    const kappa = 3.5, theta = 0.15 ** 2, xi = 0.45, rho = -0.65, mu = 0.11;
    let S = 10000, v = theta;
    const dates = [], close = [], iv = [];
    const d = new Date(Date.UTC(2013, 0, 1));
    for (let i = 0; i < n; i++) {
      do d.setUTCDate(d.getUTCDate() + 1); while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
      const z1 = r.gauss(), z2 = rho * z1 + Math.sqrt(1 - rho * rho) * r.gauss();
      v = Math.max(v + kappa * (theta - v) * dt + xi * Math.sqrt(v) * Math.sqrt(dt) * z2, 0.0025);
      let J = 0;
      if (r() < 0.004) { J = -0.03 + 0.025 * r.gauss(); v = Math.min(v * 1.8, 1); }
      S *= Math.exp((mu - 0.5 * v) * dt + Math.sqrt(v * dt) * z1 + J);
      dates.push(d.toISOString().slice(0, 10)); close.push(S);
      iv.push(Math.min(0.9, Math.max(0.06, Math.sqrt(v) * (1 + vrp) + 0.006 * r.gauss())));
    }
    return { dates, close, iv, label: `Synthetic market · seed ${seed} · ${years}y · vol premium ${Math.round(vrp * 100)}%`, synthetic: true };
  }

  /** CSV with date + close (+ optional vix / iv). Missing IV is proxied by 21-day realised vol x 1.1. */
  function parseCSV(text, label = 'Uploaded CSV') {
    const lines = text.trim().split(/\r?\n/).filter(Boolean);
    const delim = lines[0].includes('\t') ? '\t' : lines[0].includes(';') ? ';' : ',';
    const head = lines[0].split(delim).map((h) => h.trim().toLowerCase().replace(/"/g, ''));
    const find = (...names) => head.findIndex((h) => names.some((n) => h === n || h.includes(n)));
    const di = find('date', 'time');
    let ci = head.findIndex((h) => h === 'close'); if (ci < 0) ci = find('adj close', 'close', 'price', 'ltp');
    const vi = find('vix', 'iv', 'implied');
    if (di < 0 || ci < 0) throw new Error('CSV needs a date column and a close/price column');
    const rows = [];
    for (const line of lines.slice(1)) {
      const c = line.split(delim).map((x) => x.trim().replace(/"/g, ''));
      const t = Date.parse(c[di]); const px = parseFloat(c[ci].replace(/,/g, ''));
      if (!isFinite(t) || !(px > 0)) continue;
      const ivv = vi >= 0 ? parseFloat(c[vi]) : NaN;
      rows.push({ t, date: new Date(t).toISOString().slice(0, 10), px, iv: isFinite(ivv) ? (ivv > 3 ? ivv / 100 : ivv) : NaN });
    }
    rows.sort((a, b) => a.t - b.t);
    if (rows.length < 300) throw new Error(`Need at least 300 daily rows, found ${rows.length}`);
    return fillIv({ dates: rows.map((r) => r.date), close: rows.map((r) => r.px), iv: rows.map((r) => r.iv), label, synthetic: false });
  }

  function fillIv(ds) {
    const n = ds.close.length; let proxied = 0;
    const iv = ds.iv.slice();
    for (let i = 0; i < n; i++) {
      if (isFinite(iv[i]) && iv[i] > 0) continue;
      const a = Math.max(1, i - 21); let s = 0, s2 = 0, k = 0;
      for (let j = a; j <= i; j++) { const r = Math.log(ds.close[j] / ds.close[j - 1]); if (isFinite(r)) { s += r; s2 += r * r; k++; } }
      const rv = k > 5 ? Math.sqrt(Math.max(s2 / k - (s / k) ** 2, 0) * 252) : 0.15;
      iv[i] = Math.min(0.9, Math.max(0.06, rv * 1.1)); proxied++;
    }
    return { ...ds, iv, ivProxied: proxied };
  }

  /** Precompute causal indicators (IV rank, SMAs) and split points. */
  function prepare(ds) {
    const n = ds.close.length;
    const ivRank = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const a = Math.max(0, i - 251);
      if (i - a < 60) { ivRank[i] = 50; continue; }
      let lo = Infinity, hi = -Infinity;
      for (let j = a; j <= i; j++) { if (ds.iv[j] < lo) lo = ds.iv[j]; if (ds.iv[j] > hi) hi = ds.iv[j]; }
      ivRank[i] = hi > lo ? 100 * (ds.iv[i] - lo) / (hi - lo) : 50;
    }
    const smaCache = new Map();
    const sma = (len) => {
      if (smaCache.has(len)) return smaCache.get(len);
      const out = new Float64Array(n); let s = 0;
      for (let i = 0; i < n; i++) { s += ds.close[i]; if (i >= len) s -= ds.close[i - len]; out[i] = i >= len - 1 ? s / len : NaN; }
      smaCache.set(len, out); return out;
    };
    const warm = Math.min(252, Math.floor(n * 0.1));
    const usable = n - warm;
    const a = warm, b = warm + Math.floor(usable * H.splits[0]), c = b + Math.floor(usable * H.splits[1]);
    return { ...ds, n, ivRank, sma, splits: { train: [a, b], val: [b, c], test: [c, n - 1] } };
  }

  // ------------------------------------------------------------ strategy mechanics
  const smile = (atmIv, S, K, T) => {
    const m = Math.log(K / S) / Math.max(Math.sqrt(T), 0.05);
    return atmIv * Math.min(2.5, Math.max(0.6, 1 - 0.35 * m + 0.45 * m * m));
  };
  const roundK = (K) => Math.max(H.strikeStep, Math.round(K / H.strikeStep) * H.strikeStep);

  function buildLegs(cfg, S, T, atmIv) {
    const volAt = (K) => smile(atmIv, S, K, T);
    const kD = (type, d) => roundK(strikeForDelta(type, S, T, d, volAt));
    const atm = roundK(S);
    const sd = cfg.short_delta, wd = cfg.wing_delta;
    const away = (type, core, wing) => { // ensure wing is at least one step further OTM than core
      if (type === 'C') return Math.max(wing, core + H.strikeStep);
      return Math.min(wing, core - H.strikeStep);
    };
    const within = (type, core, inner) => { // debit spread: sold leg further OTM than bought leg
      if (type === 'C') return Math.max(inner, core + H.strikeStep);
      return Math.min(inner, core - H.strikeStep);
    };
    let L;
    switch (cfg.structure) {
      case 'short_put': L = [['P', -1, kD('P', sd)]]; break;
      case 'short_call': L = [['C', -1, kD('C', sd)]]; break;
      case 'short_strangle': L = [['P', -1, kD('P', sd)], ['C', -1, kD('C', sd)]]; break;
      case 'short_straddle': L = [['P', -1, atm], ['C', -1, atm]]; break;
      case 'iron_condor': { const p = kD('P', sd), c = kD('C', sd); L = [['P', -1, p], ['P', 1, away('P', p, kD('P', wd))], ['C', -1, c], ['C', 1, away('C', c, kD('C', wd))]]; break; }
      case 'iron_fly': L = [['P', -1, atm], ['C', -1, atm], ['P', 1, away('P', atm, kD('P', wd))], ['C', 1, away('C', atm, kD('C', wd))]]; break;
      case 'bull_put_spread': { const p = kD('P', sd); L = [['P', -1, p], ['P', 1, away('P', p, kD('P', wd))]]; break; }
      case 'bear_call_spread': { const c = kD('C', sd); L = [['C', -1, c], ['C', 1, away('C', c, kD('C', wd))]]; break; }
      case 'bull_call_spread': { const c = kD('C', sd); L = [['C', 1, c], ['C', -1, within('C', c, kD('C', wd))]]; break; }
      case 'bear_put_spread': { const p = kD('P', sd); L = [['P', 1, p], ['P', -1, within('P', p, kD('P', wd))]]; break; }
      case 'long_call': L = [['C', 1, kD('C', sd)]]; break;
      case 'long_put': L = [['P', 1, kD('P', sd)]]; break;
      case 'long_straddle': L = [['C', 1, atm], ['P', 1, atm]]; break;
      case 'long_strangle': L = [['C', 1, kD('C', sd)], ['P', 1, kD('P', sd)]]; break;
      default: L = [];
    }
    return L.map(([type, side, K]) => ({ type, side, K }));
  }

  /** Per-lot capital at risk for sizing. */
  function riskPerLot(legs, prices, S) {
    const premium = legs.reduce((a, l, i) => a - l.side * prices[i], 0); // >0 credit
    const shortC = legs.filter((l) => l.type === 'C' && l.side < 0).length, longC = legs.filter((l) => l.type === 'C' && l.side > 0).length;
    const shortP = legs.filter((l) => l.type === 'P' && l.side < 0).length, longP = legs.filter((l) => l.type === 'P' && l.side > 0).length;
    const naked = Math.max(0, shortC - longC) + Math.max(0, shortP - longP);
    if (naked > 0) return S * H.lot * (H.nakedMargin + H.extraNakedMargin * (naked - 1));
    // defined risk: worst expiry P&L over all strikes and extremes
    const pts = [0, ...legs.map((l) => l.K), S * 3];
    let worst = 0;
    for (const x of pts) {
      let pnl = premium;
      for (const l of legs) pnl += l.side * (l.type === 'C' ? Math.max(x - l.K, 0) : Math.max(l.K - x, 0));
      worst = Math.min(worst, pnl);
    }
    return Math.max(-worst * H.lot, 1);
  }

  const slip = (p) => Math.max(H.slippageMin, p * H.slippagePct);
  function tradeCost(legs, prices, lots) {
    let c = 0;
    legs.forEach((l, i) => {
      const units = lots * H.lot, p = prices[i];
      c += H.brokeragePerOrder + slip(p) * units + H.exchangeFees * p * units;
      if (l.side < 0) c += H.sttSell * p * units;
    });
    return c;
  }
  const closeCost = (legs, prices, lots) => {
    let c = 0;
    legs.forEach((l, i) => {
      const units = lots * H.lot, p = prices[i];
      c += H.brokeragePerOrder + slip(p) * units + H.exchangeFees * p * units;
      if (l.side > 0) c += H.sttSell * p * units; // closing a long = selling
    });
    return c;
  };

  // ------------------------------------------------------------ backtest
  function run(ds, cfgIn, a, b, { record = false } = {}) {
    const cfg = clampConfig(cfgIn);
    const smaArr = cfg.trend_filter === 'none' ? null : ds.sma(cfg.sma_len);
    const dteTd = Math.max(1, Math.round(cfg.dte * 252 / 365));
    const nakedLegs = { short_put: 1, short_call: 1, short_strangle: 2, short_straddle: 2 }[cfg.structure] || 0;
    let cash = H.capital, pos = null, lastClose = -1e9;
    const eq = record ? [] : null;
    let peak = H.capital, maxDD = 0, prevEq = H.capital;
    let sum = 0, sum2 = 0, nRet = 0, trades = 0, wins = 0, inPos = 0, ruined = false;
    const tradeLog = record ? [] : null;

    const markValue = (i, legs, expiryIdx) => {
      const S = ds.close[i]; const T = Math.max(expiryIdx - i, 0) / 252;
      return legs.map((l) => (T <= 0 ? (l.type === 'C' ? Math.max(S - l.K, 0) : Math.max(l.K - S, 0)) : bsPrice(l.type, S, l.K, T, smile(ds.iv[i], S, l.K, T))));
    };

    for (let i = a; i <= b; i++) {
      const S = ds.close[i];
      // ---- manage open position
      let px = null;
      if (pos) {
        inPos++;
        px = markValue(i, pos.legs, pos.expiry);
        const val = pos.legs.reduce((s, l, k) => s + l.side * px[k], 0) * pos.lots * H.lot;
        const pnl = val - pos.entryVal;
        const prem = Math.abs(pos.entryVal);
        const daysLeft = (pos.expiry - i) * 365 / 252;
        let reason = null;
        if (i >= pos.expiry) reason = 'expiry';
        else if (cfg.profit_target > 0 && pnl >= cfg.profit_target * prem) reason = 'target';
        else if (cfg.stop_loss > 0 && pnl <= -cfg.stop_loss * prem) reason = 'stop';
        else if (cfg.exit_dte > 0 && daysLeft <= cfg.exit_dte) reason = 'time';
        else if (i === b) reason = 'end';
        if (reason) {
          const cost = reason === 'expiry' ? H.brokeragePerOrder * pos.legs.length : closeCost(pos.legs, px, pos.lots);
          cash += val - cost;
          const tradePnl = pnl - cost - pos.entryCost;
          trades++; if (tradePnl > 0) wins++;
          if (tradeLog) tradeLog.push({ open: ds.dates[pos.open], close: ds.dates[i], lots: pos.lots, pnl: tradePnl, reason });
          pos = null; lastClose = i;
        }
      }
      // ---- equity
      let equity = cash;
      if (pos) equity += pos.legs.reduce((s, l, k) => s + l.side * px[k], 0) * pos.lots * H.lot;
      if (equity <= H.capital * 0.02) { ruined = true; equity = Math.max(equity, 0); }
      if (i > a) { const r = equity / prevEq - 1; if (isFinite(r)) { sum += r; sum2 += r * r; nRet++; } }
      prevEq = Math.max(equity, 1e-9);
      if (equity > peak) peak = equity;
      maxDD = Math.max(maxDD, 1 - equity / peak);
      if (eq) eq.push(equity);
      if (ruined) { if (eq) for (let j = i + 1; j <= b; j++) eq.push(0); break; }

      // ---- entry
      if (!pos && i < b - 1 && i - lastClose > cfg.cooldown) {
        const rank = ds.ivRank[i];
        if (rank < cfg.iv_rank_min || rank > cfg.iv_rank_max) continue;
        if (smaArr) {
          const m = smaArr[i]; if (!isFinite(m)) continue;
          if (cfg.trend_filter === 'above_sma' && !(S > m)) continue;
          if (cfg.trend_filter === 'below_sma' && !(S < m)) continue;
        }
        // Naked structures: margin does not depend on strikes, so skip the strike search when unaffordable
        if (nakedLegs && Math.floor((equity * cfg.risk_per_trade) / (S * H.lot * (H.nakedMargin + H.extraNakedMargin * (nakedLegs - 1)))) < 1) continue;
        const expiry = Math.min(i + dteTd, ds.n - 1);
        const T = (expiry - i) / 252; if (T <= 0) continue;
        const legs = buildLegs(cfg, S, T, ds.iv[i]); if (!legs.length) continue;
        const prices = legs.map((l) => bsPrice(l.type, S, l.K, T, smile(ds.iv[i], S, l.K, T)));
        if (prices.some((p) => !(p > 0.05))) continue;           // untradeable (worthless) strike
        const perLot = riskPerLot(legs, prices, S);
        const lots = Math.floor((equity * cfg.risk_per_trade) / perLot);
        if (lots < 1) continue;
        const entryVal = legs.reduce((s, l, k) => s + l.side * prices[k], 0) * lots * H.lot;
        const entryCost = tradeCost(legs, prices, lots);
        cash += -entryVal - entryCost;
        pos = { legs, lots, entryVal, entryCost, expiry, open: i };
      }
    }
    const days = Math.max(nRet, 1);
    const final = eq ? eq[eq.length - 1] : prevEq;
    const cagr = ruined ? -1 : Math.pow(Math.max(final, 1e-9) / H.capital, 252 / days) - 1;
    const mean = sum / days, sd = Math.sqrt(Math.max(sum2 / days - mean * mean, 0));
    return {
      cagr, maxDD: ruined ? 1 : maxDD, sharpe: sd > 0 ? (mean / sd) * Math.sqrt(252) : 0,
      trades, winRate: trades ? wins / trades : 0, exposure: (inPos) / Math.max(b - a + 1, 1),
      final, ruined, equity: eq, tradeLog, from: ds.dates[a], to: ds.dates[b],
    };
  }

  /** Evaluate a config on train / val / test and score it per the program's objective. */
  function evaluate(ds, cfg, program) {
    const t0 = performance.now();
    const res = {};
    for (const k of ['train', 'val', 'test']) {
      const [a, b] = ds.splits[k];
      const r = run(ds, cfg, a, b);
      res[k] = { cagr: r.cagr, maxDD: r.maxDD, sharpe: r.sharpe, trades: r.trades, winRate: r.winRate, exposure: r.exposure, ruined: r.ruined };
    }
    const obj = program.objective || 'robust';
    let score = obj === 'val' ? res.val.cagr : Math.min(res.train.cagr, res.val.cagr);
    const reasons = [];
    const ddSplits = obj === 'val' ? ['val'] : ['train', 'val'];
    for (const k of ddSplits) {
      if (res[k].maxDD > program.maxDD) reasons.push(`${k} drawdown ${(res[k].maxDD * 100).toFixed(1)}% > ${(program.maxDD * 100).toFixed(0)}% limit`);
      if (res[k].trades < program.minTrades) reasons.push(`${k} only ${res[k].trades} trades (< ${program.minTrades})`);
    }
    const ok = reasons.length === 0;
    return { ...res, score: ok ? score : -Infinity, rawScore: score, ok, reason: reasons.join('; '), ms: performance.now() - t0 };
  }

  window.BT = { H, SPACE, STRUCTURES, DEFAULT_CONFIG, clampConfig, configKey, synthMarket, parseCSV, fillIv, prepare, buildLegs, riskPerLot, run, evaluate, smile };
})();
