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
    this.worker = new Worker('web/worker.js?v=2');
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
  $('.dir-note', card).textContent = state.case.type === 'rotor' ? 'polar angle from the upstream (flight) axis' : 'angle from the downstream chord line';
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
  const d = state.meta.defaults;
  c.options = Object.assign({}, d.options, c.options || {});
  c.frequency = Object.assign({}, d.frequency, c.frequency || {});
  c.observers = c.observers || { R: c.type === 'rotor' ? 10 : 1, theta_deg: [90] };
  c.observers.theta_deg = asList(c.observers.theta_deg);
  if (c.type !== 'rotor') {
    const orig = c.type;
    c.type = 'airfoil';
    if (c.turbulence) { if (c.turbulence.enabled === undefined) c.turbulence.enabled = orig !== 'airfoil_te'; }
    else c.turbulence = { enabled: false, spectrum: ['vonkarman'], tke: 1.5 * (0.03 * c.airfoil.U) ** 2, Lambda: 0.03 };
    if (c.self_noise) { if (c.self_noise.enabled === undefined) c.self_noise.enabled = orig !== 'airfoil_le'; }
    else c.self_noise = { enabled: false, models: ['goody'], boundary_layer: structuredClone(BPM_BL) };
    c.turbulence.spectrum = asList(c.turbulence.spectrum);
  } else {
    c.formulations = asList(c.formulations || ['full', 'simplified']);
    if (!c.self_noise) c.self_noise = { enabled: false, models: ['goody'], boundary_layer: structuredClone(BPM_BL) };
    if (c.self_noise.enabled === undefined) c.self_noise.enabled = true;
    if (c.rotors.length >= 2) {
      if (!c.rwi) c.rwi = { enabled: false, front: c.rotors[0].name, rear: c.rotors[1].name, spectrum: ['vonkarman'], wake: { tu_c: 0.05, Lw_over_s: 0.08, Lambda_over_Lw: 0.42, model: 'periodic' } };
      if (c.rwi.enabled === undefined) c.rwi.enabled = true;
      c.rwi.spectrum = asList(c.rwi.spectrum);
      c.rwi.wake = c.rwi.wake || {};
    }
    if (!c.ingestion) c.ingestion = { enabled: false, spectrum: ['vonkarman'], intensity: 0.02, Lambda: 0.5 };
    if (c.ingestion.enabled === undefined) c.ingestion.enabled = true;
    c.ingestion.spectrum = asList(c.ingestion.spectrum);
  }
  const sn = c.self_noise;
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
function frontRotor() { const c = state.case; return c.rotors.find((r) => r.name === c.rwi.front) || c.rotors[0]; }

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
  const w = state.case.rwi.wake;
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
      lk === 'tke_c' ? num('Centreline TKE k_c', 'rwi.wake.tke_c', { unit: 'm²/s²', onchange: refresh })
        : lk === 'tke_mean' ? num('Passage-averaged TKE', 'rwi.wake.tke_mean', { unit: 'm²/s²', onchange: refresh })
          : num('Centreline intensity w_c / U₁', 'rwi.wake.tu_c', { onchange: refresh }),
      num('Wake semi-width / front pitch', 'rwi.wake.Lw_over_s', { onchange: refresh }),
      choose('Integral length scale given as', mk, [['Lambda', 'Λ in metres'], ['Lambda_over_Lw', 'Λ / wake semi-width']], (nk) => {
        const r = ref();
        const lam = scalarAt(w.Lambda) ?? (w.Lambda_over_Lw ?? 0.42) * r.Lw;
        delete w.Lambda; delete w.Lambda_over_Lw;
        if (nk === 'Lambda') w.Lambda = +lam.toPrecision(4); else w.Lambda_over_Lw = +(lam / r.Lw).toPrecision(4);
        syncJson(); build();
      }),
      mk === 'Lambda' ? num('Integral length scale Λ', 'rwi.wake.Lambda', { unit: 'm', onchange: refresh })
        : num('Λ / wake semi-width', 'rwi.wake.Lambda_over_Lw', { onchange: refresh }),
      pick('Wake turbulence model', 'rwi.wake.model', [['periodic', 'periodic wakes'], ['averaged', 'passage-averaged'], [['periodic', 'averaged'], 'both']]),
      hint);
    refresh();
  };
  build();
  return box;
}

/* boundary layer inputs: BPM / flat plate / user table */
const BL_ROWS = [['delta_star_over_c', 'δ*/c', false], ['delta_over_c', 'δ/c', true], ['theta_over_c', 'θ/c', true], ['H', 'H = δ*/θ', true],
  ['cf', 'C_f', true], ['beta_c', 'β_C = (θ/τ_w) dp/dx', true], ['Ue_over_U', 'Uₑ/U', true]];

