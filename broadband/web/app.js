/* Broadband Rotor Noise Lab - dashboard logic (v2: Inputs / Interaction / Self / Combined tabs).
 * Backend: the local `bbnoise serve` API when available, otherwise Pyodide in a Web Worker. */
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
};
const SVGNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const fmt = (v, d = 3) => (v === null || v === undefined || !isFinite(v)) ? '–' : (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-2 && v !== 0) ? v.toExponential(d - 1) : (+v.toPrecision(d)).toString());
const fmtF = (v) => v >= 1000 ? `${+(v / 1000).toPrecision(3)}k` : `${+v.toPrecision(3)}`;
const LN2 = Math.log(2);

/* ================================================================== backend */
const backend = {
  mode: null, worker: null, id: 0, pending: new Map(), readyResolve: null, ready: null,
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
    this.worker = new Worker('web/worker.js?v=7');
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

/* ================================================================== charts */
const SLOTS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function niceTicks(lo, hi, n = 6) {
  const span = hi - lo || 1;
  const mag = 10 ** Math.floor(Math.log10(span / n));
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

/** series: [{label, x, y, color, dash, hidden, wide}] */
function lineChart(el, series, o = {}) {
  el.innerHTML = '';
  const vis = series.filter((d) => !d.hidden);
  if (!series.length) { el.append(h('div', { class: 'empty' }, o.empty || 'Run a case to see results.')); return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 360;
  const m = { l: 56, r: 16, t: 12, b: 42 };
  const xs = series.flatMap((d) => d.x).filter((v) => isFinite(v) && (!o.xlog || v > 0));
  const ys = (vis.length ? vis : series).flatMap((d) => d.y).filter((v) => v !== null && isFinite(v));
  if (!xs.length || !ys.length) { el.append(h('div', { class: 'empty' }, 'No data.')); return; }
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (o.yFloorSpan) y0 = Math.max(y0, y1 - o.yFloorSpan);
  const pad = (y1 - y0) * 0.06 || 1; y0 -= pad; y1 += pad;
  if (x1 === x0) { x0 *= 0.9; x1 = x1 * 1.1 || 1; }
  const X = o.xlog ? (v) => m.l + (Math.log10(v) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) * (W - m.l - m.r)
                   : (v) => m.l + (v - x0) / ((x1 - x0) || 1) * (W - m.l - m.r);
  const Y = (v) => m.t + (y1 - v) / ((y1 - y0) || 1) * (H - m.t - m.b);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.aria || o.ylabel || 'chart' });
  const g = s('g', { class: 'axis' });
  for (const t of niceTicks(y0, y1)) {
    g.append(s('line', { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: 'gridline' }));
    const tx = s('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }); tx.textContent = +t.toPrecision(6); g.append(tx);
  }
  for (const t of (o.xlog ? logTicks(x0, x1) : niceTicks(x0, x1, 8))) {
    g.append(s('line', { x1: X(t), x2: X(t), y1: m.t, y2: H - m.b, class: 'gridline' }));
    const tx = s('text', { x: X(t), y: H - m.b + 16, 'text-anchor': 'middle' }); tx.textContent = o.xlog ? fmtF(t) : +t.toPrecision(6); g.append(tx);
  }
  g.append(s('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'baseline' }));
  svg.append(g);
  const xl = s('text', { x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axis-title' }); xl.textContent = o.xlabel || ''; svg.append(xl);
  const yc = (m.t + H - m.b) / 2;
  const yl = s('text', { x: 14, y: yc, 'text-anchor': 'middle', class: 'axis-title', transform: `rotate(-90 14 ${yc})` }); yl.textContent = o.ylabel || ''; svg.append(yl);
  for (const d of vis) {
    let path = '', pen = false;
    d.x.forEach((xv, i) => {
      const yv = d.y[i];
      if (yv === null || yv === undefined || !isFinite(yv) || (o.xlog && xv <= 0)) { pen = false; return; }
      path += `${pen ? 'L' : 'M'}${X(xv).toFixed(1)},${Y(Math.max(yv, y0)).toFixed(1)}`; pen = true;
    });
    const p = s('path', { d: path, class: 'series' + (d.wide ? ' total' : ''), stroke: d.color });
    if (d.dash) p.setAttribute('stroke-dasharray', d.dash);
    svg.append(p);
    if (o.markers) d.x.forEach((xv, i) => { if (d.y[i] !== null && isFinite(d.y[i])) svg.append(s('circle', { cx: X(xv), cy: Y(d.y[i]), r: 4, fill: d.color, stroke: 'var(--panel)', 'stroke-width': 2 })); });
  }
  const cross = s('line', { y1: m.t, y2: H - m.b, class: 'cross', visibility: 'hidden' });
  svg.append(cross);
  const hit = s('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
  svg.append(hit);
  const tip = $('#tip');
  const xsRef = vis.length ? vis[0].x : [];
  hit.addEventListener('pointermove', (ev) => {
    if (!xsRef.length) return;
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    let best = 0, bd = Infinity;
    xsRef.forEach((xv, i) => { const dd = Math.abs(X(xv) - px); if (dd < bd) { bd = dd; best = i; } });
    const xv = xsRef[best];
    cross.setAttribute('x1', X(xv)); cross.setAttribute('x2', X(xv)); cross.setAttribute('visibility', 'visible');
    const rows = vis.map((d) => ({ d, v: d.y[d.x.indexOf(xv)] })).filter((q) => q.v !== undefined && q.v !== null && isFinite(q.v)).sort((a, b) => b.v - a.v);
    tip.replaceChildren(h('div', { class: 'h' }, o.xfmt ? o.xfmt(xv) : fmt(xv)),
      ...rows.map(({ d, v }) => {
        const key = h('span'); key.innerHTML = `<svg width="16" height="6"><line x1="0" x2="16" y1="3" y2="3" stroke="${d.color}" stroke-width="2" ${d.dash ? `stroke-dasharray="${d.dash}"` : ''}/></svg>`;
        return h('div', { class: 'r' }, key, h('span', { class: 'v' }, `${(+v).toPrecision(o.digits || 4).replace(/\.?0+$/, '')} ${o.unit || ''}`), h('span', { class: 'n' }, d.label));
      }));
    tip.style.display = 'block';
    tip.style.left = `${Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${ev.clientY + 14}px`;
  });
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; cross.setAttribute('visibility', 'hidden'); });
  el.append(svg);
}

function legend(el, series, onToggle) {
  el.replaceChildren(...series.map((d, i) => {
    const key = h('span'); key.innerHTML = `<svg viewBox="0 0 22 10"><line x1="1" x2="21" y1="5" y2="5" stroke="${d.color}" stroke-width="${d.wide ? 3 : 2}" ${d.dash ? `stroke-dasharray="${d.dash}"` : ''}/></svg>`;
    return h('span', { class: 'item' + (d.hidden ? ' off' : ''), role: 'button', tabindex: 0, title: 'show / hide',
      onclick: () => onToggle(i), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(i); } } }, key, d.label);
  }));
}

/** A spectrum card with narrowband / 1/3-octave / table views and a toggleable legend. */
function spectrumCard(root, title) {
  const hidden = new Set();
  let view = 'psd', data = null;
  const chart = h('div', { class: 'chart' });
  const leg = h('div', { class: 'legend' });
  const titleEl = h('h2', {}, title);
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Spectrum type' },
    ...[['psd', 'Narrowband PSD'], ['oct', '1/3 octave'], ['table', 'Table']].map(([k, t]) =>
      h('button', { class: k === 'psd' ? 'on' : '', onclick: (e) => { view = k; $$('button', seg).forEach((b) => b.classList.toggle('on', b === e.target)); draw(); } }, t)));
  root.replaceChildren(h('div', { class: 'panel chart-card' }, h('div', { class: 'card-head' }, titleEl, seg), chart, leg));
  function draw() {
    if (!data || !data.items.length) { lineChart(chart, [], { empty: data ? data.empty : 'Run a case to see results.' }); leg.innerHTML = ''; return; }
    const series = data.items.map((it) => ({ ...it, hidden: hidden.has(it.label),
      x: view === 'oct' ? it.oct.fc : data.f, y: view === 'oct' ? it.oct.spl : it.psd }));
    if (view === 'table') {
      const head = h('tr', {}, h('th', {}, 'f [Hz]'), ...data.items.map((c) => h('th', {}, c.label)));
      const rows = data.f.map((f, i) => h('tr', {}, h('td', { class: 'num' }, fmt(f, 4)), ...data.items.map((c) => h('td', { class: 'num' }, c.psd[i] == null ? '–' : (+c.psd[i]).toFixed(1)))));
      chart.replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, ...rows))));
    } else {
      lineChart(chart, series, { xlog: true, xlabel: 'Frequency [Hz]', unit: 'dB', digits: 3, xfmt: (v) => `${fmtF(v)}Hz`, yFloorSpan: 80,
        ylabel: view === 'oct' ? '1/3-octave SPL [dB re 20 µPa]' : 'PSD [dB re (20 µPa)²/Hz]' });
    }
    legend(leg, series, (i) => { const l = data.items[i].label; hidden.has(l) ? hidden.delete(l) : hidden.add(l); draw(); });
  }
  return { update(d) { data = d; if (d && d.title) titleEl.textContent = d.title; draw(); }, redraw: draw };
}

function directivity(card, el, items) {
  const withDir = items.filter((it) => it.dir);
  card.style.display = withDir.length ? '' : 'none';
  if (!withDir.length) return;
  $('.dir-note', card).textContent = state.case.type !== 'airfoil' ? 'polar angle from the upstream (flight) axis' : 'angle from the downstream chord line';
  lineChart(el, withDir.map((it) => {
    const o = it.dir.theta.map((t, k) => [t, it.dir.oaspl[k]]).sort((a, b) => a[0] - b[0]);
    return { ...it, x: o.map((p) => p[0]), y: o.map((p) => p[1]) };
  }), { xlabel: 'Polar angle θ [deg]', ylabel: 'OASPL [dB]', unit: 'dB', digits: 3, markers: true, xfmt: (v) => `θ = ${v}°` });
}

/* ================================================================== state + case helpers */
const state = { meta: null, case: null, result: null, cards: {} };
const asList = (v) => v == null ? [] : Array.isArray(v) ? v : [v];
function getPath(obj, path) { return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, v) {
  const ks = path.split('.'); let o = obj;
  for (let i = 0; i < ks.length - 1; i++) { const k = ks[i]; if (o[k] == null) o[k] = /^\d+$/.test(ks[i + 1]) ? [] : {}; o = o[k]; }
  if (v === undefined) { if (Array.isArray(o)) o[+ks.at(-1)] = null; else delete o[ks.at(-1)]; } else o[ks.at(-1)] = v;
}
function syncJson() { $('#case-json').value = JSON.stringify(state.case, null, 2); }

const BPM_BL = { method: 'bpm', alpha_deg: 0, tripped: true, H: [1.4, 1.4], beta_c: [0, 0] };

function normaliseCase(c) {
  if (c.type === 'bob') return normaliseBob(c);
  const d = state.meta.defaults;
  // earlier section names: self_noise -> brte, rwi -> brwi
  for (const [o, n] of [['self_noise', 'brte'], ['rwi', 'brwi']]) if (c[o] !== undefined) { if (c[n] === undefined) c[n] = c[o]; delete c[o]; }
  c.options = Object.assign({}, d.options, c.options || {});
  c.frequency = Object.assign({}, d.frequency, c.frequency || {});
  c.observers = c.observers || { R: c.type === 'rotor' ? 10 : 1, theta_deg: [90] };
  c.observers.theta_deg = asList(c.observers.theta_deg);
  if (c.type !== 'rotor') {
    const orig = c.type;
    c.type = 'airfoil';
    if (c.turbulence) { if (c.turbulence.enabled === undefined) c.turbulence.enabled = orig !== 'airfoil_te'; }
    else c.turbulence = { enabled: false, spectrum: ['vonkarman'], tke: 1.5 * (0.03 * c.airfoil.U) ** 2, Lambda: 0.03 };
    if (c.brte) { if (c.brte.enabled === undefined) c.brte.enabled = orig !== 'airfoil_le'; }
    else c.brte = { enabled: false, models: ['goody'], boundary_layer: structuredClone(BPM_BL) };
    c.turbulence.spectrum = asList(c.turbulence.spectrum);
  } else {
    c.formulations = asList(c.formulations || ['full', 'simplified']);
    if (!c.brte) c.brte = { enabled: false, models: ['goody'], boundary_layer: structuredClone(BPM_BL) };
    if (c.brte.enabled === undefined) c.brte.enabled = true;
    if (c.rotors.length >= 2) {
      if (!c.brwi) c.brwi = { enabled: false, front: c.rotors[0].name, rear: c.rotors[1].name, spectrum: ['vonkarman'], wake: { tu_c: 0.05, Lw_over_s: 0.08, Lambda_over_Lw: 0.42, model: 'periodic' } };
      if (c.brwi.enabled === undefined) c.brwi.enabled = true;
      c.brwi.spectrum = asList(c.brwi.spectrum);
      c.brwi.wake = c.brwi.wake || {};
    }
    if (!c.ingestion) c.ingestion = { enabled: false, spectrum: ['vonkarman'], intensity: 0.02, Lambda: 0.5 };
    if (c.ingestion.enabled === undefined) c.ingestion.enabled = true;
    c.ingestion.spectrum = asList(c.ingestion.spectrum);
  }
  const sn = c.brte;
  sn.models = asList(sn.models);
  if (sn.Uc_over_Ue === undefined) sn.Uc_over_Ue = 0.7;
  if (sn.b_c === undefined) sn.b_c = 1.47;
  sn.boundary_layer = sn.boundary_layer || structuredClone(BPM_BL);
  const bl = sn.boundary_layer;
  if (bl.method === 'bpm') {
    if (bl.H === undefined) bl.H = [1.4, 1.4];
    if (bl.beta_c === undefined) bl.beta_c = [0, 0];
    if (!Array.isArray(bl.H)) bl.H = [bl.H, bl.H];
    if (!Array.isArray(bl.beta_c)) bl.beta_c = [bl.beta_c, bl.beta_c];
    if (bl.alpha_deg === undefined) bl.alpha_deg = 0;
    if (bl.tripped === undefined) bl.tripped = true;
  }
  return c;
}

