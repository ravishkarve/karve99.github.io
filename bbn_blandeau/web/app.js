/* Blandeau Broadband Noise - dashboard.
 * Three input sections (rotor, noise model, spectra) edit one case object; Run sends it to the
 * Python solver (local `bbn serve` API when available, otherwise Pyodide in a Web Worker). */
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
const P2 = 4e-10;
const dB = (x, ref = P2) => (x > 0 ? 10 * Math.log10(x / ref) : null);

/* ================================================================== backend */
const backend = {
  mode: null, worker: null, id: 0, pending: new Map(), readyResolve: null, ready: null,
  async init() {
    this.ready = new Promise((r) => { this.readyResolve = r; });
    try {
      const r = await fetch('api/ping', { cache: 'no-store' });
      if (r.ok && (await r.json()).server === 'bbn') {
        this.mode = 'server';
        setRuntime('Local bbn server (native NumPy)', 1, 'ok');
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
      else if (m.type === 'result') { const p = this.pending.get(m.id); this.pending.delete(m.id); if (p) p.resolve(m.payload); }
    };
  },
  async call(fn, args = []) {
    await this.ready;
    if (this.mode === 'server') {
      const r = await fetch('api/' + fn, { method: 'POST', body: JSON.stringify(args) });
      return r.json();
    }
    const id = ++this.id;
    return new Promise((resolve) => { this.pending.set(id, { resolve }); this.worker.postMessage({ type: 'call', id, fn, args }); });
  },
};

function setRuntime(text, progress, cls) {
  $('#rt-text').textContent = text;
  $('#rt-bar').style.width = `${Math.round((progress || 0) * 100)}%`;
  $('#rt-dot').className = 'dot ' + (cls || '');
  if (cls === 'ok') $('#run').disabled = false;
}

/* ================================================================== charts */
const SLOTS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const color = (i) => cssVar(SLOTS[i % SLOTS.length]);

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
  if (!series.length) { el.append(h('div', { class: 'empty' }, o.empty || 'No data.')); return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 360;
  const m = { l: 56, r: 16, t: 12, b: 42 };
  const xs = series.flatMap((d) => d.x).filter((v) => isFinite(v) && (!o.xlog || v > 0));
  const ys = (vis.length ? vis : series).flatMap((d) => d.y).filter((v) => v !== null && isFinite(v));
  if (!xs.length || !ys.length) { el.append(h('div', { class: 'empty' }, 'No data.')); return; }
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (o.yFloorSpan) y0 = Math.max(y0, y1 - o.yFloorSpan);
  const pad = (y1 - y0) * 0.06 || 1; y0 -= pad; y1 += pad;
  if (x1 === x0) { x0 = x0 * 0.9 || -1; x1 = x1 * 1.1 || 1; }
  const X = o.xlog ? (v) => m.l + (Math.log10(v) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) * (W - m.l - m.r)
                   : (v) => m.l + (v - x0) / ((x1 - x0) || 1) * (W - m.l - m.r);
  const Y = (v) => m.t + (y1 - v) / ((y1 - y0) || 1) * (H - m.t - m.b);
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.ylabel || 'chart' });
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
        return h('div', { class: 'r' }, key, h('span', { class: 'v' }, `${(+v).toFixed(1)} ${o.unit || ''}`), h('span', { class: 'n' }, d.label));
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

/** Chart + legend whose entries can be hidden. */
function toggleChart(chartEl, legEl, opts0) {
  const hidden = new Set();
  let series = [], opts = opts0;
  const draw = () => {
    const ss = series.map((d) => ({ ...d, hidden: hidden.has(d.label) }));
    lineChart(chartEl, ss, opts);
    legend(legEl, ss, (i) => { const l = series[i].label; hidden.has(l) ? hidden.delete(l) : hidden.add(l); draw(); });
  };
  return { update(s2, o2) { series = s2; if (o2) opts = o2; draw(); }, redraw: draw };
}

