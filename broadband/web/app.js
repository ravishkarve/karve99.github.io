/* Broadband Rotor Noise Lab - dashboard logic.
 * Backend: the local `bbnoise serve` API when available, otherwise Pyodide in a Web Worker. */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
};
const SVGNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const fmt = (v, d = 3) => (v === null || v === undefined || !isFinite(v)) ? '–' : (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-2 && v !== 0) ? v.toExponential(d - 1) : (+v.toPrecision(d)).toString());

/* ------------------------------------------------------------------ backend */
const backend = {
  mode: null, worker: null, id: 0, pending: new Map(), readyResolve: null,
  ready: null,
  async init() {
    this.ready = new Promise((r) => { this.readyResolve = r; });
    try {
      const r = await fetch('api/ping', { cache: 'no-store' });
      if (r.ok && (await r.json()).server === 'bbnoise') {
        this.mode = 'server';
        setRuntime('Local bbnoise server (native NumPy)', 1, 'ok');
        this.readyResolve();
        return;
      }
    } catch (e) { /* static hosting */ }
    this.mode = 'worker';
    this.worker = new Worker('web/worker.js?v=1');
    this.worker.onmessage = (ev) => {
      const m = ev.data;
      if (m.type === 'status') { setRuntime(m.text, m.progress, m.ready ? 'ok' : ''); if (m.ready) this.readyResolve(); }
      else if (m.type === 'fatal') setRuntime('Could not start Python: ' + m.error, 1, 'err');
      else if (m.type === 'progress') { const p = this.pending.get(m.id); if (p && p.onProgress) p.onProgress(m.text); }
      else if (m.type === 'result') { const p = this.pending.get(m.id); this.pending.delete(m.id); if (p) p.resolve(m.payload); }
    };
  },
  async call(fn, args = [], onProgress = null) {
    await this.ready;
    if (this.mode === 'server') {
      if (onProgress) onProgress('running on the local server…');
      const r = await fetch('api/' + fn, { method: 'POST', body: JSON.stringify(args) });
      return r.json();
    }
    const id = ++this.id;
    return new Promise((resolve) => { this.pending.set(id, { resolve, onProgress }); this.worker.postMessage({ type: 'call', id, fn, args }); });
  },
};

function setRuntime(text, progress, cls) {
  $('#rt-text').textContent = text;
  $('#rt-bar').style.width = `${Math.round((progress || 0) * 100)}%`;
  $('#rt-dot').className = 'dot ' + (cls || '');
}