/* reference velocities used to convert between intensity and TKE */
function rotorOmega(r) { return Math.abs(r.rpm) * Math.PI / 30; }
function scalarAt(v) { return (v && typeof v === 'object') ? null : v; }
function midU(r) { const rr = 0.7 * r.r_tip; return Math.hypot(rotorOmega(r) * rr, scalarAt(r.Ux) || 0); }
function homRefU() {
  const c = state.case;
  if (c.type !== 'rotor') return c.airfoil.U;
  return c.ingestion.U_ref || midU(c.rotors[0]);
}
function frontRotor() { const c = state.case; return c.rotors.find((r) => r.name === c.brwi.front) || c.rotors[0]; }

/* ================================================================== input widgets */
function fieldRow(label, input, unit) { return h('div', { class: 'f' }, h('label', {}, label, unit ? h('span', { class: 'unit' }, ` [${unit}]`) : null), input); }

function num(label, path, o = {}) {
  const v = getPath(state.case, path);
  if (v && typeof v === 'object') return fieldRow(label, h('input', { value: 'radial (edit JSON)', disabled: true }), o.unit);
  const inp = h('input', { type: 'number', step: 'any', value: v ?? '', placeholder: o.optional ? 'estimate' : '', 'aria-label': label });
  inp.addEventListener('change', () => {
    const x = parseFloat(inp.value);
    if (!isFinite(x)) { if (o.optional || inp.value === '') setPath(state.case, path, undefined); }
    else setPath(state.case, path, o.int ? Math.round(x) : x);
    syncJson(); if (o.onchange) o.onchange();
  });
  return fieldRow(label, inp, o.unit);
}
function pick(label, path, options, onchange) {
  const v = getPath(state.case, path);
  const sel = h('select', { 'aria-label': label }, ...options.map(([val, txt]) => h('option', { value: JSON.stringify(val), selected: JSON.stringify(val) === JSON.stringify(v) }, txt)));
  sel.addEventListener('change', () => { setPath(state.case, path, JSON.parse(sel.value)); syncJson(); if (onchange) onchange(); });
  return fieldRow(label, sel);
}
function choose(label, value, options, onchange) {
  const sel = h('select', { 'aria-label': label }, ...options.map(([val, txt]) => h('option', { value: val, selected: val === value }, txt)));
  sel.addEventListener('change', () => onchange(sel.value));
  return fieldRow(label, sel);
}
function checks(path, options) {
  const cur = new Set(asList(getPath(state.case, path)));
  return h('div', { class: 'checks' }, ...options.map(([val, txt]) => {
    const cb = h('input', { type: 'checkbox', checked: cur.has(val) });
    cb.addEventListener('change', () => {
      const now = new Set(asList(getPath(state.case, path)));
      cb.checked ? now.add(val) : now.delete(val);
      setPath(state.case, path, options.map((q) => q[0]).filter((x) => now.has(x)));
      syncJson();
    });
    return h('label', {}, cb, txt);
  }));
}
function enable(label, path, body) {
  const on = getPath(state.case, path) !== false;
  const cb = h('input', { type: 'checkbox', checked: on });
  body.classList.toggle('disabled-body', !on);
  cb.addEventListener('change', () => { setPath(state.case, path, cb.checked); body.classList.toggle('disabled-body', !cb.checked); syncJson(); });
  return h('div', { class: 'checks' }, h('label', {}, cb, h('strong', {}, label)));
}
const fs = (title, ...kids) => h('fieldset', {}, h('legend', {}, title), ...kids);
const card = (title, sub, ...kids) => h('div', { class: 'panel card' }, h('h2', {}, title), sub ? h('p', { class: 'sub' }, sub) : null, ...kids);
const SPECTRA = [['vonkarman', 'von Kármán'], ['liepmann', 'Liepmann']];

/* homogeneous turbulence level: TKE [m²/s²] or intensity */
function homogeneousInputs(sec) {
  const base = sec;                // 'turbulence' or 'ingestion'
  const t = state.case[base];
  if (t.w_rms !== undefined && t.tke === undefined) { t.tke = 1.5 * t.w_rms ** 2; delete t.w_rms; }
  const mode = t.tke !== undefined ? 'tke' : 'intensity';
  const box = h('div');
  const hint = h('p', { class: 'muted' });
  const refresh = () => {
    const U = homRefU();
    const w = t.tke !== undefined ? Math.sqrt(2 * t.tke / 3) : (t.intensity || 0) * U;
    hint.textContent = `w_rms = ${fmt(w, 3)} m/s, k = ${fmt(1.5 * w * w, 3)} m²/s², Tu = ${fmt(100 * w / U, 3)} % of ${fmt(U, 3)} m/s`;
  };
  const build = () => {
    const m = t.tke !== undefined ? 'tke' : 'intensity';
    box.replaceChildren(
      choose('Turbulence level given as', m, [['tke', 'turbulent kinetic energy k'], ['intensity', 'intensity w_rms / U']], (nm) => {
        const U = homRefU();
        if (nm === 'tke') { t.tke = 1.5 * ((t.intensity ?? 0.03) * U) ** 2; delete t.intensity; }
        else { t.intensity = Math.sqrt(2 * (t.tke ?? 1) / 3) / U; delete t.tke; }
        syncJson(); build();
      }),
      m === 'tke' ? num('Turbulent kinetic energy k', `${base}.tke`, { unit: 'm²/s²', onchange: refresh })
                  : num('Intensity w_rms / U', `${base}.intensity`, { onchange: refresh }),
      num('Integral length scale Λ', `${base}.Lambda`, { unit: 'm' }), hint);
    refresh();
  };
  build();
  void mode;
  return box;
}

/* front-rotor wake turbulence: centreline TKE / passage-averaged TKE / centreline intensity; Λ absolute or / L_w */
function wakeInputs() {
  const w = state.case.brwi.wake;
  const box = h('div');
  const hint = h('p', { class: 'muted' });
  const levelKey = () => (w.tke_c !== undefined ? 'tke_c' : w.tke_mean !== undefined ? 'tke_mean' : 'tu_c');
  const lamKey = () => (w.Lambda !== undefined ? 'Lambda' : 'Lambda_over_Lw');
  const ref = () => {   // reference values at 0.7 R of the front rotor
    const fr = frontRotor();
    const U1 = midU(fr);
    const lw = scalarAt(w.Lw_over_s) ?? 0.08;
    const s1 = 2 * Math.PI * 0.7 * fr.r_tip / fr.B;
    return { U1, lw, s1, Lw: lw * s1, fac: lw * Math.sqrt(Math.PI / LN2) };
  };
  const refresh = () => {
    const r = ref();
    let kc = null;
    if (scalarAt(w.tke_c) != null) kc = w.tke_c;
    else if (scalarAt(w.tke_mean) != null) kc = w.tke_mean / r.fac;
    else if (scalarAt(w.tu_c) != null) kc = 1.5 * (w.tu_c * r.U1) ** 2;
    const lam = scalarAt(w.Lambda) ?? (w.Lambda_over_Lw ?? 0.42) * r.Lw;
    hint.textContent = kc == null ? 'radial distribution (see JSON)' :
      `at 0.7 R₁: centreline k = ${fmt(kc, 3)} m²/s², passage-averaged k = ${fmt(kc * r.fac, 3)} m²/s², L_w = ${fmt(r.Lw * 1000, 3)} mm, Λ = ${fmt(lam * 1000, 3)} mm`;
  };
  const build = () => {
    const lk = levelKey(), mk = lamKey();
    box.replaceChildren(
      choose('Wake turbulence given as', lk, [['tke_c', 'centreline TKE k_c'], ['tke_mean', 'passage-averaged TKE'], ['tu_c', 'centreline intensity (of front U)']], (nk) => {
        const r = ref();
        let kc = scalarAt(w.tke_c) ?? (scalarAt(w.tke_mean) != null ? w.tke_mean / r.fac : 1.5 * ((w.tu_c ?? 0.05) * r.U1) ** 2);
        delete w.tke_c; delete w.tke_mean; delete w.tu_c;
        if (nk === 'tke_c') w.tke_c = +kc.toPrecision(4);
        else if (nk === 'tke_mean') w.tke_mean = +(kc * r.fac).toPrecision(4);
        else w.tu_c = +(Math.sqrt(2 * kc / 3) / r.U1).toPrecision(4);
        syncJson(); build();
      }),
      lk === 'tke_c' ? num('Centreline TKE k_c', 'brwi.wake.tke_c', { unit: 'm²/s²', onchange: refresh })
        : lk === 'tke_mean' ? num('Passage-averaged TKE', 'brwi.wake.tke_mean', { unit: 'm²/s²', onchange: refresh })
          : num('Centreline intensity w_c / U₁', 'brwi.wake.tu_c', { onchange: refresh }),
      num('Wake semi-width / front pitch', 'brwi.wake.Lw_over_s', { onchange: refresh }),
      choose('Integral length scale given as', mk, [['Lambda', 'Λ in metres'], ['Lambda_over_Lw', 'Λ / wake semi-width']], (nk) => {
        const r = ref();
        const lam = scalarAt(w.Lambda) ?? (w.Lambda_over_Lw ?? 0.42) * r.Lw;
        delete w.Lambda; delete w.Lambda_over_Lw;
        if (nk === 'Lambda') w.Lambda = +lam.toPrecision(4); else w.Lambda_over_Lw = +(lam / r.Lw).toPrecision(4);
        syncJson(); build();
      }),
      mk === 'Lambda' ? num('Integral length scale Λ', 'brwi.wake.Lambda', { unit: 'm', onchange: refresh })
        : num('Λ / wake semi-width', 'brwi.wake.Lambda_over_Lw', { onchange: refresh }),
      pick('Wake turbulence model', 'brwi.wake.model', [['periodic', 'periodic wakes'], ['averaged', 'passage-averaged'], [['periodic', 'averaged'], 'both']]),
      hint);
    refresh();
  };
  build();
  return box;
}

/* boundary layer inputs: BPM / flat plate / user table */
/* ---------- radial tables: helpers ---------- */
function valueAt(v, x, hub = 0.2) {
  if (v === null || v === undefined || v === '') return null;
  if (typeof v === 'number') return v;
  if (Array.isArray(v)) {
    const n = v.length;
    return valueAt({ r_over_R: v.map((_, i) => hub + (1 - hub) * i / Math.max(n - 1, 1)), value: v }, x);
  }
  const xs = v.r_over_R || [], ys = v.value || [];
  if (!xs.length) return null;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  for (let i = 1; i < xs.length; i++) if (x <= xs[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
  return ys[ys.length - 1];
}
const isRadial = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) && Array.isArray(v.r_over_R);
const r4 = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(+v)) ? '' : +(+v).toPrecision(4);
function toRadial(rows, key) {
  const pts = rows.filter((q) => q[key] !== null && q[key] !== undefined && q[key] !== '' && Number.isFinite(+q[key]) && Number.isFinite(+q.r_over_R))
    .sort((a, b) => a.r_over_R - b.r_over_R);
  if (!pts.length) return undefined;
  if (pts.length === 1) return +pts[0][key];
  return { r_over_R: pts.map((q) => +q.r_over_R), value: pts.map((q) => +q[key]) };
}
function pickFile(accept = '.csv,.tsv,.txt,.dat,.json') {
  return new Promise((resolve) => {
    const inp = h('input', { type: 'file', accept, style: 'display:none' });
    inp.addEventListener('change', async () => { const f = inp.files[0]; inp.remove(); resolve(f ? { name: f.name, text: await f.text() } : null); });
    document.body.append(inp); inp.click();
  });
}
async function downloadTemplate(kind) {
  const r = await backend.call('template', [kind]);
  if (r.ok) download(kind === 'blade' ? 'blade_template.csv' : 'boundary_layer_template.csv', r.text, 'text/csv');
}

