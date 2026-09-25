/* Half-section engine schematics (SVG) with station numbers.
 * renderSchematic(arch, temps) -> svg string
 *   temps: optional {stationId: Tt_degR}; when given, components are coloured by exit temperature.
 */
(function () {
  function tempColor(T) {
    // 400 R (cold, blue) -> 3400 R (hot, red)
    const f = Math.max(0, Math.min(1, (T - 400) / 3000));
    const hue = 215 - 215 * f;
    const light = 55 - 8 * Math.sin(Math.PI * f);
    return `hsl(${hue.toFixed(0)}, 78%, ${light.toFixed(0)}%)`;
  }

  const poly = (pts) => pts.map((p) => p.join(',')).join(' ');

  // Each component: {name, x0, x1, top0, top1, bot0, bot1, st (station whose Tt colours it), kind}
  const LAYOUTS = {
    turbojet: {
      width: 760,
      hub: 205,
      comps: [
        { name: 'Inlet', x0: 20, x1: 100, t0: 70, t1: 80, b0: 205, b1: 205, st: '2', kind: 'duct' },
        { name: 'Compressor', x0: 108, x1: 318, t0: 80, t1: 150, b0: 205, b1: 205, st: '3', kind: 'comp' },
        { name: 'Burner', x0: 326, x1: 440, t0: 140, t1: 140, b0: 205, b1: 205, st: '4', kind: 'burner' },
        { name: 'Turbine', x0: 448, x1: 548, t0: 150, t1: 120, b0: 205, b1: 205, st: '5', kind: 'turb' },
        { name: 'Nozzle', x0: 556, x1: 690, t0: 120, t1: 145, b0: 205, b1: 190, st: '9', kind: 'nozz' },
      ],
      stations: [['0', 12], ['2', 104], ['3', 322], ['4', 444], ['5', 552], ['9', 694]],
      shafts: [{ x0: 200, x1: 500, y: 236, label: 'Shaft' }],
      bypass: null,
    },
    turbofan: {
      width: 820,
      hub: 212,
      comps: [
        { name: 'Inlet', x0: 20, x1: 92, t0: 34, t1: 40, b0: 212, b1: 212, st: '2', kind: 'duct' },
        { name: 'Fan', x0: 98, x1: 138, t0: 40, t1: 44, b0: 212, b1: 212, st: '21', kind: 'fan' },
        { name: 'LPC', x0: 160, x1: 228, t0: 132, t1: 142, b0: 212, b1: 212, st: '24', kind: 'comp' },
        { name: 'HPC', x0: 244, x1: 380, t0: 146, t1: 178, b0: 212, b1: 212, st: '3', kind: 'comp' },
        { name: 'Burner', x0: 388, x1: 470, t0: 172, t1: 172, b0: 212, b1: 212, st: '4', kind: 'burner' },
        { name: 'HPT', x0: 478, x1: 528, t0: 176, t1: 164, b0: 212, b1: 212, st: '45', kind: 'turb' },
        { name: 'LPT', x0: 544, x1: 636, t0: 162, t1: 136, b0: 212, b1: 212, st: '5', kind: 'turb' },
        { name: 'Core nozzle', x0: 644, x1: 752, t0: 136, t1: 158, b0: 212, b1: 196, st: '9', kind: 'nozz' },
      ],
      bypass: { x0: 146, x1: 600, xn: 668, top: 44, splitter: 124, st: '13', stn: '19' },
      stations: [['0', 12], ['2', 95], ['21', 138], ['13', 158], ['24', 236, 'core'], ['3', 384, 'core'], ['4', 474, 'core'],
        ['45', 536, 'core'], ['5', 640, 'core'], ['19', 672, 'byp'], ['9', 756, 'core']],
      shafts: [
        { x0: 118, x1: 590, y: 250, label: 'LP spool' },
        { x0: 300, x1: 504, y: 238, label: 'HP spool' },
      ],
    },
  };

  const BASE = {
    duct: 'var(--surface-2)', fan: '#7aa7e8', comp: '#7aa7e8', burner: '#f0a35e', turb: '#e9806f', nozz: 'var(--surface-2)',
  };

  function renderSchematic(arch, temps) {
    const L = LAYOUTS[arch];
    const W = L.width, H = L.hub + 74;
    const colored = temps && Object.keys(temps).length > 0;
    const fill = (c) => (colored && temps[c.st] ? tempColor(temps[c.st]) : BASE[c.kind]);
    let s = `<svg class="schematic" viewBox="0 0 ${W} ${H}" role="img" aria-label="${arch} schematic with station numbers">`;

    // station lines
    for (const [id, x, zone] of L.stations) {
      const y2 = zone === 'byp' ? L.bypass.splitter : L.hub + 4;
      const y1 = zone === 'core' && L.bypass ? L.bypass.splitter + 2 : 22;
      s += `<line x1="${x}" y1="${y1}" x2="${x}" y2="${y2}" stroke="var(--border)" stroke-dasharray="3 3"/>`;
      if (zone === 'core' && L.bypass) s += `<text class="st-label" x="${x}" y="${y1 + 12}" text-anchor="middle">${id}</text>`;
      else s += `<text class="st-label" x="${x}" y="16" text-anchor="middle">${id}</text>`;
    }

    // bypass duct
    if (L.bypass) {
      const b = L.bypass;
      const bf = colored && temps[b.st] ? tempColor(temps[b.st]) : 'var(--accent-soft)';
      s += `<polygon points="${poly([[b.x0, b.top + 4], [b.x1, b.top + 12], [b.xn, b.top + 30], [b.xn, b.splitter - 4], [b.x1, b.splitter], [b.x0, b.splitter]])}" fill="${bf}" opacity=".55" stroke="var(--border)"/>`;
      // nacelle
      s += `<path d="M20 ${b.top - 8} Q 60 ${b.top - 18} 140 ${b.top - 6} L ${b.x1} ${b.top + 6} L ${b.xn} ${b.top + 26}" fill="none" stroke="var(--text)" stroke-width="2.2"/>`;
      // splitter / core cowl
      s += `<path d="M${b.x0 - 4} ${b.splitter + 2} L ${b.x0 + 8} ${b.splitter - 3} L ${b.x1} ${b.splitter - 1} L ${b.xn} ${b.splitter + 6}" fill="none" stroke="var(--text)" stroke-width="1.6"/>`;
      s += `<text class="comp-label" x="${(b.x0 + b.x1) / 2}" y="${(b.top + b.splitter) / 2 + 6}" text-anchor="middle">Bypass duct</text>`;
      s += `<path d="M${b.xn + 4} ${(b.top + 30 + b.splitter) / 2} l 26 0" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr)"/>`;
    }

    // components
    for (const c of L.comps) {
      const pts = [[c.x0, c.t0], [c.x1, c.t1], [c.x1, c.b1], [c.x0, c.b0]];
      s += `<polygon points="${poly(pts)}" fill="${fill(c)}" stroke="var(--text)" stroke-width="1.2" stroke-opacity=".6"/>`;
      if (c.kind === 'comp' || c.kind === 'turb' || c.kind === 'fan') {
        // blade rows
        const n = c.kind === 'fan' ? 1 : Math.max(2, Math.round((c.x1 - c.x0) / 22));
        for (let i = 0; i < n; i++) {
          const x = c.x0 + (i + 0.5) * (c.x1 - c.x0) / n;
          const f = (x - c.x0) / (c.x1 - c.x0);
          const top = c.t0 + f * (c.t1 - c.t0);
          s += `<line x1="${x}" y1="${top + 3}" x2="${x}" y2="${c.b0 - 3}" stroke="var(--text)" stroke-opacity=".35" stroke-width="${c.kind === 'fan' ? 5 : 2}"/>`;
        }
      }
      if (c.kind === 'burner') {
        s += `<ellipse cx="${(c.x0 + c.x1) / 2}" cy="${(c.t0 + c.b0) / 2}" rx="${(c.x1 - c.x0) / 3}" ry="${(c.b0 - c.t0) / 4}" fill="var(--hot)" opacity=".55"/>`;
      }
      const lx = (c.x0 + c.x1) / 2;
      if (c.kind !== 'fan') s += `<text class="comp-label" x="${lx}" y="${L.hub + 15}" text-anchor="middle">${c.name}</text>`;
      else s += `<text class="comp-label" x="${lx}" y="${(c.t0 + c.b0) / 2 + 58}" text-anchor="middle" transform="rotate(-90 ${lx} ${(c.t0 + c.b0) / 2 + 58})" dy="4">Fan</text>`;
    }
    // exhaust arrow
    const last = L.comps[L.comps.length - 1];
    s += `<path d="M${last.x1 + 4} ${(last.t1 + last.b1) / 2} l 30 0" stroke="var(--hot)" stroke-width="2.4" marker-end="url(#arrh)"/>`;
    // intake arrow
    s += `<path d="M0 ${(L.comps[0].t0 + L.hub) / 2} l 16 0" stroke="var(--accent)" stroke-width="2" marker-end="url(#arr)"/>`;

    // hub / centreline / shafts
    s += `<line x1="0" y1="${L.hub}" x2="${W}" y2="${L.hub}" stroke="var(--text)" stroke-opacity=".5"/>`;
    s += `<line x1="0" y1="${H - 6}" x2="${W}" y2="${H - 6}" stroke="var(--muted)" stroke-dasharray="14 4 3 4"/>`;
    for (const sh of L.shafts) {
      s += `<line x1="${sh.x0}" y1="${sh.y}" x2="${sh.x1}" y2="${sh.y}" stroke="var(--muted)" stroke-width="4" stroke-linecap="round"/>`;
      s += `<text class="st-label" x="${sh.x1 + 8}" y="${sh.y + 4}">${sh.label}</text>`;
    }

    if (colored) {
      const lx = W - 160, ly = H - 22;
      s += `<defs><linearGradient id="tg" x1="0" x2="1">`;
      for (let i = 0; i <= 10; i++) s += `<stop offset="${i / 10}" stop-color="${tempColor(400 + 300 * i)}"/>`;
      s += `</linearGradient></defs>`;
      s += `<rect x="${lx}" y="${ly}" width="150" height="8" rx="3" fill="url(#tg)"/>`;
      s += `<text class="st-label" x="${lx}" y="${ly - 4}">cold</text><text class="st-label" x="${lx + 150}" y="${ly - 4}" text-anchor="end">hot (Tt)</text>`;
    }

    s += `<defs>
      <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="var(--accent)"/></marker>
      <marker id="arrh" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="var(--hot)"/></marker>
    </defs></svg>`;
    return s;
  }

  window.renderSchematic = renderSchematic;
  window.tempColor = tempColor;
})();