/** 1/3-octave band levels (bands wholly inside the computed range), from a linear PSD per Hz. */
function thirdOctave(f, psd) {
  const out = { fc: [], spl: [] };
  const lf = f.map(Math.log), lp = psd.map((v) => Math.log(Math.max(v, 1e-300)));
  const interp = (x) => {
    let i = 1; while (i < lf.length - 1 && lf[i] < x) i++;
    const t = (x - lf[i - 1]) / (lf[i] - lf[i - 1]);
    return Math.exp(lp[i - 1] + t * (lp[i] - lp[i - 1]));
  };
  for (let k = -30; k <= 30; k++) {
    const fc = 1000 * 2 ** (k / 3), lo = fc * 2 ** (-1 / 6), hi = fc * 2 ** (1 / 6);
    if (lo < f[0] * (1 - 1e-9) || hi > f[f.length - 1] * (1 + 1e-9)) continue;
    const n = 100; let sum = 0, prev = null, pf = null;
    for (let j = 0; j <= n; j++) {
      const ff = lo * (hi / lo) ** (j / n), v = interp(Math.log(ff));
      if (prev !== null) sum += 0.5 * (v + prev) * (ff - pf);
      prev = v; pf = ff;
    }
    out.fc.push(fc); out.spl.push(dB(sum));
  }
  return out;
}

/* ================================================================== case state */
const STORE = 'bbn-case-v1';
const state = { case: null, defaults: null, result: null, theta: 0, view: 'psd' };
const getPath = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
function setPath(obj, path, v) {
  const ks = path.split('.'); let o = obj;
  for (const k of ks.slice(0, -1)) { if (o[k] == null || typeof o[k] !== 'object') o[k] = {}; o = o[k]; }
  o[ks[ks.length - 1]] = v;
}
const get = (p) => getPath(state.case, p);
function set(p, v, rebuild = false) {
  setPath(state.case, p, v);
  try { localStorage.setItem(STORE, JSON.stringify(state.case)); } catch (e) { /* storage unavailable */ }
  if (rebuild) buildInputs();
}
const clone = (x) => JSON.parse(JSON.stringify(x));

/* ================================================================== input widgets */
const card = (title, sub, ...kids) => h('div', { class: 'panel card' }, h('h2', {}, title), sub ? h('p', { class: 'sub' }, sub) : null, ...kids);
const fs = (title, ...kids) => h('fieldset', {}, h('legend', {}, title), ...kids);
const row = (label, input, unit) => h('div', { class: 'f' }, h('label', {}, label, unit ? h('span', { class: 'unit' }, ` [${unit}]`) : null), input);

function num(label, path, o = {}) {
  const v = get(path);
  const inp = h('input', { type: 'number', step: o.step || 'any', value: v ?? '', min: o.min,
    onchange: (e) => { const x = e.target.value === '' ? undefined : +e.target.value; set(path, o.int ? Math.round(x) : x, o.rebuild); } });
  return row(label, inp, o.unit);
}
function sel(label, path, options, o = {}) {
  const v = get(path) ?? options[0][0];
  const el = h('select', { onchange: (e) => set(path, isNaN(+e.target.value) || o.text ? e.target.value : +e.target.value, o.rebuild !== false) },
    ...options.map(([k, t]) => h('option', { value: k, selected: String(k) === String(v) }, t)));
  return row(label, el, o.unit);
}
function chk(label, path, o = {}) {
  const inp = h('input', { type: 'checkbox', checked: !!get(path), disabled: o.disabled,
    onchange: (e) => set(path, e.target.checked, o.rebuild !== false) });
  return h('label', { class: 'chk' + (o.disabled ? ' dis' : '') }, inp, label, o.note ? h('span', { class: 'muted' }, ` ${o.note}`) : null);
}
function listField(label, path, unit) {
  const v = get(path) || [];
  const inp = h('input', { value: v.join(', '), onchange: (e) => set(path, e.target.value.split(/[ ,;]+/).filter((x) => x !== '').map(Number)) });
  return row(label, inp, unit);
}

function pickFile(accept = '.csv,.tsv,.txt,.dat') {
  return new Promise((resolve) => {
    const inp = h('input', { type: 'file', accept, style: 'display:none' });
    inp.addEventListener('change', async () => resolve(inp.files[0] ? await inp.files[0].text() : null));
    document.body.append(inp); inp.click(); setTimeout(() => inp.remove(), 60000);
  });
}
function download(name, text, type = 'text/plain') {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}