/** Editable radial table.  cols: [{key, label, group?, required?}], rows: [{r_over_R, key: value}] */
function radialGrid(cols, rows, onChange, o = {}) {
  const wrap = h('div', { class: 'table-wrap grid-wrap' });
  const draw = () => {
    const groups = [...new Set(cols.map((c) => c.group || ''))];
    const head = [];
    if (groups.some((g) => g)) head.push(h('tr', {}, h('th', {}, ''), ...groups.map((g) => h('th', { colspan: cols.filter((c) => (c.group || '') === g).length, class: 'grp' }, g)), h('th', {}, '')));
    head.push(h('tr', {}, h('th', {}, 'r/R'), ...cols.map((c) => h('th', {}, c.label)), h('th', {}, '')));
    const body = rows.map((row, k) => h('tr', {},
      h('td', {}, cellInput(row, 'r_over_R', true)),
      ...cols.map((c) => h('td', {}, cellInput(row, c.key, c.required, c.placeholder))),
      h('td', {}, h('button', { class: 'ghost tiny', title: 'remove row', 'aria-label': 'remove row', onclick: () => { rows.splice(k, 1); commit(); draw(); } }, '×'))));
    wrap.replaceChildren(h('table', { class: 'grid' }, h('thead', {}, ...head), h('tbody', {}, ...body)),
      h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: () => {
        const last = rows[rows.length - 1] || { r_over_R: 0.5 };
        rows.push({ ...last, r_over_R: Math.min(1, +(last.r_over_R + 0.1).toFixed(3)) }); commit(); draw();
      } }, '+ Add radius'), o.note ? h('span', { class: 'muted' }, o.note) : null));
  };
  const cellInput = (row, key, required, placeholder) => {
    const inp = h('input', { type: 'number', step: 'any', value: r4(row[key]), placeholder: required ? '' : (placeholder ?? 'est.'), 'aria-label': key });
    inp.addEventListener('change', () => { const x = parseFloat(inp.value); row[key] = isFinite(x) ? x : null; if (key === 'r_over_R') rows.sort((a, b) => a.r_over_R - b.r_over_R); commit(); if (key === 'r_over_R') draw(); });
    return inp;
  };
  const commit = () => onChange(rows);
  draw();
  return wrap;
}

/* ---------- blade chord along the radius ---------- */
const BLADE_COLS = [
  { key: 'chord', label: 'chord [m]', required: true },
  { key: 'stagger_deg', label: 'stagger α [deg]', placeholder: 'flow' },
  { key: 'U_X', label: 'U_X [m/s]', placeholder: 'flow' },
];
/** Blade editor: chord, stagger (from the rotor axis) and chordwise speed along the radius. */
function chordEditor(i) {
  const rot = state.case.rotors[i];
  const box = h('div');
  const msg = h('span', { class: 'muted' });
  const hub = rot.r_hub / rot.r_tip;
  const points = (v) => {
    if (v === undefined || v === null || v === '') return [];
    if (isRadial(v)) return v.r_over_R.map((x, k) => [x, v.value[k]]);
    if (Array.isArray(v)) return v.map((y, k) => [+(hub + (1 - hub) * k / Math.max(v.length - 1, 1)).toFixed(4), y]);
    return [[+hub.toFixed(4), +v], [1, +v]];
  };
  const build = () => {
    const byR = new Map();
    for (const c of BLADE_COLS) for (const [x, y] of points(rot[c.key] ?? (c.key === 'chord' ? 0.05 : undefined))) {
      const row = byR.get(x) || { r_over_R: x }; row[c.key] = y; byR.set(x, row);
    }
    const rows = [...byR.values()].sort((a, b) => a.r_over_R - b.r_over_R);
    const kids = [];
    if (rot.blade_file) kids.push(h('p', { class: 'muted' }, `Blade table file: ${rot.blade_file} (command line). Loading a table here replaces it.`));
    kids.push(radialGrid(BLADE_COLS, rows, (rs) => {
      const chord = toRadial(rs, 'chord');
      if (chord === undefined) return;
      rot.chord = chord;
      for (const k of ['stagger_deg', 'U_X']) { const v = toRadial(rs, k); if (v === undefined) delete rot[k]; else rot[k] = v; }
      delete rot.blade_file; delete rot.blade_table; syncJson();
    }, { note: 'Blank stagger / U_X: the blade follows the relative inflow (Ωr, Uₓ).' }),
    h('div', { class: 'row' },
      h('button', { class: 'ghost', onclick: async () => {
        const f = await pickFile(); if (!f) return;
        const r = await backend.call('parse_table', ['blade', f.text, rot.r_tip]);
        if (!r.ok) { msg.textContent = r.error; return; }
        rot.chord = r.blade.chord;
        const got = ['chord'];
        for (const k of ['Ux', 'stagger_deg', 'U_X']) if (r.blade[k] !== undefined) { rot[k] = r.blade[k]; got.push(k); }
        delete rot.blade_file; delete rot.blade_table;
        const rmax = isRadial(r.blade.chord) ? Math.max(...r.blade.chord.r_over_R) : 1;
        msg.textContent = `loaded ${f.name} (${got.join(', ')})` +
          (rmax > 1.001 ? ` - warning: radii up to r/R = ${rmax.toFixed(2)} lie beyond this rotor's tip and are ignored` : '');
        syncJson(); build();
      } }, 'Load blade file…'),
      h('button', { class: 'ghost', onclick: () => downloadTemplate('blade') }, 'Template'), msg));
    box.replaceChildren(...kids);
  };
  build();
  return box;
}

/* ---------- boundary layer inputs ---------- */
const BL_ROWS = [['delta_star_over_c', 'δ*/c', false], ['delta_over_c', 'δ/c', true], ['theta_over_c', 'θ/c', true], ['H', 'H = δ*/θ', true],
  ['cf', 'C_f', true], ['beta_c', 'β_C = (θ/τ_w) dp/dx', true], ['Ue_over_U', 'Uₑ/U', true]];
const BL_GRID = [['delta_star_over_c', 'δ*/c', true], ['H', 'H', false], ['cf', 'C_f', false], ['beta_c', 'β_C', false], ['Ue_over_U', 'Uₑ/U', false]];

function blBasePath() {
  const sn = state.case.brte;
  if (state.case.type === 'rotor' && sn.boundary_layers && Object.keys(sn.boundary_layers).length) {
    if (!state.blRotor || !sn.boundary_layers[state.blRotor]) state.blRotor = Object.keys(sn.boundary_layers)[0];
    return `brte.boundary_layers.${state.blRotor}`;
  }
  return 'brte.boundary_layer';
}
function blRotorTip() {
  const c = state.case;
  if (c.type !== 'rotor') return null;
  const name = c.brte.boundary_layers ? state.blRotor : (c.brte.rotors || [c.rotors[0].name])[0];
  return (c.rotors.find((r) => r.name === name) || c.rotors[0]).r_tip;
}
function flattenBoth(b) {
  if (b.both) {
    for (const side of ['suction', 'pressure']) b[side] = { ...b.both, ...(b[side] || {}) };
    delete b.both;
  }
  b.suction = b.suction || {}; b.pressure = b.pressure || {};
}
const specIsRadial = (b) => ['suction', 'pressure', 'both'].some((sd) => Object.values(b[sd] || {}).some(isRadial));

function blInputs() {
  const box = h('div');
  const msg = h('span', { class: 'muted' });
  const c = state.case;
  const build = () => {
    const base = blBasePath();
    const bl = getPath(c, base);
    const kids = [];
    if (c.type === 'rotor' && c.rotors.length > 1) {
      const per = !!(c.brte.boundary_layers && Object.keys(c.brte.boundary_layers).length);
      kids.push(choose('Boundary layers', per ? 'per' : 'shared', [['shared', 'same for all rotors'], ['per', 'separate for each rotor']], (v) => {
        if (v === 'per') { c.brte.boundary_layers = Object.fromEntries(c.rotors.map((r) => [r.name, structuredClone(c.brte.boundary_layer)])); state.blRotor = c.rotors[0].name; }
        else { c.brte.boundary_layer = structuredClone(getPath(c, blBasePath())); delete c.brte.boundary_layers; }
        syncJson(); build();
      }));
      if (per) kids.push(choose('Editing rotor', state.blRotor, c.rotors.map((r) => [r.name, r.name]), (v) => { state.blRotor = v; build(); }));
    }
    kids.push(pick('Boundary layer from', `${base}.method`, [['bpm', 'BPM NACA 0012 correlations'], ['flat_plate', 'flat plate (1/7 power law)'], ['user', 'user input or file'], ...(bl.method === 'file' ? [['file', 'table file (command line)']] : [])], async () => {
      const b = getPath(c, base);
      if (b.method === 'user' && !b.suction && !b.both) await prefill(false);
      if (b.method === 'bpm') Object.assign(b, { ...BPM_BL, ...b, H: Array.isArray(b.H) ? b.H : [1.4, 1.4], beta_c: Array.isArray(b.beta_c) ? b.beta_c : [0, 0] });
      syncJson(); build();
    }));
    if (bl.method === 'bpm') {
      if (!Array.isArray(bl.H)) bl.H = [1.4, 1.4];
      if (!Array.isArray(bl.beta_c)) bl.beta_c = [0, 0];
      kids.push(num('Angle of attack', `${base}.alpha_deg`, { unit: 'deg' }),
        pick('Transition', `${base}.tripped`, [[true, 'tripped'], [false, 'natural (untripped)']]),
        blTable([['H', 'H = δ*/θ', `${base}.H.0`, `${base}.H.1`], ['beta_c', 'β_C = (θ/τ_w) dp/dx', `${base}.beta_c.0`, `${base}.beta_c.1`]]));
    } else if (bl.method === 'file') {
      kids.push(h('p', { class: 'muted' }, `Boundary layers are read from ${bl.path || 'an inline table'} when the case runs. Load the file here to edit it.`));
    } else if (bl.method === 'user') {
      const radial = specIsRadial(bl);
      if (c.type === 'rotor') kids.push(choose('Values', radial ? 'radial' : 'uniform', [['uniform', 'uniform along the blade'], ['radial', 'varying along the blade']], (v) => {
        flattenBoth(bl);
        if (v === 'radial') {
          for (const side of ['suction', 'pressure']) for (const [k] of BL_GRID) {
            const val = bl[side][k];
            if (typeof val === 'number') bl[side][k] = { r_over_R: [0.3, 1.0], value: [val, val] };
          }
        } else {
          for (const side of ['suction', 'pressure']) for (const k of Object.keys(bl[side])) if (isRadial(bl[side][k])) bl[side][k] = r4(valueAt(bl[side][k], 0.7));
        }
        syncJson(); build();
      }));
      if (radial && c.type === 'rotor') kids.push(blGrid(bl));
      else kids.push(blTable(BL_ROWS.map(([k, lab]) => [k, lab, `${base}.suction.${k}`, `${base}.pressure.${k}`]), true));
      kids.push(h('div', { class: 'row' },
        h('button', { class: 'ghost', onclick: async () => {
          const f = await pickFile(); if (!f) return;
          const r = await backend.call('parse_table', ['bl', f.text, blRotorTip()]);
          if (!r.ok) { msg.textContent = r.error; return; }
          setPath(c, base, r.boundary_layer);
          msg.textContent = `loaded ${f.name}`;
          syncJson(); build();
        } }, 'Load boundary-layer file…'),
        h('button', { class: 'ghost', onclick: () => downloadTemplate('bl') }, 'Template'),
        h('button', { class: 'ghost', onclick: async () => { await prefill(specIsRadial(getPath(c, base))); build(); } }, 'Fill from BPM'), msg),
        h('p', { class: 'muted' }, 'Lengths are ratios to the local chord. Blank cells are estimated: H = 1.4, C_f from Ludwieg–Tillmann, δ from Drela, Π from Durbin–Reif. A file may give delta_star_over_c, delta_over_c, theta_over_c (or δ*, δ, θ in metres), H, cf, beta_c or dpdx, Pi and Ue_over_U, per side and per radius.'));
    }
    box.replaceChildren(...kids);
  };
  function blGrid(bl) {
    flattenBoth(bl);
    const xs = new Set();
    for (const side of ['suction', 'pressure']) for (const v of Object.values(bl[side])) if (isRadial(v)) v.r_over_R.forEach((x) => xs.add(+x));
    if (!xs.size) [0.3, 0.7, 1.0].forEach((x) => xs.add(x));
    const rows = [...xs].sort((a, b) => a - b).map((x) => {
      const row = { r_over_R: x };
      for (const side of ['suction', 'pressure']) for (const [k] of BL_GRID) row[`${side}.${k}`] = r4(valueAt(bl[side][k], x));
      return row;
    });
    const holder = h('div');
    const side = state.blSide || 'suction';
    const drawSide = (sd) => {
      state.blSide = sd;
      const cols = BL_GRID.map(([k, lab, req]) => ({ key: `${sd}.${k}`, label: lab, required: req }));
      holder.replaceChildren(
        h('div', { class: 'seg', role: 'group', 'aria-label': 'Side' }, ...['suction', 'pressure'].map((x) =>
          h('button', { class: x === sd ? 'on' : '', onclick: () => drawSide(x) }, `${x} side`))),
        radialGrid(cols, rows, (rs) => {
          for (const sd2 of ['suction', 'pressure']) for (const [k] of BL_GRID) {
            const v = toRadial(rs, `${sd2}.${k}`);
            if (v === undefined) delete bl[sd2][k]; else bl[sd2][k] = v;
          }
          syncJson();
        }, { note: 'Radii are shared by both sides. δ/c and θ/c can be added in a file or the JSON.' }));
    };
    drawSide(side);
    return holder;
  }
  async function prefill(radial) {
    msg.textContent = 'estimating…';
    const cc = structuredClone(state.case);
    cc.brte.boundary_layer = structuredClone(BPM_BL);
    delete cc.brte.boundary_layers;
    const rot = c.type === 'rotor' ? (c.brte.boundary_layers ? state.blRotor : (c.brte.rotors || [c.rotors[0].name])[0]) : null;
    const r = await backend.call('estimate_bl', [JSON.stringify(cc), rot]);
    if (!r.ok) { msg.textContent = r.error; return; }
    const b = { method: 'user' };
    const keys = ['delta_star_over_c', 'H', 'beta_c'];
    for (const side of ['suction', 'pressure']) {
      b[side] = { Ue_over_U: 1 };
      for (const k of keys) {
        b[side][k] = radial && r.radial.length
          ? { r_over_R: r.radial.map((q) => r4(q.r_over_R)), value: r.radial.map((q) => r4(q[side][k])) }
          : r4(r.sides[side][k]);
      }
    }
    // delta/c stays blank so that it follows delta* and H (Drela) when edited
    setPath(c, blBasePath(), b);
    msg.textContent = `filled from BPM at ${radial ? 'every strip' : r.where}`;
    syncJson();
  }
  build();
  return box;
}
function blTable(rows, optionalBlank = false) {
  return h('table', { class: 'bltab' }, h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, 'suction side'), h('th', {}, 'pressure side'))),
    h('tbody', {}, ...rows.map(([k, lab, p1, p2]) => {
      const opt = optionalBlank && k !== 'delta_star_over_c';
      const cell = (p) => { const f = num(lab, p, { optional: opt }); return h('td', {}, f.lastChild); };
      return h('tr', {}, h('td', {}, lab), cell(p1), cell(p2));
    })));
}