/* ------------------------------------------------------------------ charts */
const SLOTS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function niceTicks(lo, hi, n = 6) {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => span / st <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
    for (const m of [1, 2, 5]) { const v = m * 10 ** e; if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
  return out;
}
const fmtF = (v) => v >= 1000 ? `${+(v / 1000).toPrecision(3)}k` : `${+v.toPrecision(3)}`;

/** series: [{label, x, y, color, dash, hidden}] */
function lineChart(el, series, o = {}) {
  el.innerHTML = '';
  const vis = series.filter((d) => !d.hidden);
  if (!series.length) { el.append(h('div', { class: 'empty' }, o.empty || 'Run a case to see results.')); return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 360;
  const m = { l: 56, r: 16, t: 12, b: 42 };
  const xs = series.flatMap((d) => d.x).filter((v) => isFinite(v) && (!o.xlog || v > 0));
  const ys = (vis.length ? vis : series).flatMap((d) => d.y).filter((v) => v !== null && isFinite(v));
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (o.yFloorSpan) y0 = Math.max(y0, y1 - o.yFloorSpan);
  const pad = (y1 - y0) * 0.06 || 1; y0 -= pad; y1 += pad;
  const X = o.xlog ? (v) => m.l + (Math.log10(v) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) * (W - m.l - m.r)
                   : (v) => m.l + (v - x0) / ((x1 - x0) || 1) * (W - m.l - m.r);
  const Y = (v) => m.t + (y1 - v) / ((y1 - y0) || 1) * (H - m.t - m.b);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.aria || 'chart' });
  const g = s('g', { class: 'axis' });
  for (const t of niceTicks(y0, y1)) {
    g.append(s('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: 'gridline' }));
    const tx = s('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }); tx.textContent = t; g.append(tx);
  }
  const xt = o.xlog ? logTicks(x0, x1) : niceTicks(x0, x1, 8);
  for (const t of xt) {
    g.append(s('line', { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'gridline' }));
    const tx = s('text', { x: X(t), y: H - m.b + 16, 'text-anchor': 'middle' }); tx.textContent = o.xlog ? fmtF(t) : t; g.append(tx);
  }
  g.append(s('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'baseline' }));
  svg.append(g);
  const xl = s('text', { x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axis-title' }); xl.textContent = o.xlabel || ''; svg.append(xl);
  const yl = s('text', { x: 14, y: (m.t + H - m.b) / 2, 'text-anchor': 'middle', class: 'axis-title', transform: `rotate(-90 14 ${(m.t + H - m.b) / 2})` }); yl.textContent = o.ylabel || ''; svg.append(yl);
  for (const d of vis) {
    let path = '', pen = false;
    d.x.forEach((xv, i) => {
      const yv = d.y[i];
      if (yv === null || !isFinite(yv) || (o.xlog && xv <= 0)) { pen = false; return; }
      path += `${pen ? 'L' : 'M'}${X(xv).toFixed(1)},${Y(Math.max(yv, y0)).toFixed(1)}`; pen = true;
    });
    const p = s('path', { d: path, class: 'series', stroke: d.color });
    if (d.dash) p.setAttribute('stroke-dasharray', d.dash);
    svg.append(p);
    if (o.markers) d.x.forEach((xv, i) => { if (d.y[i] !== null) svg.append(s('circle', { cx: X(xv), cy: Y(d.y[i]), r: 4, fill: d.color, stroke: 'var(--panel)', 'stroke-width': 2 })); });
  }
  // crosshair + tooltip
  const cross = s('line', { y1: m.t, y2: H - m.b, class: 'cross', visibility: 'hidden' });
  svg.append(cross);
  const hit = s('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
  svg.append(hit);
  const tip = $('#tip');
  const xsRef = vis.length ? vis[0].x : [];
  const move = (ev) => {
    if (!xsRef.length) return;
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    let best = 0, bd = Infinity;
    xsRef.forEach((xv, i) => { const dd = Math.abs(X(xv) - px); if (dd < bd) { bd = dd; best = i; } });
    const xv = xsRef[best];
    cross.setAttribute('x1', X(xv)); cross.setAttribute('x2', X(xv)); cross.setAttribute('visibility', 'visible');
    const rows = vis.map((d) => ({ d, v: d.y[d.x.indexOf(xv)] })).filter((q) => q.v !== undefined && q.v !== null)
      .sort((a, b) => b.v - a.v);
    tip.replaceChildren(h('div', { class: 'h' }, o.xfmt ? o.xfmt(xv) : fmt(xv)),
      ...rows.map(({ d, v }) => {
        const key = h('span'); key.innerHTML = `<svg width="16" height="6"><line x1="0" x2="16" y1="3" y2="3" stroke="${d.color}" stroke-width="2" ${d.dash ? `stroke-dasharray="${d.dash}"` : ''}/></svg>`;
        return h('div', { class: 'r' }, key, h('span', { class: 'v' }, `${v.toFixed(1)} ${o.unit || ''}`), h('span', { class: 'n' }, d.label));
      }));
    tip.style.display = 'block';
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(ev.clientX + 14, window.innerWidth - tw - 8)}px`;
    tip.style.top = `${ev.clientY + 14}px`;
  };
  hit.addEventListener('pointermove', move);
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; cross.setAttribute('visibility', 'hidden'); });
  el.append(svg);
}

function legend(el, series, onToggle) {
  el.replaceChildren(...series.map((d, i) => {
    const key = h('span'); key.innerHTML = `<svg viewBox="0 0 22 10"><line x1="1" x2="21" y1="5" y2="5" stroke="${d.color}" stroke-width="2" ${d.dash ? `stroke-dasharray="${d.dash}"` : ''}/></svg>`;
    return h('span', { class: 'item' + (d.hidden ? ' off' : ''), role: 'button', tabindex: 0, title: 'show / hide',
      onclick: () => onToggle(i), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(i); } } }, key, d.label);
  }));
}

/* ------------------------------------------------------------------ state */
const state = { meta: null, case: null, result: null, view: 'psd', hidden: new Set() };

function colorFor(result) {
  // identity = everything except the formulation; full solid, simplified dashed
  const ids = [];
  const keyOf = (c) => `${c.rotor}|${c.mechanism}|${c.variant}`;
  for (const c of result.curves) if (!ids.includes(keyOf(c))) ids.push(keyOf(c));
  return (c) => {
    const i = ids.indexOf(keyOf(c));
    return { color: i < SLOTS.length ? cssVar(SLOTS[i]) : cssVar('--muted'), dash: c.formulation === 'simplified' ? '6 4' : null };
  };
}

/* ------------------------------------------------------------------ quick controls */
function getPath(obj, path) { return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, v) {
  const ks = path.split('.'); let o = obj;
  for (const k of ks.slice(0, -1)) { if (o[k] == null) o[k] = /^\d+$/.test(k) ? [] : {}; o = o[k]; }
  o[ks.at(-1)] = v;
}
const asList = (v) => v == null ? [] : Array.isArray(v) ? v : [v];

function numField(label, path, opts = {}) {
  const v = getPath(state.case, path);
  const inp = h('input', { type: 'number', step: opts.step || 'any', value: v ?? '', 'aria-label': label });
  inp.addEventListener('change', () => { const x = parseFloat(inp.value); if (isFinite(x)) { setPath(state.case, path, opts.int ? Math.round(x) : x); syncJson(); } });
  return h('div', { class: 'f' }, h('label', {}, label), inp);
}
function selectField(label, path, options) {
  const v = getPath(state.case, path);
  const sel = h('select', { 'aria-label': label }, ...options.map(([val, txt]) => h('option', { value: JSON.stringify(val), selected: JSON.stringify(val) === JSON.stringify(v) }, txt)));
  sel.addEventListener('change', () => { setPath(state.case, path, JSON.parse(sel.value)); syncJson(); });
  return h('div', { class: 'f' }, h('label', {}, label), sel);
}
function checkList(path, options) {
  const cur = new Set(asList(getPath(state.case, path)));
  return h('div', { class: 'checks' }, ...options.map(([val, txt]) => {
    const cb = h('input', { type: 'checkbox', checked: cur.has(val) });
    cb.addEventListener('change', () => {
      const now = new Set(asList(getPath(state.case, path)));
      cb.checked ? now.add(val) : now.delete(val);
      setPath(state.case, path, options.map((o) => o[0]).filter((x) => now.has(x)));
      syncJson();
    });
    return h('label', {}, cb, txt);
  }));
}
function toggle(label, path) {
  const cb = h('input', { type: 'checkbox', checked: getPath(state.case, path) !== false });
  cb.addEventListener('change', () => { setPath(state.case, path, cb.checked); syncJson(); });
  return h('div', { class: 'checks' }, h('label', {}, cb, label));
}
const fs = (title, ...kids) => h('fieldset', {}, h('legend', {}, title), ...kids);

function buildQuick() {
  const c = state.case;
  const q = $('#quick');
  q.innerHTML = '';
  const wpsOpts = state.meta.wps_models.map((m) => [m.key, m.key.replace('_', ' ').replace('dominique gep', 'VKI GEP')]);
  const specOpts = [['vonkarman', 'von Kármán'], ['liepmann', 'Liepmann']];
  if (c.type === 'rotor') {
    q.append(fs('Formulation', checkList('formulations', [['full', 'Full (rotating dipole)'], ['simplified', 'Simplified (Amiet)']]),
      numField('Doppler exponent (simplified)', 'options.doppler_exponent'), numField('Azimuth points (simplified)', 'options.n_psi', { int: true })));
    c.rotors.forEach((r, i) => q.append(fs(`Rotor: ${r.name}`, numField('Blades B', `rotors.${i}.B`, { int: true }),
      numField('Speed [rpm]', `rotors.${i}.rpm`), numField('Tip radius [m]', `rotors.${i}.r_tip`),
      numField('Hub radius [m]', `rotors.${i}.r_hub`), numField('Axial velocity [m/s]', `rotors.${i}.Ux`),
      numField('Strips', `rotors.${i}.n_strips`, { int: true }))));
    if (c.rwi) q.append(fs('Rotor-wake interaction (rear rotor)', toggle('enabled', 'rwi.enabled'), checkList('rwi.spectrum', specOpts),
      numField('Wake centreline TI (of front U)', 'rwi.wake.tu_c'), numField('Wake semi-width / pitch', 'rwi.wake.Lw_over_s'),
      numField('Λ / wake semi-width', 'rwi.wake.Lambda_over_Lw'),
      selectField('Wake turbulence', 'rwi.wake.model', [['periodic', 'periodic (cyclostationary)'], ['averaged', 'passage-averaged'], [['periodic', 'averaged'], 'both']])));
    if (c.ingestion) q.append(fs('Turbulence ingestion', toggle('enabled', 'ingestion.enabled'), checkList('ingestion.spectrum', specOpts),
      numField('Intensity', 'ingestion.intensity'), numField('Integral scale Λ [m]', 'ingestion.Lambda')));
    if (c.self_noise) q.append(fs('Self noise (trailing edge)', toggle('enabled', 'self_noise.enabled'), checkList('self_noise.models', wpsOpts),
      selectField('Boundary layer', 'self_noise.boundary_layer.method', [['bpm', 'BPM NACA 0012'], ['flat_plate', 'flat plate']])));
    q.append(fs('Observer', numField('Distance R [m]', 'observers.R'), numField('Polar angle θ [deg]', 'observers.theta_deg.0')));
  } else {
    q.append(fs('Airfoil', numField('Chord [m]', 'airfoil.chord'), numField('Span [m]', 'airfoil.span'), numField('Velocity U [m/s]', 'airfoil.U')));
    if (c.type === 'airfoil_le') q.append(fs('Turbulence', checkList('turbulence.spectrum', specOpts), numField('Intensity', 'turbulence.intensity'), numField('Integral scale Λ [m]', 'turbulence.Lambda'),
      selectField('LE response', 'options.le_method', [['auto', 'Amiet switch (auto)'], ['high', 'high frequency'], ['low', 'low frequency']])));
    else q.append(fs('Wall pressure', checkList('self_noise.models', wpsOpts),
      selectField('Boundary layer', 'self_noise.boundary_layer.method', [['bpm', 'BPM NACA 0012'], ['flat_plate', 'flat plate']]),
      numField('Angle of attack [deg]', 'self_noise.boundary_layer.alpha_deg'),
      numField('Suction-side β_C', 'self_noise.boundary_layer.beta_c.0'), numField('Suction-side H', 'self_noise.boundary_layer.H.0')));
    q.append(fs('Observer', numField('Distance R [m]', 'observers.R'), numField('Angle θ [deg]', 'observers.theta_deg.0')));
  }
  q.append(fs('Frequencies', numField('f min [Hz]', 'frequency.f_min'), numField('f max [Hz]', 'frequency.f_max'), numField('Points', 'frequency.n', { int: true })));
}

function syncJson() { $('#case-json').value = JSON.stringify(state.case, null, 2); }

function normaliseCase(c) {
  c.options = Object.assign({}, state.meta.defaults.options, c.options || {});
  c.frequency = Object.assign({}, state.meta.defaults.frequency, c.frequency || {});
  if (c.type === 'airfoil_te' && c.self_noise && c.self_noise.boundary_layer) {
    const bl = c.self_noise.boundary_layer;
    if (bl.beta_c === undefined) bl.beta_c = [0, 0];
    if (bl.H === undefined) bl.H = [1.4, 1.4];
    if (bl.alpha_deg === undefined) bl.alpha_deg = 0;
  }
  return c;
}

async function loadCase(key) {
  const r = await backend.call('case', [key]);
  if (!r.ok) { $('#run-msg').textContent = r.error; return; }
  state.case = normaliseCase(r.case);
  const meta = state.meta.cases.find((x) => x.key === key);
  $('#case-desc').textContent = meta.description;
  $('#case-ref').textContent = meta.reference;
  buildQuick();
  syncJson();
}

/* ------------------------------------------------------------------ run + render */
async function run() {
  const btn = $('#run');
  btn.disabled = true;
  $('#run-msg').textContent = 'running…';
  $('#psd-chart').style.opacity = 0.5;
  const t0 = performance.now();
  const r = await backend.call('run', [JSON.stringify(state.case)], (t) => { $('#run-msg').textContent = t; });
  $('#psd-chart').style.opacity = 1;
  btn.disabled = false;
  if (!r.ok) { $('#run-msg').textContent = r.error; return; }
  $('#run-msg').textContent = `${r.result.curves.length} curves in ${((performance.now() - t0) / 1000).toFixed(1)} s`;
  state.result = r.result;
  state.hidden = new Set();
  render();
}

function render() {
  const res = state.result;
  if (!res) { lineChart($('#psd-chart'), []); lineChart($('#dir-chart'), []); return; }
  const col = colorFor(res);
  const series = res.curves.map((c, i) => ({ ...col(c), label: c.label, hidden: state.hidden.has(i),
    x: state.view === 'oct' ? c.third_octave.fc : res.f, y: state.view === 'oct' ? c.third_octave.spl : c.psd_db }));
  const toggleIdx = (i) => { state.hidden.has(i) ? state.hidden.delete(i) : state.hidden.add(i); render(); };
  if (state.view === 'table') renderTable(res);
  else lineChart($('#psd-chart'), series, { xlog: true, xlabel: 'Frequency [Hz]', unit: 'dB',
    ylabel: state.view === 'oct' ? '1/3-octave SPL [dB re 20 µPa]' : 'PSD [dB re (20 µPa)²/Hz]', xfmt: (v) => `${fmtF(v)}Hz`, yFloorSpan: 80 });
  legend($('#psd-legend'), series, toggleIdx);
  const th = res.curves[0] ? res.curves[0].theta_deg : 90;
  $('#psd-title').textContent = `Far-field spectrum at θ = ${th}°, R = ${state.case.observers ? state.case.observers.R : ''} m`;
  const dirs = res.curves.map((c, i) => ({ c, i })).filter(({ c }) => c.directivity);
  $('#dir-card').style.display = dirs.length ? '' : 'none';
  if (dirs.length) {
    const ds = dirs.map(({ c, i }) => {
      const o = c.directivity.theta.map((t, k) => [t, c.directivity.oaspl[k]]).sort((a, b) => a[0] - b[0]);
      return { ...col(c), label: c.label, hidden: state.hidden.has(i), x: o.map((p) => p[0]), y: o.map((p) => p[1]) };
    });
    lineChart($('#dir-chart'), ds, { xlabel: 'Polar angle θ [deg]', ylabel: 'OASPL [dB]', unit: 'dB', markers: true, xfmt: (v) => `θ = ${v}°` });
  }
  renderStats(res);
  renderInfo(res);
  $('#dl-csv').disabled = false; $('#dl-json').disabled = false;
}

function renderTable(res) {
  const el = $('#psd-chart');
  const head = h('tr', {}, h('th', {}, 'f [Hz]'), ...res.curves.map((c) => h('th', {}, c.label)));
  const rows = res.f.map((f, i) => h('tr', {}, h('td', { class: 'num' }, fmt(f, 4)), ...res.curves.map((c) => h('td', { class: 'num' }, c.psd_db[i] == null ? '–' : c.psd_db[i].toFixed(1)))));
  el.replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, ...rows))));
}

function renderStats(res) {
  const byMech = {};
  for (const c of res.curves) {
    const k = `${c.rotor}: ${c.mechanism}`;
    if (!byMech[k] || c.oaspl > byMech[k].oaspl) byMech[k] = c;
  }
  const tiles = Object.entries(byMech).slice(0, 6).map(([k, c]) => h('div', { class: 'stat' },
    h('div', { class: 'k' }, k), h('div', { class: 'v' }, `${c.oaspl.toFixed(1)} dB`), h('div', { class: 's' }, `OASPL, ${c.variant}, ${c.formulation}`)));
  if (res.info && res.info.wake_passing_hz) tiles.push(h('div', { class: 'stat' }, h('div', { class: 'k' }, 'Wake-passing frequency'),
    h('div', { class: 'v' }, `${fmtF(res.info.wake_passing_hz)}Hz`), h('div', { class: 's' }, 'B₁(Ω₁+Ω₂)/2π seen by the rear rotor')));
  $('#stats').replaceChildren(...tiles);
}

function kvTable(obj, keys) {
  return h('div', { class: 'kv' }, ...keys.flatMap(([k, lab]) => [h('span', { class: 'k' }, lab), h('span', {}, fmt(obj[k], 4))]));
}

function renderInfo(res) {
  const el = $('#info');
  el.innerHTML = '';
  const info = res.info || {};
  if (info.reference) el.append(h('p', { class: 'ref' }, info.reference));
  if (res.warnings && res.warnings.length) el.append(h('p', { class: 'warn' }, res.warnings.join('; ')));
  const blKeys = [['Ue', 'Uₑ [m/s]'], ['delta', 'δ [m]'], ['delta_star', 'δ* [m]'], ['theta', 'θ [m]'], ['H', 'H'], ['cf', 'C_f'],
    ['tau_w', 'τ_w [Pa]'], ['beta_c', 'β_C'], ['Pi', 'Π'], ['Rt', 'R_t (δ)'], ['RT_star', 'R_T (δ*)'], ['Delta', 'Δ = δ/δ*']];
  const bls = info.boundary_layers;
  if (bls) {
    const groups = bls.suction ? { airfoil: bls } : bls;
    for (const [name, sides] of Object.entries(groups)) {
      const t = h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, `Boundary layer (${name}, mid-span)`), h('th', {}, 'suction'), h('th', {}, 'pressure'))),
        h('tbody', {}, ...blKeys.map(([k, lab]) => h('tr', {}, h('td', {}, lab), h('td', { class: 'num' }, fmt(sides.suction[k], 4)), h('td', { class: 'num' }, fmt(sides.pressure[k], 4))))));
      el.append(t);
    }
  }
  if (info.rotors) {
    for (const r of Object.values(info.rotors)) {
      el.append(h('h3', {}, `Rotor ${r.name}: B = ${r.B}, ${r.rpm} rpm, BPF ${fmtF(r.bpf_hz)}Hz, tip Mach ${r.tip_mach_relative.toFixed(3)} (relative), Mx = ${r.Mx.toFixed(3)}`));
      el.append(h('table', {}, h('thead', {}, h('tr', {}, ...['r [m]', 'dr [m]', 'chord [m]', 'U [m/s]', 'ψ [deg]', 'M'].map((x) => h('th', {}, x)))),
        h('tbody', {}, ...r.strips.map((st) => h('tr', {}, ...[st.r, st.dr, st.chord, st.U, st.psi_deg, st.M].map((v) => h('td', { class: 'num' }, fmt(v, 4))))))));
    }
  }
  const oa = h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'curve'), h('th', {}, 'OASPL [dB]'))),
    h('tbody', {}, ...res.curves.map((c) => h('tr', {}, h('td', {}, c.label), h('td', { class: 'num' }, c.oaspl.toFixed(1))))));
  el.append(oa);
}

function download(name, text, type) {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}

/* ------------------------------------------------------------------ wall pressure tab */
const BL_FIELDS = [['Ue', 'Uₑ [m/s]', 50], ['delta_star', 'δ* [m]', 0.002], ['delta', 'δ [m]', ''], ['H', 'H = δ*/θ', ''],
  ['cf', 'C_f', ''], ['beta_c', 'β_C = θ/τ_w dp/dx', 0], ['nu', 'ν [m²/s]', 1.5e-5], ['c0', 'c₀ [m/s]', 340]];
function buildBlForm() {
  $('#bl-form').replaceChildren(...BL_FIELDS.map(([k, lab, v]) => h('div', {}, h('label', { for: `bl-${k}` }, lab), h('input', { id: `bl-${k}`, type: 'number', step: 'any', value: v }))));
}
async function runWps() {
  const bl = {};
  for (const [k] of BL_FIELDS) { const v = parseFloat($(`#bl-${k}`).value); if (isFinite(v)) bl[k] = v; }
  $('#wps-msg').textContent = 'evaluating…';
  const r = await backend.call('wall_pressure', [JSON.stringify(bl), JSON.stringify(state.meta.wps_models.map((m) => m.key))]);
  if (!r.ok) { $('#wps-msg').textContent = r.error; return; }
  $('#wps-msg').textContent = r.notes.length ? `estimated: ${r.notes.join(', ')}` : '';
  const mk = (key) => r.models.map((m, i) => ({ label: m.key === 'dominique_gep' ? 'VKI GEP (Dominique et al. 2021)' : m.key.replace('_', '-'),
    color: cssVar(SLOTS[i % SLOTS.length]), x: key === 'n' ? r.omega_tilde : r.f, y: key === 'n' ? m.normalised_db : m.psd_db, hidden: state.wpsHidden.has(i) }));
  const draw = () => {
    const a = mk('n'), b = mk('d');
    lineChart($('#wps-norm'), a, { xlog: true, xlabel: 'ω δ*/Uₑ', ylabel: '10 log₁₀(Φ Uₑ/τ_w² δ*)', unit: 'dB', xfmt: (v) => `ω δ*/Uₑ = ${fmt(v)}`, yFloorSpan: 70 });
    lineChart($('#wps-dim'), b, { xlog: true, xlabel: 'Frequency [Hz]', ylabel: 'PSD [dB re (20 µPa)²/Hz]', unit: 'dB', xfmt: (v) => `${fmtF(v)}Hz`, yFloorSpan: 70 });
    legend($('#wps-legend'), a, (i) => { state.wpsHidden.has(i) ? state.wpsHidden.delete(i) : state.wpsHidden.add(i); draw(); });
  };
  draw();
  const keys = [['delta', 'δ [m]'], ['delta_star', 'δ* [m]'], ['theta', 'θ [m]'], ['H', 'H'], ['cf', 'C_f'], ['tau_w', 'τ_w [Pa]'], ['u_tau', 'u_τ [m/s]'],
    ['beta_c', 'β_C'], ['Pi', 'Π (Durbin–Reif)'], ['Rt', 'R_t'], ['RT_star', 'R_T (δ*)'], ['Delta', 'Δ'], ['mach', 'M']];
  $('#bl-out').replaceChildren(kvTable(r.bl, keys));
}
state.wpsHidden = new Set();

/* ------------------------------------------------------------------ verification tab */
async function runVerify() {
  $('#verify-run').disabled = true;
  $('#verify-msg').textContent = 'running checks…';
  const r = await backend.call('verify', []);
  $('#verify-run').disabled = false;
  if (!r.ok) { $('#verify-msg').textContent = r.error; return; }
  const n = r.checks.filter((c) => c.passed).length;
  $('#verify-msg').textContent = `${n} / ${r.checks.length} passed`;
  $('#verify-table').replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ...['Check', 'What it tests', 'Metric', 'Value', 'Tolerance', 'Result', 'Reference'].map((x) => h('th', {}, x)))),
    h('tbody', {}, ...r.checks.map((c) => h('tr', {}, h('td', {}, c.name), h('td', {}, c.description, c.details ? h('div', { class: 'muted' }, c.details.slice(0, 240)) : null),
      h('td', {}, c.metric), h('td', { class: 'num' }, fmt(c.value, 3)), h('td', { class: 'num' }, fmt(c.tolerance, 3)),
      h('td', { class: c.passed ? 'pass' : 'fail' }, c.passed ? 'PASS' : 'FAIL'), h('td', { class: 'muted' }, c.reference))))));
}

/* ------------------------------------------------------------------ theory tab */
const THEORY = `
<h2>What is implemented</h2>
<p>The package follows the structure of V. P. Blandeau's thesis, <em>Aerodynamic broadband noise from contra-rotating open rotors</em> (ISVR, University of Southampton, 2011): each blade is cut into radial strips, each strip is an Amiet flat plate, and the radiation of the rotating strips is computed either exactly (full formulation) or with Amiet's azimuthal average (simplified formulation).</p>
<h3>Blade-element response (Amiet)</h3>
<p>Both mechanisms reduce to an effective force spectrum S<sub>F</sub> of a strip of chord c and span d, which contains the chordwise non-compactness through the chordwise radiation wavenumber q̄:</p>
<div class="eq">leading edge : S_F = 2 π³ ρ₀² c² U d |L(K̄₁, k̄_y, q̄)|² Φ_ww(K₁, k_y)        (Amiet 1975, + Roger's 2nd-order term)
trailing edge: S_F = c² (d/2) |I(K̄, k̄_y, q̄)|² Φ_pp(ω) l_y(ω) / (1 + k_y² l_y²)   (Amiet 1976, Roger &amp; Moreau back-scattering)
stationary   : S_pp = (k x₃/σ / 4πσ)² S_F,   q̄ = μ̄ (M − x₁/σ)</div>
<h3>Full formulation (exact rotating dipole)</h3>
<div class="eq">S_pp(x, ω) = B / (4πσ)² Σₙ Jₙ²(K_r R) Dₙ² S_F(ω + nΩ; q̄ₙ, k_y,n)
Dₙ  = K_z cos ψ − (n/R) sin ψ          dipole projection of azimuthal mode n
q̄ₙ  = −b (n cos ψ / R + K_z sin ψ)     chordwise radiation wavenumber of mode n
k_y,n = K_r √(1 − (n / K_r R)²)         local radial wavenumber of Jₙ
K   = k (ρ/σ, (z/σ − M_x)/β_x²)        convected far-field wave vector, σ² = z² + β_x² ρ²</div>
<h3>Simplified formulation (Amiet 1977)</h3>
<div class="eq">S_pp(x, ω) = B/2π ∫ (ω_s/ω)^p S_pp^Amiet(x_b(Ψ), ω_s(Ψ)) dΨ,     ω_s/ω = 1 − K·V_b / k</div>
<p>The observer is placed in the blade frame at the reception time. The verification suite shows that with that choice the exponent p = 2 reproduces the exact result at high frequency (p = 1 is available for comparison with Amiet's original). The two formulations agree to within about 0.1 dB above a few shaft orders and differ at low frequency, which is Blandeau &amp; Joseph's (2011) conclusion.</p>
<h3>Rotor-wake interaction</h3>
<p>The rear rotor ingests turbulence confined to the front-rotor wakes. The turbulence intensity has a Gaussian profile across each wake (semi-width L_w), repeated with the front-rotor pitch, and is frozen in the fluid. The upwash spectrum seen by a rear-rotor strip is</p>
<div class="eq">Φ(K₁, k_y) = Σ_m |E_m|² Φ_s(K₁ − m B₁(Ω₁+Ω₂)/U, k_y),   |E_m|² = w_c² (π/a)/s₁² exp(−2π²m²/(a s₁²)),  a = ln2/(2 L_w²)</div>
<p>with Φ_s the von Kármán or Liepmann spectrum of unit variance. The passage-averaged model keeps only the mean square Σ|E_m|² = w_c² (L_w/s₁)√(π/ln2) in a homogeneous spectrum.</p>
<h3>Wall-pressure models</h3>
<p>Amiet (1976), Chase–Howe (1998), Goody (2004), Rozenberg et al. (2012), Kamruzzaman et al. (2015), Lee (2018) and the VKI gene-expression-programming model of Dominique, Christophe, Schram &amp; Sandberg (JSV 506, 2021):</p>
<div class="eq">Φ Uₑ/(τ_w² δ*) = (5.41 + C_f(β_C+1)^5.41) ω̃ / (ω̃² + ω̃ + (β_C+1) M + (ω̃+3.6) ω̃^4.76 / (C_f R_T^5.83)),   ω̃ = ωδ*/Uₑ</div>
<p>Boundary layers come from the BPM NACA 0012 correlations, a 1/7-power flat plate, or user values; missing parameters follow Ludwieg–Tillmann (C_f), Drela (δ) and Durbin–Reif (Π). Spanwise coherence follows Corcos, l_y = b_c U_c/ω.</p>
<h3>Conventions</h3>
<p>Output spectra are one-sided PSDs per hertz, in dB re (20 µPa)²/Hz. The polar angle of rotor observers is measured from the upstream (flight) axis, and that of airfoil observers from the downstream chord line. Blades are assumed statistically independent, so levels add as 10 log₁₀ B.</p>`;

/* ------------------------------------------------------------------ boot */
async function boot() {
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => {
    $$('.tabs button').forEach((x) => x.setAttribute('aria-selected', x === b));
    $$('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${b.dataset.tab}`));
    if (b.dataset.tab === 'cases') render();
  }));
  $$('.seg button').forEach((b) => b.addEventListener('click', () => {
    $$('.seg button').forEach((x) => x.classList.toggle('on', x === b));
    state.view = b.dataset.view; render();
  }));
  $('#theory').innerHTML = THEORY;
  buildBlForm();
  lineChart($('#psd-chart'), []);
  lineChart($('#wps-norm'), [], { empty: 'Evaluate the models to see the spectra.' });
  lineChart($('#wps-dim'), [], { empty: ' ' });
  $('#run').addEventListener('click', run);
  $('#wps-run').addEventListener('click', runWps);
  $('#verify-run').addEventListener('click', runVerify);
  $('#json-apply').addEventListener('click', () => {
    try { state.case = normaliseCase(JSON.parse($('#case-json').value)); buildQuick(); $('#json-msg').textContent = 'applied'; }
    catch (e) { $('#json-msg').textContent = 'invalid JSON: ' + e.message; }
  });
  $('#dl-json').addEventListener('click', () => download(`${state.case.key || 'case'}.json`, JSON.stringify(state.result, null, 1), 'application/json'));
  $('#dl-csv').addEventListener('click', () => {
    const r = state.result;
    const rows = [['f_Hz', ...r.curves.map((c) => `"${c.label}"`)].join(',')];
    r.f.forEach((f, i) => rows.push([f, ...r.curves.map((c) => c.psd_db[i])].join(',')));
    download(`${state.case.key || 'case'}_psd.csv`, rows.join('\n'), 'text/csv');
  });
  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(render, 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);

  await backend.init();
  const m = await backend.call('meta', []);
  if (!m.ok) { setRuntime('API error: ' + m.error, 1, 'err'); return; }
  state.meta = m;
  $('#case-select').replaceChildren(...m.cases.map((c) => h('option', { value: c.key }, c.name)));
  $('#case-select').addEventListener('change', (e) => loadCase(e.target.value));
  await loadCase(m.cases[0].key);
  $('#run').disabled = false; $('#wps-run').disabled = false; $('#verify-run').disabled = false;
}
boot();