/** Editable columnar table stored at `path` as {column: [values]}. cols: [[key, header]]. */
function tableEditor(path, cols, kind, o = {}) {
  const wrap = h('div');
  const msg = h('p', { class: 'note' });
  const draw = () => {
    const t = get(path);
    if (typeof t === 'string') {
      wrap.replaceChildren(h('p', { class: 'note' }, `Read from file "${t}" when run from the command line. Load the file here to edit it.`));
      return;
    }
    const tab = t || {};
    const n = Math.max(0, ...cols.map(([k]) => (tab[k] || []).length));
    const head = h('tr', {}, h('th', {}, '#'), ...cols.map(([, t2]) => h('th', {}, t2)));
    const body = [...Array(n).keys()].map((i) => h('tr', {}, h('td', { class: 'muted' }, i + 1), ...cols.map(([k]) => h('td', {},
      h('input', { type: 'number', step: 'any', value: tab[k] && tab[k][i] !== undefined ? +(+tab[k][i]).toPrecision(6) : '',
        onchange: (e) => { const tt = clone(get(path) || {}); (tt[k] = tt[k] || [])[i] = +e.target.value; set(path, tt); } })))));
    wrap.replaceChildren(h('div', { class: 'table-wrap grid-wrap' }, h('table', { class: 'grid' }, h('thead', {}, head), h('tbody', {}, ...body))));
  };
  const addRow = () => { const tt = clone(get(path) || {}); for (const [k] of cols) { const a = tt[k] || (tt[k] = []); a.push(a.length ? a[a.length - 1] : 0); } set(path, tt); draw(); };
  const delRow = () => { const tt = clone(get(path) || {}); for (const [k] of cols) if (tt[k] && tt[k].length) tt[k].pop(); set(path, tt); draw(); };
  const load = async () => {
    const text = await pickFile(); if (!text) return;
    const r = await backend.call('parse_table', [kind, text]);
    if (!r.ok) { msg.textContent = r.error; msg.className = 'err'; return; }
    const tt = {}; for (const [k] of cols) if (r.table[k]) tt[k] = r.table[k];
    set(path, tt); msg.textContent = `Loaded ${(tt[cols[0][0]] || []).length} rows.`; msg.className = 'note'; draw(); if (o.onload) o.onload();
  };
  const tmpl = async () => { const r = await backend.call('template', [kind]); if (r.ok) download(`${kind}_template.txt`, r.text); };
  draw();
  return h('div', {}, wrap, h('div', { class: 'row' },
    h('button', { class: 'ghost tiny', onclick: addRow, title: 'add a row' }, '+ row'),
    h('button', { class: 'ghost tiny', onclick: delRow, title: 'remove the last row' }, '− row'),
    h('button', { class: 'ghost', onclick: load }, 'Load file…'),
    h('button', { class: 'ghost', onclick: tmpl }, 'Template')), msg);
}

/* ================================================================== section 1: rotor */
const BLADE_COLS = [['r', 'r [m]'], ['chord', 'chord [m]'], ['stagger_deg', 'stagger [deg]']];

function rotorCard(which) {
  const p = `rotor.${which}`;
  const two = +get('rotor.stages') === 2;
  if (which === 'rear' && !two) return card('Rear rotor', 'Not used: the rotor has one stage.');
  if (!get(p)) set(p, clone(state.defaults.rotor[which]));
  const om = get(`${p}.rpm`) ?? (get(`${p}.omega`) ? get(`${p}.omega`) * 30 / Math.PI : '');
  return card(which === 'front' ? 'Front rotor' : 'Rear rotor',
    'Blade geometry from hub to tip. Stagger is measured from the rotor axis. Strips are placed at equal fractions of the span.',
    fs('Rotor', num('Blades', `${p}.blades`, { int: true, min: 1 }),
      row('Speed', h('input', { type: 'number', step: 'any', value: om, onchange: (e) => { const q = clone(get(p)); delete q.omega; q.rpm = +e.target.value; set(p, q); } }), 'rpm')),
    fs('Blade table', tableEditor(`${p}.blade`, BLADE_COLS, 'blade')));
}