/* ================================================================== BoB 3.5 cases (type "bob") */
const BOB_CHOICES = {
  noise_type: [['BOTH', 'BRWI + BRTE (BOTH)'], ['BRWI', 'BRWI'], ['BRTE', 'BRTE']],
  StageCount: [[2, '2 (contra-rotating)'], [1, '1 (single rotor)']],
  phi_sw: [['RZ', 'RZ · Rozenberg'], ['WA', 'WA · Willmarth–Roos–Amiet'], ['CH', 'CH · Chase–Howe'], ['GY', 'GY · Goody'], ['KG', 'KG · Kim–George']],
  Uc: [['DEL2', 'DEL2 · Del Álamo fit (Gliebe form)'], ['0.8', '0.8 · U_c = 0.8 U_x'], ['DEL', 'DEL · Del Álamo'], ['GLB', 'GLB · Gliebe']],
  lr: [['SLZ', 'SLZ · Salze'], ['COR', 'COR · Corcos'], ['ROG', 'ROG · Roger'], ['LGL', 'LGL · Roger (Languille)'], ['RGS', 'RGS · Roger (Shelekhov)'], ['CORL', 'CORL · Corcos limited by δ'], ['EFP', 'EFP · Efimtsov–Palumbo']],
  baddata: [['IGNORE', 'IGNORE · use anyway'], ['REPLACE', 'REPLACE · copy neighbouring strip'], ['DISCARD', 'DISCARD · drop the strip']],
  contraction_perc: [[100, '100 %'], [0, '0 %']],
};
const BOB_BL_SLOTS = [['front rotor, top (suction) surface', 0], ['front rotor, bottom (pressure) surface', 1], ['rear rotor, top (suction) surface', 2], ['rear rotor, bottom (pressure) surface', 3]];
const BOB_BL_COLS = ['R', 'δ', 'δ*', 'θ', '(unused)', 'τ_max', 'dp/dx', 'ρ_w', 'U_∞', 'Π', 'ν_w', 'τ_w', 'discard'];
const BOB_WAKE = [['bw', 'b_w [m]'], ['wrms_bg', 'w_rms bg [m/s]'], ['wrms_wake', 'w_rms wake [m/s]'], ['L_bg', 'L bg [m]'], ['L_wake', 'L wake [m]']];
const BOB_GEOM_SCALARS = [['geom.B1', 'B1', ''], ['geom.B2', 'B2', ''], ['cond.Omega1', 'Ω1', 'rad/s'], ['cond.Omega2', 'Ω2', 'rad/s'], ['cond.Mx', 'M_x (flight)', ''],
  ['cond.c0', 'c0', 'm/s'], ['cond.rho', 'ρ', 'kg/m³'], ['geom.eta', 'η (rotor gap)', 'm'], ['geom.scale', 'scale', ''], ['geom.c_pylon', 'pylon chord', 'm']];
const BOB_GEOM_ARRAYS = [['geom.r1', 'r1 [m]'], ['geom.c1', 'c1 [m]'], ['geom.alpha1', 'α1 stagger [rad]'], ['geom.s1', 's1 sweep [m]'], ['cond.AoA1', 'AoA1 [rad]'],
  ['geom.r2', 'r2 [m]'], ['geom.c2', 'c2 [m]'], ['geom.alpha2', 'α2 stagger [rad]'], ['geom.s2', 's2 sweep [m]'], ['cond.AoA2', 'AoA2 [rad]'],
  ['cond.Cd', 'C_d (front rotor)'], ['cond.Ux1', 'U_x1 [m/s] (LPC2 inputs)'], ['cond.Ux2', 'U_x2 [m/s] (LPC2 inputs)']];

function normaliseBob(c) {
  c.options = c.options || {};
  c.inputs = c.inputs || { geom: {}, cond: {} };
  c.bl_files = c.bl_files || [];
  const o = c.options;
  c.observers = { R: o.r0 ?? 2.54, theta_deg: asList(o.theta ?? [Math.PI / 2]).map((t) => +(t * 180 / Math.PI).toFixed(6)) };
  return c;
}
function bobOpt(name) { return getPath(state.case, `options.${name}`); }
function bobBool(label, name, onchange) {
  const cb = h('input', { type: 'checkbox', checked: !!bobOpt(name) });
  cb.addEventListener('change', () => { setPath(state.case, `options.${name}`, cb.checked); syncJson(); if (onchange) onchange(); });
  return h('label', { class: 'bobchk' }, cb, ` ${label}`, h('code', { class: 'optname' }, ` opt.${name}`));
}
function bobPick(label, name, options, onchange) { return pick(label, `options.${name}`, options, onchange); }
function bobNum(label, name, o = {}) { return num(label, `options.${name}`, o); }
function bobList(label, path, scale = 1, unit = '') {
  const v = asList(getPath(state.case, path) ?? []);
  const inp = h('input', { value: v.map((x) => +(x * scale).toPrecision(8)).join(', '), 'aria-label': label });
  inp.addEventListener('change', () => {
    const xs = inp.value.split(/[ ,;]+/).map(parseFloat).filter(isFinite);
    setPath(state.case, path, xs.map((x) => x / scale)); syncJson(); if (path === 'options.theta') normaliseBob(state.case);
  });
  return fieldRow(`${label} (${v.length})`, inp, unit);
}
function pickFileB64(accept = '.mat') {
  return new Promise((resolve) => {
    const inp = h('input', { type: 'file', accept, style: 'display:none' });
    inp.addEventListener('change', async () => {
      const f = inp.files[0]; inp.remove();
      if (!f) return resolve(null);
      const buf = new Uint8Array(await f.arrayBuffer());
      let s = '';
      for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      resolve({ name: f.name, b64: btoa(s) });
    });
    document.body.append(inp); inp.click();
  });
}
function bobTable(cols, rows, onEdit) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'grid' },
    h('thead', {}, h('tr', {}, ...cols.map((c) => h('th', {}, c)))),
    h('tbody', {}, ...rows.map((row, i) => h('tr', {}, ...row.map((v, k) => {
      if (!onEdit) return h('td', { class: 'num' }, fmt(v, 4));
      const inp = h('input', { type: 'number', step: 'any', value: r4(v), 'aria-label': `${cols[k]} row ${i + 1}` });
      inp.addEventListener('change', () => { const x = parseFloat(inp.value); if (isFinite(x)) onEdit(i, k, x); });
      return h('td', {}, inp);
    }))))));
}

