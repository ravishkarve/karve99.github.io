/* Gas Turbine Design Studio - front end.
 * Internal state is kept in pyCycle's native US-customary units; the UI converts for display.
 */
(() => {
  'use strict';

  // ======================================================================= //
  //  Units
  // ======================================================================= //
  const U = {
    none: { US: ['', 1], SI: ['', 1] },
    pct: { US: ['%', 100], SI: ['%', 100] },
    alt: { US: ['ft', 1], SI: ['m', 0.3048] },
    temp: { US: ['°R', 1], SI: ['K', 1 / 1.8] },
    dtemp: { US: ['°R', 1], SI: ['K', 1 / 1.8] },
    thrust: { US: ['lbf', 1], SI: ['kN', 4.4482216e-3] },
    tsfc: { US: ['lbm/(lbf·h)', 1], SI: ['g/(kN·s)', 28.32546] },
    flow: { US: ['lbm/s', 1], SI: ['kg/s', 0.45359237] },
    press: { US: ['psia', 1], SI: ['kPa', 6.894757] },
    area: { US: ['in²', 1], SI: ['m²', 0.00064516] },
    length: { US: ['in', 1], SI: ['m', 0.0254] },
    power: { US: ['hp', 1], SI: ['kW', 0.7456999] },
    vel: { US: ['ft/s', 1], SI: ['m/s', 0.3048] },
    fsp: { US: ['lbf·s/lbm', 1], SI: ['N·s/kg', 9.80665] },
    entropy: { US: ['Btu/(lbm·°R)', 1], SI: ['kJ/(kg·K)', 4.1868] },
    rpm: { US: ['rpm', 1], SI: ['rpm', 1] },
  };
  const unit = (q) => U[q][state.units][0];
  const toD = (q, v) => (v == null ? null : v * U[q][state.units][1]);
  const fromD = (q, v) => v / U[q][state.units][1];

  function fmt(v, sig = 4) {
    if (v == null || !isFinite(v)) return '–';
    const a = Math.abs(v);
    if (a === 0) return '0';
    const mag = Math.floor(Math.log10(a));
    const dec = Math.max(0, Math.min(6, sig - 1 - mag));
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  const fq = (q, v, sig) => fmt(toD(q, v), sig);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ======================================================================= //
  //  Atmosphere (ISA) for instant feedback in the UI
  // ======================================================================= //
  function isa(altFt, dTs = 0) {
    const h = altFt * 0.3048;
    let T, P;
    if (h <= 11000) { T = 288.15 - 0.0065 * h; P = 101325 * Math.pow(T / 288.15, 5.25588); }
    else { T = 216.65; P = 22632.06 * Math.exp(-(h - 11000) / 6341.62); }
    T += dTs / 1.8;
    const a = Math.sqrt(1.4 * 287.05 * T);
    return { T_K: T, P_Pa: P, a, rho: P / (287.05 * T) };
  }
  // MIL-E-5008B inlet recovery for supersonic flight, times subsonic duct recovery
  const ramRecovery = (MN, base) => (MN > 1 ? base * (1 - 0.075 * Math.pow(MN - 1, 1.35)) : base);

  // ======================================================================= //
  //  Presets
  // ======================================================================= //
  const TECH = {
    '1970s': { label: '1970s', desc: 'First-generation high-bypass & military turbojets (JT9D, CFM56-2 era)',
      fan_eff: 0.86, lpc_eff: 0.86, hpc_eff: 0.835, hpt_eff: 0.86, lpt_eff: 0.88, comp_eff: 0.82, turb_eff: 0.85,
      T4max: 2950, T3max: 1460, burner_dPqP: 0.05, Cv: 0.985, ram: 0.993, HPX: 150 },
    '1990s': { label: '1990s', desc: 'Mature designs with 3-D aero and single-crystal blades (CFM56-7, V2500, GE90)',
      fan_eff: 0.885, lpc_eff: 0.885, hpc_eff: 0.86, hpt_eff: 0.88, lpt_eff: 0.905, comp_eff: 0.84, turb_eff: 0.87,
      T4max: 3200, T3max: 1560, burner_dPqP: 0.045, Cv: 0.99, ram: 0.996, HPX: 200 },
    '2020s': { label: '2020s', desc: 'Current state of the art: ceramic coatings, 3-D printed parts (LEAP, GTF, GE9X)',
      fan_eff: 0.915, lpc_eff: 0.905, hpc_eff: 0.875, hpt_eff: 0.895, lpt_eff: 0.925, comp_eff: 0.86, turb_eff: 0.89,
      T4max: 3450, T3max: 1750, burner_dPqP: 0.04, Cv: 0.993, ram: 0.998, HPX: 250 },
  };

  const PRESETS = {
    airliner: {
      label: 'Single-aisle airliner', icon: '✈', desc: '150–200 seats, 2 engines. CFM56 / LEAP / PW1100G class.',
      arch: 'turbofan', tech: '2020s',
      req: { alt: 35000, MN: 0.78, Fn: 5000, TSFC: 0.50, Fn_TO: 27000, TO_alt: 0, TO_MN: 0, TO_dTs: 27, D_max: 80, SM_min: 8 },
      cycle: { OPR: 38, FPR: 1.5, LPC_PR: 2.0, BPR: 9, T4: 2750 },
    },
    bizjet: {
      label: 'Business jet', icon: '🛩', desc: 'Long-range business jet, 2 aft-mounted engines. PW300 / HTF7000 class.',
      arch: 'turbofan', tech: '1990s',
      req: { alt: 41000, MN: 0.8, Fn: 1200, TSFC: 0.64, Fn_TO: 6500, TO_alt: 0, TO_MN: 0, TO_dTs: 27, D_max: 34, SM_min: 8 },
      cycle: { OPR: 24, FPR: 1.7, LPC_PR: 1.6, BPR: 5.5, T4: 2600 },
    },
    uav: {
      label: 'Small UAV / target drone', icon: '🎯', desc: 'Expendable, low-cost, short life. Simple single-spool turbojet.',
      arch: 'turbojet', tech: '1970s',
      req: { alt: 20000, MN: 0.7, Fn: 350, TSFC: 1.25, Fn_TO: 750, TO_alt: 0, TO_MN: 0, TO_dTs: 0, D_max: 12, SM_min: 8 },
      cycle: { OPR: 7, FPR: 1.6, LPC_PR: 1.8, BPR: 5, T4: 2500 },
    },
    supersonic: {
      label: 'Supersonic trainer', icon: '⚡', desc: 'Dry (non-afterburning) turbojet for sustained Mach 1.4 flight.',
      arch: 'turbojet', tech: '1990s',
      req: { alt: 36089, MN: 1.4, Fn: 2200, TSFC: 1.42, Fn_TO: 4800, TO_alt: 0, TO_MN: 0, TO_dTs: 27, D_max: 20, SM_min: 6 },
      cycle: { OPR: 9, FPR: 1.6, LPC_PR: 1.8, BPR: 5, T4: 2900 },
    },
  };

  const SWEEP_VARS = {
    OPR: { label: 'Overall pressure ratio (OPR)', q: 'none', turbofan: [20, 55], turbojet: [4, 20] },
    T4: { label: 'Turbine inlet temperature T4', q: 'temp', turbofan: [2600, 3300], turbojet: [2100, 3000] },
    BPR: { label: 'Bypass ratio (BPR)', q: 'none', turbofan: [4, 13] },
    FPR: { label: 'Fan pressure ratio (FPR)', q: 'none', turbofan: [1.35, 1.9] },
  };

  const STEPS = [
    { id: 'req', phase: 'Define', title: 'Mission & requirements', desc: 'Top-level objectives' },
    { id: 'arch', phase: 'Define', title: 'Architecture', desc: 'Choose the engine concept' },
    { id: 'tech', phase: 'Define', title: 'Technology level', desc: 'Component performance & limits' },
    { id: 'cycle', phase: 'Design', title: 'Cycle selection', desc: 'Parametric trade studies' },
    { id: 'design', phase: 'Design', title: 'Design point & sizing', desc: 'Size the engine in pyCycle' },
    { id: 'offdesign', phase: 'Analyse', title: 'Off-design performance', desc: 'Takeoff, climb, throttle' },
    { id: 'review', phase: 'Analyse', title: 'Requirements check', desc: 'Verify, iterate, export' },
  ];

  // ======================================================================= //
  //  State
  // ======================================================================= //
  const STORE_KEY = 'gtds-state-v2';

  function defaultState() {
    const p = PRESETS.airliner;
    return {
      units: 'SI', step: 0, maxStep: 0,
      preset: 'airliner',
      req: { ...p.req },
      arch: p.arch,
      techLevel: p.tech,
      tech: { ...TECH[p.tech] },
      cycle: { ...p.cycle },
      sweep: { var: 'OPR', from: null, to: null, n: 6, carpetVar: 'T4', carpetVals: '', results: null, key: null },
      quick: null,
      design: null,       // {key, data}
      odPoints: null, odEdited: false, odResults: null,
      hook: { point: 0, n: 7, lowFrac: 0.72, results: null, key: null },
    };
  }

  let state = defaultState();
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (saved && saved.req && saved.cycle) state = Object.assign(defaultState(), saved);
  } catch (e) { /* storage unavailable */ }

  let saveTimer = null;
  function save() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
    }, 250);
  }

  function designInputs() {
    const r = state.req, t = state.tech, c = state.cycle;
    const d = {
      alt: r.alt, MN: r.MN, dTs: 0, Fn: r.Fn, T4: c.T4, OPR: c.OPR,
      ram_recovery: +ramRecovery(r.MN, t.ram).toFixed(5), burner_dPqP: t.burner_dPqP, Cv: t.Cv,
    };
    if (state.arch === 'turbojet') Object.assign(d, { comp_eff: t.comp_eff, turb_eff: t.turb_eff });
    else Object.assign(d, {
      FPR: c.FPR, LPC_PR: c.LPC_PR, BPR: c.BPR, fan_eff: t.fan_eff, lpc_eff: t.lpc_eff,
      hpc_eff: t.hpc_eff, hpt_eff: t.hpt_eff, lpt_eff: t.lpt_eff, HPX: t.HPX,
    });
    return d;
  }
  const designKey = () => JSON.stringify([state.arch, designInputs()]);
  const designCurrent = () => state.design && state.design.key === designKey();

  function defaultOdPoints() {
    const r = state.req, t = state.tech;
    return [
      { name: r.TO_dTs > 0 ? 'Takeoff (hot day)' : 'Takeoff (ISA day)', role: 'takeoff', alt: r.TO_alt, MN: r.TO_MN, dTs: r.TO_dTs, T4: t.T4max },
      { name: 'Top of climb', role: 'toc', alt: r.alt, MN: r.MN, dTs: 0, T4: t.T4max - 150 },
      { name: 'Cruise (design check)', role: 'cruise', alt: r.alt, MN: r.MN, dTs: 0, T4: state.cycle.T4 },
      { name: 'Part-power cruise', role: 'part', alt: r.alt, MN: r.MN, dTs: 0, T4: state.cycle.T4 - 250 },
    ];
  }
  const odInputs = (p) => ({ alt: p.alt, MN: p.MN, dTs: p.dTs, T4: p.T4, ram_recovery: +ramRecovery(p.MN, state.tech.ram).toFixed(5) });

  // ======================================================================= //
  //  Python worker
  // ======================================================================= //
  const py = { ready: false, failed: false, pending: new Map(), seq: 0, busy: 0 };
  const statusEl = document.getElementById('py-status');
  const statusText = document.getElementById('py-status-text');
  const progTrack = document.getElementById('py-progress');
  const progBar = progTrack.querySelector('.progress-bar');

  function setPill(cls, text) {
    statusEl.className = 'pill ' + cls;
    statusText.textContent = text;
  }

  py.worker = new Worker('js/worker.js?v=5');
  py.worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === 'status') {
      progBar.style.width = (m.progress * 100).toFixed(0) + '%';
      if (m.ready) {
        py.ready = true;
        progTrack.classList.add('done');
        setPill('ready', m.text);
        prebuild();
        render();
      } else {
        setPill(m.progress > 0 ? 'loading' : 'error', m.text);
      }
    } else if (m.type === 'fatal') {
      py.failed = true;
      setPill('error', 'Python failed to load – check your connection and reload');
      render();
    } else if (m.type === 'result') {
      const cb = py.pending.get(m.id);
      py.pending.delete(m.id);
      py.busy = Math.max(0, py.busy - 1);
      if (py.ready) setPill(py.busy ? 'busy' : 'ready', py.busy ? 'Computing…' : 'Python ready');
      if (cb) cb(m.payload);
    }
  };

  function call(fn, ...args) {
    return new Promise((resolve) => {
      const id = ++py.seq;
      py.pending.set(id, resolve);
      py.busy++;
      if (py.ready) setPill('busy', 'Computing…');
      py.worker.postMessage({ type: 'call', id, fn, args });
    });
  }

  const built = new Set();
  function prebuild() {
    // build the models for the chosen architecture in the background
    for (const withOd of [false, true]) {
      const k = state.arch + withOd;
      if (built.has(k)) continue;
      built.add(k);
      call('build', state.arch, withOd);
    }
  }

  // ======================================================================= //
  //  Generic UI helpers
  // ======================================================================= //
  const main = document.getElementById('main');
  const stepper = document.getElementById('stepper');
  const charts = [];
  function destroyCharts() { while (charts.length) charts.pop().destroy(); }

  function toast(msg, ms = 3800) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), ms);
  }

  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  const PALETTE = ['#1f6feb', '#e5534b', '#1a7f37', '#bf8700', '#8250df', '#0891b2', '#db2777'];

  function chart(canvasId, config) {
    const el = document.getElementById(canvasId);
    if (!el || !window.Chart) return null;
    Chart.defaults.color = cssVar('--muted');
    Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
    Chart.defaults.borderColor = cssVar('--chart-grid');
    config.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: false }, config.options || {});
    const c = new Chart(el, config);
    charts.push(c);
    return c;
  }
  const axis = (title, extra = {}) => Object.assign({ type: 'linear', title: { display: true, text: title }, grid: { color: cssVar('--chart-grid') } }, extra);

  /* field descriptor: {obj, key, label, q, hint, min, max, sig, step} */
  function field(f) {
    const obj = state[f.obj];
    const val = toD(f.q || 'none', obj[f.key]);
    const u = unit(f.q || 'none');
    return `<div class="field" data-field="${f.obj}.${f.key}">
      <label for="f-${f.obj}-${f.key}">${f.label}</label>
      <div class="input-wrap"><input id="f-${f.obj}-${f.key}" type="number" inputmode="decimal" step="any"
        data-obj="${f.obj}" data-key="${f.key}" data-q="${f.q || 'none'}" data-min="${f.min ?? ''}" data-max="${f.max ?? ''}"
        value="${val == null ? '' : +val.toPrecision(f.sig || 5)}">${u ? `<span class="unit">${u}</span>` : ''}</div>
      ${f.hint ? `<span class="hint">${f.hint}</span>` : ''}
    </div>`;
  }

  function bindFields(root, onChange) {
    root.querySelectorAll('input[data-obj]').forEach((inp) => {
      inp.addEventListener('input', () => {
        const wrap = inp.closest('.field');
        const v = parseFloat(inp.value);
        const q = inp.dataset.q;
        if (!isFinite(v)) { wrap.classList.add('invalid'); return; }
        const internal = fromD(q, v);
        const min = inp.dataset.min === '' ? -Infinity : +inp.dataset.min;
        const max = inp.dataset.max === '' ? Infinity : +inp.dataset.max;
        if (internal < min || internal > max) { wrap.classList.add('invalid'); wrap.title = `Allowed: ${fmt(toD(q, min))} – ${fmt(toD(q, max))} ${unit(q)}`; return; }
        wrap.classList.remove('invalid'); wrap.title = '';
        state[inp.dataset.obj][inp.dataset.key] = internal;
        if (inp.dataset.obj === 'tech') state.techLevel = 'custom';
        if (inp.dataset.obj === 'req') state.preset = state.preset === 'custom' ? 'custom' : state.preset;
        save();
        if (onChange) onChange(inp.dataset.obj, inp.dataset.key);
        renderStepper();
      });
    });
  }

  function kpi(label, value, u, cls = '', sub = '') {
    return `<div class="kpi ${cls}"><div class="k-label">${label}</div><div class="k-val">${value}<span class="k-unit">${u || ''}</span></div>${sub ? `<div class="k-sub">${sub}</div>` : ''}</div>`;
  }

  function learn(title, body, open = false) {
    return `<details class="learn" ${open ? 'open' : ''}><summary>📘 ${title}</summary><div class="learn-body">${body}</div></details>`;
  }

  function header(i, lede) {
    const s = STEPS[i];
    return `<div class="step-header"><div class="eyebrow">Step ${i + 1} of ${STEPS.length} · ${s.phase}</div>
      <h1>${s.title}</h1><p class="lede">${lede}</p></div>`;
  }

  function navRow(i, nextLabel, nextEnabled = true, nextHint = '') {
    const prev = i > 0 ? `<button class="btn ghost" data-go="${i - 1}">← ${STEPS[i - 1].title}</button>` : '<span></span>';
    const next = i < STEPS.length - 1
      ? `<div class="btn-row">${nextHint ? `<span class="small-muted">${nextHint}</span>` : ''}<button class="btn" data-go="${i + 1}" ${nextEnabled ? '' : 'disabled'}>${nextLabel || STEPS[i + 1].title} →</button></div>`
      : '';
    return `<div class="nav-row">${prev}${next}</div>`;
  }

  function pyGate() {
    if (py.failed) return `<div class="banner bad"><b>Python unavailable.</b> The pyCycle runtime could not be downloaded. Check your internet connection and reload the page.</div>`;
    if (!py.ready) return `<div class="banner info"><span class="spinner" style="border-color:var(--accent-soft);border-top-color:var(--accent)"></span><div><b>Python is still loading.</b> The first visit downloads ~40 MB (Pyodide, NumPy, SciPy, OpenMDAO, pyCycle); later visits are cached. You can keep working through the earlier steps meanwhile.</div></div>`;
    return '';
  }

  function staleBanner() {
    return `<div class="banner warn"><b>Out of date.</b> Requirements, technology or cycle inputs changed since this engine was sized. Re-run the design point to refresh.</div>`;
  }

  // ======================================================================= //
  //  Navigation
  // ======================================================================= //
  function stepStatus(i) {
    const id = STEPS[i].id;
    if (id === 'design' && state.design) return designCurrent() ? 'done' : 'stale';
    if (id === 'offdesign' && state.odResults) return state.odResults.key === designKey() ? 'done' : 'stale';
    if (id === 'cycle' && state.quick) return state.quick.key === designKey() ? 'done' : '';
    if (i < state.maxStep && ['req', 'arch', 'tech'].includes(id)) return 'done';
    return '';
  }

  function renderStepper() {
    let html = '', phase = '';
    STEPS.forEach((s, i) => {
      if (s.phase !== phase) { phase = s.phase; html += `<div class="phase">${phase}</div>`; }
      const st = stepStatus(i);
      const cls = ['step-link', i === state.step ? 'active' : '', st].join(' ');
      const icon = st === 'done' ? '✓' : st === 'stale' ? '!' : i + 1;
      html += `<button class="${cls}" data-go="${i}" ${i > state.maxStep ? 'disabled' : ''} title="${st === 'stale' ? 'Inputs changed – re-run' : ''}">
        <span class="step-num">${icon}</span><span><span class="step-title">${s.title}</span><span class="step-desc">${s.desc}</span></span></button>`;
    });
    stepper.innerHTML = html;
  }

  function go(i) {
    state.step = i;
    state.maxStep = Math.max(state.maxStep, i);
    save();
    render();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  document.addEventListener('click', (e) => {
    const g = e.target.closest('[data-go]');
    if (g && !g.disabled) { go(+g.dataset.go); }
  });

  document.querySelectorAll('[data-units]').forEach((b) => b.addEventListener('click', () => {
    state.units = b.dataset.units; save(); render();
  }));
  document.getElementById('reset-btn').addEventListener('click', () => {
    if (!confirm('Reset all inputs and results to the default airliner example?')) return;
    const units = state.units;
    state = defaultState(); state.units = units; save(); render();
  });

  // ======================================================================= //
  //  Step 1 – Requirements
  // ======================================================================= //
  function derivedAtm() {
    const r = state.req;
    const a = isa(r.alt);
    const V = r.MN * a.a;
    const Tt = a.T_K * (1 + 0.2 * r.MN * r.MN);
    const Pt = a.P_Pa * Math.pow(1 + 0.2 * r.MN * r.MN, 3.5);
    const q = 0.5 * a.rho * V * V;
    const rec = ramRecovery(r.MN, state.tech.ram);
    const T = (k) => fq('temp', k * 1.8, 4);
    const P = (pa) => fq('press', pa / 6894.757, 4);
    return `
      <div><span>Static temperature</span><span>${T(a.T_K)} ${unit('temp')}</span></div>
      <div><span>Static pressure</span><span>${P(a.P_Pa)} ${unit('press')}</span></div>
      <div><span>Speed of sound</span><span>${fq('vel', a.a / 0.3048)} ${unit('vel')}</span></div>
      <div><span>Flight speed</span><span>${fq('vel', V / 0.3048)} ${unit('vel')} (${fmt(V * 1.94384, 3)} kt)</span></div>
      <div><span>Total (ram) temperature Tt0</span><span>${T(Tt)} ${unit('temp')}</span></div>
      <div><span>Total pressure Pt0</span><span>${P(Pt)} ${unit('press')}</span></div>
      <div><span>Dynamic pressure</span><span>${P(q)} ${unit('press')}</span></div>
      <div><span>Inlet recovery used</span><span>${fmt(rec, 4)}</span></div>`;
  }

  function renderReq(i) {
    const presetCards = Object.entries(PRESETS).map(([k, p]) => `
      <button class="choice ${state.preset === k ? 'selected' : ''}" data-preset="${k}">
        <div class="c-title">${p.icon} ${p.label}</div><div class="c-desc">${p.desc}</div></button>`).join('')
      + `<button class="choice ${state.preset === 'custom' ? 'selected' : ''}" data-preset="custom">
        <div class="c-title">✎ Custom</div><div class="c-desc">Start from the current values and type your own requirements.</div></button>`;

    main.innerHTML = header(i, 'Every engine program starts from the aircraft, not the engine. The airframer states what the engine must deliver — thrust at key flight conditions, fuel burn, size and operability — and everything that follows is judged against these numbers.')
      + learn('How engine requirements are set', `
        <p>The aircraft's mission (range, payload, cruise speed, airfield length) is flown in a sizing study. That study produces the numbers you enter below:</p>
        <ul>
          <li><b>Cruise thrust</b> = aircraft drag at cruise ÷ number of engines. The engine is usually <i>sized</i> near cruise or top-of-climb, where it spends most of its time.</li>
          <li><b>Cruise TSFC</b> (thrust-specific fuel consumption) links directly to range through the Breguet equation: fuel burn ∝ TSFC.</li>
          <li><b>Takeoff thrust</b> comes from field length and engine-out climb gradient, usually at a <i>hot day</i> (ISA + 15 °C) because hot air is less dense and the engine is temperature-limited.</li>
          <li><b>Maximum diameter</b> is set by ground clearance under the wing, nacelle drag and weight.</li>
          <li><b>Surge margin</b> is an operability requirement: compressors must stay away from stall during transients.</li>
        </ul>
        <span class="eq">Range = (V / (g · TSFC)) · (L/D) · ln(W_initial / W_final)   (Breguet)</span>`)
      + `<div class="card"><h3>1 · Pick a starting mission</h3><div class="choices">${presetCards}</div></div>
      <div class="grid side">
        <div class="card"><h3>2 · Design (cruise) condition</h3>
          <div class="fields">
            ${field({ obj: 'req', key: 'alt', label: 'Cruise altitude', q: 'alt', min: 0, max: 60000, hint: 'Where the engine is sized' })}
            ${field({ obj: 'req', key: 'MN', label: 'Cruise Mach number', min: 0, max: 2.5, hint: 'Flight speed ÷ speed of sound' })}
            ${field({ obj: 'req', key: 'Fn', label: 'Required cruise thrust (per engine)', q: 'thrust', min: 10, max: 100000 })}
            ${field({ obj: 'req', key: 'TSFC', label: 'Target cruise TSFC', q: 'tsfc', min: 0.2, max: 3, hint: 'Lower is better — drives range and fuel cost' })}
          </div>
        </div>
        <div class="card"><h3>Flight condition at a glance</h3><div class="derived" id="derived">${derivedAtm()}</div>
          <p class="small-muted" style="margin-top:10px">Standard atmosphere. The ram rise in temperature and pressure is "free" compression the engine gets from flight speed.</p></div>
      </div>
      <div class="card"><h3>3 · Takeoff & installation constraints</h3>
        <div class="fields">
          ${field({ obj: 'req', key: 'Fn_TO', label: 'Required takeoff thrust (per engine)', q: 'thrust', min: 10, max: 200000 })}
          ${field({ obj: 'req', key: 'TO_alt', label: 'Takeoff airfield altitude', q: 'alt', min: 0, max: 15000 })}
          ${field({ obj: 'req', key: 'TO_MN', label: 'Takeoff Mach number', min: 0, max: 0.4, hint: '0 = static (brakes on)' })}
          ${field({ obj: 'req', key: 'TO_dTs', label: 'Hot-day temperature offset', q: 'dtemp', min: -60, max: 90, hint: 'ISA + ΔT. 27 °R = 15 K' })}
          ${field({ obj: 'req', key: 'D_max', label: 'Maximum fan / inlet diameter', q: 'length', min: 1, max: 200 })}
          ${field({ obj: 'req', key: 'SM_min', label: 'Minimum surge margin', q: 'none', min: 0, max: 50, hint: 'Percent, applies to every compressor' })}
        </div>
      </div>`
      + navRow(i, 'Choose the architecture');

    main.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => applyPreset(b.dataset.preset)));
    bindFields(main, () => {
      state.preset = 'custom';
      main.querySelectorAll('[data-preset]').forEach((b) => b.classList.toggle('selected', b.dataset.preset === 'custom'));
      document.getElementById('derived').innerHTML = derivedAtm();
    });
  }

  function applyPreset(k) {
    state.preset = k;
    if (k !== 'custom') {
      const p = PRESETS[k];
      state.req = { ...p.req };
      state.arch = p.arch;
      state.techLevel = p.tech;
      state.tech = { ...TECH[p.tech] };
      state.cycle = { ...p.cycle };
      state.odEdited = false;
      state.odPoints = null;
      state.sweep.from = state.sweep.to = null;
      state.sweep.results = null;
      if (py.ready) prebuild();
    }
    save();
    render();
  }

  // ======================================================================= //
  //  Step 2 – Architecture
  // ======================================================================= //
  function renderArch(i) {
    const M = state.req.MN;
    const rec = M <= 1.0 ? 'turbofan' : 'turbojet';
    const why = M <= 1.0
      ? `At Mach ${fmt(M, 3)} a turbofan is the natural choice: moving a lot of air slowly is more propulsively efficient than moving a little air fast.`
      : `At Mach ${fmt(M, 3)} the flight speed is high, so a high jet velocity is needed; a turbojet (or very low bypass ratio fan) keeps frontal area and drag low.`;
    const card = (k, title, pros, cons) => `
      <button class="choice arch-card ${state.arch === k ? 'selected' : ''}" data-arch="${k}">
        <div class="c-title">${title} ${rec === k ? '<span class="tag">recommended</span>' : ''}</div>
        <ul class="pros">${pros.map((p) => `<li>${p}</li>`).join('')}</ul>
        <ul class="cons">${cons.map((p) => `<li>${p}</li>`).join('')}</ul>
      </button>`;

    main.innerHTML = header(i, 'With the requirements fixed, choose the engine concept. The architecture decides which cycle parameters you can play with and which components pyCycle will model.')
      + learn('Propulsive efficiency — why bypass matters', `
        <p>An engine makes thrust by accelerating air from flight speed V<sub>0</sub> to jet speed V<sub>j</sub>. The kinetic energy left in the jet is wasted, so the propulsive efficiency is:</p>
        <span class="eq">η_prop ≈ 2 / (1 + Vj / V0)        F = ṁ · (Vj − V0)</span>
        <p>For a given thrust you can use a <i>small</i> mass flow with a <i>fast</i> jet (turbojet), or a <i>large</i> mass flow with a <i>slow</i> jet (turbofan). The second is far more efficient at subsonic speed, but needs a bigger, heavier fan and nacelle.</p>
        <p>The <b>bypass ratio (BPR)</b> is the ratio of air going around the core to air going through it. Modern airliners use BPR 9–12; business jets 4–6; fighters 0.3–1; pure turbojets 0.</p>`)
      + `<div class="banner info"><b>Guidance:</b> ${why}</div>
      <div class="arch-cards">
        ${card('turbojet', 'Single-spool turbojet', ['Simple, light, compact frontal area', 'High specific thrust — good for high Mach', 'Cheap: ideal for expendable UAVs'], ['High jet velocity → poor propulsive efficiency when subsonic', 'Noisy', 'High TSFC at subsonic cruise'])}
        ${card('turbofan', 'Two-spool separate-flow turbofan', ['Low jet velocity → high propulsive efficiency', 'Low TSFC and noise', 'Standard for airliners & business jets'], ['Large fan diameter, weight and nacelle drag', 'Thrust lapses faster with speed and altitude', 'More complex: two shafts, fan + booster + HPC'])}
      </div>
      <div class="card" style="margin-top:18px"><div class="card-head"><h3>Engine layout & station numbering</h3><span class="small-muted">SAE ARP755 station numbers used throughout</span></div>
        <div class="schematic-wrap">${renderSchematic(state.arch)}</div>
        <p class="small-muted" style="margin-top:8px">${state.arch === 'turbofan'
          ? 'Air enters at station 2. The fan splits it: bypass air (13 → 19) makes most of the thrust; core air is compressed by the booster (LPC) and HPC to station 3, burned to T4, and expanded through the HP turbine (which drives the HPC) and LP turbine (which drives the fan and booster).'
          : 'Air enters at station 2, is compressed to station 3, heated in the burner to T4, and expanded through the turbine (which drives the compressor through the shaft). The remaining energy accelerates the jet in the nozzle (9).'}</p>
      </div>`
      + navRow(i, 'Set the technology level');

    main.querySelectorAll('[data-arch]').forEach((b) => b.addEventListener('click', () => {
      state.arch = b.dataset.arch;
      state.preset = state.preset === 'custom' ? 'custom' : state.preset;
      state.sweep.results = null; state.sweep.from = state.sweep.to = null;
      if (!SWEEP_VARS[state.sweep.var][state.arch]) state.sweep.var = 'OPR';
      state.odPoints = null; state.odEdited = false;
      save();
      if (py.ready) prebuild();
      render();
    }));
  }

  // ======================================================================= //
  //  Step 3 – Technology
  // ======================================================================= //
  function renderTech(i) {
    const tf = state.arch === 'turbofan';
    const levels = Object.entries(TECH).map(([k, t]) => `
      <button class="choice ${state.techLevel === k ? 'selected' : ''}" data-tech="${k}">
        <div class="c-title">${t.label}</div><div class="c-desc">${t.desc}</div></button>`).join('')
      + `<button class="choice ${state.techLevel === 'custom' ? 'selected' : ''}" data-tech="custom"><div class="c-title">Custom</div><div class="c-desc">Your own component assumptions.</div></button>`;
    const e = (key, label, hint) => field({ obj: 'tech', key, label, min: 0.5, max: 0.99, sig: 4, hint });

    main.innerHTML = header(i, 'Before choosing a cycle, decide what technology the program can rely on. Component efficiencies and temperature limits come from the state of the art in aerodynamics, materials and cooling — they cap what any cycle can achieve.')
      + learn('Why technology level matters', `
        <ul>
          <li><b>Component efficiencies</b> (isentropic, used by pyCycle) measure how close each compressor/turbine is to ideal. A 1-point gain in HPC or LPT efficiency is worth roughly 0.5–1 % TSFC.</li>
          <li><b>T4 limit</b> — the turbine inlet temperature — is set by blade materials, coatings and cooling air. Higher T4 raises specific thrust (smaller engine) and allows higher OPR, but costs cooling air and life.</li>
          <li><b>T3 limit</b> — compressor delivery temperature — is a disk/material limit that caps the overall pressure ratio, especially at hot-day takeoff.</li>
          <li><b>Pressure losses</b> in the burner and inlet, and the nozzle velocity coefficient C<sub>v</sub>, subtract directly from thrust.</li>
        </ul>`)
      + `<div class="card"><h3>Technology baseline</h3><div class="choices">${levels}</div></div>
      <div class="grid two">
        <div class="card"><h3>Turbomachinery efficiencies</h3><div class="fields">
          ${tf ? e('fan_eff', 'Fan efficiency') + e('lpc_eff', 'LPC (booster) efficiency') + e('hpc_eff', 'HPC efficiency') + e('hpt_eff', 'HPT efficiency') + e('lpt_eff', 'LPT efficiency')
            : e('comp_eff', 'Compressor efficiency') + e('turb_eff', 'Turbine efficiency')}
        </div><p class="small-muted" style="margin-top:10px">Isentropic (adiabatic) efficiencies at the design point. Off-design, pyCycle reads efficiency from the component maps.</p></div>
        <div class="card"><h3>Limits & losses</h3><div class="fields">
          ${field({ obj: 'tech', key: 'T4max', label: 'Max turbine inlet temp T4', q: 'temp', min: 1800, max: 4000, hint: 'Takeoff / max-climb rating' })}
          ${field({ obj: 'tech', key: 'T3max', label: 'Max compressor exit temp T3', q: 'temp', min: 1000, max: 2200, hint: 'Checked at hot-day takeoff' })}
          ${field({ obj: 'tech', key: 'burner_dPqP', label: 'Burner pressure loss', q: 'pct', min: 0.01, max: 0.1, sig: 3 })}
          ${field({ obj: 'tech', key: 'ram', label: 'Inlet pressure recovery', min: 0.9, max: 1, sig: 4, hint: 'Subsonic duct; shock losses added above Mach 1' })}
          ${field({ obj: 'tech', key: 'Cv', label: 'Nozzle velocity coefficient Cv', min: 0.9, max: 1, sig: 4 })}
          ${tf ? field({ obj: 'tech', key: 'HPX', label: 'Aircraft power extraction', q: 'power', min: 0, max: 2000, hint: 'Generators & pumps on the HP spool' }) : ''}
        </div></div>
      </div>`
      + navRow(i, 'Select the cycle');

    main.querySelectorAll('[data-tech]').forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.tech;
      state.techLevel = k;
      if (k !== 'custom') state.tech = { ...TECH[k] };
      state.odPoints = state.odEdited ? state.odPoints : null;
      save(); render();
    }));
    bindFields(main, () => main.querySelectorAll('[data-tech]').forEach((b) => b.classList.toggle('selected', b.dataset.tech === 'custom')));
  }

  // ======================================================================= //
  //  Step 4 – Cycle selection & trade studies
  // ======================================================================= //
  function checkClass(ok) { return ok == null ? '' : ok ? 'good' : 'bad'; }

  function quickKpis(res) {
    const p = res.perf, s = res.sizing, r = state.req;
    const tsfcOk = p.TSFC <= r.TSFC;
    const dOk = s.fan_diameter <= r.D_max;
    let h = kpi('Cruise TSFC', fq('tsfc', p.TSFC, 4), unit('tsfc'), checkClass(tsfcOk), `target ≤ ${fq('tsfc', r.TSFC, 4)}`)
      + kpi('Specific thrust', fq('fsp', p.Fsp, 4), unit('fsp'), '', 'thrust per unit airflow')
      + kpi('Inlet airflow', fq('flow', p.W, 4), unit('flow'), '', 'sized to meet thrust')
      + kpi(state.arch === 'turbofan' ? 'Fan diameter' : 'Inlet diameter', fq('length', s.fan_diameter, 3), unit('length'), checkClass(dOk), `limit ${fq('length', r.D_max, 3)}`)
      + kpi('Thermal efficiency', fmt(p.eta_th * 100, 3), '%')
      + kpi('Propulsive efficiency', p.eta_prop == null ? '–' : fmt(p.eta_prop * 100, 3), '%')
      + (p.Vratio != null ? kpi('Jet velocity ratio', fmt(p.Vratio, 3), '', '', `bypass ÷ core; textbook optimum ≈ η_fan·η_LPT = ${fmt(p.Vratio_opt, 2)}`) : '')
      + kpi('T3 at cruise', fq('temp', p.T3, 4), unit('temp'))
      + kpi('Fuel flow', fq('flow', p.Wfuel * 3600, 4), unit('flow').replace('/s', '/h'));
    return h;
  }

  function sweepDefaults() {
    const sv = SWEEP_VARS[state.sweep.var];
    let rng = sv[state.arch];
    const cur = state.cycle[state.sweep.var];
    if (state.sweep.var === 'FPR') rng = [Math.max(1.2, cur - 0.25), cur + 0.35];
    if (state.sweep.var === 'BPR') rng = [Math.max(0.5, cur * 0.6), cur * 1.4];
    if (state.sweep.from == null) state.sweep.from = +rng[0].toPrecision(3);
    if (state.sweep.to == null) state.sweep.to = +rng[1].toPrecision(3);
  }

  function renderCycle(i) {
    const tf = state.arch === 'turbofan';
    const c = state.cycle;
    sweepDefaults();
    const sw = state.sweep;
    const hpc = tf ? c.OPR / (c.FPR * c.LPC_PR) : null;
    const varOpts = Object.entries(SWEEP_VARS).filter(([, v]) => v[state.arch])
      .map(([k, v]) => `<option value="${k}" ${sw.var === k ? 'selected' : ''}>${v.label}</option>`).join('');
    const carpetOpts = `<option value="">— none —</option>` + Object.entries(SWEEP_VARS).filter(([k, v]) => v[state.arch] && k !== sw.var)
      .map(([k, v]) => `<option value="${k}" ${sw.carpetVar === k ? 'selected' : ''}>${v.label}</option>`).join('');
    const sq = SWEEP_VARS[sw.var].q;
    const quickCur = state.quick && state.quick.key === designKey();

    main.innerHTML = header(i, 'Now pick the thermodynamic cycle: overall pressure ratio, turbine inlet temperature and — for a turbofan — bypass and fan pressure ratio. Engineers explore these with parametric "trade studies" before committing to one design point.')
      + learn('What each cycle parameter does', `
        <ul>
          <li><b>OPR</b> (overall pressure ratio, P3/P2) mostly drives <i>thermal efficiency</i>: higher OPR → lower TSFC, up to the point where T3 and component losses bite.</li>
          <li><b>T4</b> sets how much energy goes into each kilogram of air: higher T4 → higher <i>specific thrust</i> → smaller, lighter engine for the same thrust. For a given OPR there is an optimum T4 for TSFC.</li>
          ${tf ? `<li><b>BPR</b> and <b>FPR</b> set how the core's energy is shared with the bypass stream. Higher BPR with lower FPR → slower jets → better propulsive efficiency, but a bigger fan (check the diameter constraint!).</li>
          <li><b>FPR has an optimum at fixed BPR.</b> The LP turbine takes energy out of the core jet and the fan puts it into the bypass jet. TSFC is lowest when the two jets are matched: V<sub>bypass</sub>/V<sub>core</sub> ≈ η<sub>fan</sub>·η<sub>LPT</sub> (about 0.8). If the ratio is below that, the core jet is too fast and <i>raising</i> FPR improves TSFC; if it's above, lowering FPR helps. "Lower FPR is better" only holds when BPR rises at the same time. Watch the <i>jet velocity ratio</i> in the results. In this model the TSFC minimum usually sits a bit lower (≈ 0.55–0.75), because the convergent nozzles are choked and part of the thrust comes from exit pressure — run an FPR sweep with BPR as the carpet variable to find the real optimum.</li>
          <li><i>Model note:</i> these cycles leave out turbine cooling air, so the core is somewhat more energetic than in a real engine and optimum FPRs come out a little high.</li>
          <li>For a turbofan the HPC pressure ratio is derived: HPC PR = OPR ÷ (FPR × LPC PR).</li>` : ''}
        </ul>
        <p>In pyCycle, the design point is solved by a Newton solver with three kinds of "balances": airflow is varied until net thrust equals the requirement, fuel-air ratio until the burner exit equals T4, and each turbine's pressure ratio until its shaft's power is balanced.</p>
        <span class="eq">TSFC = ṁ_fuel / F_net        Specific thrust = F_net / ṁ_air</span>`)
      + pyGate()
      + `<div class="grid side">
        <div class="card"><h3>Candidate cycle</h3>
          <div class="fields">
            ${field({ obj: 'cycle', key: 'OPR', label: 'Overall pressure ratio', min: 2, max: 80, sig: 4 })}
            ${field({ obj: 'cycle', key: 'T4', label: 'Cruise T4', q: 'temp', min: 1600, max: 4000, hint: `≤ max T4 ${fq('temp', state.tech.T4max, 4)} ${unit('temp')}` })}
            ${tf ? field({ obj: 'cycle', key: 'BPR', label: 'Bypass ratio', min: 0.3, max: 20, sig: 4 })
              + field({ obj: 'cycle', key: 'FPR', label: 'Fan pressure ratio', min: 1.1, max: 3.5, sig: 4 })
              + field({ obj: 'cycle', key: 'LPC_PR', label: 'Booster (LPC) pressure ratio', min: 1.0, max: 4, sig: 4 }) : ''}
          </div>
          ${tf ? `<p class="small-muted" id="hpc-pr" style="margin-top:10px">Derived HPC pressure ratio: <b class="mono">${fmt(hpc, 4)}</b></p>` : ''}
          <div class="btn-row" style="margin-top:12px">
            <button class="btn" id="quick-run" ${py.ready ? '' : 'disabled'}>Evaluate this cycle</button>
            <span class="small-muted" id="quick-msg">${quickCur ? `Evaluated in ${fmt(state.quick.ms / 1000, 2)} s` : 'Runs a pyCycle design point'}</span>
          </div>
        </div>
        <div class="card"><h3>Result</h3><div id="quick-out">${quickCur ? `<div class="kpis">${quickKpis(state.quick.data)}</div>`
          : state.quick && state.quick.error ? `<div class="banner bad">${esc(state.quick.error)}</div>` : '<p class="small-muted">Evaluate the candidate cycle to see TSFC, size and efficiencies.</p>'}</div></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Parametric trade study</h3><span class="small-muted">Each point is a full pyCycle design-point solution</span></div>
        <div class="fields">
          <div class="field"><label>Sweep variable</label><div class="input-wrap"><select id="sw-var">${varOpts}</select></div></div>
          <div class="field"><label>From</label><div class="input-wrap"><input id="sw-from" type="number" step="any" value="${+toD(sq, sw.from).toPrecision(5)}">${unit(sq) ? `<span class="unit">${unit(sq)}</span>` : ''}</div></div>
          <div class="field"><label>To</label><div class="input-wrap"><input id="sw-to" type="number" step="any" value="${+toD(sq, sw.to).toPrecision(5)}">${unit(sq) ? `<span class="unit">${unit(sq)}</span>` : ''}</div></div>
          <div class="field"><label>Points</label><div class="input-wrap"><input id="sw-n" type="number" min="2" max="15" step="1" value="${sw.n}"></div></div>
          <div class="field"><label>Carpet (2nd variable)</label><div class="input-wrap"><select id="sw-cvar">${carpetOpts}</select></div>
            <span class="hint">Optional — creates a classic carpet plot</span></div>
          <div class="field"><label>Carpet values</label><div class="input-wrap"><input id="sw-cvals" type="text" placeholder="e.g. 3 values" value="${esc(carpetValsDisplay())}">${sw.carpetVar && unit(SWEEP_VARS[sw.carpetVar].q) ? `<span class="unit">${unit(SWEEP_VARS[sw.carpetVar].q)}</span>` : ''}</div>
            <span class="hint">Comma-separated; blank = current ±</span></div>
        </div>
        <div class="btn-row" style="margin-top:14px">
          <button class="btn secondary" id="sw-run" ${py.ready ? '' : 'disabled'}>Run trade study</button>
          <button class="btn ghost" id="sw-stop" style="display:none">Stop</button>
          <div class="sweep-progress" id="sw-prog" style="display:none"><div></div></div>
          <span class="small-muted" id="sw-msg"></span>
        </div>
        <div id="sw-out" style="margin-top:16px"></div>
      </div>`
      + navRow(i, 'Size the engine', true, 'Happy with the cycle?');

    bindFields(main, () => {
      if (tf) {
        const el = document.getElementById('hpc-pr');
        if (el) el.innerHTML = `Derived HPC pressure ratio: <b class="mono">${fmt(c.OPR / (c.FPR * c.LPC_PR), 4)}</b>`;
      }
      document.getElementById('quick-msg').textContent = 'Inputs changed — evaluate again';
    });

    document.getElementById('quick-run').addEventListener('click', runQuick);
    document.getElementById('sw-var').addEventListener('change', (e) => {
      sw.var = e.target.value; sw.from = sw.to = null;
      if (sw.carpetVar === sw.var) sw.carpetVar = '';
      sw.carpetVals = ''; save(); render();
    });
    document.getElementById('sw-cvar').addEventListener('change', (e) => { sw.carpetVar = e.target.value; sw.carpetVals = ''; save(); render(); });
    const num = (id, q, k) => document.getElementById(id).addEventListener('input', (e) => { const v = parseFloat(e.target.value); if (isFinite(v)) { sw[k] = q ? fromD(q, v) : v; save(); } });
    num('sw-from', sq, 'from'); num('sw-to', sq, 'to'); num('sw-n', null, 'n');
    document.getElementById('sw-cvals').addEventListener('input', (e) => { sw.carpetVals = e.target.value; save(); });
    document.getElementById('sw-run').addEventListener('click', runSweep);
    document.getElementById('sw-stop').addEventListener('click', () => { sweepStop = true; });
    if (sw.results) drawSweep();
  }

  function carpetValsDisplay() {
    const sw = state.sweep;
    if (!sw.carpetVar) return '';
    if (sw.carpetVals) return sw.carpetVals;
    return carpetValues().map((v) => +toD(SWEEP_VARS[sw.carpetVar].q, v).toPrecision(4)).join(', ');
  }

  function carpetValues() {
    const sw = state.sweep;
    if (!sw.carpetVar) return [null];
    const q = SWEEP_VARS[sw.carpetVar].q;
    if (sw.carpetVals && sw.carpetVals.trim()) {
      const vals = sw.carpetVals.split(/[,;\s]+/).map(parseFloat).filter(isFinite).map((v) => fromD(q, v));
      if (vals.length) return vals.slice(0, 5);
    }
    const cur = state.cycle[sw.carpetVar];
    const d = { OPR: cur * 0.2, T4: 150, BPR: cur * 0.2, FPR: 0.1 }[sw.carpetVar];
    return [cur - d, cur, cur + d].map((v) => +v.toPrecision(4));
  }

  async function runQuick() {
    const btn = document.getElementById('quick-run');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Solving…';
    const key = designKey();
    const res = await call('design_point', state.arch, designInputs());
    state.quick = res.ok ? { key, data: res.data, ms: res.ms } : { key: null, error: res.error };
    if (!res.ok) toast('Cycle did not converge — see the explanation in the result panel.');
    save();
    if (STEPS[state.step].id === 'cycle') render();
  }

  let sweepStop = false;
  async function runSweep() {
    const sw = state.sweep;
    const xs = [];
    const n = Math.max(2, Math.min(15, Math.round(sw.n)));
    for (let k = 0; k < n; k++) xs.push(sw.from + (sw.to - sw.from) * k / (n - 1));
    const cvals = carpetValues();
    sw.carpetList = cvals;
    const total = xs.length * cvals.length;
    const out = [];
    sweepStop = false;
    const run = document.getElementById('sw-run'), stop = document.getElementById('sw-stop'), prog = document.getElementById('sw-prog'), msg = document.getElementById('sw-msg');
    run.disabled = true; stop.style.display = ''; prog.style.display = ''; msg.textContent = '';
    let done = 0, fails = 0;
    const t0 = performance.now();
    for (const cv of cvals) {
      for (const x of xs) {
        if (sweepStop) break;
        const inputs = designInputs();
        inputs[sw.var] = x;
        if (sw.carpetVar) inputs[sw.carpetVar] = cv;
        const res = await call('design_point', state.arch, inputs);
        done++;
        const rec = { x, c: cv, ok: res.ok, error: res.error };
        if (res.ok) {
          const p = res.data.perf;
          Object.assign(rec, { TSFC: p.TSFC, Fsp: p.Fsp, W: p.W, D: res.data.sizing.fan_diameter, T3: p.T3, eta_th: p.eta_th, eta_prop: p.eta_prop, Vr: p.Vratio });
        } else fails++;
        out.push(rec);
        if (prog.isConnected) {
          prog.firstElementChild.style.width = (100 * done / total) + '%';
          const eta = (performance.now() - t0) / done * (total - done) / 1000;
          msg.textContent = `${done}/${total} points · ~${Math.ceil(eta)} s left${fails ? ` · ${fails} did not converge` : ''}`;
        }
      }
    }
    sw.results = out;
    sw.var_done = sw.var; sw.cvar_done = sw.carpetVar;
    save();
    if (STEPS[state.step].id === 'cycle') {
      render();
      const m = document.getElementById('sw-msg');
      if (m) m.textContent = `${out.filter((r) => r.ok).length}/${out.length} points converged in ${fmt((performance.now() - t0) / 1000, 2)} s${sweepStop ? ' (stopped)' : ''}`;
    }
  }

  function drawSweep() {
    const sw = state.sweep;
    const res = sw.results;
    if (!res || !res.length) return;
    const xv = sw.var_done || sw.var, cvar = sw.cvar_done;
    const xq = SWEEP_VARS[xv].q;
    const groups = [...new Set(res.map((r) => r.c))];
    const lbl = (c) => (cvar ? `${cvar} = ${fmt(toD(SWEEP_VARS[cvar].q, c), 4)}${unit(SWEEP_VARS[cvar].q) ? ' ' + unit(SWEEP_VARS[cvar].q) : ''}` : 'TSFC');
    const out = document.getElementById('sw-out');
    const failed = res.filter((r) => !r.ok);
    out.innerHTML = `
      ${failed.length ? `<div class="banner warn"><b>${failed.length} point(s) did not converge.</b> This usually means the cycle cannot close there — e.g. the turbine cannot extract enough work to drive the compressor at that T4, or a component is pushed off its map. Treat these regions as infeasible.</div>` : ''}
      <div class="grid two">
        <div><h3>TSFC vs ${esc(xv)}</h3><div class="chart-box"><canvas id="ch-sw1"></canvas></div></div>
        <div><h3>${cvar ? 'Carpet plot: TSFC vs specific thrust' : 'TSFC vs specific thrust'}</h3><div class="chart-box"><canvas id="ch-sw2"></canvas></div></div>
      </div>
      <p class="small-muted" style="margin-top:6px">Click a point on either chart to adopt that cycle as your candidate. The dashed line marks the TSFC target; lower-left in the carpet plot is lower fuel burn, and further right is a smaller engine.</p>
      <div class="table-wrap" style="margin-top:10px;max-height:300px"><table class="data"><thead><tr>
        ${cvar ? `<th class="l">${cvar}</th>` : ''}<th class="l">${xv}</th><th>TSFC<br>${unit('tsfc')}</th><th>Spec. thrust<br>${unit('fsp')}</th><th>Airflow<br>${unit('flow')}</th>
        <th>Diameter<br>${unit('length')}</th><th>T3<br>${unit('temp')}</th><th>η th</th><th>η prop</th>${state.arch === 'turbofan' ? '<th>V<sub>byp</sub>/V<sub>core</sub></th>' : ''}<th></th></tr></thead><tbody>
        ${res.map((r, k) => `<tr>${cvar ? `<td>${fq(SWEEP_VARS[cvar].q, r.c, 4)}</td>` : ''}<td>${fq(xq, r.x, 4)}</td>
          ${r.ok ? `<td>${fq('tsfc', r.TSFC, 4)}</td><td>${fq('fsp', r.Fsp, 4)}</td><td>${fq('flow', r.W, 4)}</td><td>${fq('length', r.D, 3)}</td><td>${fq('temp', r.T3, 4)}</td>
          <td>${fmt(r.eta_th * 100, 3)}%</td><td>${r.eta_prop == null ? '–' : fmt(r.eta_prop * 100, 3) + '%'}</td>${r.Vr != null ? `<td>${fmt(r.Vr, 3)}</td>` : ''}
          <td><button class="btn ghost small" data-adopt="${k}">Adopt</button></td>` : `<td colspan="9" class="l small-muted">did not converge</td>`}</tr>`).join('')}
      </tbody></table></div>`;

    const target = state.req.TSFC;
    const ds1 = groups.map((g, gi) => ({
      label: lbl(g), borderColor: PALETTE[gi % PALETTE.length], backgroundColor: PALETTE[gi % PALETTE.length], showLine: true, tension: 0.25,
      data: res.filter((r) => r.c === g && r.ok).map((r) => ({ x: toD(xq, r.x), y: toD('tsfc', r.TSFC), k: res.indexOf(r) })),
    }));
    const xs = res.filter((r) => r.ok).map((r) => toD(xq, r.x));
    ds1.push({ label: 'Target', data: [{ x: Math.min(...xs), y: toD('tsfc', target) }, { x: Math.max(...xs), y: toD('tsfc', target) }], borderColor: cssVar('--bad'), borderDash: [6, 4], pointRadius: 0, showLine: true });
    const adopt = (k) => {
      const r = res[k];
      if (!r || !r.ok) return;
      state.cycle[xv] = +r.x.toPrecision(5);
      if (cvar) state.cycle[cvar] = +r.c.toPrecision(5);
      save(); toast(`Adopted ${xv} = ${fq(xq, r.x, 4)}${cvar ? `, ${cvar} = ${fq(SWEEP_VARS[cvar].q, r.c, 4)}` : ''}. Evaluate or size the engine next.`);
      render();
    };
    const onClick = (evt, els, ch) => { if (els.length) { const pt = ch.data.datasets[els[0].datasetIndex].data[els[0].index]; if (pt.k != null) adopt(pt.k); } };
    chart('ch-sw1', {
      type: 'scatter', data: { datasets: ds1 },
      options: { onClick, scales: { x: axis(`${xv}${unit(xq) ? ' [' + unit(xq) + ']' : ''}`), y: axis(`TSFC [${unit('tsfc')}]`) }, plugins: { legend: { display: !!cvar || true } } },
    });
    // carpet
    const ds2 = groups.map((g, gi) => ({
      label: lbl(g), borderColor: PALETTE[gi % PALETTE.length], backgroundColor: PALETTE[gi % PALETTE.length], showLine: true,
      data: res.filter((r) => r.c === g && r.ok).map((r) => ({ x: toD('fsp', r.Fsp), y: toD('tsfc', r.TSFC), k: res.indexOf(r) })),
    }));
    if (cvar) {
      const xsU = [...new Set(res.map((r) => r.x))];
      xsU.forEach((x) => {
        const pts = res.filter((r) => r.x === x && r.ok).map((r) => ({ x: toD('fsp', r.Fsp), y: toD('tsfc', r.TSFC), k: res.indexOf(r) }));
        if (pts.length > 1) ds2.push({ label: `_${xv}=${fmt(toD(xq, x), 3)}`, data: pts, showLine: true, borderColor: cssVar('--muted'), borderDash: [3, 3], pointRadius: 0, borderWidth: 1 });
      });
    }
    chart('ch-sw2', {
      type: 'scatter', data: { datasets: ds2 },
      options: {
        onClick,
        scales: { x: axis(`Specific thrust [${unit('fsp')}]`), y: axis(`TSFC [${unit('tsfc')}]`) },
        plugins: { legend: { labels: { filter: (it) => !it.text.startsWith('_') } }, tooltip: { callbacks: { label: (ctx) => { const r = res[ctx.raw.k]; return r ? `${xv}=${fq(xq, r.x, 4)}${cvar ? `, ${cvar}=${fq(SWEEP_VARS[cvar].q, r.c, 4)}` : ''}: TSFC ${fmt(ctx.raw.y, 4)}` : ''; } } } },
      },
    });
    out.querySelectorAll('[data-adopt]').forEach((b) => b.addEventListener('click', () => adopt(+b.dataset.adopt)));
  }

  // ======================================================================= //
  //  Step 5 – Design point
  // ======================================================================= //
  async function runDesign() {
    const btn = document.getElementById('des-run');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sizing engine…'; }
    const key = designKey();
    const res = await call('design_full', state.arch, designInputs());
    if (res.ok) {
      state.design = { key, data: res.data, ms: res.ms, arch: state.arch };
      state.odResults = null; state.hook.results = null;
    } else {
      state.designError = res.error;
      toast('Design point did not converge.');
    }
    save();
    if (STEPS[state.step].id === 'design') render();
  }

  function renderDesign(i) {
    const cur = designCurrent();
    const D = state.design && state.design.arch === state.arch ? state.design.data : null;
    let body = '';
    if (D) {
      const p = D.perf, r = state.req, s = D.sizing;
      const temps = {};
      D.stations.forEach((st) => { if (st.Tt) temps[st.id] = st.Tt; });
      body = `${cur ? '' : staleBanner()}
        <div class="card"><div class="card-head"><h3>Design-point summary</h3><span class="small-muted">${esc(state.arch)} · ${fq('alt', r.alt, 4)} ${unit('alt')}, Mach ${fmt(r.MN, 3)} · solved in ${fmt(state.design.ms / 1000, 2)} s</span></div>
          <div class="kpis">
            ${kpi('Net thrust', fq('thrust', p.Fn, 4), unit('thrust'), 'good', 'meets requirement by construction')}
            ${kpi('TSFC', fq('tsfc', p.TSFC, 4), unit('tsfc'), checkClass(p.TSFC <= r.TSFC), `target ≤ ${fq('tsfc', r.TSFC, 4)}`)}
            ${kpi('Inlet airflow', fq('flow', p.W, 4), unit('flow'), '', `corrected: ${fq('flow', p.compressors[0].Wc, 4)}`)}
            ${kpi(state.arch === 'turbofan' ? 'Fan tip diameter' : 'Inlet diameter', fq('length', s.fan_diameter, 3), unit('length'), checkClass(s.fan_diameter <= r.D_max), `hub/tip ${s.hub_tip}, limit ${fq('length', r.D_max, 3)}`)}
            ${kpi('OPR', fmt(p.OPR, 4), '')}
            ${state.arch === 'turbofan' ? kpi('Bypass ratio', fmt(p.BPR, 4), '') : ''}
            ${p.Vratio != null ? kpi('Jet velocity ratio', fmt(p.Vratio, 3), '', '', `bypass ÷ core; textbook optimum ≈ ${fmt(p.Vratio_opt, 2)}`) : ''}
            ${kpi('Fuel–air ratio', fmt(p.FAR, 3), '')}
            ${kpi('Fuel flow', fq('flow', p.Wfuel * 3600, 4), unit('flow').replace('/s', '/h'))}
            ${kpi('Thermal efficiency', fmt(p.eta_th * 100, 3), '%')}
            ${kpi('Propulsive efficiency', p.eta_prop == null ? '–' : fmt(p.eta_prop * 100, 3), '%')}
            ${kpi('Overall efficiency', p.eta_overall == null ? '–' : fmt(p.eta_overall * 100, 3), '%', '', 'η_th × η_prop')}
            ${kpi('Gross thrust / ram drag', fq('thrust', p.Fg, 3), '/ ' + fq('thrust', p.ram_drag, 3) + ' ' + unit('thrust'))}
          </div></div>
        <div class="card"><div class="card-head"><h3>Engine temperatures</h3><span class="small-muted">Components coloured by exit total temperature</span></div>
          <div class="schematic-wrap">${renderSchematic(state.arch, temps)}</div></div>
        <div class="card">
          <div class="tabs" id="des-tabs">
            <button class="tab active" data-tab="stations">Station data</button>
            <button class="tab" data-tab="components">Components</button>
            <button class="tab" data-tab="profile">Tt & Pt through engine</button>
            <button class="tab" data-tab="ts">T–s diagram</button>
            <button class="tab" data-tab="maps">Compressor maps</button>
          </div>
          <div id="des-tab-body"></div>
        </div>`;
    } else if (state.designError && !cur) {
      body = `<div class="banner bad"><b>Did not converge.</b> ${esc(state.designError)}<br>Try moving the cycle back towards the preset values, raising T4, or lowering OPR — then run again.</div>`;
    }

    main.innerHTML = header(i, 'Commit to one cycle and let pyCycle size the engine: it finds the airflow that delivers exactly the required cruise thrust, then reports every station, component and the physical size.')
      + learn('What "sizing" means', `
        <p>At the design point, pyCycle treats the cycle parameters (PRs, efficiencies, T4, BPR) as <i>inputs</i> and solves for the airflow needed to meet thrust. From airflow and the assumed Mach number at each station it computes <b>flow areas</b> — this is the physical size of the engine.</p>
        <p>It also <b>scales the component maps</b>: a generic compressor or turbine map is stretched so that its design point lands on your pressure ratio, flow and efficiency. Those scaled maps and the frozen areas (especially nozzle throats) are what determine how the engine behaves at every other condition — the subject of the next step.</p>
        <span class="eq">Fn = Fg − ṁ₀·V₀      Fg = Σ ṁⱼ·Vⱼ + (Pⱼ − P₀)·Aⱼ</span>`)
      + pyGate()
      + `<div class="card"><div class="btn-row">
          <button class="btn" id="des-run" ${py.ready ? '' : 'disabled'}>${D ? 'Re-run design point' : 'Run design point'}</button>
          <span class="small-muted">Cycle: OPR ${fmt(state.cycle.OPR, 4)} · T4 ${fq('temp', state.cycle.T4, 4)} ${unit('temp')}${state.arch === 'turbofan' ? ` · BPR ${fmt(state.cycle.BPR, 3)} · FPR ${fmt(state.cycle.FPR, 3)}` : ''}</span>
        </div></div>`
      + body
      + navRow(i, 'Off-design analysis', !!D && cur, D && cur ? '' : 'Run the design point to continue');

    document.getElementById('des-run').addEventListener('click', runDesign);
    if (D) {
      const tabs = document.getElementById('des-tabs');
      const show = (t) => {
        tabs.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === t));
        destroyCharts();
        designTab(t, D);
      };
      tabs.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => show(b.dataset.tab)));
      show('stations');
    }
  }

  function stationTable(stations) {
    return `<div class="table-wrap"><table class="data"><thead><tr>
      <th class="l">Station</th><th class="l">Location</th><th>W<br>${unit('flow')}</th><th>Tt<br>${unit('temp')}</th><th>Pt<br>${unit('press')}</th>
      <th>Ts<br>${unit('temp')}</th><th>Ps<br>${unit('press')}</th><th>Mach</th><th>V<br>${unit('vel')}</th><th>Area<br>${unit('area')}</th></tr></thead><tbody>
      ${stations.map((s) => `<tr><td class="mono">${s.id}</td><td class="l">${s.name}</td><td>${fq('flow', s.W, 4)}</td><td>${fq('temp', s.Tt, 4)}</td><td>${fq('press', s.Pt, 4)}</td>
        <td>${fq('temp', s.Ts, 4)}</td><td>${fq('press', s.Ps, 4)}</td><td>${fmt(s.MN, 3)}</td><td>${fq('vel', s.V, 4)}</td><td>${s.id === '0' ? '–' : fq('area', s.A, 4)}</td></tr>`).join('')}
      </tbody></table></div>`;
  }

  function designTab(t, D) {
    const el = document.getElementById('des-tab-body');
    const p = D.perf;
    if (t === 'stations') {
      el.innerHTML = stationTable(D.stations) + '<p class="small-muted" style="margin-top:8px">Totals (Tt, Pt) include the kinetic energy of the flow; statics (Ts, Ps) are what a thermometer moving with the gas would read. Areas are the physical flow areas pyCycle computed from the assumed station Mach numbers.</p>';
    } else if (t === 'components') {
      el.innerHTML = `<div class="grid two">
        <div><h3>Compressors</h3><div class="table-wrap"><table class="data"><thead><tr><th class="l">Component</th><th>PR</th><th>η</th><th>Corr. flow<br>${unit('flow')}</th><th>Power<br>${unit('power')}</th><th>Surge margin</th></tr></thead><tbody>
          ${p.compressors.map((c) => `<tr><td class="l">${c.name}</td><td>${fmt(c.PR, 4)}</td><td>${fmt(c.eff, 4)}</td><td>${fq('flow', c.Wc, 4)}</td><td>${fq('power', c.power, 4)}</td><td>${fmt(c.SMN, 3)}%</td></tr>`).join('')}
        </tbody></table></div>
        <h3 style="margin-top:16px">Turbines</h3><div class="table-wrap"><table class="data"><thead><tr><th class="l">Component</th><th>PR</th><th>η</th><th>Power<br>${unit('power')}</th></tr></thead><tbody>
          ${p.turbines.map((c) => `<tr><td class="l">${c.name}</td><td>${fmt(c.PR, 4)}</td><td>${fmt(c.eff, 4)}</td><td>${fq('power', c.power, 4)}</td></tr>`).join('')}
        </tbody></table></div></div>
        <div><h3>Shafts</h3><div class="table-wrap"><table class="data"><thead><tr><th class="l">Spool</th><th>Speed<br>rpm</th></tr></thead><tbody>
          ${p.shafts.map((s) => `<tr><td class="l">${s.name}</td><td>${fmt(s.N, 5)}</td></tr>`).join('')}</tbody></table></div>
        <h3 style="margin-top:16px">Nozzles</h3><div class="table-wrap"><table class="data"><thead><tr><th class="l">Nozzle</th><th>Gross thrust<br>${unit('thrust')}</th><th>Jet V<br>${unit('vel')}</th><th>Exit Mach</th><th>Throat area<br>${unit('area')}</th><th>Pt/Ps</th></tr></thead><tbody>
          ${p.nozzles.map((n) => `<tr><td class="l">${n.name}</td><td>${fq('thrust', n.Fg, 4)}</td><td>${fq('vel', n.V, 4)}</td><td>${fmt(n.MN, 3)}</td><td>${fq('area', n.A_throat, 4)}</td><td>${fmt(n.PR, 3)}</td></tr>`).join('')}</tbody></table></div>
        <p class="small-muted" style="margin-top:8px">The turbines' power exactly equals the power absorbed by the compressors on the same shaft (plus any power extraction) — that is the shaft balance pyCycle enforces. Surge margin at the design point is set by where the map is scaled; it changes off-design.</p></div>
      </div>`;
    } else if (t === 'profile') {
      el.innerHTML = '<div class="chart-box tall"><canvas id="ch-prof"></canvas></div><p class="small-muted">Pressure rises through the compressors and falls through the turbines; temperature jumps in the burner. Notice how much of the burner\'s temperature rise is needed just to drive the compressors.</p>';
      const st = D.stations.filter((s) => s.Tt != null);
      chart('ch-prof', {
        type: 'bar',
        data: {
          labels: st.map((s) => `${s.id} ${s.name}`),
          datasets: [
            { type: 'bar', label: `Tt [${unit('temp')}]`, data: st.map((s) => toD('temp', s.Tt)), backgroundColor: st.map((s) => tempColor(s.Tt)), yAxisID: 'y' },
            { type: 'line', label: `Pt [${unit('press')}]`, data: st.map((s) => toD('press', s.Pt)), borderColor: PALETTE[0], backgroundColor: PALETTE[0], yAxisID: 'y1', tension: 0 },
          ],
        },
        options: { scales: { x: { ticks: { autoSkip: false, maxRotation: 60, minRotation: 30 } }, y: axis(`Total temperature [${unit('temp')}]`), y1: axis(`Total pressure [${unit('press')}]`, { position: 'right', grid: { display: false } }) } },
      });
    } else if (t === 'ts') {
      el.innerHTML = '<div class="chart-box tall"><canvas id="ch-ts"></canvas></div><p class="small-muted">The Brayton cycle on a temperature–entropy diagram (total conditions). Compression (2→3) climbs steeply, heat addition (3→4) moves right along a constant-pressure line, expansion (4→9) drops back down. Entropy rise in compressors and turbines is the signature of their inefficiency; the burner pressure loss also adds entropy.</p>';
      const byId = Object.fromEntries(D.stations.map((s) => [s.id, s]));
      const s0 = byId['0'].S;
      const pts = (path) => path.map((id) => byId[id]).filter((s) => s && s.S != null).map((s) => ({ x: toD('entropy', s.S - s0), y: toD('temp', s.Tt), id: s.id }));
      const ds = [{ label: 'Core', data: pts(D.ts_path), borderColor: PALETTE[1], backgroundColor: PALETTE[1], showLine: true, pointRadius: 4 }];
      if (D.ts_bypass) ds.push({ label: 'Bypass', data: pts(D.ts_bypass), borderColor: PALETTE[0], backgroundColor: PALETTE[0], showLine: true, pointRadius: 4, borderDash: [5, 4] });
      chart('ch-ts', {
        type: 'scatter', data: { datasets: ds },
        options: {
          scales: { x: axis(`Entropy rise s − s₀ [${unit('entropy')}]`), y: axis(`Total temperature [${unit('temp')}]`) },
          plugins: { tooltip: { callbacks: { label: (c) => `Station ${c.raw.id}: Tt ${fmt(c.raw.y, 4)}` } } },
        },
        plugins: [stationLabels],
      });
    } else if (t === 'maps') {
      mapTabs(el, D.maps, [], []);
    }
  }

  // Chart.js plugin: label points with their station id
  const stationLabels = {
    id: 'stationLabels',
    afterDatasetsDraw(ch) {
      const ctx = ch.ctx;
      ctx.save();
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.fillStyle = cssVar('--text');
      ch.data.datasets.forEach((ds, di) => {
        const meta = ch.getDatasetMeta(di);
        meta.data.forEach((pt, k) => { const id = ds.data[k].id; if (id) ctx.fillText(id, pt.x + 6, pt.y - 6); });
      });
      ctx.restore();
    },
  };

  /* Compressor maps with design point, OD points and operating lines.
   * odPts: [{label, comps:[{Wc, PR}]}] ; lines: [{label, pts:[[{Wc,PR}...] per comp]}] */
  function mapTabs(el, maps, odPts, lines) {
    el.innerHTML = `<div class="tabs" id="map-tabs">${maps.map((m, k) => `<button class="tab ${k === 0 ? 'active' : ''}" data-map="${k}">${m.name}</button>`).join('')}</div>
      <div class="chart-box tall"><canvas id="ch-map"></canvas></div>
      <p class="small-muted">Scaled performance map: grey lines are constant corrected-speed lines (labelled as a fraction of design speed), the red line is the surge (stall) line. Surge margin measures how far the operating point sits below it. ${odPts.length || lines.length ? 'Off-design points and the operating line show how the engine moves across the map as conditions and throttle change.' : 'Run off-design cases in the next step to see the operating line.'}</p>`;
    let mapChart = null;
    const draw = (k) => {
      if (mapChart) { mapChart.destroy(); charts.splice(charts.indexOf(mapChart), 1); }
      const m = maps[k];
      const ds = m.lines.map((l) => ({
        label: `_N ${fmt(l.N * 100, 3)}%`, data: l.Wc.map((w, j) => ({ x: toD('flow', w), y: l.PR[j] })), showLine: true, pointRadius: 0, borderWidth: 1,
        borderColor: cssVar('--muted'), nlabel: `${fmt(l.N * 100, 3)}%`,
      }));
      ds.push({ label: 'Surge line', data: m.surge.Wc.map((w, j) => ({ x: toD('flow', w), y: m.surge.PR[j] })), showLine: true, pointRadius: 0, borderColor: cssVar('--bad'), borderWidth: 2.5 });
      lines.forEach((ln, li) => ds.push({ label: ln.label, data: ln.pts.map((p) => p[k]).filter(Boolean).map((c) => ({ x: toD('flow', c.Wc), y: c.PR })), showLine: true, borderColor: PALETTE[(li + 2) % PALETTE.length], backgroundColor: PALETTE[(li + 2) % PALETTE.length], pointRadius: 3 }));
      odPts.forEach((o, oi) => ds.push({ label: o.label, data: [{ x: toD('flow', o.comps[k].Wc), y: o.comps[k].PR }], pointRadius: 7, pointStyle: 'triangle', borderColor: PALETTE[(oi + 1) % PALETTE.length], backgroundColor: PALETTE[(oi + 1) % PALETTE.length] }));
      ds.push({ label: 'Design point', data: [{ x: toD('flow', m.design.Wc), y: m.design.PR }], pointRadius: 9, pointStyle: 'star', borderColor: cssVar('--text'), backgroundColor: cssVar('--text'), borderWidth: 2 });
      // sensible axis limits: data around design
      const allW = m.lines.flatMap((l) => l.Wc), allP = m.lines.flatMap((l) => l.PR);
      mapChart = chart('ch-map', {
        type: 'scatter', data: { datasets: ds },
        options: {
          scales: {
            x: axis(`Corrected inlet flow [${unit('flow')}]`, { min: toD('flow', Math.min(...allW)) * 0.95, max: toD('flow', Math.max(...allW)) * 1.02 }),
            y: axis('Pressure ratio', { min: 1, max: Math.max(...allP) * 1.03 }),
          },
          plugins: { legend: { labels: { filter: (it) => !it.text.startsWith('_') } } },
        },
        plugins: [{
          id: 'speedLabels',
          afterDatasetsDraw(ch) {
            const ctx = ch.ctx; ctx.save(); ctx.font = '10px JetBrains Mono, monospace'; ctx.fillStyle = cssVar('--muted');
            ch.data.datasets.forEach((d, di) => {
              if (!d.nlabel) return;
              const meta = ch.getDatasetMeta(di);
              const last = meta.data[0];
              if (last && last.x > ch.chartArea.left && last.y > ch.chartArea.top) ctx.fillText(d.nlabel, last.x - 30, last.y - 4);
            });
            ctx.restore();
          },
        }],
      });
    };
    el.querySelectorAll('[data-map]').forEach((b) => b.addEventListener('click', () => {
      el.querySelectorAll('[data-map]').forEach((x) => x.classList.toggle('active', x === b));
      draw(+b.dataset.map);
    }));
    draw(0);
  }

  // ======================================================================= //
  //  Step 6 – Off-design
  // ======================================================================= //
  function ensureOdPoints() {
    const key = JSON.stringify([state.req, state.tech.T4max, state.cycle.T4]);
    if (!state.odPoints || (!state.odEdited && state.odPointsKey !== key)) {
      state.odPoints = defaultOdPoints();
      state.odPointsKey = key;
    }
  }

  async function runOd() {
    const btn = document.getElementById('od-run');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running…';
    const key = designKey();
    const res = [];
    for (let k = 0; k < state.odPoints.length; k++) {
      const pnt = state.odPoints[k];
      btn.innerHTML = `<span class="spinner"></span> Point ${k + 1}/${state.odPoints.length}…`;
      const r = await call('off_design', state.arch, designInputs(), odInputs(pnt));
      res.push(r.ok ? { ok: true, perf: r.data.perf, stations: r.data.stations } : { ok: false, error: r.error });
    }
    state.odResults = { key, points: JSON.parse(JSON.stringify(state.odPoints)), res };
    save();
    if (STEPS[state.step].id === 'offdesign') render();
  }

  async function runHook() {
    const h = state.hook;
    const base = state.odPoints[h.point] || state.odPoints[0];
    const n = Math.max(3, Math.min(15, Math.round(h.n)));
    const hi = state.tech.T4max, lo = hi * h.lowFrac;
    const btn = document.getElementById('hook-run');
    btn.disabled = true;
    const out = [];
    for (let k = 0; k < n; k++) {
      const T4 = hi - (hi - lo) * k / (n - 1);
      btn.innerHTML = `<span class="spinner"></span> ${k + 1}/${n}`;
      const r = await call('off_design', state.arch, designInputs(), odInputs({ ...base, T4 }));
      out.push(r.ok ? { ok: true, T4, perf: r.data.perf } : { ok: false, T4, error: r.error });
    }
    h.results = out; h.key = designKey(); h.base = { ...base };
    save();
    if (STEPS[state.step].id === 'offdesign') render();
  }

  function renderOffDesign(i) {
    ensureOdPoints();
    const D = state.design && designCurrent() ? state.design.data : null;
    const od = state.odResults && state.odResults.key === designKey() ? state.odResults : null;
    const h = state.hook;
    const hookCur = h.results && h.key === designKey();
    const tf = state.arch === 'turbofan';

    const rows = state.odPoints.map((p, k) => `<tr>
      <td class="l"><input class="plain wide" data-od="${k}" data-k="name" value="${esc(p.name)}"></td>
      <td><input class="plain" type="number" step="any" data-od="${k}" data-k="alt" data-q="alt" value="${+toD('alt', p.alt).toPrecision(5)}"></td>
      <td><input class="plain" type="number" step="any" data-od="${k}" data-k="MN" data-q="none" value="${p.MN}"></td>
      <td><input class="plain" type="number" step="any" data-od="${k}" data-k="dTs" data-q="dtemp" value="${+toD('dtemp', p.dTs).toPrecision(4)}"></td>
      <td><input class="plain" type="number" step="any" data-od="${k}" data-k="T4" data-q="temp" value="${+toD('temp', p.T4).toPrecision(5)}"></td>
      <td><button class="btn ghost small" data-del="${k}" title="Remove">✕</button></td></tr>`).join('');

    let results = '';
    if (od) {
      const smMin = state.req.SM_min;
      results = `<div class="table-wrap" style="margin-top:14px"><table class="data"><thead><tr>
        <th class="l">Point</th><th>Net thrust<br>${unit('thrust')}</th><th>TSFC<br>${unit('tsfc')}</th><th>Airflow<br>${unit('flow')}</th>${tf ? '<th>BPR</th>' : ''}<th>OPR</th>
        <th>T3<br>${unit('temp')}</th><th>T4<br>${unit('temp')}</th>${od.res.find((r) => r.ok) ? od.res.find((r) => r.ok).perf.shafts.map((s) => `<th>${s.name}<br>% design</th>`).join('') : ''}
        ${D.perf.compressors.map((c) => `<th>${c.name.split(' ')[0]} SM</th>`).join('')}</tr></thead><tbody>
        ${od.res.map((r, k) => {
          const pnt = od.points[k];
          if (!r.ok) return `<tr><td class="l">${esc(pnt.name)}</td><td colspan="12" class="l small-muted">did not converge — ${esc(r.error)}</td></tr>`;
          const p = r.perf;
          const toFail = pnt.role === 'takeoff' && p.Fn < state.req.Fn_TO;
          return `<tr><td class="l">${esc(pnt.name)}</td><td style="${toFail ? 'color:var(--bad);font-weight:600' : ''}">${fq('thrust', p.Fn, 4)}</td><td>${fq('tsfc', p.TSFC, 4)}</td><td>${fq('flow', p.W, 4)}</td>${tf ? `<td>${fmt(p.BPR, 3)}</td>` : ''}<td>${fmt(p.OPR, 3)}</td>
            <td style="${p.T3 > state.tech.T3max ? 'color:var(--bad);font-weight:600' : ''}">${fq('temp', p.T3, 4)}</td><td>${fq('temp', p.T4, 4)}</td>
            ${p.shafts.map((s, j) => `<td>${fmt(100 * s.N / D.perf.shafts[j].N, 3)}</td>`).join('')}
            ${p.compressors.map((c) => `<td style="${c.SMN < smMin ? 'color:var(--bad);font-weight:600' : ''}">${fmt(c.SMN, 3)}%</td>`).join('')}</tr>`;
        }).join('')}</tbody></table></div>
        <p class="small-muted" style="margin-top:8px">Red values violate a requirement (takeoff thrust, T3 limit or minimum surge margin). The "cruise (design check)" row should reproduce the design point — a useful sanity check that the off-design model is consistent.</p>`;
    }

    main.innerHTML = header(i, 'A real engine flies the whole mission, not just the design point. With the hardware now frozen (areas and scaled maps), pyCycle finds where the engine settles at other flight conditions and throttle settings.')
      + learn('How off-design analysis works', `
        <p>Off-design, the unknowns change. The geometry is fixed, so pyCycle now solves for <b>airflow</b>, <b>shaft speeds</b> and (for a turbofan) <b>bypass ratio</b> such that:</p>
        <ul><li>each shaft's power balances,</li><li>the flow squeezes through the fixed nozzle throat areas,</li><li>every compressor and turbine operates somewhere on its map (not just at the design point).</li></ul>
        <p>The throttle here is <b>T4</b>. At hot-day takeoff the engine runs at the T4 limit — hot air is less dense, so thrust drops and T3 rises. The throttle sweep traces the classic <i>thrust–TSFC "hook"</i> and the <i>operating line</i> across the compressor maps.</p>
        <p>Watch the <b>surge margin</b>: as the throttle is pulled back, compressors (especially boosters) often move closer to surge. Real engines use bleed valves and variable stators to manage this.</p>`)
      + pyGate()
      + (D ? '' : `<div class="banner warn"><b>No current design.</b> Run the design point first. <button class="btn small" data-go="4" style="margin-left:8px">Go to design point</button></div>`)
      + `<div class="card"><div class="card-head"><h3>Operating points</h3>
          <div class="btn-row"><button class="btn ghost small" id="od-add">+ Add point</button><button class="btn ghost small" id="od-reset">Reset from requirements</button></div></div>
        <div class="table-wrap"><table class="data"><thead><tr><th class="l">Name</th><th>Altitude<br>${unit('alt')}</th><th>Mach</th><th>ISA ΔT<br>${unit('dtemp')}</th><th>T4 (throttle)<br>${unit('temp')}</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>
        <div class="btn-row" style="margin-top:12px"><button class="btn" id="od-run" ${py.ready && D ? '' : 'disabled'}>Run operating points</button>
          <span class="small-muted">Takeoff requirement: ${fq('thrust', state.req.Fn_TO, 4)} ${unit('thrust')} · T4 limit ${fq('temp', state.tech.T4max, 4)} ${unit('temp')} · T3 limit ${fq('temp', state.tech.T3max, 4)} ${unit('temp')}</span></div>
        ${results}
      </div>
      <div class="card"><div class="card-head"><h3>Throttle sweep (thrust hook & operating line)</h3></div>
        <div class="fields">
          <div class="field"><label>Flight condition</label><div class="input-wrap"><select id="hook-pt">${state.odPoints.map((p, k) => `<option value="${k}" ${h.point === k ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div></div>
          <div class="field"><label>Lowest T4 (fraction of max)</label><div class="input-wrap"><input id="hook-lo" type="number" step="0.01" min="0.5" max="0.95" value="${h.lowFrac}"></div></div>
          <div class="field"><label>Points</label><div class="input-wrap"><input id="hook-n" type="number" step="1" min="3" max="15" value="${h.n}"></div></div>
        </div>
        <div class="btn-row" style="margin-top:12px"><button class="btn secondary" id="hook-run" ${py.ready && D ? '' : 'disabled'}>Run throttle sweep</button></div>
        <div id="hook-out"></div>
      </div>
      ${D ? `<div class="card"><h3>Compressor maps</h3><div id="od-maps"></div></div>` : ''}`
      + navRow(i, 'Check requirements', !!D);

    // bindings
    main.querySelectorAll('input[data-od]').forEach((inp) => inp.addEventListener('input', () => {
      const p = state.odPoints[+inp.dataset.od];
      if (inp.dataset.k === 'name') p.name = inp.value;
      else { const v = parseFloat(inp.value); if (!isFinite(v)) return; p[inp.dataset.k] = fromD(inp.dataset.q, v); }
      state.odEdited = true; save();
    }));
    main.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => { state.odPoints.splice(+b.dataset.del, 1); state.odEdited = true; save(); render(); }));
    document.getElementById('od-add').addEventListener('click', () => {
      state.odPoints.push({ name: 'Custom point', role: 'custom', alt: state.req.alt, MN: state.req.MN, dTs: 0, T4: state.cycle.T4 });
      state.odEdited = true; save(); render();
    });
    document.getElementById('od-reset').addEventListener('click', () => { state.odPoints = null; state.odEdited = false; save(); render(); });
    document.getElementById('od-run').addEventListener('click', runOd);
    document.getElementById('hook-pt').addEventListener('change', (e) => { h.point = +e.target.value; save(); });
    document.getElementById('hook-lo').addEventListener('input', (e) => { const v = parseFloat(e.target.value); if (v > 0.3 && v < 1) { h.lowFrac = v; save(); } });
    document.getElementById('hook-n').addEventListener('input', (e) => { const v = parseInt(e.target.value, 10); if (v >= 3) { h.n = v; save(); } });
    document.getElementById('hook-run').addEventListener('click', runHook);

    if (hookCur) {
      const ok = h.results.filter((r) => r.ok);
      const failed = h.results.length - ok.length;
      document.getElementById('hook-out').innerHTML = `
        ${failed ? `<div class="banner warn" style="margin-top:12px">${failed} throttle point(s) did not converge (usually the lowest T4s, where the engine approaches idle and components leave their maps).</div>` : ''}
        <div class="grid two" style="margin-top:14px">
          <div><h3>Thrust hook — ${esc(h.base.name)}</h3><div class="chart-box"><canvas id="ch-hook"></canvas></div></div>
          <div><h3>Net thrust & shaft speed vs T4</h3><div class="chart-box"><canvas id="ch-hook2"></canvas></div></div>
        </div>`;
      chart('ch-hook', {
        type: 'scatter',
        data: { datasets: [{ label: 'TSFC', data: ok.map((r) => ({ x: toD('thrust', r.perf.Fn), y: toD('tsfc', r.perf.TSFC), T4: r.T4 })), showLine: true, borderColor: PALETTE[0], backgroundColor: PALETTE[0], tension: 0.3 }] },
        options: { scales: { x: axis(`Net thrust [${unit('thrust')}]`), y: axis(`TSFC [${unit('tsfc')}]`) }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `T4 ${fq('temp', c.raw.T4, 4)} ${unit('temp')}: Fn ${fmt(c.raw.x, 4)}, TSFC ${fmt(c.raw.y, 4)}` } } } },
      });
      const shafts = ok[0] ? ok[0].perf.shafts.map((s, j) => ({
        label: `${s.name} speed [% design]`, yAxisID: 'y1', borderColor: PALETTE[j + 2], backgroundColor: PALETTE[j + 2], borderDash: [4, 3], showLine: true,
        data: ok.map((r) => ({ x: toD('temp', r.T4), y: 100 * r.perf.shafts[j].N / D.perf.shafts[j].N })),
      })) : [];
      chart('ch-hook2', {
        type: 'scatter',
        data: { datasets: [{ label: `Net thrust [${unit('thrust')}]`, data: ok.map((r) => ({ x: toD('temp', r.T4), y: toD('thrust', r.perf.Fn) })), showLine: true, borderColor: PALETTE[1], backgroundColor: PALETTE[1] }, ...shafts] },
        options: { scales: { x: axis(`T4 [${unit('temp')}]`), y: axis(`Net thrust [${unit('thrust')}]`), y1: axis('Shaft speed [% design]', { position: 'right', grid: { display: false } }) } },
      });
    }

    if (D) {
      const odPts = od ? od.res.map((r, k) => (r.ok ? { label: od.points[k].name, comps: r.perf.compressors } : null)).filter(Boolean) : [];
      const lines = hookCur ? [{ label: `Operating line (${h.base.name})`, pts: h.results.filter((r) => r.ok).map((r) => r.perf.compressors) }] : [];
      mapTabs(document.getElementById('od-maps'), D.maps, odPts, lines);
    }
  }

  // ======================================================================= //
  //  Step 7 – Review
  // ======================================================================= //
  function evaluateChecks() {
    const D = state.design && designCurrent() ? state.design.data : null;
    const r = state.req, t = state.tech;
    const od = state.odResults && state.odResults.key === designKey() ? state.odResults : null;
    const hook = state.hook.results && state.hook.key === designKey() ? state.hook.results : null;
    const checks = [];
    if (!D) return { D, checks };
    const p = D.perf;
    checks.push({ name: 'Cruise thrust', detail: 'Engine sized to deliver the required cruise thrust.', status: 'pass', val: `${fq('thrust', p.Fn, 4)} ${unit('thrust')}` });
    const tsfcM = (r.TSFC - p.TSFC) / r.TSFC;
    checks.push({ name: 'Cruise TSFC', detail: `Target ≤ ${fq('tsfc', r.TSFC, 4)} ${unit('tsfc')}`, status: tsfcM >= 0 ? (tsfcM < 0.01 ? 'marg' : 'pass') : 'fail', val: `${fq('tsfc', p.TSFC, 4)} ${unit('tsfc')}`,
      fix: 'Raise OPR (thermal efficiency), raise BPR / lower FPR (propulsive efficiency), or assume better component efficiencies.' });
    const d = D.sizing.fan_diameter;
    checks.push({ name: state.arch === 'turbofan' ? 'Fan diameter' : 'Inlet diameter', detail: `Limit ${fq('length', r.D_max, 3)} ${unit('length')}`, status: d <= r.D_max ? 'pass' : 'fail', val: `${fq('length', d, 3)} ${unit('length')}`,
      fix: 'Increase specific thrust: raise T4 or FPR, lower BPR. This usually costs some TSFC — a classic trade-off.' });
    checks.push({ name: 'Cruise T4 within limit', detail: `Max ${fq('temp', t.T4max, 4)} ${unit('temp')}`, status: state.cycle.T4 <= t.T4max ? 'pass' : 'fail', val: `${fq('temp', state.cycle.T4, 4)} ${unit('temp')}`,
      fix: 'Lower cruise T4 or assume a more advanced turbine technology.' });

    const toIdx = od ? od.points.findIndex((pt) => pt.role === 'takeoff') : -1;
    const to = toIdx >= 0 ? od.res[toIdx] : null;
    if (!od || toIdx < 0) {
      checks.push({ name: 'Takeoff thrust', detail: 'Run the operating points in step 6 (with a takeoff point).', status: 'na', val: '–' });
      checks.push({ name: 'Takeoff T3 within limit', detail: 'Needs the takeoff operating point.', status: 'na', val: '–' });
    } else if (!to.ok) {
      checks.push({ name: 'Takeoff thrust', detail: 'Takeoff point did not converge.', status: 'fail', val: '–', fix: 'The engine could not reach this condition — revisit the cycle (lower OPR or higher T4 limit).' });
    } else {
      const m = (to.perf.Fn - r.Fn_TO) / r.Fn_TO;
      checks.push({ name: 'Takeoff thrust', detail: `Required ≥ ${fq('thrust', r.Fn_TO, 4)} ${unit('thrust')} at ${od.points[toIdx].name}`, status: m >= 0 ? (m < 0.02 ? 'marg' : 'pass') : 'fail',
        val: `${fq('thrust', to.perf.Fn, 4)} ${unit('thrust')}`, fix: 'Increase engine size (raise cruise thrust margin), raise the T4 limit, or lower BPR — high-BPR engines lapse strongly from takeoff to cruise.' });
      checks.push({ name: 'Takeoff T3 within limit', detail: `Max ${fq('temp', t.T3max, 4)} ${unit('temp')} (compressor disk material)`, status: to.perf.T3 <= t.T3max ? 'pass' : 'fail',
        val: `${fq('temp', to.perf.T3, 4)} ${unit('temp')}`, fix: 'Lower OPR, or assume better compressor materials (higher T3 limit).' });
    }
    // surge margins at the design and operating points (the requirement)
    let minSM = Infinity, where = '';
    const consider = (perf, label) => perf.compressors.forEach((c) => { if (c.SMN < minSM) { minSM = c.SMN; where = `${c.name} at ${label}`; } });
    consider(p, 'design point');
    if (od) od.res.forEach((rr, k) => rr.ok && consider(rr.perf, od.points[k].name));
    checks.push({ name: 'Surge margin', detail: `Minimum ≥ ${fmt(r.SM_min, 3)}% at the design and operating points. Lowest: ${where}.`, status: minSM >= r.SM_min ? 'pass' : 'fail', val: `${fmt(minSM, 3)}%`,
      fix: 'Change the pressure-ratio split between compressors (e.g. less booster PR, more HPC PR), or rematch the cycle (a turbojet moves towards surge when takeoff T4/T2 is much higher than at the design point — try a higher design T4).' });
    // part-power margins from the throttle sweep: informative, real engines use handling bleeds here
    if (hook) {
      let hm = Infinity, hw = '';
      hook.forEach((rr) => rr.ok && rr.perf.compressors.forEach((c) => { if (c.SMN < hm) { hm = c.SMN; hw = `${c.name} at T4 ${fq('temp', rr.T4, 4)} ${unit('temp')}`; } }));
      if (isFinite(hm)) checks.push({ name: 'Part-power surge margin (throttle sweep)', detail: `Lowest: ${hw}. Informative — at low power real engines open handling-bleed valves or close variable stators to protect the compressors.`,
        status: hm >= r.SM_min ? 'pass' : 'marg', val: `${fmt(hm, 3)}%`, fix: 'Not a failure here: it tells you the engine would need a handling bleed or variable geometry at low power — both standard features.' });
    }
    return { D, checks };
  }

  function renderReview(i) {
    const { D, checks } = evaluateChecks();
    const icon = { pass: '✓', fail: '✕', na: '?', marg: '!' };
    const nFail = checks.filter((c) => c.status === 'fail').length;
    const nMarg = checks.filter((c) => c.status === 'marg').length;
    const nNa = checks.filter((c) => c.status === 'na').length;
    let verdict = '';
    if (D) {
      verdict = nFail === 0 && nNa === 0
        ? `<div class="banner good"><b>All requirements met${nMarg ? ` (${nMarg} item(s) worth a look)` : ''}.</b> This cycle closes the design. Real programs would now move on to preliminary component design (flow-path, stage counts, cooling flows, weight) and iterate the cycle again with better estimates.</div>`
        : nFail
          ? `<div class="banner bad"><b>${nFail} requirement(s) not met.</b> This is normal — engine design is iterative. Use the suggestions below, return to the cycle step, and try again.</div>`
          : `<div class="banner warn"><b>Some checks still need data.</b> Run the operating points in step 6.</div>`;
    }
    const p = D ? D.perf : null;
    main.innerHTML = header(i, 'Close the loop: compare what the engine does against what the aircraft asked for. Failing checks send you back up the process — this iteration is the heart of engine design.')
      + learn('The design spiral', `
        <p>Engine design is a spiral, not a straight line: requirements → concept → cycle → sizing → off-design → check → <i>iterate</i>. Every pass adds detail (component design, weights, cooling, installation effects) and the cycle is re-optimised. Typical conflicts you will see here:</p>
        <ul><li><b>TSFC vs diameter:</b> high BPR saves fuel but grows the fan.</li>
          <li><b>Cruise vs takeoff:</b> an engine sized for cruise may lack takeoff thrust (thrust lapse), especially at high BPR.</li>
          <li><b>OPR vs T3:</b> high OPR is efficient but overheats the compressor exit on a hot day.</li></ul>`)
      + (D ? '' : `<div class="banner warn"><b>No current design.</b> Size the engine first. <button class="btn small" data-go="4" style="margin-left:8px">Go to design point</button></div>`)
      + verdict
      + (D ? `<div class="grid side">
          <div class="card"><h3>Requirements compliance</h3><ul class="checklist">
            ${checks.map((c) => `<li><span class="icon ${c.status}">${icon[c.status]}</span><div><div class="c-name">${c.name}</div><div class="c-detail">${c.detail}</div>
              ${c.status === 'fail' || c.status === 'marg' ? `<div class="c-detail" style="margin-top:4px;color:var(--text)">💡 ${c.fix || ''}</div>` : ''}</div><div class="c-val">${c.val}</div></li>`).join('')}
          </ul>
          <div class="btn-row" style="margin-top:14px"><button class="btn secondary" data-go="3">↺ Iterate the cycle</button><button class="btn ghost" data-go="2">Change technology</button><button class="btn ghost" data-go="0">Revisit requirements</button></div>
          </div>
          <div class="card"><h3>Engine specification</h3>
            <div class="table-wrap"><table class="data"><tbody>
              <tr><td class="l">Architecture</td><td>${state.arch === 'turbofan' ? '2-spool separate-flow turbofan' : 'Single-spool turbojet'}</td></tr>
              <tr><td class="l">Technology level</td><td>${esc(state.techLevel)}</td></tr>
              <tr><td class="l">Design point</td><td>${fq('alt', state.req.alt, 4)} ${unit('alt')}, M ${fmt(state.req.MN, 3)}</td></tr>
              <tr><td class="l">OPR</td><td>${fmt(p.OPR, 4)}</td></tr>
              ${state.arch === 'turbofan' ? `<tr><td class="l">BPR / FPR</td><td>${fmt(p.BPR, 3)} / ${fmt(state.cycle.FPR, 3)}</td></tr>` : ''}
              <tr><td class="l">Cruise T4 / max T4</td><td>${fq('temp', state.cycle.T4, 4)} / ${fq('temp', state.tech.T4max, 4)} ${unit('temp')}</td></tr>
              <tr><td class="l">Design airflow</td><td>${fq('flow', p.W, 4)} ${unit('flow')}</td></tr>
              <tr><td class="l">${state.arch === 'turbofan' ? 'Fan diameter' : 'Inlet diameter'}</td><td>${fq('length', D.sizing.fan_diameter, 3)} ${unit('length')}</td></tr>
              <tr><td class="l">Cruise thrust / TSFC</td><td>${fq('thrust', p.Fn, 4)} ${unit('thrust')} / ${fq('tsfc', p.TSFC, 4)}</td></tr>
            </tbody></table></div>
            <div class="btn-row" style="margin-top:14px">
              <button class="btn ghost small" id="exp-json">Download design (JSON)</button>
              <button class="btn ghost small" id="exp-csv">Stations (CSV)</button>
              <button class="btn ghost small" onclick="window.print()">Print</button>
            </div>
            <p class="small-muted" style="margin-top:10px">The JSON contains every input and pyCycle result so you can reproduce or share this design.</p>
          </div></div>` : '')
      + navRow(i);

    if (D) {
      document.getElementById('exp-json').addEventListener('click', () => {
        download('engine-design.json', JSON.stringify({ generator: 'Gas Turbine Design Studio (pyCycle)', arch: state.arch, requirements: state.req, technology: state.tech, cycle: state.cycle, design_inputs: designInputs(), design: D, off_design: state.odResults, units: 'pyCycle native (ft, degR, psia, lbm/s, lbf, lbm/(h*lbf), in^2, hp)' }, null, 2), 'application/json');
      });
      document.getElementById('exp-csv').addEventListener('click', () => {
        const cols = ['id', 'name', 'W', 'Tt', 'Pt', 'Ts', 'Ps', 'MN', 'V', 'A'];
        const head = 'station,location,W[lbm/s],Tt[degR],Pt[psia],Ts[degR],Ps[psia],Mach,V[ft/s],Area[in2]';
        download('design-stations.csv', [head, ...D.stations.map((s) => cols.map((c) => (s[c] == null ? '' : s[c])).join(','))].join('\n'), 'text/csv');
      });
    }
  }

  function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ======================================================================= //
  //  Render
  // ======================================================================= //
  const RENDER = [renderReq, renderArch, renderTech, renderCycle, renderDesign, renderOffDesign, renderReview];

  function render() {
    destroyCharts();
    document.querySelectorAll('[data-units]').forEach((b) => b.classList.toggle('active', b.dataset.units === state.units));
    renderStepper();
    RENDER[state.step](state.step);
  }

  render();
})();