function buildRotor() {
  $('#cards-rotor').replaceChildren(
    card('Operating point', 'Flight condition and rotor arrangement.',
      fs('Rotor', sel('Stages', 'rotor.stages', [[2, '2 · contra-rotating pair'], [1, '1 · single rotor']]),
        num('Axial gap between rotors', 'rotor.gap', { unit: 'm' }), num('Scale factor', 'rotor.scale')),
      fs('Flight and air', num('Flight Mach number', 'rotor.mach'), num('Speed of sound c₀', 'rotor.c0', { unit: 'm/s' }),
        num('Air density ρ', 'rotor.rho', { unit: 'kg/m³' }))),
    rotorCard('front'), rotorCard('rear'));
}

/* ================================================================== section 2: noise model */
function buildModel() {
  const two = +get('rotor.stages') === 2;
  const selfs = new Set(get('noise_model.self_noise') || []);
  const setSelf = (r, on) => { on ? selfs.add(r) : selfs.delete(r); set('noise_model.self_noise', ['front', 'rear'].filter((x) => selfs.has(x)), true); };
  const selfChk = (r, label, dis) => h('label', { class: 'chk' + (dis ? ' dis' : '') },
    h('input', { type: 'checkbox', checked: selfs.has(r) && !dis, disabled: dis, onchange: (e) => setSelf(r, e.target.checked) }), label);
  const ing = !!get('noise_model.bl_ingestion');
  const simplified = get('noise_model.formulation') === 'simplified';
  $('#cards-model').replaceChildren(
    card('Noise sources', 'Choose the mechanisms and rotors to model.',
      fs('Rotor-wake interaction (BRWI)', chk('Rear rotor in the front-rotor wakes', 'noise_model.interaction', { disabled: !two, note: two ? '' : '(needs two rotors)' }),
        h('p', { class: 'note' }, 'Full rotational formulation (thesis ch. 2).')),
      fs('Trailing-edge self noise (BRTE)', selfChk('front', 'Front rotor', false), selfChk('rear', 'Rear rotor', !two)),
      fs('Installation', chk('Front rotor ingesting a wall boundary layer', 'noise_model.bl_ingestion'),
        h('p', { class: 'note' }, 'Amiet\'s simplified formulation with an image source for the hard wall.'))),
    card('Formulation and strips', null,
      fs('Trailing-edge noise', sel('Formulation', 'noise_model.formulation', [['full', 'Full rotational (thesis eq. 3.18)'], ['simplified', 'Simplified, Amiet (thesis eq. 5.7)']], { text: true }),
        simplified || ing ? num('Azimuthal integration points', 'noise_model.azimuth_points', { int: true, min: 4 }) : null),
      fs('Discretisation', num('Radial strips', 'noise_model.strips', { int: true, min: 1 }),
        sel('Stream-tube contraction at the rear rotor', 'noise_model.contraction_percent', [[100, '100 %'], [0, '0 %']])),
      fs('Corrections', chk('Chapman mean-flow correction', 'noise_model.chapman', { note: simplified ? '(always on for the simplified formulation)' : '' }),
        chk('Results in emission co-ordinates', 'noise_model.emission_angle'))),
    card('Observers and frequencies', 'Polar angles θ* from the upstream (flight) axis, on an arc of the given radius.',
      fs('Observers', listField('Polar angles θ*', 'noise_model.observers.theta_deg', 'deg'), num('Observer radius', 'noise_model.observers.radius', { unit: 'm' })),
      fs('Frequencies (log-spaced)', num('Lowest', 'noise_model.frequency.min', { unit: 'Hz' }), num('Highest', 'noise_model.frequency.max', { unit: 'Hz' }),
        num('Number', 'noise_model.frequency.n', { int: true, min: 1 }))),
    card('Boundary-layer ingestion', ing ? null : 'Enable the source to use these settings.',
      h('div', { class: ing ? '' : 'disabled-body' },
        fs('Wall', num('Wall distance from the hub centre', 'noise_model.ingestion.wall_distance', { unit: 'm' }),
          num('Boundary-layer height', 'noise_model.ingestion.bl_height', { unit: 'm' }),
          chk('Hard wall (image source)', 'noise_model.ingestion.hard_wall', { rebuild: false }),
          chk('Partial loading (blades loaded only inside the boundary layer)', 'noise_model.ingestion.partial_loading', { rebuild: false }),
          chk('Blade-to-blade correlation', 'noise_model.ingestion.blade_correlation', { rebuild: false })))));
}

