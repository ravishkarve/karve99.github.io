/* Options Desk core: option math, formatting, theme, payoff charts.
   Plain script (no build step) - exposes window.OD. */
(function () {
  'use strict';

  // ---------------------------------------------------------------- math
  const RISK_FREE = 0.06;          // annual, continuously compounded (approximate Indian T-bill yield)
  const DAYS_PER_YEAR = 365;

  // Normal CDF via erf (Abramowitz & Stegun 7.1.26 on |x|, max error ~1.5e-7)
  function erf(x) {
    const s = x < 0 ? -1 : 1; x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  const ncdf = (x) => 0.5 * (1 + erf(x / Math.SQRT2));
  const npdf = (x) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);

  /**
   * Black-Scholes price and Greeks for a European option.
   * type 'C' | 'P'; S spot; K strike; T years; r rate; sigma vol (decimal).
   * theta is per calendar day, vega per 1 vol point (1%).
   */
  function bs(type, S, K, T, sigma, r = RISK_FREE) {
    if (!(S > 0) || !(K > 0)) return { price: 0, delta: 0, gamma: 0, theta: 0, vega: 0 };
    if (T <= 1e-9 || sigma <= 1e-9) {
      const intrinsic = type === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
      const delta = type === 'C' ? (S > K ? 1 : 0) : (S < K ? -1 : 0);
      return { price: intrinsic, delta, gamma: 0, theta: 0, vega: 0 };
    }
    const sq = Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sq);
    const d2 = d1 - sigma * sq;
    const disc = Math.exp(-r * T);
    let price, delta, theta;
    if (type === 'C') {
      price = S * ncdf(d1) - K * disc * ncdf(d2);
      delta = ncdf(d1);
      theta = -S * npdf(d1) * sigma / (2 * sq) - r * K * disc * ncdf(d2);
    } else {
      price = K * disc * ncdf(-d2) - S * ncdf(-d1);
      delta = ncdf(d1) - 1;
      theta = -S * npdf(d1) * sigma / (2 * sq) + r * K * disc * ncdf(-d2);
    }
    return {
      price: Math.max(price, 0),
      delta,
      gamma: npdf(d1) / (S * sigma * sq),
      theta: theta / DAYS_PER_YEAR,
      vega: S * npdf(d1) * sq / 100,
    };
  }

  /** Fast paths used in hot loops (backtests, strike searches). */
  function bsPrice(type, S, K, T, sigma, r = RISK_FREE) {
    if (T <= 1e-9 || sigma <= 1e-9) return type === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
    const sq = sigma * Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq;
    const d2 = d1 - sq; const disc = K * Math.exp(-r * T);
    const p = type === 'C' ? S * ncdf(d1) - disc * ncdf(d2) : disc * ncdf(-d2) - S * ncdf(-d1);
    return p > 0 ? p : 0;
  }
  function bsDelta(type, S, K, T, sigma, r = RISK_FREE) {
    if (T <= 1e-9 || sigma <= 1e-9) return type === 'C' ? (S > K ? 1 : 0) : (S < K ? -1 : 0);
    const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
    return type === 'C' ? ncdf(d1) : ncdf(d1) - 1;
  }

  /** Implied volatility by bisection. Returns decimal or NaN. */
  function impliedVol(type, price, S, K, T, r = RISK_FREE) {
    if (!(price > 0) || T <= 0) return NaN;
    const intrinsic = type === 'C' ? Math.max(S - K * Math.exp(-r * T), 0) : Math.max(K * Math.exp(-r * T) - S, 0);
    if (price < intrinsic - 1e-6) return NaN;
    let lo = 1e-4, hi = 5;
    for (let i = 0; i < 80; i++) {
      const mid = 0.5 * (lo + hi);
      if (bsPrice(type, S, K, T, mid, r) > price) hi = mid; else lo = mid;
    }
    return 0.5 * (lo + hi);
  }

  /** Strike whose |delta| equals target (continuous), for option type at vol fn volAt(K). */
  function strikeForDelta(type, S, T, target, volAt, r = RISK_FREE) {
    // |delta| decreases as the option goes further OTM: calls -> higher K, puts -> lower K
    let lo = S * 0.3, hi = S * 3;
    for (let i = 0; i < 36; i++) {
      const mid = 0.5 * (lo + hi);
      const d = Math.abs(bsDelta(type, S, mid, T, volAt(mid), r));
      if (type === 'C') { if (d > target) lo = mid; else hi = mid; }
      else { if (d > target) hi = mid; else lo = mid; }
    }
    return 0.5 * (lo + hi);
  }

  // Seedable PRNG (mulberry32) + Gaussian
  function rng(seed) {
    let a = (seed >>> 0) || 1;
    const next = () => {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    let spare = null;
    next.gauss = () => {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u, v, s;
      do { u = next() * 2 - 1; v = next() * 2 - 1; s = u * u + v * v; } while (s >= 1 || s === 0);
      const m = Math.sqrt(-2 * Math.log(s) / s);
      spare = v * m; return u * m;
    };
    return next;
  }

  // ---------------------------------------------------------------- payoff
  /**
   * legs: [{type:'C'|'P'|'F', side:+1|-1, K, lots, premium, iv, T}]  (T in years, iv decimal)
   * Returns P&L in rupees for spot x, at expiry (atExpiry=true) or after `elapsed` years.
   */
  function legValue(leg, x, T) {
    if (leg.type === 'F') return x;
    return bs(leg.type, x, leg.K, Math.max(T, 0), leg.iv || 0.15).price;
  }
  function positionPnl(legs, x, lotSize, elapsed = null) {
    let pnl = 0;
    for (const l of legs) {
      const T = elapsed === null ? 0 : Math.max(l.T - elapsed, 0);
      const v = l.type === 'F' ? x : (elapsed === null
        ? (l.type === 'C' ? Math.max(x - l.K, 0) : Math.max(l.K - x, 0))
        : legValue(l, x, T));
      pnl += l.side * l.lots * lotSize * (v - l.premium);
    }
    return pnl;
  }

  /** Summary stats over a price grid: max profit/loss (with unlimited detection), breakevens. */
  function payoffStats(legs, lotSize, lo, hi, n = 600) {
    const xs = [], ys = [];
    for (let i = 0; i <= n; i++) {
      const x = lo + (hi - lo) * i / n;
      xs.push(x); ys.push(positionPnl(legs, x, lotSize));
    }
    // Prices can rise without limit but cannot fall below zero: the slope above the
    // highest strike decides "unlimited"; the downside extreme is the P&L at price 0.
    let slopeHi = 0;
    for (const l of legs) if (l.type === 'C' || l.type === 'F') slopeHi += l.side * l.lots * lotSize;
    const y0 = positionPnl(legs, 0, lotSize);
    const maxP = Math.max(y0, ...ys), maxL = Math.min(y0, ...ys);
    const unlimitedProfit = slopeHi > 1e-9;
    const unlimitedLoss = slopeHi < -1e-9;
    const be = [];
    for (let i = 1; i < xs.length; i++) {
      if ((ys[i - 1] < 0 && ys[i] >= 0) || (ys[i - 1] > 0 && ys[i] <= 0)) {
        const t = ys[i - 1] / (ys[i - 1] - ys[i]);
        be.push(xs[i - 1] + t * (xs[i] - xs[i - 1]));
      }
    }
    return { xs, ys, maxProfit: unlimitedProfit ? Infinity : maxP, maxLoss: unlimitedLoss ? -Infinity : maxL, breakevens: be };
  }

  // ---------------------------------------------------------------- format
  const inr0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
  const inr2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmt = {
    rs(v, dp = 0) {
      if (v === Infinity) return 'Unlimited';
      if (v === -Infinity) return 'Unlimited';
      if (!isFinite(v)) return '-';
      const s = (dp ? inr2 : inr0).format(Math.abs(v));
      return (v < 0 ? '−₹' : '₹') + s;
    },
    n(v, dp = 2) { return isFinite(v) ? (dp ? inr2.format(v) : inr0.format(v)) : '-'; },
    px(v) { return isFinite(v) ? v.toFixed(2) : '-'; },
    pct(v, dp = 1) { return isFinite(v) ? (v * 100).toFixed(dp) + '%' : '-'; },
    signPct(v, dp = 1) { return isFinite(v) ? (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(dp) + '%' : '-'; },
    compact(v) {
      if (!isFinite(v)) return '-';
      const a = Math.abs(v);
      if (a >= 1e7) return (v / 1e7).toFixed(2) + ' Cr';
      if (a >= 1e5) return (v / 1e5).toFixed(2) + ' L';
      if (a >= 1e3) return (v / 1e3).toFixed(1) + 'k';
      return v.toFixed(0);
    },
    cls(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : ''; },
  };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------------------------------------------------------------- storage (never required)
  const store = {
    get(k, d = null) { try { const v = localStorage.getItem('od.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('od.' + k, JSON.stringify(v)); } catch { /* ignore */ } },
    del(k) { try { localStorage.removeItem('od.' + k); } catch { /* ignore */ } },
    sget(k, d = null) { try { const v = sessionStorage.getItem('od.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    sset(k, v) { try { sessionStorage.setItem('od.' + k, JSON.stringify(v)); } catch { /* ignore */ } },
  };

  // ---------------------------------------------------------------- theme
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute('data-theme', t);
    else document.documentElement.removeAttribute('data-theme');
    document.dispatchEvent(new CustomEvent('od:theme'));
  }
  applyTheme(store.get('theme'));
  function isDark() {
    const t = document.documentElement.getAttribute('data-theme');
    if (t) return t === 'dark';
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function initTopbar() {
    const btn = document.getElementById('theme-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        const next = isDark() ? 'light' : 'dark';
        store.set('theme', next); applyTheme(next);
      });
    }
    if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => document.dispatchEvent(new CustomEvent('od:theme')));
  }

  // ---------------------------------------------------------------- charts
  function chartDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = css('--muted');
    Chart.defaults.borderColor = css('--grid');
    Chart.defaults.animation = false;
    Chart.defaults.plugins.tooltip.backgroundColor = isDark() ? '#1d232c' : '#ffffff';
    Chart.defaults.plugins.tooltip.titleColor = css('--text');
    Chart.defaults.plugins.tooltip.bodyColor = css('--text');
    Chart.defaults.plugins.tooltip.borderColor = css('--border');
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 8;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.elements.line.borderWidth = 2;
    Chart.defaults.elements.point.radius = 0;
    Chart.defaults.elements.point.hoverRadius = 4;
  }

  /** Vertical line plugin at x = spot (options.plugins.spotLine = {x, label}) */
  const spotLinePlugin = {
    id: 'spotLine',
    afterDatasetsDraw(chart, _args, opts) {
      if (!opts || opts.x == null) return;
      const xs = chart.scales.x; const ya = chart.chartArea;
      const px = xs.getPixelForValue(opts.x);
      if (px < ya.left || px > ya.right) return;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = css('--muted'); ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, ya.top); ctx.lineTo(px, ya.bottom); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = css('--muted'); ctx.font = '11px Inter, sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(opts.label || 'Spot', px, ya.top + 10);
      ctx.restore();
    },
  };

  /**
   * Payoff chart. Creates or updates a Chart on canvas.
   * series: [{label, data:[{x,y}], color, dashed, fill}]
   */
  function payoffChart(canvas, series, { spot = null, xLabel = 'Underlying price at expiry', yLabel = 'Profit / loss (₹)' } = {}) {
    if (!window.Chart) { canvas.parentElement.innerHTML = '<p class="muted small">Charts need Chart.js, which failed to load. Check your connection.</p>'; return null; }
    chartDefaults();
    const good = css('--good'), bad = css('--bad');
    const datasets = series.map((s) => ({
      label: s.label,
      data: s.data,
      borderColor: s.color,
      borderDash: s.dashed ? [5, 4] : [],
      borderWidth: s.width || 2,
      fill: s.fill ? { target: 'origin', above: hexA(good, 0.13), below: hexA(bad, 0.13) } : false,
      tension: 0,
      parsing: false,
    }));
    const opts = {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', axis: 'x', intersect: false },
      scales: {
        x: { type: 'linear', title: { display: true, text: xLabel }, grid: { display: false }, ticks: { maxTicksLimit: 8, callback: (v) => fmt.n(v, 0) } },
        y: {
          title: { display: true, text: yLabel }, ticks: { maxTicksLimit: 7, callback: (v) => fmt.compact(v) },
          grid: { color: (c) => (c.tick && c.tick.value === 0 ? css('--muted') : css('--grid')) },
        },
      },
      plugins: {
        spotLine: { x: spot },
        tooltip: {
          callbacks: {
            title: (items) => 'At ' + fmt.n(items[0].parsed.x, 0),
            label: (it) => ` ${it.dataset.label}: ${fmt.rs(it.parsed.y)}`,
          },
        },
      },
    };
    if (canvas._chart) {
      canvas._chart.data.datasets = datasets;
      canvas._chart.options = opts;
      canvas._chart.update();
      return canvas._chart;
    }
    canvas._chart = new Chart(canvas, { type: 'line', data: { datasets }, options: opts, plugins: [spotLinePlugin] });
    return canvas._chart;
  }

  function hexA(color, a) {
    const c = color.trim();
    if (c.startsWith('#')) {
      let h = c.slice(1); if (h.length === 3) h = h.split('').map((x) => x + x).join('');
      const n = parseInt(h, 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }
    return c;
  }

  function toast(msg, kind = '') {
    let el = document.getElementById('od-toast');
    if (!el) {
      el = document.createElement('div'); el.id = 'od-toast'; el.setAttribute('role', 'status');
      el.style.cssText = 'position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:50;padding:10px 16px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.2);font-size:.9rem;max-width:calc(100vw - 32px);transition:opacity .3s';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.background = kind === 'bad' ? css('--bad') : css('--text');
    el.style.color = css('--bg');
    el.style.opacity = '1';
    clearTimeout(el._t); el._t = setTimeout(() => { el.style.opacity = '0'; }, 3200);
  }

  // ---------------------------------------------------------------- phone pairing token
  // The bridge's phone link ends in #bridge-token=...; keep it for later requests and strip it from the URL.
  (function captureBridgeToken() {
    const m = /(?:^|[#&])bridge-token=([\w-]+)/.exec(location.hash);
    if (!m) return;
    store.set('bridgeToken', m[1]);
    try { history.replaceState(null, '', location.pathname + location.search); } catch { /* ignore */ }
  })();
  const bridgeHeaders = () => { const t = store.get('bridgeToken'); return t ? { 'X-Bridge-Token': t } : {}; };

  window.OD = {
    bridgeHeaders,
    RISK_FREE, DAYS_PER_YEAR, ncdf, npdf, bs, bsPrice, bsDelta, impliedVol, strikeForDelta, rng,
    positionPnl, payoffStats, fmt, esc, store, isDark, css, hexA, initTopbar, chartDefaults, payoffChart, spotLinePlugin, toast,
  };
  document.addEventListener('DOMContentLoaded', initTopbar);
})();