function buildBobInputs() {
  const c = state.case;
  const o = c.options;
  const rebuild = () => { normaliseBob(c); syncJson(); buildBobInputs(); };
  const msg = h('span', { class: 'muted' });
  const cards = [];
  // launch options -------------------------------------------------------
  const rotorOn = o.rotor_noise !== false;
  const instOn = !!o.installation_noise;
  cards.push(card('BoB launch options', 'The options of launch_BoB.m (names shown as opt.<name>). Load an existing launch file or download these settings as one; `bbnoise bob launch_BoB.m` runs the same file from the command line.',
    h('div', { class: 'row' },
      h('button', { class: 'ghost', onclick: async () => {
        const f = await pickFile('.m,.txt'); if (!f) return;
        const r = await backend.call('bob_parse', ['launch', f.text]);
        if (!r.ok) { msg.textContent = r.error; return; }
        Object.assign(o, r.options); msg.textContent = `loaded ${f.name} (${Object.keys(r.options).length} options)`; rebuild();
      } }, 'Load launch_BoB.m…'),
      h('button', { class: 'ghost', onclick: async () => {
        const r = await backend.call('bob_parse', ['launch_out', JSON.stringify(o)]);
        if (r.ok) download('launch_BoB.m', r.text, 'text/plain');
      } }, 'Download launch_BoB.m'), msg),
    fs('Noise sources', bobBool('Rotor noise', 'rotor_noise', rebuild),
      rotorOn ? bobPick('Rotor noise type', 'noise_type', BOB_CHOICES.noise_type, rebuild) : null,
      bobPick('Rotor stages', 'StageCount', BOB_CHOICES.StageCount, rebuild),
      bobBool('Installation noise: boundary-layer ingestion (BPRI_BL)', 'installation_noise', () => { setPath(c, 'options.p_noise_type', 'BPRI_BL'); rebuild(); }),
      bobBool('Amiet’s simplified rotational model (else the full model)', 'amiet', rebuild),
      o.amiet ? bobNum('Azimuthal integration points', 'phi_num', { int: true }) : null),
    fs('Models', bobPick('Wall pressure Φ_pp', 'phi_sw', BOB_CHOICES.phi_sw), bobPick('Convection velocity U_c', 'Uc', BOB_CHOICES.Uc),
      bobPick('Spanwise correlation length l_r', 'lr', BOB_CHOICES.lr),
      choose('Wake integral length scale', typeof o.L === 'number' ? 'C' : o.L, [['C', 'L = C × L from the wake data'], ['BW', 'BW · L = 0.42 b_w'], ['Pope', 'Pope (Re_λ)']],
        (v) => { o.L = v === 'C' ? 0.4 : v; rebuild(); }),
      typeof o.L === 'number' ? bobNum('C', 'L') : null,
      bobBool('von Kármán spectrum (else Liepmann)', 'Karman_spec'), bobBool('Airbus empirical correction on Rozenberg', 'emp_corr'),
      bobPick('Bad boundary-layer strips (discard flag)', 'baddata', BOB_CHOICES.baddata),
      bobBool('Chapman mean-flow correction', 'chapman'), bobBool('Results in emission co-ordinates', 'emission_angle'),
      bobPick('Flow contraction', 'contraction_perc', BOB_CHOICES.contraction_perc), bobBool('U_x from the case file (LPC2 inputs)', 'LPC_inputs')),
    fs('Observers and frequencies', bobBool('Spectral study (else a single-frequency directivity)', 'spectral_study', rebuild),
      o.spectral_study !== false ? h('div', {}, bobNum('f low', 'f_l', { unit: 'Hz' }), bobNum('f high', 'f_h', { unit: 'Hz' }), bobNum('Frequencies', 'f_num', { int: true }),
        h('p', { class: 'muted' }, 'BoB’s 1/3-octave sound power needs f low ≤ 89 Hz and f high ≥ 11.3 kHz.'))
        : bobNum('Frequency', 'f_d', { unit: 'Hz' }),
      bobList('Polar angles θ* from upstream', 'options.theta', 180 / Math.PI, 'deg'), bobNum('Observer radius r0', 'r0', { unit: 'm' }),
      bobNum('Radial strips', 'st_num', { int: true }))));
  // geometry -----------------------------------------------------------
  const gmsg = h('span', { class: 'muted' });
  cards.push(card('Geometry and conditions (CaseInputs)', 'BoB’s geom/cond structures. BoB places its strips at equal fractions of each array’s index range, so every array is resampled by position, not by radius.',
    h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: async () => {
      const f = await pickFileB64('.mat'); if (!f) return;
      const r = await backend.call('bob_parse', ['mat', f.b64]);
      if (!r.ok) { gmsg.textContent = r.error; return; }
      c.inputs = r.inputs; gmsg.textContent = `loaded ${f.name}`; rebuild();
    } }, 'Load case .mat…'), gmsg),
    fs('Scalars', ...BOB_GEOM_SCALARS.map(([p, l, u]) => num(l, `inputs.${p}`, { unit: u }))),
    fs('Arrays (comma-separated)', ...BOB_GEOM_ARRAYS.map(([p, l]) => bobList(l, `inputs.${p}`)))));
  // boundary layers ----------------------------------------------------------
  if (rotorOn && o.noise_type !== 'BRWI') {
    const slots = BOB_BL_SLOTS.slice(0, (o.StageCount ?? 2) * 2).map(([label, i]) => {
      const st = h('span', { class: 'muted' });
      const box = h('div');
      const show = async () => {
        if (!c.bl_files[i]) { st.textContent = 'no file'; box.replaceChildren(); return; }
        const r = await backend.call('bob_parse', ['bl', c.bl_files[i]]);
        if (!r.ok) { st.textContent = r.error; return; }
        const t = r.table;
        const keys = ['R', 'delta', 'delta_star', 'theta', 'tau_max', 'dpdx', 'rho_wall', 'U_inf', 'Pi', 'nu_wall', 'tau_wall', 'discard'];
        st.textContent = `${r.rows} rows${r.rows < (o.st_num ?? 5) ? ` — BoB needs one per strip (${o.st_num})` : ''}`;
        box.replaceChildren(h('details', {}, h('summary', {}, 'show table'),
          bobTable(BOB_BL_COLS.filter((x) => x !== '(unused)'), t.R.map((_, k) => keys.map((key) => t[key][k])))));
      };
      show();
      return fs(label, h('div', { class: 'row' },
        h('button', { class: 'ghost', onclick: async () => { const f = await pickFile('.txt,.dat,.csv'); if (!f) return; c.bl_files[i] = f.text; syncJson(); show(); } }, 'Load file…'), st), box);
    });
    cards.push(card('Boundary layers (BRTE)', 'One BoB boundary-layer file per surface, as read by read_bl.m: one header line, then one row per strip with 13 columns — R, boundary-layer thickness δ, displacement thickness δ*, momentum thickness θ, (unused), τ_max, dp/dx, ρ_wall, U_∞, Π, ν_wall, τ_wall, discard flag.',
      h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: async () => { const r = await backend.call('template', ['bob_bl']); if (r.ok) download('bl_quantities.txt', r.text, 'text/plain'); } }, 'Template')),
      ...slots));
  }
  // wake ----------------------------------------------------------------------
  if (rotorOn && o.noise_type !== 'BRTE' && (o.StageCount ?? 2) === 2) {
    const w = c.wake || (c.wake = Object.fromEntries(BOB_WAKE.map(([k]) => [k, Array(o.st_num ?? 5).fill(0)])));
    const n = Math.max(...BOB_WAKE.map(([k]) => asList(w[k]).length));
    const wmsg = h('span', { class: 'muted' });
    cards.push(card('Wake and background turbulence (BRWI)', 'Per strip, as BoB’s Wake_data.mat: wake half-width b_w, rms turbulence velocities and integral length scales of the background and wake turbulence.',
      h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: async () => {
        const f = await pickFileB64('.mat'); if (!f) return;
        const r = await backend.call('bob_parse', ['wake_mat', f.b64]);
        if (!r.ok) { wmsg.textContent = r.error; return; }
        c.wake = r.wake; delete c.wake_file; rebuild();
      } }, 'Load Wake_data.mat…'), wmsg),
      bobTable(['strip', ...BOB_WAKE.map(([, l]) => l)], Array.from({ length: n }, (_, j) => [j + 1, ...BOB_WAKE.map(([k]) => asList(w[k])[j])]),
        (i, k, x) => { if (k === 0) return; w[BOB_WAKE[k - 1][0]][i] = x; syncJson(); })));
  }
  // BL ingestion ------------------------------------------------------------
  if (instOn) {
    const t = c.bl_ingestion || (c.bl_ingestion = { z: [0.01, 0.1], ua: [1, 1], la: [0.3, 0.2], ut: [2, 2], lt: [0.15, 0.1] });
    const imsg = h('span', { class: 'muted' });
    const keys = ['z', 'ua', 'la', 'ut', 'lt'];
    cards.push(card('Boundary-layer ingestion (BPRI_BL)', 'Rotor 1 ingests a wall boundary layer; the hard wall adds an image source and two interference terms. Turbulence from the table below (wall-normal distance z) or constants.',
      fs('Wall and loading', bobNum('Wall distance from the hub centre', 'dwall', { unit: 'm' }), bobNum('Boundary-layer height', 'bl_height', { unit: 'm' }),
        bobBool('Hard wall', 'wall'), bobBool('Partial loading (only inside the boundary layer)', 'partial_loading'),
        bobBool('Blade-to-blade correlation', 'BPRI_correlation'), bobBool('Turbulence from the table (else constants)', 'bondary_layer_input_from_file', rebuild)),
      o.bondary_layer_input_from_file ? h('div', {},
        h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: async () => {
          const f = await pickFile('.dat,.txt,.csv'); if (!f) return;
          const r = await backend.call('bob_parse', ['ingestion', f.text]);
          if (!r.ok) { imsg.textContent = r.error; return; }
          c.bl_ingestion = r.table; rebuild();
        } }, 'Load table…'), h('button', { class: 'ghost', onclick: async () => { const r = await backend.call('template', ['bob_ingestion']); if (r.ok) download('boundary_layer_ingestion_inputs.dat', r.text, 'text/plain'); } }, 'Template'), imsg),
        bobTable(['z [m]', 'u_a', 'l_a [m]', 'u_t', 'l_t [m]'], t.z.map((_, j) => keys.map((k) => t[k][j])), (i, k, x) => { t[keys[k]][i] = x; syncJson(); }))
        : fs('Constants', bobNum('u_a', 'ua'), bobNum('u_t', 'ut'), bobNum('l_a', 'la', { unit: 'm' }), bobNum('l_t', 'lt', { unit: 'm' }))));
  }
  $('#input-cards').replaceChildren(...cards);
}

function buildInputs() {
  const c = state.case;
  if (c.type === 'bob') { buildBobInputs(); return; }
  const wpsOpts = state.meta.wps_models.map((m) => [m.key, PRETTY[m.key] || m.key]);
  const cards = [];
  // configuration
  if (c.type === 'rotor') {
    cards.push(card('Configuration', `${c.rotors.length === 2 ? 'Contra-rotating pair: the rear rotor ingests the front-rotor wakes.' : 'Isolated rotor.'} Chords are interpolated linearly between the radii of the table.`,
      ...c.rotors.map((r, i) => fs(`Rotor: ${r.name}`, num('Blades B', `rotors.${i}.B`, { int: true }), num('Speed', `rotors.${i}.rpm`, { unit: 'rpm' }),
        num('Tip radius', `rotors.${i}.r_tip`, { unit: 'm' }), num('Hub radius', `rotors.${i}.r_hub`, { unit: 'm' }),
        num('Axial velocity through the disc', `rotors.${i}.Ux`, { unit: 'm/s' }), num('Radial strips', `rotors.${i}.n_strips`, { int: true }),
        h('div', { class: 'lbl sub-lbl' }, 'Blade along the radius: chord, stagger, chordwise speed'), chordEditor(i)))));
  } else {
    cards.push(card('Configuration', 'Stationary flat plate (Amiet).', num('Chord', 'airfoil.chord', { unit: 'm' }), num('Span', 'airfoil.span', { unit: 'm' }), num('Free-stream velocity U', 'airfoil.U', { unit: 'm/s' })));
  }
  // interaction noise
  const inter = [];
  if (c.type === 'rotor' && c.brwi) {
    const body = h('div', {}, checks('brwi.spectrum', SPECTRA), wakeInputs());
    inter.push(fs('BRWI: rotor-wake interaction (rear rotor)', enable('enabled', 'brwi.enabled', body), body));
  }
  if (c.type === 'rotor') {
    const body = h('div', {}, checks('ingestion.spectrum', SPECTRA), homogeneousInputs('ingestion'));
    inter.push(fs(`Inflow turbulence ingestion (${(c.ingestion.rotors || [c.rotors[0].name]).join(', ')} rotor)`, enable('enabled', 'ingestion.enabled', body), body));
  } else {
    const body = h('div', {}, checks('turbulence.spectrum', SPECTRA), homogeneousInputs('turbulence'),
      pick('LE response', 'options.le_method', [['auto', 'Amiet switch (auto)'], ['high', 'high frequency'], ['low', 'low frequency']]));
    inter.push(fs('Leading-edge turbulence interaction', enable('enabled', 'turbulence.enabled', body), body));
  }
  cards.push(card('BRWI · interaction noise', 'Isotropic turbulence: k = 3 w_rms² / 2. The integral length scale Λ sets the spectral peak.', ...inter));
  // self noise
  const sbody = h('div', {}, h('div', { class: 'lbl' }, 'Wall-pressure models'), checks('brte.models', wpsOpts), blInputs(),
    num('Convection velocity Uc/Uₑ', 'brte.Uc_over_Ue'), num('Corcos constant b_c', 'brte.b_c'));
  cards.push(card('BRTE · trailing-edge self noise', 'Turbulent boundary layers on both sides of the trailing edge, Amiet (1976) with Roger & Moreau back-scattering.',
    enable('enabled', 'brte.enabled', sbody), sbody));
  // observer & numerics
  const thetaInp = h('input', { value: asList(c.observers.theta_deg).join(', '), 'aria-label': 'Polar angles' });
  thetaInp.addEventListener('change', () => {
    const v = thetaInp.value.split(/[ ,;]+/).map(parseFloat).filter(isFinite);
    if (v.length) { c.observers.theta_deg = v; syncJson(); }
  });
  const numerics = [num('Distance R', 'observers.R', { unit: 'm' }), fieldRow('Polar angles (first = spectra)', thetaInp, 'deg'),
    num('f min', 'frequency.f_min', { unit: 'Hz' }), num('f max', 'frequency.f_max', { unit: 'Hz' }), num('Frequency points', 'frequency.n', { int: true })];
  if (c.type === 'rotor') {
    const dsel = h('select', { 'aria-label': 'Thesis Doppler pairing' },
      h('option', { value: '1', selected: getPath(c, 'options.thesis_doppler_sign') !== -1 }, 'as printed (ω + lΩ)'),
      h('option', { value: '-1', selected: getPath(c, 'options.thesis_doppler_sign') === -1 }, 'mirrored (ω − lΩ)'));
    dsel.addEventListener('change', () => { setPath(state.case, 'options.thesis_doppler_sign', parseFloat(dsel.value)); syncJson(); });
    numerics.push(fs('Formulation', checks('formulations', [['full', 'Full (rotating dipole)'], ['simplified', 'Simplified (Amiet)'],
      ['eq3.18', 'Thesis eq. 3.18 (BRTE)'], ['eq5.7', 'Thesis eq. 5.7 (BRTE)'], ['eq2.73', 'Thesis eq. 2.73 (BRWI)']]),
    num('Doppler exponent (simplified)', 'options.doppler_exponent'), num('Azimuth points (simplified)', 'options.n_psi', { int: true }),
    fieldRow('Thesis eqs. 2.73 / 3.18 / 5.7 Doppler pairing', dsel, ''),
    fieldRow('Thesis eq. 2.73 × 2π (matches full)', (() => {
      const cb = h('input', { type: 'checkbox', checked: !!getPath(c, 'options.thesis_brwi_2pi') });
      cb.addEventListener('change', () => { setPath(state.case, 'options.thesis_brwi_2pi', cb.checked); syncJson(); });
      return cb;
    })(), '')));
  }
  cards.push(card('Observer, frequencies and formulation', c.type === 'rotor' ? 'Rotor observers: θ from the upstream (flight) axis.' : 'Airfoil observers: θ from the downstream chord line, mid-span plane.', ...numerics));
  $('#input-cards').replaceChildren(...cards);
}

async function loadCase(key) {
  const r = await backend.call('case', [key]);
  if (!r.ok) { $('#run-msg').textContent = r.error; return; }
  state.case = normaliseCase(r.case);
  const meta = state.meta.cases.find((x) => x.key === key);
  $('#case-desc').textContent = meta.description;
  $('#case-ref').textContent = meta.reference;
  buildInputs();
  syncJson();
}

/* ================================================================== run + results */
async function run() {
  const btn = $('#run');
  btn.disabled = true;
  $('#run-msg').textContent = 'running…';
  $$('.chart').forEach((c) => { c.style.opacity = 0.5; });
  const t0 = performance.now();
  const r = await backend.call('run', [JSON.stringify(state.case)], (t) => { $('#run-msg').textContent = t; });
  $$('.chart').forEach((c) => { c.style.opacity = 1; });
  btn.disabled = false;
  if (!r.ok) { $('#run-msg').textContent = r.error; return; }
  const res = r.result;
  $('#run-msg').textContent = `${res.curves.length} spectra in ${((performance.now() - t0) / 1000).toFixed(1)} s` + (res.warnings.length ? ` · ${res.warnings.join('; ')}` : '');
  state.result = res;
  state.combo = null;
  renderAll();
  const cur = $('.tabs button[aria-selected="true"]').dataset.tab;
  if (cur === 'inputs') showTab('combined');
}

const PRETTY = { vonkarman: 'von Kármán', liepmann: 'Liepmann', amiet: 'Amiet', chase_howe: 'Chase–Howe', goody: 'Goody',
  rozenberg: 'Rozenberg', kamruzzaman: 'Kamruzzaman', lee: 'Lee', dominique_gep: 'VKI GEP', kim_george: 'Kim–George',
  rozenberg_2010: 'Rozenberg (2010, thesis)' };