/* ================================================================== section 3: spectra */
const WP = [['rozenberg', 'Rozenberg'], ['willmarth_amiet', 'Willmarth–Roos–Amiet'], ['chase_howe', 'Chase–Howe'], ['goody', 'Goody'], ['kim_george', 'Kim–George'], ['vki', 'VKI (gene-expression programming)']];
const UC_FULL = [['del_alamo_fit', 'del Alamo fit'], ['del_alamo', 'del Alamo'], ['gliebe', 'Gliebe'], ['constant', 'U_c = 0.8 U']];
const UC_SIMPLE = [['gliebe', 'Gliebe'], ['del_alamo', 'del Alamo'], ['constant', 'U_c = 0.8 U']];
const LR_FULL = [['salze', 'Salze'], ['corcos', 'Corcos'], ['corcos_delta', 'Corcos, δ at low frequency'], ['roger', 'Roger'], ['roger_delta', 'Roger (scaled on δ)'], ['roger_a110', 'Roger (A = 1.10)'], ['efimtsov', 'Efimtsov']];
const LR_SIMPLE = [['roger', 'Roger'], ['corcos', 'Corcos'], ['roger_delta', 'Roger (scaled on δ)']];
const TURB = [['von_karman', 'von Kármán'], ['liepmann', 'Liepmann']];
const WAKE_COLS = [['bw', 'wake half-width b_w [m]'], ['wrms_bg', 'w_rms background [m/s]'], ['wrms_wake', 'w_rms wake [m/s]'], ['L_bg', 'L background [m]'], ['L_wake', 'L wake [m]']];
const BL_COLS = [['R', 'R [m]'], ['delta', 'δ [m]'], ['delta_star', 'δ* [m]'], ['theta', 'θ [m]'], ['tau_max', 'τ_max [Pa]'], ['dpdx', 'dp/dx [Pa/m]'],
  ['rho_wall', 'ρ_w [kg/m³]'], ['U_inf', 'U_e [m/s]'], ['Pi', 'Π'], ['nu_wall', 'ν_w [m²/s]'], ['tau_wall', 'τ_w [Pa]'], ['discard', 'discard (0/1)']];
const ING_COLS = [['z', 'z [m]'], ['ua', 'u_a [m/s]'], ['la', 'l_a [m]'], ['ut', 'u_t [m/s]'], ['lt', 'l_t [m]']];
const SURF = [['front_top', 'Front rotor, suction (top) side'], ['front_bottom', 'Front rotor, pressure (bottom) side'], ['rear_top', 'Rear rotor, suction (top) side'], ['rear_bottom', 'Rear rotor, pressure (bottom) side']];