function blInputs() {
  const box = h('div');
  const msg = h('p', { class: 'muted' });
  const build = () => {
    const bl = state.case.self_noise.boundary_layer;
    const kids = [pick('Boundary layer from', 'self_noise.boundary_layer.method', [['bpm', 'BPM NACA 0012 correlations'], ['flat_plate', 'flat plate (1/7 power law)'], ['user', 'user input']], async () => {
      const b = state.case.self_noise.boundary_layer;
      if (b.method === 'user' && !b.suction) await prefill(structuredClone(BPM_BL));
      if (b.method === 'bpm') Object.assign(b, { ...BPM_BL, ...b, H: b.H ?? [1.4, 1.4], beta_c: b.beta_c ?? [0, 0] });
      syncJson(); build();
    })];
    if (bl.method === 'bpm') {
      if (!Array.isArray(bl.H)) bl.H = [1.4, 1.4];
      if (!Array.isArray(bl.beta_c)) bl.beta_c = [0, 0];
      kids.push(num('Angle of attack', 'self_noise.boundary_layer.alpha_deg', { unit: 'deg' }),
        pick('Transition', 'self_noise.boundary_layer.tripped', [[true, 'tripped'], [false, 'natural (untripped)']]),
        blTable([['H', 'H = δ*/θ', 'self_noise.boundary_layer.H.0', 'self_noise.boundary_layer.H.1'],
          ['beta_c', 'β_C = (θ/τ_w) dp/dx', 'self_noise.boundary_layer.beta_c.0', 'self_noise.boundary_layer.beta_c.1']]));
    } else if (bl.method === 'user') {
      kids.push(blTable(BL_ROWS.map(([k, lab]) => [k, lab, `self_noise.boundary_layer.suction.${k}`, `self_noise.boundary_layer.pressure.${k}`]), true),
        h('div', { class: 'row' }, h('button', { class: 'ghost', onclick: async () => { await prefill(structuredClone(BPM_BL)); build(); } }, 'Fill from BPM correlations'), msg),
        h('p', { class: 'muted' }, 'Lengths are ratios to the local chord, so they scale along a rotor blade. Blank fields are estimated: H = 1.4, C_f from Ludwieg–Tillmann, δ from Drela, Π from Durbin–Reif. δ* may be replaced by θ/c with H.'));
    }
    box.replaceChildren(...kids);
  };
  async function prefill(spec) {
    msg.textContent = 'estimating…';
    const c = structuredClone(state.case);
    c.self_noise.boundary_layer = spec;
    const r = await backend.call('estimate_bl', [JSON.stringify(c)]);
    if (!r.ok) { msg.textContent = r.error; return; }
    const b = state.case.self_noise.boundary_layer;
    for (const side of ['suction', 'pressure']) {
      const v = r.sides[side];
      // delta/c is left blank so that it follows delta* and H (Drela) when the user edits them
      b[side] = { delta_star_over_c: +v.delta_star_over_c.toPrecision(4), H: +v.H.toPrecision(4), beta_c: +v.beta_c.toPrecision(4), Ue_over_U: 1 };
    }
    msg.textContent = `filled from BPM at ${r.where}`;
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

function buildInputs() {
  const c = state.case;
  const wpsOpts = state.meta.wps_models.map((m) => [m.key, ({ dominique_gep: 'VKI GEP', chase_howe: 'Chase–Howe', amiet: 'Amiet' })[m.key] || m.key[0].toUpperCase() + m.key.slice(1)]);
  const cards = [];
  // configuration
  if (c.type === 'rotor') {
    cards.push(card('Configuration', `${c.rotors.length === 2 ? 'Contra-rotating pair: the rear rotor ingests the front-rotor wakes.' : 'Isolated rotor.'} Blade chord distributions are edited in the JSON.`,
      ...c.rotors.map((r, i) => fs(`Rotor: ${r.name}`, num('Blades B', `rotors.${i}.B`, { int: true }), num('Speed', `rotors.${i}.rpm`, { unit: 'rpm' }),
        num('Tip radius', `rotors.${i}.r_tip`, { unit: 'm' }), num('Hub radius', `rotors.${i}.r_hub`, { unit: 'm' }),
        num('Axial velocity through the disc', `rotors.${i}.Ux`, { unit: 'm/s' }), num('Radial strips', `rotors.${i}.n_strips`, { int: true })))));
  } else {
    cards.push(card('Configuration', 'Stationary flat plate (Amiet).', num('Chord', 'airfoil.chord', { unit: 'm' }), num('Span', 'airfoil.span', { unit: 'm' }), num('Free-stream velocity U', 'airfoil.U', { unit: 'm/s' })));
  }
  // interaction noise
  const inter = [];
  if (c.type === 'rotor' && c.rwi) {
    const body = h('div', {}, checks('rwi.spectrum', SPECTRA), wakeInputs());
    inter.push(fs('Rotor-wake interaction (rear rotor)', enable('enabled', 'rwi.enabled', body), body));
  }
  if (c.type === 'rotor') {
    const body = h('div', {}, checks('ingestion.spectrum', SPECTRA), homogeneousInputs('ingestion'));
    inter.push(fs(`Inflow turbulence ingestion (${(c.ingestion.rotors || [c.rotors[0].name]).join(', ')} rotor)`, enable('enabled', 'ingestion.enabled', body), body));
  } else {
    const body = h('div', {}, checks('turbulence.spectrum', SPECTRA), homogeneousInputs('turbulence'),
      pick('LE response', 'options.le_method', [['auto', 'Amiet switch (auto)'], ['high', 'high frequency'], ['low', 'low frequency']]));
    inter.push(fs('Leading-edge turbulence interaction', enable('enabled', 'turbulence.enabled', body), body));
  }
  cards.push(card('Interaction noise', 'Isotropic turbulence: k = 3 w_rms² / 2. The integral length scale Λ sets the spectral peak.', ...inter));
  // self noise
  const sbody = h('div', {}, h('div', { class: 'lbl' }, 'Wall-pressure models'), checks('self_noise.models', wpsOpts), blInputs(),
    num('Convection velocity Uc/Uₑ', 'self_noise.Uc_over_Ue'), num('Corcos constant b_c', 'self_noise.b_c'));
  cards.push(card('Self noise (trailing edge)', 'Turbulent boundary layers on both sides of the trailing edge, Amiet (1976) with Roger & Moreau back-scattering.',
    enable('enabled', 'self_noise.enabled', sbody), sbody));
  // observer & numerics
  const thetaInp = h('input', { value: asList(c.observers.theta_deg).join(', '), 'aria-label': 'Polar angles' });
  thetaInp.addEventListener('change', () => {
    const v = thetaInp.value.split(/[ ,;]+/).map(parseFloat).filter(isFinite);
    if (v.length) { c.observers.theta_deg = v; syncJson(); }
  });
  const numerics = [num('Distance R', 'observers.R', { unit: 'm' }), fieldRow('Polar angles (first = spectra)', thetaInp, 'deg'),
    num('f min', 'frequency.f_min', { unit: 'Hz' }), num('f max', 'frequency.f_max', { unit: 'Hz' }), num('Frequency points', 'frequency.n', { int: true })];
  if (c.type === 'rotor') numerics.push(fs('Formulation', checks('formulations', [['full', 'Full (rotating dipole)'], ['simplified', 'Simplified (Amiet)']]),
    num('Doppler exponent (simplified)', 'options.doppler_exponent'), num('Azimuth points (simplified)', 'options.n_psi', { int: true })));
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
  rozenberg: 'Rozenberg', kamruzzaman: 'Kamruzzaman', lee: 'Lee', dominique_gep: 'VKI GEP' };
const prettyVariant = (v) => v.replace(/^[a-z_]+/, (k) => PRETTY[k] || k);
const idKey = (c) => `${c.rotor}|${c.mechanism}|${c.variant}`;
function itemsFor(curves) {
  const ids = [...new Set(curves.map(idKey))];
  return curves.map((c) => {
    const i = ids.indexOf(idKey(c));
    return { label: c.label, color: i < SLOTS.length ? cssVar(SLOTS[i]) : cssVar('--muted'), dash: c.formulation === 'simplified' ? '6 4' : null,
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
  state.cards.int.update({ f: res.f, items, title: `Interaction noise ${titleAt(res)}`, empty: 'No interaction-noise mechanism was enabled. Enable one on the Inputs tab and run again.' });
  directivity($('#int-dir-card'), $('#int-dir'), items);
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
  state.cards.self.update({ f: res.f, items, title: `Self noise ${titleAt(res)}`, empty: 'Self noise was not enabled. Enable it on the Inputs tab and run again.' });
  directivity($('#self-dir-card'), $('#self-dir'), items);
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
    const series = Object.entries(models).map(([m, y], i) => ({ label: ({ dominique_gep: 'VKI GEP', chase_howe: 'Chase–Howe', amiet: 'Amiet' })[m] || m[0].toUpperCase() + m.slice(1),
      x: res.f, y, color: cssVar(SLOTS[i % SLOTS.length]) }));
    lineChart($('#self-wps'), series, { xlog: true, xlabel: 'Frequency [Hz]', ylabel: 'Φ_pp [dB re (20 µPa)²/Hz]', unit: 'dB', digits: 3, xfmt: (v) => `${fmtF(v)}Hz`, yFloorSpan: 70 });
    legend($('#self-wps-legend'), series, () => {});
  };
  sel.onchange = draw;
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
  if (!state.combo) state.combo = { pick: Object.fromEntries(Object.entries(groups).map(([k, g]) => [k, g.variants[0]])), forms: new Set(forms) };
  const combo = state.combo;
  const nice = prettyVariant;
  const pk = $('#combo-pickers');
  pk.replaceChildren(...[...Object.entries(groups).map(([k, g]) => {
    const sel = h('select', { 'aria-label': k }, h('option', { value: '__off', selected: combo.pick[k] === '__off' }, 'exclude'),
      ...g.variants.map((v) => h('option', { value: v, selected: combo.pick[k] === v }, nice(v))));
    sel.addEventListener('change', () => { combo.pick[k] = sel.value; renderCombined(res); });
    return h('div', {}, h('label', {}, `${g.rotor === 'airfoil' ? '' : g.rotor + ': '}${g.mechanism}`), sel);
  }), forms.length > 1 ? h('div', {}, h('label', {}, 'Formulation'), h('div', { class: 'checks' }, ...forms.map((f) => {
    const cb = h('input', { type: 'checkbox', checked: combo.forms.has(f) });
    cb.addEventListener('change', () => { cb.checked ? combo.forms.add(f) : combo.forms.delete(f); renderCombined(res); });
    return h('label', {}, cb, f);
  }))) : null].filter(Boolean));
  const items = [], stats = [];
  for (const f of forms.filter((x) => combo.forms.has(x))) {
    const chosen = res.curves.filter((c) => c.formulation === f && combo.pick[`${c.rotor}|${c.mechanism}`] === c.variant);
    const inter = sumCurves(chosen.filter((c) => c.category === 'interaction'));
    const self = sumCurves(chosen.filter((c) => c.category === 'self'));
    const tot = sumCurves(chosen);
    const dash = f === 'simplified' ? '6 4' : null;
    const tag = forms.length > 1 ? ` - ${f}` : '';
    if (tot) items.push({ label: `total (interaction + self)${tag}`, color: cssVar('--s1'), dash, wide: true, ...tot });
    if (inter) items.push({ label: `interaction noise${tag}`, color: cssVar('--s2'), dash, ...inter });
    if (self) items.push({ label: `self noise${tag}`, color: cssVar('--s3'), dash, ...self });
    if (tot) stats.push([`Total${tag}`, `${tot.oaspl.toFixed(1)} dB`, 'OASPL, interaction + self']);
    if (inter && self) stats.push([`Interaction − self${tag}`, `${(inter.oaspl - self.oaspl).toFixed(1)} dB`, `${inter.oaspl.toFixed(1)} dB vs ${self.oaspl.toFixed(1)} dB`]);
  }
  state.comboItems = items;
  state.cards.combo.update({ f: res.f, items, title: `Interaction and self noise ${titleAt(res)}`, empty: 'Nothing selected.' });
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
      el.append(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, ...['r [m]', 'dr [m]', 'chord [m]', 'U [m/s]', 'ψ [deg]', 'M'].map((x) => h('th', {}, x)))),
        h('tbody', {}, ...r.strips.map((st) => h('tr', {}, ...[st.r, st.dr, st.chord, st.U, st.psi_deg, st.M].map((v) => h('td', { class: 'num' }, fmt(v, 4)))))))));
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
  state.cards.int = spectrumCard($('#int-spec'), 'Interaction noise');
  state.cards.self = spectrumCard($('#self-spec'), 'Self noise');
  state.cards.combo = spectrumCard($('#combo-spec'), 'Interaction and self noise');
  for (const k of ['int', 'self', 'combo']) state.cards[k].update(null);
  for (const id of ['#int-dir-card', '#self-dir-card', '#combo-dir-card', '#int-turb-card', '#self-wps-card', '#self-bl-card']) $(id).style.display = 'none';
  $('#run').addEventListener('click', run);
  $('#verify-run').addEventListener('click', runVerify);
  $('#json-apply').addEventListener('click', () => {
    try { state.case = normaliseCase(JSON.parse($('#case-json').value)); buildInputs(); $('#json-msg').textContent = 'applied'; }
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