const FORM_LABEL = { 'eq3.18': 'thesis eq. 3.18', 'eq5.7': 'thesis eq. 5.7', 'eq2.73': 'thesis eq. 2.73' };
const FORM_DASH = { simplified: '6 4', 'eq3.18': '2 3', 'eq5.7': '8 3 2 3', 'eq2.73': '2 3' };
const INTERACTION_FOR = { 'eq3.18': 'full', 'eq5.7': 'simplified' };
const prettyVariant = (v) => v.replace(/^[a-z0-9_]+/, (k) => PRETTY[k] || k);
const idKey = (c) => `${c.rotor}|${c.mechanism}|${c.variant}`;
function itemsFor(curves) {
  const ids = [...new Set(curves.map(idKey))];
  return curves.map((c) => {
    const i = ids.indexOf(idKey(c));
    return { label: c.label, color: i < SLOTS.length ? cssVar(SLOTS[i]) : cssVar('--muted'), dash: FORM_DASH[c.formulation] || null,
      psd: c.psd_db, oct: c.third_octave, dir: c.directivity, oaspl: c.oaspl, curve: c };
  });
}
function tiles(el, list) { el.replaceChildren(...list.map(([k, v, sub]) => h('div', { class: 'stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v), h('div', { class: 's' }, sub)))); }
function bestPerGroup(curves) {
  const g = {};
  for (const c of curves) { const k = `${c.rotor === 'airfoil' ? '' : c.rotor + ': '}${c.mechanism}`; if (!g[k] || c.oaspl > g[k].oaspl) g[k] = c; }
  return Object.entries(g).map(([k, c]) => [k, `${c.oaspl.toFixed(1)} dB`, `OASPL, ${c.label.split(' - ').slice(1).join(', ')}`]);
}
const titleAt = (res) => `at θ = ${res.curves[0] ? res.curves[0].theta_deg : 90}°, R = ${state.case.observers.R} m`;

function renderAll() {
  const res = state.result;
  if (!res) return;
  renderInteraction(res);
  renderSelf(res);
  renderCombined(res);
  $('#dl-csv').disabled = false; $('#dl-json').disabled = false;
}

function renderInteraction(res) {
  const curves = res.curves.filter((c) => c.category === 'interaction');
  const items = itemsFor(curves);
  state.cards.int.update({ f: res.f, items, title: `BRWI · interaction noise ${titleAt(res)}`, empty: 'No interaction-noise mechanism was enabled. Enable one on the Inputs tab and run again.' });
  directivity($('#int-dir-card'), $('#int-dir'), items);
  state.cards.intStrips.update({ f: res.f, items });
  const t = [...bestPerGroup(curves)];
  const info = res.info || {};
  if (info.wake_passing_hz) t.push(['Wake-passing frequency', `${fmtF(info.wake_passing_hz)}Hz`, 'B₁(Ω₁+Ω₂)/2π seen by the rear rotor']);
  if (info.turbulence) t.push(['Inflow turbulence', `k = ${fmt(info.turbulence.tke, 3)} m²/s²`, `w_rms = ${fmt(info.turbulence.w_rms, 3)} m/s, Λ = ${fmt(info.turbulence.Lambda, 3)} m`]);
  tiles($('#int-stats'), t);
  const tc = $('#int-turb-card');
  if (info.wake) {
    tc.style.display = '';
    $('#int-turb-title').textContent = 'Front-rotor wake turbulence along the rear blade';
    const w = info.wake;
    $('#int-turb-chart').style.display = '';
    lineChart($('#int-turb-chart'), [
      { label: 'centreline TKE k_c', x: w.r, y: w.tke_c, color: cssVar('--s1') },
      { label: 'passage-averaged TKE', x: w.r, y: w.tke_mean, color: cssVar('--s2') }],
    { xlabel: 'Rear-rotor radius r [m]', ylabel: 'TKE [m²/s²]', unit: 'm²/s²', digits: 3, markers: true, xfmt: (v) => `r = ${fmt(v, 4)} m` });
    $('#int-turb').replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ...['r [m]', 'front pitch s₁ [mm]', 'wake semi-width L_w [mm]', 'Λ [mm]', 'k_c [m²/s²]', 'mean k [m²/s²]'].map((x) => h('th', {}, x)))),
      h('tbody', {}, ...w.r.map((r, i) => h('tr', {}, ...[r, w.s1[i] * 1e3, w.Lw[i] * 1e3, w.Lambda[i] * 1e3, w.tke_c[i], w.tke_mean[i]].map((v) => h('td', { class: 'num' }, fmt(v, 4)))))))));
  } else if (info.turbulence) {
    tc.style.display = '';
    $('#int-turb-title').textContent = 'Inflow turbulence';
    $('#int-turb-chart').style.display = 'none';
    const tb = info.turbulence;
    $('#int-turb').replaceChildren(h('div', { class: 'kv' }, ...[['Turbulent kinetic energy k', `${fmt(tb.tke, 4)} m²/s²`], ['w_rms = √(2k/3)', `${fmt(tb.w_rms, 4)} m/s`],
      ['Intensity (of the reference velocity)', `${fmt(100 * tb.intensity, 3)} %`], ['Integral length scale Λ', `${fmt(tb.Lambda, 4)} m`]].flatMap(([k, v]) => [h('span', { class: 'k' }, k), h('span', {}, v)])));
  } else tc.style.display = 'none';
}

function renderSelf(res) {
  const curves = res.curves.filter((c) => c.category === 'self');
  const items = itemsFor(curves);
  state.cards.self.update({ f: res.f, items, title: `BRTE · self noise ${titleAt(res)}`, empty: 'BRTE was not enabled. Enable it on the Inputs tab and run again.' });
  directivity($('#self-dir-card'), $('#self-dir'), items);
  state.cards.selfStrips.update({ f: res.f, items });
  renderBlDist(res);
  tiles($('#self-stats'), bestPerGroup(curves));
  const info = res.info || {};
  // boundary layer table
  const blKeys = [['Ue', 'Uₑ [m/s]'], ['delta', 'δ [m]'], ['delta_star', 'δ* [m]'], ['theta', 'θ [m]'], ['H', 'H'], ['cf', 'C_f'],
    ['tau_w', 'τ_w [Pa]'], ['u_tau', 'u_τ [m/s]'], ['beta_c', 'β_C'], ['Pi', 'Π'], ['Rt', 'R_t (δ)'], ['RT_star', 'R_T (δ*)'], ['Delta', 'Δ = δ/δ*'], ['mach', 'M']];
  const bls = info.boundary_layers || {};
  $('#self-bl-card').style.display = Object.keys(bls).length ? '' : 'none';
  $('#self-bl').replaceChildren(...Object.entries(bls).map(([name, sides]) => h('table', {},
    h('thead', {}, h('tr', {}, h('th', {}, name === 'airfoil' ? 'Airfoil' : `${name} rotor, mid-span`), h('th', {}, 'suction'), h('th', {}, 'pressure'))),
    h('tbody', {}, ...blKeys.map(([k, lab]) => h('tr', {}, h('td', {}, lab), h('td', { class: 'num' }, fmt(sides.suction[k], 4)), h('td', { class: 'num' }, fmt(sides.pressure[k], 4))))))));
  // wall pressure spectra
  const wp = info.wall_pressure || {};
  const opts = Object.entries(wp).flatMap(([name, sides]) => Object.keys(sides).map((side) => [`${name}|${side}`, `${name === 'airfoil' ? 'airfoil' : name + ' rotor'}, ${side} side`]));
  $('#self-wps-card').style.display = opts.length ? '' : 'none';
  if (!opts.length) return;
  const sel = $('#wps-pick');
  const prev = sel.value;
  sel.replaceChildren(...opts.map(([v, t]) => h('option', { value: v, selected: v === prev }, t)));
  const draw = () => {
    const [name, side] = sel.value.split('|');
    const models = wp[name][side];
    const series = Object.entries(models).map(([m, y], i) => ({ label: PRETTY[m] || m,
      x: res.f, y, color: cssVar(SLOTS[i % SLOTS.length]) }));
    lineChart($('#self-wps'), series, { xlog: true, xlabel: 'Frequency [Hz]', ylabel: 'Φ_pp [dB re (20 µPa)²/Hz]', unit: 'dB', digits: 3, xfmt: (v) => `${fmtF(v)}Hz`, yFloorSpan: 70 });
    legend($('#self-wps-legend'), series, () => {});
  };
  sel.onchange = draw;
  draw();
}

/* ================================================================== per-strip contributions */
const RAMP = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
const isDark = () => getComputedStyle(document.documentElement).colorScheme.includes('dark');
function hexLerp(a, b, t) {
  const p = (x) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const A = p(a), B = p(b);
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(',')})`;
}
function rampColor(t) {       // t in [0, 1]: low values recede toward the surface in both themes
  const ramp = isDark() ? [...RAMP].reverse() : RAMP;
  const x = Math.min(Math.max(t, 0), 1) * (ramp.length - 1);
  const i = Math.min(Math.floor(x), ramp.length - 2);
  return hexLerp(ramp[i], ramp[i + 1], x - i);
}

/** Heatmap of strip PSD (rows = strips, columns = frequencies). */
function heatmap(el, f, st, o = {}) {
  el.innerHTML = '';
  const W = el.clientWidth || 700, H = el.clientHeight || 340;
  const m = { l: 56, r: 74, t: 10, b: 42 };
  const Z = st.psd_db.map((row) => row.map((v) => (v === null ? -Infinity : v)));
  const zmax = Math.max(...Z.flat().filter(isFinite));
  const span = o.span || 40, zmin = zmax - span;
  const fe = [f[0] ** 2 / Math.sqrt(f[0] * f[1])];
  for (let i = 0; i < f.length - 1; i++) fe.push(Math.sqrt(f[i] * f[i + 1]));
  fe.push(f[f.length - 1] ** 2 / fe[fe.length - 1]);
  const re = [st.r[0] - st.dr[0] / 2, ...st.r.map((r, k) => r + st.dr[k] / 2)];
  const X = (v) => m.l + (Math.log10(v) - Math.log10(fe[0])) / (Math.log10(fe[fe.length - 1]) - Math.log10(fe[0])) * (W - m.l - m.r);
  const Y = (v) => m.t + (re[re.length - 1] - v) / (re[re.length - 1] - re[0]) * (H - m.t - m.b);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'strip spectrum map' });
  const g = s('g');
  Z.forEach((row, k) => row.forEach((z, i) => {
    g.append(s('rect', { x: X(fe[i]), y: Y(re[k + 1]), width: Math.max(X(fe[i + 1]) - X(fe[i]), 0.5) + 0.3, height: Math.max(Y(re[k]) - Y(re[k + 1]), 0.5) + 0.3,
      fill: isFinite(z) ? rampColor((z - zmin) / span) : 'transparent' }));
  }));
  svg.append(g);
  const ax = s('g', { class: 'axis' });
  for (const t of logTicks(fe[0], fe[fe.length - 1])) {
    const tx = s('text', { x: X(t), y: H - m.b + 16, 'text-anchor': 'middle' }); tx.textContent = fmtF(t); ax.append(tx);
    ax.append(s('line', { x1: X(t), x2: X(t), y1: H - m.b, y2: H - m.b + 4, class: 'baseline' }));
  }
  for (const t of niceTicks(re[0], re[re.length - 1], 6)) {
    const tx = s('text', { x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }); tx.textContent = +t.toPrecision(4); ax.append(tx);
  }
  svg.append(ax);
  const xl = s('text', { x: (m.l + W - m.r) / 2, y: H - 6, 'text-anchor': 'middle', class: 'axis-title' }); xl.textContent = 'Frequency [Hz]'; svg.append(xl);
  const yc = (m.t + H - m.b) / 2;
  const yl = s('text', { x: 14, y: yc, 'text-anchor': 'middle', class: 'axis-title', transform: `rotate(-90 14 ${yc})` }); yl.textContent = 'Strip radius r [m]'; svg.append(yl);
  // colour bar
  const cbx = W - m.r + 18, cbw = 12, cb0 = m.t, cb1 = H - m.b;
  const defs = s('defs'), grad = s('linearGradient', { id: `cb-${el.id}`, x1: 0, x2: 0, y1: 1, y2: 0 });
  for (let k = 0; k <= 10; k++) grad.append(s('stop', { offset: `${k * 10}%`, 'stop-color': rampColor(k / 10) }));
  defs.append(grad); svg.append(defs);
  svg.append(s('rect', { x: cbx, y: cb0, width: cbw, height: cb1 - cb0, fill: `url(#cb-${el.id})`, rx: 2 }));
  const cbax = s('g', { class: 'axis' });
  for (const t of niceTicks(zmin, zmax, 5)) {
    const y = cb1 - (t - zmin) / span * (cb1 - cb0);
    const tx = s('text', { x: cbx + cbw + 4, y: y + 4 }); tx.textContent = Math.round(t); cbax.append(tx);
  }
  svg.append(cbax);
  const cbl = s('text', { x: cbx + 6, y: H - 12, 'text-anchor': 'middle', class: 'axis-title' }); cbl.textContent = 'dB/Hz'; svg.append(cbl);
  const hi = s('rect', { fill: 'none', stroke: 'var(--ink)', 'stroke-width': 1.5, visibility: 'hidden' });
  svg.append(hi);
  const hit = s('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
  svg.append(hit);
  const tip = $('#tip');
  hit.addEventListener('pointermove', (ev) => {
    const b = svg.getBoundingClientRect();
    const px = (ev.clientX - b.left) * (W / b.width), py = (ev.clientY - b.top) * (H / b.height);
    let i = fe.findIndex((v, j) => j < fe.length - 1 && px >= X(fe[j]) && px < X(fe[j + 1]));
    let k = re.findIndex((v, j) => j < re.length - 1 && py <= Y(re[j]) && py > Y(re[j + 1]));
    if (i < 0 || k < 0) return;
    hi.setAttribute('x', X(fe[i])); hi.setAttribute('width', X(fe[i + 1]) - X(fe[i]));
    hi.setAttribute('y', Y(re[k + 1])); hi.setAttribute('height', Y(re[k]) - Y(re[k + 1])); hi.setAttribute('visibility', 'visible');
    tip.replaceChildren(h('div', { class: 'h' }, `r = ${fmt(st.r[k], 4)} m, f = ${fmtF(f[i])}Hz`),
      h('div', {}, h('span', { class: 'v' }, `${isFinite(Z[k][i]) ? Z[k][i].toFixed(1) : '–'} dB/Hz`)),
      h('div', { class: 'muted' }, `strip OASPL ${st.oaspl[k].toFixed(1)} dB, ${(100 * st.share[k]).toFixed(1)} % of the energy`));
    tip.style.display = 'block';
    tip.style.left = `${Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${ev.clientY + 14}px`;
  });
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hi.setAttribute('visibility', 'hidden'); });
  el.append(svg);
}