function buildSpectra() {
  const inter = !!get('noise_model.interaction') && +get('rotor.stages') === 2;
  const selfs = get('noise_model.self_noise') || [];
  const ing = !!get('noise_model.bl_ingestion');
  const simplified = get('noise_model.formulation') === 'simplified';
  const ls = get('spectra.interaction.length_scale');
  const lsMode = typeof ls === 'string' ? ls : 'factor';
  const off = (on) => (on ? '' : 'disabled-body');
  const surfaces = SURF.filter(([k]) => selfs.includes(k.split('_')[0]) || (selfs.includes('rear') && k.startsWith('front')));
  const uc = simplified ? UC_SIMPLE : UC_FULL, lr = simplified ? LR_SIMPLE : LR_FULL;
  if (!uc.some(([k]) => k === get('spectra.wall_pressure.convection'))) set('spectra.wall_pressure.convection', uc[0][0]);
  if (!lr.some(([k]) => k === get('spectra.wall_pressure.correlation_length'))) set('spectra.wall_pressure.correlation_length', lr[0][0]);
  $('#cards-spectra').replaceChildren(
    card('Interaction-noise spectrum', inter ? 'Turbulence in the front-rotor wakes and in the background flow, one row per strip.' : 'Interaction noise is not selected.',
      h('div', { class: off(inter) },
        fs('Turbulence', sel('Velocity spectrum', 'spectra.interaction.turbulence', TURB, { text: true }),
          row('Integral length scale', h('select', { onchange: (e) => set('spectra.interaction.length_scale', e.target.value === 'factor' ? 0.4 : e.target.value, true) },
            ...[['factor', 'C × L from the table'], ['pope', 'Pope (from the table)'], ['bw', '0.42 b_w (wake only)']].map(([k, t]) => h('option', { value: k, selected: k === lsMode }, t)))),
          lsMode === 'factor' ? num('Factor C', 'spectra.interaction.length_scale') : null),
        fs('Wake table (one row per strip)', tableEditor('spectra.interaction.wake', WAKE_COLS, 'wake')))),
    card('Wall-pressure spectrum', selfs.length ? 'Boundary layers at the trailing edge, one row per strip, for the suction and pressure sides.' : 'Self noise is not selected.',
      h('div', { class: off(selfs.length) },
        fs('Models', sel('Wall-pressure model', 'spectra.wall_pressure.model', WP, { text: true }),
          sel('Convection velocity', 'spectra.wall_pressure.convection', uc, { text: true }),
          sel('Spanwise correlation length', 'spectra.wall_pressure.correlation_length', lr, { text: true }),
          sel('Strips flagged in the discard column', 'spectra.wall_pressure.bad_strips', [['ignore', 'use as they are'], ['replace', 'replace by a neighbour'], ['discard', 'leave out']], { text: true }),
          get('spectra.wall_pressure.model') === 'vki' ? h('p', { class: 'note' }, 'VKI model: Dominique, Christophe, Schram & Sandberg, J. Sound Vib. 506 (2021). Uses δ*, θ, τ_w, dp/dx, U_e, ν_w and the edge Mach number.') : null),
        ...surfaces.map(([k, t]) => h('details', { class: 'bl' }, h('summary', {}, t), tableEditor(`spectra.wall_pressure.boundary_layers.${k}`, BL_COLS, 'bl'))))),
    card('Ingested turbulence', ing ? 'Turbulence of the wall boundary layer against the wall-normal distance z.' : 'Boundary-layer ingestion is not selected.',
      h('div', { class: off(ing) },
        fs('Spectrum', sel('Velocity spectrum', 'spectra.ingestion.turbulence', TURB, { text: true })),
        fs('Turbulence table', tableEditor('spectra.ingestion.table', ING_COLS, 'ingestion')))));
}

function buildInputs() {
  if (+get('rotor.stages') !== 2) { if (get('noise_model.interaction')) set('noise_model.interaction', false); set('noise_model.self_noise', (get('noise_model.self_noise') || []).filter((r) => r === 'front')); }
  buildRotor(); buildModel(); buildSpectra();
}

/* ================================================================== run + results */
async function run() {
  const btn = $('#run'), msg = $('#run-msg');
  btn.disabled = true; msg.textContent = 'running…'; msg.className = 'muted';
  const t0 = performance.now();
  const r = await backend.call('run', [JSON.stringify(state.case)]);
  btn.disabled = false;
  if (!r.ok) { msg.textContent = r.error; msg.className = 'err'; return; }
  msg.textContent = `${r.result.curves.length} spectra in ${((performance.now() - t0) / 1000).toFixed(1)} s`;
  state.result = r.result; state.theta = 0;
  renderResults();
  showTab('results');
}

let specChart = null, dirChart = null, pwlChart = null, stripChart = null;

