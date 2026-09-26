/* Data feeds for the Live page.
   Both feeds return the same normalised chain:
   { source, underlying, spot, updatedAt (ms), lotSize,
     expiries: [{ expiry:'YYYY-MM-DD', future, atmStrike, atmIv (decimal),
                  strikes: [{ K, CE:{ltp, iv, delta, gamma, theta, vega, oi, volume}, PE:{...} }] }] } */
(function () {
  'use strict';
  const { bs, rng } = OD;

  const UNDERLYINGS = {
    NIFTY: { spot: 25000, step: 50, lot: 75, iv: 0.125, weekly: true },
    BANKNIFTY: { spot: 55000, step: 100, lot: 35, iv: 0.14, weekly: false },
    FINNIFTY: { spot: 26500, step: 50, lot: 65, iv: 0.13, weekly: false },
    MIDCPNIFTY: { spot: 13000, step: 25, lot: 140, iv: 0.16, weekly: false },
    SENSEX: { spot: 82000, step: 100, lot: 20, iv: 0.13, weekly: true },
  };

  /** Normalise IV to a decimal whether the source sends 12.5 or 0.125. */
  const ivDec = (v) => (v == null || !isFinite(v) ? NaN : (v > 3 ? v / 100 : +v));

  /** Years from now until 15:30 IST on the expiry date. */
  function yearsToExpiry(expiry, now = Date.now()) {
    const t = Date.parse(expiry + 'T15:30:00+05:30');
    return Math.max((t - now) / (365 * 24 * 3600 * 1000), 0);
  }

  // ------------------------------------------------------------ bridge feed
  class BridgeFeed {
    constructor(base) { this.base = String(base || '').replace(/\/+$/, ''); this.name = 'sensibull'; }
    async req(path, { method = 'GET', body, timeout = 12000 } = {}) {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), timeout);
      try {
        const r = await fetch(this.base + path, {
          method, signal: ctl.signal,
          headers: body ? { 'Content-Type': 'application/json' } : {},
          body: body ? JSON.stringify(body) : undefined,
        });
        let data = null; try { data = await r.json(); } catch { /* non-JSON */ }
        if (!r.ok || (data && data.ok === false)) throw new Error((data && data.error) || `Bridge answered HTTP ${r.status}`);
        return data;
      } catch (e) {
        if (e.name === 'AbortError') throw new Error('Bridge did not answer in time');
        if (e instanceof TypeError) throw new Error(`Cannot reach the bridge at ${this.base}. Is it running?`);
        throw e;
      } finally { clearTimeout(t); }
    }
    status() { return this.req('/api/status', { timeout: 2500 }); }
    login(body) { return this.req('/api/login', { method: 'POST', body, timeout: 20000 }); }
    logout() { return this.req('/api/logout', { method: 'POST', body: {} }); }
    async chain(underlying, token) {
      const q = new URLSearchParams({ underlying }); if (token) q.set('token', token);
      const d = await this.req('/api/chain?' + q);
      return normaliseBridgeChain(d.chain);
    }
  }

  function normaliseBridgeChain(c) {
    const side = (o) => o ? ({
      ltp: num(o.ltp), iv: ivDec(o.iv), delta: num(o.delta), gamma: num(o.gamma), theta: num(o.theta), vega: num(o.vega),
      oi: num(o.oi), volume: num(o.volume), symbol: o.tradingsymbol || '',
    }) : null;
    return {
      source: 'sensibull', underlying: c.underlying, spot: num(c.spot), lotSize: c.lot_size || null,
      updatedAt: c.updated_at ? Date.parse(c.updated_at) || Date.now() : Date.now(),
      expiries: (c.expiries || []).map((e) => ({
        expiry: e.expiry, future: num(e.future), atmStrike: num(e.atm_strike), atmIv: ivDec(e.atm_iv),
        strikes: (e.strikes || []).map((s) => ({ K: +s.strike, CE: side(s.CE), PE: side(s.PE) })).sort((a, b) => a.K - b.K),
      })),
    };
  }
  const num = (v) => (v == null || v === '' ? NaN : +v);

  // ------------------------------------------------------------ simulated feed
  class SimFeed {
    constructor(seed = Date.now() % 1e9) {
      this.name = 'sim';
      this.r = rng(seed);
      this.state = {};
      for (const [u, c] of Object.entries(UNDERLYINGS)) this.state[u] = { spot: c.spot * (0.98 + 0.04 * this.r()), iv: c.iv, last: Date.now(), oiSeed: Math.floor(this.r() * 1e6) };
    }
    step(u) {
      const s = this.state[u]; const now = Date.now();
      const secs = Math.min((now - s.last) / 1000, 30); s.last = now;
      // Market-hours vol, sped up 4x so movement is visible
      const dt = (secs * 4) / (252 * 6.25 * 3600);
      const z = this.r.gauss();
      s.spot *= Math.exp(-0.5 * s.iv * s.iv * dt + s.iv * Math.sqrt(dt) * z);
      s.iv = Math.max(0.07, Math.min(0.45, s.iv + (-0.25 * z) * 0.02 * Math.sqrt(secs / 60) + (UNDERLYINGS[u].iv - s.iv) * 0.002 * secs));
    }
    expiries(u, now = new Date()) {
      const out = [];
      const ist = new Date(now.getTime() + 5.5 * 3600e3); // shift to IST calendar date
      const d = new Date(Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate()));
      const iso = (x) => x.toISOString().slice(0, 10);
      const isPast = (x) => yearsToExpiry(iso(x), now.getTime()) <= 0;
      if (UNDERLYINGS[u].weekly) {
        const x = new Date(d); while (x.getUTCDay() !== 2 || isPast(x)) x.setUTCDate(x.getUTCDate() + 1);
        for (let i = 0; i < 4; i++) { out.push(iso(x)); x.setUTCDate(x.getUTCDate() + 7); }
      }
      // monthly: last Tuesday of the month, three months
      for (let m = 0; out.length < (UNDERLYINGS[u].weekly ? 6 : 3) && m < 6; m++) {
        const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + m + 1, 0));
        while (last.getUTCDay() !== 2) last.setUTCDate(last.getUTCDate() - 1);
        if (!isPast(last) && !out.includes(iso(last))) out.push(iso(last));
      }
      return out.sort();
    }
    async chain(u) {
      this.step(u);
      const cfg = UNDERLYINGS[u]; const s = this.state[u]; const S = s.spot;
      const noise = rng(s.oiSeed); const now = Date.now();
      const expiries = this.expiries(u).map((expiry, ei) => {
        const T = Math.max(yearsToExpiry(expiry, now), 0.5 / 365);
        const F = S * Math.exp(OD.RISK_FREE * T);
        const atmIv = s.iv * (1 + 0.04 * ei);
        const atmK = Math.round(S / cfg.step) * cfg.step;
        const strikes = [];
        for (let i = -40; i <= 40; i++) {
          const K = atmK + i * cfg.step;
          const m = Math.log(K / F) / Math.max(Math.sqrt(T), 0.05);
          const iv = Math.max(0.05, atmIv * (1 - 0.35 * m + 0.45 * m * m));
          const row = { K };
          for (const type of ['C', 'P']) {
            // puts trade slightly richer than calls (bid for protection), as on real index chains
            const ivT = type === 'P' ? iv + 0.004 : iv;
            const g = bs(type, S, K, T, ivT);
            const otm = type === 'C' ? K >= S : K <= S;
            const dist = Math.abs(K - S) / (S * Math.max(atmIv * Math.sqrt(T), 0.01));
            const round = K % (cfg.step * 10) === 0 ? 1.8 : K % (cfg.step * 2) === 0 ? 1.2 : 0.8;
            const oi = (otm ? 1 : 0.35) * Math.exp(-0.5 * (dist / 1.6) ** 2) * round * (0.8 + 0.4 * noise()) * 1.2e6 / (1 + ei);
            const tick = Math.max(0.05, Math.round(g.price * 20) / 20);
            row[type === 'C' ? 'CE' : 'PE'] = {
              ltp: tick, iv: ivT, delta: g.delta, gamma: g.gamma, theta: g.theta, vega: g.vega,
              oi: Math.round(oi / cfg.lot) * cfg.lot, volume: Math.round(oi * (1.5 + noise()) / cfg.lot) * cfg.lot, symbol: '',
            };
          }
          strikes.push(row);
        }
        return { expiry, future: F, atmStrike: atmK, atmIv, strikes };
      });
      return { source: 'sim', underlying: u, spot: S, lotSize: cfg.lot, updatedAt: now, expiries };
    }
  }

  // ------------------------------------------------------------ analytics
  function chainStats(exp, spot) {
    let ceOi = 0, peOi = 0;
    for (const s of exp.strikes) { ceOi += s.CE?.oi || 0; peOi += s.PE?.oi || 0; }
    // Max pain: strike minimising total intrinsic value paid out to option holders
    let best = null, bestPay = Infinity;
    for (const t of exp.strikes) {
      let pay = 0;
      for (const s of exp.strikes) {
        pay += (s.CE?.oi || 0) * Math.max(t.K - s.K, 0) + (s.PE?.oi || 0) * Math.max(s.K - t.K, 0);
      }
      if (pay < bestPay) { bestPay = pay; best = t.K; }
    }
    let atmK = exp.atmStrike;
    if (!isFinite(atmK) && exp.strikes.length) atmK = exp.strikes.reduce((a, s) => (Math.abs(s.K - spot) < Math.abs(a - spot) ? s.K : a), exp.strikes[0].K);
    let atmIv = exp.atmIv;
    if (!isFinite(atmIv)) {
      const row = exp.strikes.find((s) => s.K === atmK);
      atmIv = row ? ((row.CE?.iv || NaN) + (row.PE?.iv || NaN)) / 2 : NaN;
    }
    const T = yearsToExpiry(exp.expiry);
    return { pcr: ceOi ? peOi / ceOi : NaN, ceOi, peOi, maxPain: best, atmK, atmIv, T, move: spot * atmIv * Math.sqrt(T) };
  }

  window.Feeds = { UNDERLYINGS, BridgeFeed, SimFeed, chainStats, yearsToExpiry, ivDec, normaliseBridgeChain };
})();