/** Card: strip OASPL along the blade (all spectra), radius x frequency map, table. */
function stripCard(root) {
  let view = 'oaspl', data = null, sel = 0;
  const chart = h('div', { class: 'chart short', id: `${root.id}-chart` });
  const leg = h('div', { class: 'legend' });
  const picker = h('select', { class: 'compact', 'aria-label': 'Spectrum' });
  picker.addEventListener('change', () => { sel = +picker.value; draw(); });
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Strip view' },
    ...[['oaspl', 'OASPL by strip'], ['map', 'Radius × frequency'], ['table', 'Table']].map(([k, t]) =>
      h('button', { class: k === view ? 'on' : '', onclick: (e) => { view = k; $$('button', seg).forEach((b) => b.classList.toggle('on', b === e.target)); draw(); } }, t)));
  const note = h('p', { class: 'muted' });
  root.replaceChildren(h('div', { class: 'panel chart-card' }, h('div', { class: 'card-head' }, h('h2', {}, 'Contribution of each radial strip'), h('div', { class: 'row tight' }, picker, seg)), chart, leg, note));
  function draw() {
    if (!data || !data.items.length) { root.style.display = 'none'; return; }
    root.style.display = '';
    picker.style.display = view === 'oaspl' ? 'none' : '';
    const it = data.items[Math.min(sel, data.items.length - 1)];
    if (view === 'oaspl') {
      const series = data.items.map((q) => ({ ...q, x: q.curve.strips.r, y: q.curve.strips.oaspl }));
      lineChart(chart, series, { xlabel: 'Strip radius r [m]', ylabel: 'Strip OASPL [dB]', unit: 'dB', digits: 3, markers: true, xfmt: (v) => `r = ${fmt(v, 4)} m` });
      legend(leg, series, () => {});
      note.textContent = `Each point is the OASPL radiated by one blade element (all blades) at the observer; the strip energies add up to the spectrum OASPL. ${data.items[0].curve.strips.r.length} strips per rotor.`;
    } else if (view === 'map') {
      heatmap(chart, data.f, it.curve.strips);
      leg.innerHTML = '';
      note.textContent = `${it.label}: PSD of every strip, top 40 dB. Hover a cell for its level and the strip's share of the energy.`;
    } else {
      const st = it.curve.strips;
      chart.replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ...['r [m]', 'dr [m]', 'chord [m]', 'U [m/s]', 'OASPL [dB]', 'share of energy'].map((x) => h('th', {}, x)))),
        h('tbody', {}, ...st.r.map((r, k) => h('tr', {}, ...[fmt(r, 4), fmt(st.dr[k], 3), fmt(st.chord[k], 4), fmt(st.U[k], 4), st.oaspl[k].toFixed(1), `${(100 * st.share[k]).toFixed(1)} %`].map((v) => h('td', { class: 'num' }, v))))))));
      leg.innerHTML = '';
      note.textContent = it.label;
    }
  }
  return {
    update(d) {
      data = d ? { ...d, items: d.items.filter((q) => q.curve.strips) } : null;
      if (data) {
        const prev = picker.value;
        picker.replaceChildren(...data.items.map((q, i) => h('option', { value: i, selected: String(i) === prev }, q.label)));
        sel = Math.min(sel, Math.max(data.items.length - 1, 0));
      }
      draw();
    },
  };
}

/** Boundary-layer parameters along the blade (Self noise tab). */
const BL_DIST_KEYS = [['delta_star', 'δ* [mm]', 1e3], ['delta', 'δ [mm]', 1e3], ['theta', 'θ [mm]', 1e3], ['H', 'H', 1], ['cf', 'C_f', 1],
  ['beta_c', 'β_C', 1], ['Pi', 'Π', 1], ['Rt', 'R_t', 1], ['Ue', 'Uₑ [m/s]', 1]];
function renderBlDist(res) {
  const card = $('#self-bldist-card');
  const dist = (res.info || {}).bl_distribution;
  if (!dist || !Object.keys(dist).length) { card.style.display = 'none'; return; }
  card.style.display = '';
  const rs = $('#bldist-rotor'), ps = $('#bldist-param');
  const prevR = rs.value, prevP = ps.value || 'delta_star';
  rs.replaceChildren(...Object.keys(dist).map((k) => h('option', { value: k, selected: k === prevR }, `${k} rotor`)));
  ps.replaceChildren(...BL_DIST_KEYS.map(([k, lab]) => h('option', { value: k, selected: k === prevP }, lab)));
  const draw = () => {
    const d = dist[rs.value];
    const [k, lab, sc] = BL_DIST_KEYS.find((q) => q[0] === ps.value);
    const series = ['suction', 'pressure'].map((side, i) => ({ label: `${side} side`, x: d.r, y: d[`${side}_${k}`].map((v) => v * sc), color: cssVar(SLOTS[i]) }));
    lineChart($('#self-bldist'), series, { xlabel: 'Strip radius r [m]', ylabel: lab, digits: 4, markers: true, xfmt: (v) => `r = ${fmt(v, 4)} m` });
    legend($('#self-bldist-legend'), series, () => {});
  };
  rs.onchange = draw; ps.onchange = draw;
  draw();
}

/* ---- combined: pick one variant per (rotor, mechanism), sum energies ---- */
const dbSum = (arrs) => arrs[0].map((_, i) => {
  let e = 0, any = false;
  for (const a of arrs) { const v = a[i]; if (v !== null && v !== undefined && isFinite(v)) { e += 10 ** (v / 10); any = true; } }
  return any && e > 0 ? 10 * Math.log10(e) : null;
});
function sumCurves(cs) {
  if (!cs.length) return null;
  const dirOk = cs.every((c) => c.directivity) && cs.every((c) => JSON.stringify(c.directivity.theta) === JSON.stringify(cs[0].directivity.theta));
  return { psd: dbSum(cs.map((c) => c.psd_db)), oct: { fc: cs[0].third_octave.fc, spl: dbSum(cs.map((c) => c.third_octave.spl)) },
    dir: dirOk ? { theta: cs[0].directivity.theta, oaspl: dbSum(cs.map((c) => c.directivity.oaspl)) } : null,
    oaspl: 10 * Math.log10(cs.reduce((a, c) => a + 10 ** (c.oaspl / 10), 0)) };
}

function renderCombined(res) {
  const groups = {};
  for (const c of res.curves) {
    const k = `${c.rotor}|${c.mechanism}`;
    groups[k] = groups[k] || { rotor: c.rotor, mechanism: c.mechanism, category: c.category, variants: [] };
    if (!groups[k].variants.includes(c.variant)) groups[k].variants.push(c.variant);
  }
  const forms = [...new Set(res.curves.map((c) => c.formulation))];
  // thesis eqs. 3.18 / 5.7 only give self noise: pair them with the thesis eq. 2.73 interaction noise when it
  // was run (as in the thesis' chapter 4), otherwise with the full / simplified interaction noise
  const thesisRwi = forms.includes('eq2.73');
  const pairedWith = (f) => (INTERACTION_FOR[f] && thesisRwi) ? 'eq2.73'
    : (INTERACTION_FOR[f] && forms.includes(INTERACTION_FOR[f]) ? INTERACTION_FOR[f] : null);
  const shownForms = forms.filter((f) => !(f === 'eq2.73' && forms.some((g) => INTERACTION_FOR[g])));
  if (!state.combo) state.combo = { pick: Object.fromEntries(Object.entries(groups).map(([k, g]) => [k, g.variants[0]])), forms: new Set(forms) };
  const combo = state.combo;
  const nice = prettyVariant;
  const pk = $('#combo-pickers');
  pk.replaceChildren(...[...Object.entries(groups).map(([k, g]) => {
    const sel = h('select', { 'aria-label': k }, h('option', { value: '__off', selected: combo.pick[k] === '__off' }, 'exclude'),
      ...g.variants.map((v) => h('option', { value: v, selected: combo.pick[k] === v }, nice(v))));
    sel.addEventListener('change', () => { combo.pick[k] = sel.value; renderCombined(res); });
    return h('div', {}, h('label', {}, `${g.rotor === 'airfoil' ? '' : g.rotor + ': '}${g.mechanism}`), sel);
  }), shownForms.length > 1 ? h('div', {}, h('label', {}, 'Formulation'), h('div', { class: 'checks' }, ...shownForms.map((f) => {
    const cb = h('input', { type: 'checkbox', checked: combo.forms.has(f) });
    cb.addEventListener('change', () => { cb.checked ? combo.forms.add(f) : combo.forms.delete(f); renderCombined(res); });
    return h('label', {}, cb, FORM_LABEL[f] || f);
  }))) : null].filter(Boolean));
  const items = [], stats = [];
  for (const f of shownForms.filter((x) => combo.forms.has(x))) {
    const chosen = res.curves.filter((c) => (c.formulation === f || (c.category === 'interaction' && c.formulation === pairedWith(f)))
      && combo.pick[`${c.rotor}|${c.mechanism}`] === c.variant);
    const inter = sumCurves(chosen.filter((c) => c.category === 'interaction'));
    const self = sumCurves(chosen.filter((c) => c.category === 'self'));
    const tot = sumCurves(chosen);
    const dash = FORM_DASH[f] || null;
    const tag = shownForms.length > 1 ? ` - ${FORM_LABEL[f] || f}${pairedWith(f) ? ` + ${FORM_LABEL[pairedWith(f)] || pairedWith(f)} BRWI` : ''}` : '';
    if (tot) items.push({ label: `total (BRWI + BRTE)${tag}`, color: cssVar('--s1'), dash, wide: true, ...tot });
    if (inter) items.push({ label: `BRWI${tag}`, color: cssVar('--s2'), dash, ...inter });
    if (self) items.push({ label: `BRTE${tag}`, color: cssVar('--s3'), dash, ...self });
    if (tot) stats.push([`Total${tag}`, `${tot.oaspl.toFixed(1)} dB`, 'OASPL, BRWI + BRTE']);
    if (inter && self) stats.push([`BRWI − BRTE${tag}`, `${(inter.oaspl - self.oaspl).toFixed(1)} dB`, `${inter.oaspl.toFixed(1)} dB vs ${self.oaspl.toFixed(1)} dB`]);
  }
  state.comboItems = items;
  state.cards.combo.update({ f: res.f, items, title: `BRWI + BRTE ${titleAt(res)}`, empty: 'Nothing selected.' });
  directivity($('#combo-dir-card'), $('#combo-dir'), items);
  tiles($('#combo-stats'), stats);
  renderInfo(res);
}

function renderInfo(res) {
  const el = $('#info');
  el.innerHTML = '';
  const info = res.info || {};
  if (info.reference) el.append(h('p', { class: 'ref' }, info.reference));
  if (res.warnings && res.warnings.length) el.append(h('p', { class: 'warn' }, res.warnings.join('; ')));
  if (info.rotors) {
    for (const r of Object.values(info.rotors)) {
      el.append(h('h3', {}, `Rotor ${r.name}: B = ${r.B}, ${r.rpm} rpm, BPF ${fmtF(r.bpf_hz)}Hz, relative tip Mach ${r.tip_mach_relative.toFixed(3)}, Mx = ${r.Mx.toFixed(3)}`));
      el.append(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ...['r [m]', 'dr [m]', 'chord [m]', 'U_X [m/s]', 'stagger α [deg]', 'AoA [deg]', 'M'].map((x) => h('th', {}, x)))),
        h('tbody', {}, ...r.strips.map((st) => h('tr', {}, ...[st.r, st.dr, st.chord, st.U, st.stagger_deg ?? 90 - st.psi_deg, st.aoa_deg ?? 0, st.M].map((v) => h('td', { class: 'num' }, fmt(v, 4)))))))));
    }
  }
  el.append(h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'spectrum'), h('th', {}, 'OASPL [dB]'))),
    h('tbody', {}, ...[...res.curves, ...(res.totals || [])].map((c) => h('tr', {}, h('td', {}, c.label), h('td', { class: 'num' }, c.oaspl.toFixed(1)))))));
}