function curveItems() {
  const R = state.result;
  const items = R.curves.map((c, i) => ({ label: c.label, color: color(i), dash: c.source === 'ingestion' && c.key !== 'ingestion_total' ? '5 4' : null, c,
    psdLin: c.psd, oaspl: c.oaspl, pwl: c.pwl }));
  if (R.total && R.curves.filter((c) => c.in_total).length > 1)
    items.push({ label: 'total', color: cssVar('--ink'), wide: true, psdLin: R.total.psd, oaspl: R.total.oaspl });
  return items;
}

function renderResults() {
  const R = state.result;
  $('#results-empty').style.display = 'none';
  $('#results').style.display = '';
  const items = curveItems();
  const t = state.theta;
  $('#stats').replaceChildren(...items.map((it) => h('div', { class: 'stat' }, h('div', { class: 'k' }, it.label),
    h('div', { class: 'v' }, `${fmt(it.oaspl[t], 3)} dB`), h('div', { class: 's' }, `OASPL at θ* = ${R.theta_deg[t]}°` + (it.c && it.c.pwl_total_db !== undefined ? ` · PWL ${fmt(it.c.pwl_total_db, 3)} dB` : '')))));
  // spectra card
  const root = $('#spec-card');
  if (!specChart) {
    const chart = h('div', { class: 'chart' }), leg = h('div', { class: 'legend' });
    const seg = h('div', { class: 'seg' }, ...[['psd', 'Narrowband PSD'], ['oct', '1/3 octave'], ['table', 'Table']].map(([k, tt]) =>
      h('button', { class: k === 'psd' ? 'on' : '', onclick: (e) => { state.view = k; $$('button', seg).forEach((b) => b.classList.toggle('on', b === e.target)); drawSpectra(); } }, tt)));
    const thSel = h('select', { class: 'compact', id: 'theta-sel', onchange: (e) => { state.theta = +e.target.value; renderResults(); } });
    root.replaceChildren(h('div', { class: 'panel chart-card' }, h('div', { class: 'card-head' }, h('h2', {}, 'Spectra'), h('div', { class: 'toolbar' }, h('label', { class: 'muted' }, 'θ* '), thSel, seg)), chart, leg));
    specChart = toggleChart(chart, leg, {});
    specChart.chart = chart;
  }
  $('#theta-sel').replaceChildren(...R.theta_deg.map((th, i) => h('option', { value: i, selected: i === t }, `${th}°`)));
  drawSpectra();
  // directivity
  if (!dirChart) dirChart = toggleChart($('#dir-chart'), $('#dir-leg'), { xlabel: 'Polar angle θ* [deg]', ylabel: 'OASPL [dB re 20 µPa]', unit: 'dB', markers: true, xfmt: (v) => `θ* = ${v}°` });
  dirChart.update(items.map((it) => ({ ...it, x: R.theta_deg, y: it.oaspl })));
  // sound power
  if (!pwlChart) pwlChart = toggleChart($('#pwl-chart'), $('#pwl-leg'), { xlog: true, xlabel: 'Frequency [Hz]', ylabel: 'PWL [dB re 1 pW/Hz]', unit: 'dB', yFloorSpan: 80, xfmt: (v) => `${fmtF(v)}Hz` });
  pwlChart.update(items.filter((it) => it.pwl).map((it) => ({ ...it, x: R.f, y: it.pwl.map((v) => dB(v, 1e-12)) })));
  // strips
  const srcSel = $('#strip-src');
  const withStrips = R.curves.filter((c) => c.strips);
  const cur = srcSel.value;
  srcSel.replaceChildren(...withStrips.map((c) => h('option', { value: c.key, selected: c.key === cur }, c.label)));
  srcSel.onchange = drawStrips;
  if (!stripChart) stripChart = toggleChart($('#strip-chart'), $('#strip-leg'), { xlog: true, xlabel: 'Frequency [Hz]', ylabel: 'PSD [dB re (20 µPa)²/Hz]', unit: 'dB', yFloorSpan: 60, xfmt: (v) => `${fmtF(v)}Hz` });
  drawStrips();
  // strip table
  const rows = [];
  for (const [name, ro] of Object.entries(R.rotors)) for (const [j, st] of ro.strips.entries())
    rows.push(h('tr', {}, h('td', {}, j === 0 ? `${name} (${ro.blades} blades, ${fmt(ro.rpm, 4)} rpm, BPF ${fmt(ro.bpf_hz, 4)} Hz)` : ''), h('td', { class: 'num' }, j + 1),
      h('td', { class: 'num' }, fmt(st.r, 4)), h('td', { class: 'num' }, fmt(st.chord, 3)), h('td', { class: 'num' }, fmt(st.stagger_deg, 3)),
      h('td', { class: 'num' }, fmt(st.U, 4)), h('td', { class: 'num' }, fmt(st.M, 3))));
  $('#strip-table').replaceChildren(h('table', {}, h('thead', {}, h('tr', {}, ...['rotor', 'strip', 'r [m]', 'chord [m]', 'stagger [deg]', 'U [m/s]', 'M'].map((x) => h('th', {}, x)))), h('tbody', {}, ...rows)));
}