function download(name, text, type) {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}

/* ================================================================== verification */
async function runVerify() {
  $('#verify-run').disabled = true;
  $('#verify-msg').textContent = 'running checks…';
  const r = await backend.call('verify', []);
  $('#verify-run').disabled = false;
  if (!r.ok) { $('#verify-msg').textContent = r.error; return; }
  const n = r.checks.filter((c) => c.passed).length;
  $('#verify-msg').textContent = `${n} / ${r.checks.length} passed`;
  $('#verify-table').replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ...['Check', 'What it tests', 'Metric', 'Value', 'Tolerance', 'Result', 'Reference'].map((x) => h('th', {}, x)))),
    h('tbody', {}, ...r.checks.map((c) => h('tr', {}, h('td', {}, c.name), h('td', {}, c.description, c.details ? h('div', { class: 'muted' }, c.details.slice(0, 240)) : null),
      h('td', {}, c.metric), h('td', { class: 'num' }, fmt(c.value, 3)), h('td', { class: 'num' }, fmt(c.tolerance, 3)),
      h('td', { class: c.passed ? 'pass' : 'fail' }, c.passed ? 'PASS' : 'FAIL'), h('td', { class: 'muted' }, c.reference)))))));
}

/* ================================================================== theory */
const THEORY = `
<h2>What is implemented</h2>
<p>The package follows the structure of V. P. Blandeau's thesis, <em>Aerodynamic broadband noise from contra-rotating open rotors</em> (ISVR, University of Southampton, 2011). Each blade is cut into radial strips, and each strip is an Amiet flat plate. The radiation of the rotating strips is computed either exactly (full formulation) or with Amiet's azimuthal average (simplified formulation).</p>
<h3>Blade-element response (Amiet)</h3>
<p>Both mechanisms reduce to an effective force spectrum S<sub>F</sub> of a strip of chord c and span d. It contains the chordwise non-compactness through the chordwise radiation wavenumber q̄:</p>
<div class="eq">leading edge : S_F = 2 π³ ρ₀² c² U d |L(K̄₁, k̄_y, q̄)|² Φ_ww(K₁, k_y)        (Amiet 1975, + Roger's 2nd-order term)
trailing edge: S_F = c² (d/2) |I(K̄, k̄_y, q̄)|² Φ_pp(ω) l_y(ω) / (1 + k_y² l_y²)   (Amiet 1976, Roger &amp; Moreau back-scattering)
stationary   : S_pp = (k x₃/σ / 4πσ)² S_F,   q̄ = μ̄ (M − x₁/σ)</div>
<h3>Turbulence inputs</h3>
<div class="eq">isotropic turbulence : k = ½(u'² + v'² + w'²) = 3 w_rms² / 2
von Kármán           : Φ_ww = 4/(9π) w²/k_e² (k̂₁² + k̂₂²)/(1 + k̂₁² + k̂₂²)^(7/3),   k_e = √π/Λ · Γ(5/6)/Γ(1/3)
Liepmann             : Φ_ww = 3 w² Λ²/(4π) · Λ²(k₁² + k₂²)/(1 + Λ²(k₁² + k₂²))^(5/2)</div>
<h3>Full formulation (exact rotating dipole)</h3>
<div class="eq">S_pp(x, ω) = B / (4πσ)² Σₙ Jₙ²(K_r R) Dₙ² S_F(ω + nΩ; q̄ₙ, k_y,n)
Dₙ  = K_z cos ψ − (n/R) sin ψ          dipole projection of azimuthal mode n
q̄ₙ  = −b (n cos ψ / R + K_z sin ψ)     chordwise radiation wavenumber of mode n
k_y,n = K_r √(1 − (n / K_r R)²)         local radial wavenumber of Jₙ
K   = k (ρ/σ, (z/σ − M_x)/β_x²)        convected far-field wave vector, σ² = z² + β_x² ρ²</div>
<h3>Simplified formulation (Amiet 1977)</h3>
<div class="eq">S_pp(x, ω) = B/2π ∫ (ω_s/ω)^p S_pp^Amiet(x_b(Ψ), ω_s(Ψ)) dΨ,     ω_s/ω = 1 − K·V_b / k</div>
<p>The observer is placed in the blade frame at the reception time. The verification suite shows that with that choice p = 2 reproduces the exact result at high frequency; p = 1 reproduces Amiet's original factor. The two formulations agree to within about 0.1 dB above a few shaft orders and differ at low frequency, as Blandeau &amp; Joseph (2011) concluded.</p>
<h3>Thesis equations 3.18 and 5.7 (self noise)</h3>
<p>Blandeau's own trailing-edge models are also coded exactly as printed.</p>
<ul>
<li><strong>Eq. 3.18</strong> is the exact model, S<sub>pp</sub> = B/(2π)(k<sub>0</sub>b/r<sub>0</sub>)<sup>2</sup>Δr Σ<sub>l</sub> D<sub>l</sub>|ℒ<sub>TE</sub>|<sup>2</sup>S<sub>qq</sub>(0, K<sub>X,l</sub>). D<sub>l</sub> is averaged across the strip, κ<sub>l</sub> = (l/r)sin α − k<sub>0</sub>cos α cos θ, and K<sub>X,l</sub> = (ω + lΩ)/U<sub>c</sub>.</li>
<li><strong>Eq. 5.7</strong> is Amiet's approximate model in the same notation.</li>
</ul>
<p>Both use:</p>
<ul>
<li>the Corcos length l<sub>2</sub> = 1.6 U<sub>c</sub>/ω, with U<sub>c</sub> = 0.8 U<sub>X</sub>;</li>
<li>a double-sided wall-pressure spectrum summed over both blade sides;</li>
<li>a medium at rest.</li>
</ul>
<p>What the code shows:</p>
<ul>
<li>Eqs. 3.18 and 5.7 agree to within 0.01 dB at high frequency.</li>
<li>As printed, the Doppler shift is paired with the chordwise coupling in the opposite sense to the full formulation. Evaluated literally, eq. 3.18 lies 2–8 dB below it at high frequency.</li>
<li>With the pairing mirrored (ω − lΩ, an input option), eq. 3.18 agrees with the full formulation to within 0.9 dB.</li>
</ul>
<h3>Thesis equation 2.73 (rotor-wake interaction)</h3>
<p>Blandeau's simplified BRWI model is coded as printed. It is a double sum over wake harmonics m and interaction modes h, with l = mB<sub>1</sub> − h:</p>
<p>S<sub>pp</sub> = B<sub>2</sub>/4 (B<sub>1</sub>ρ<sub>0</sub>k<sub>0</sub>b<sub>2</sub>/r<sub>0</sub>)<sup>2</sup>U<sub>X2</sub>Δr Σ<sub>m,h</sub> D′<sub>ml</sub>Φ<sub>ww</sub>(0, K<sub>X,mh</sub>)|ℒ<sub>LE</sub>|<sup>2</sup></p>
<ul>
<li>The wake Fourier factors f<sub>m</sub> come from a train of Gaussian profiles exp(−aη<sup>2</sup>/b<sub>W</sub><sup>2</sup>), with a = 0.637 and L = 0.42 b<sub>W</sub>.</li>
</ul>
<p>What the code shows:</p>
<ul>
<li>With overlapping wakes, the Doppler pairing mirrored and the result multiplied by 2π (both are options), eq. 2.73 matches the full formulation to within 0.6 dB.</li>
<li>As printed, eq. 2.73 is 2π lower.</li>
<li>On the thesis CROR, the printed pair (eqs. 3.18 + 2.73) reproduces the peak frequencies and trends of Fig. 4.7. It places the interaction noise 10–13 dB higher relative to the trailing-edge noise than that figure does.</li>
</ul>
<h3>Rotor-wake interaction</h3>
<p>The rear rotor ingests turbulence confined to the front-rotor wakes. The turbulence intensity has a Gaussian profile across each wake (semi-width L_w), repeated with the front-rotor pitch s₁, and is frozen in the fluid. The upwash spectrum seen by a rear-rotor strip is</p>
<div class="eq">Φ(K₁, k_y) = Σ_m |E_m|² Φ_s(K₁ − m B₁(Ω₁+Ω₂)/U, k_y),   |E_m|² = w_c² (π/a)/s₁² exp(−2π²m²/(a s₁²)),  a = ln2/(2 L_w²)
passage-averaged TKE = centreline TKE · (L_w/s₁) √(π/ln2)</div>
<p>Φ_s is the von Kármán or Liepmann spectrum of unit variance. The passage-averaged model keeps only the mean square in a homogeneous spectrum.</p>
<h3>Wall-pressure models and boundary layer inputs</h3>
<p>Amiet (1976), Chase–Howe (1998), Goody (2004), Rozenberg et al. (2012), Kamruzzaman et al. (2015), Lee (2018) and the VKI gene-expression-programming model of Dominique, Christophe, Schram &amp; Sandberg (JSV 506, 2021):</p>
<div class="eq">Φ Uₑ/(τ_w² δ*) = (5.41 + C_f(β_C+1)^5.41) ω̃ / (ω̃² + ω̃ + (β_C+1) M + (ω̃+3.6) ω̃^4.76 / (C_f R_T^5.83)),   ω̃ = ωδ*/Uₑ</div>
<p>Boundary layers come from the BPM NACA 0012 correlations, a 1/7-power flat plate, or user input (δ*/c, δ/c, θ/c, H, C_f, β_C, Uₑ/U per side). Missing parameters follow Ludwieg–Tillmann (C_f), Drela (δ) and Durbin–Reif (Π). Spanwise coherence follows Corcos, l_y = b_c U_c/ω.</p>
<h3>Conventions</h3>
<p>Output spectra are one-sided PSDs per hertz, in dB re (20 µPa)²/Hz. Blades are assumed statistically independent, so levels add as 10 log₁₀ B. Interaction and self noise are uncorrelated, so their energies add in the combined spectra.</p>`;

/* ================================================================== boot */
function showTab(name) {
  $$('.tabs button').forEach((x) => x.setAttribute('aria-selected', x.dataset.tab === name));
  $$('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${name}`));
  if (state.result && ['interaction', 'self', 'combined'].includes(name)) renderAll();
}

async function boot() {
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  $('#theory').innerHTML = THEORY;
  state.cards.int = spectrumCard($('#int-spec'), 'BRWI · interaction noise');
  state.cards.self = spectrumCard($('#self-spec'), 'BRTE · self noise');
  state.cards.combo = spectrumCard($('#combo-spec'), 'BRWI + BRTE');
  for (const k of ['int', 'self', 'combo']) state.cards[k].update(null);
  state.cards.intStrips = stripCard($('#int-strips'));
  state.cards.selfStrips = stripCard($('#self-strips'));
  state.cards.intStrips.update(null); state.cards.selfStrips.update(null);
  for (const id of ['#int-dir-card', '#self-dir-card', '#combo-dir-card', '#int-turb-card', '#self-wps-card', '#self-bl-card', '#self-bldist-card']) $(id).style.display = 'none';
  $('#run').addEventListener('click', run);
  $('#verify-run').addEventListener('click', runVerify);
  $('#json-apply').addEventListener('click', () => {
    try { state.case = normaliseCase(JSON.parse($('#case-json').value)); buildInputs(); syncJson(); $('#json-msg').textContent = 'applied'; }
    catch (e) { $('#json-msg').textContent = 'invalid JSON: ' + e.message; }
  });
  $('#dl-json').addEventListener('click', () => download(`${state.case.key || 'case'}.json`, JSON.stringify(state.result, null, 1), 'application/json'));
  $('#dl-csv').addEventListener('click', () => {
    const r = state.result;
    const cols = [...(state.comboItems || []).map((it) => ({ label: it.label, psd: it.psd })), ...r.curves.map((c) => ({ label: c.label, psd: c.psd_db }))];
    const rows = [['f_Hz', ...cols.map((c) => `"${c.label}"`)].join(',')];
    r.f.forEach((f, i) => rows.push([f, ...cols.map((c) => c.psd[i] ?? '')].join(',')));
    download(`${state.case.key || 'case'}_psd.csv`, rows.join('\n'), 'text/csv');
  });
  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderAll, 150); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll);

  await backend.init();
  const m = await backend.call('meta', []);
  if (!m.ok) { setRuntime('API error: ' + m.error, 1, 'err'); return; }
  state.meta = m;
  $('#case-select').replaceChildren(...m.cases.map((c) => h('option', { value: c.key }, c.name)));
  $('#case-select').addEventListener('change', (e) => loadCase(e.target.value));
  await loadCase(m.cases[0].key);
  $('#run').disabled = false; $('#verify-run').disabled = false;
}
boot();