function drawSpectra() {
  const R = state.result, t = state.theta;
  const items = curveItems();
  if (state.view === 'table') {
    const chart = specChart.chart;
    const head = h('tr', {}, h('th', {}, 'f [Hz]'), ...items.map((c) => h('th', {}, c.label)));
    const rows = R.f.map((f, i) => h('tr', {}, h('td', { class: 'num' }, fmt(f, 4)), ...items.map((c) => h('td', { class: 'num' }, fmt(dB(c.psdLin[t][i]), 4)))));
    chart.replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, ...rows))));
    return;
  }
  const oct = state.view === 'oct';
  specChart.update(items.map((it) => {
    if (oct) { const o = thirdOctave(R.f, it.psdLin[t]); return { ...it, x: o.fc, y: o.spl }; }
    return { ...it, x: R.f, y: it.psdLin[t].map((v) => dB(v)) };
  }), { xlog: true, xlabel: 'Frequency [Hz]', unit: 'dB', yFloorSpan: 80, xfmt: (v) => `${fmtF(v)}Hz`,
    ylabel: oct ? '1/3-octave SPL [dB re 20 µPa]' : 'PSD [dB re (20 µPa)²/Hz]' });
}

function drawStrips() {
  const R = state.result;
  const c = R.curves.find((x) => x.key === $('#strip-src').value) || R.curves.find((x) => x.strips);
  if (!c) { stripChart.update([]); return; }
  stripChart.update(c.strips.r.map((r, j) => ({ label: `strip ${j + 1}, r = ${fmt(r, 3)} m`, color: color(j), x: R.f, y: c.strips.psd[j].map((v) => dB(v)) })));
}

/* ================================================================== tabs, load / save */
function showTab(name) {
  $$('.tabs button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === name ? 'true' : 'false'));
  $$('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${name}`));
  if (name === 'results' && state.result) renderResults();
}

async function init() {
  $$('.tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  $('#run').addEventListener('click', run);
  state.defaults = await (await fetch('web/default_case.json?v=1')).json();
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch (e) { saved = null; }
  state.case = saved && saved.rotor && saved.noise_model && saved.spectra ? saved : clone(state.defaults);
  buildInputs();
  $('#reset-case').addEventListener('click', () => { state.case = clone(state.defaults); set('rotor.stages', state.case.rotor.stages, true); });
  $('#save-case').addEventListener('click', () => download('case.json', JSON.stringify(state.case, null, 2) + '\n', 'application/json'));
  $('#load-case').addEventListener('click', async () => {
    const text = await pickFile('.json'); if (!text) return;
    try {
      const c = JSON.parse(text);
      if (!c.rotor || !c.noise_model || !c.spectra) throw new Error('the case needs rotor, noise_model and spectra sections');
      state.case = c; set('rotor.stages', c.rotor.stages ?? 2, true); $('#run-msg').textContent = 'case loaded'; $('#run-msg').className = 'muted';
    } catch (e) { $('#run-msg').textContent = String(e.message || e); $('#run-msg').className = 'err'; }
  });
  $('#dl-json').addEventListener('click', () => state.result && download('results.json', JSON.stringify(state.result), 'application/json'));
  let rt = null;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { if (state.result && $('#tab-results').classList.contains('active')) renderResults(); }, 150); });
  backend.init();
}

init();
