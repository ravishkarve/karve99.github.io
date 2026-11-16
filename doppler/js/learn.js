/* Interactive figures for the learning tabs. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var C = DL.C_REF, shown = {}, current = 'locator';
  window.addEventListener('tabshow', function (e) {
    current = e.detail;
    if (current === 'l-doppler') { drawDopChart(); startAnim(); }
    if (current === 'l-spec') drawSpecLesson();
    if (current === 'l-fit') drawFit();
    if (current === 'l-cross') drawCross();
  });
  G.onResize(function () {
    if (current === 'l-doppler') drawDopChart();
    if (current === 'l-spec') drawSpecLesson();
    if (current === 'l-fit') drawFit();
    if (current === 'l-cross') drawCross();
  });

  // ================= 1. Doppler =================
  var D = { t: -40, last: 0, raf: 0 };
  function dp() { return { v: +$('d-v').value, d: +$('d-d').value, f: +$('d-f').value }; }
  ['d-v', 'd-d', 'd-f'].forEach(function (id) { $(id).addEventListener('input', function () { drawDopChart(); }); });
  function span(p) { return Math.min(70, 5200 / p.v); }
  function drawDopChart() {
    var p = dp();
    $('d-v-o').textContent = p.v + ' m/s (' + Math.round(p.v * 3.6) + ' km/h)';
    $('d-d-o').textContent = p.d + ' m'; $('d-f-o').textContent = p.f + ' Hz';
    var hi = p.f * C / (C - p.v), lo = p.f * C / (C + p.v);
    $('d-read').innerHTML = stat('Approaching', hi.toFixed(1) + ' Hz') + stat('Overhead', p.f.toFixed(1) + ' Hz') + stat('Receding', lo.toFixed(1) + ' Hz') +
      stat('Total drop', (hi - lo).toFixed(1) + ' Hz') + stat('Steepest fall', (p.f * p.v * p.v / (C * p.d)).toFixed(2) + ' Hz/s') + stat('Sound delay at closest', (p.d / C).toFixed(1) + ' s');
    var cv = $('cv-d-chart'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, box = { x: 50, y: 12, w: g.w - 64, h: g.h - 46 }, T = span(p);
    var pad = (hi - lo) * 0.12 + 1;
    var ax = G.axes(ctx, box, [-T, T], [lo - pad, hi + pad], { xfmt: function (v) { return v + ' s'; }, yfmt: function (v) { return v.toFixed(0) + ' Hz'; }, xlabel: 'time heard, relative to closest approach' });
    ctx.strokeStyle = G.css('--muted'); ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    [hi, lo, p.f].forEach(function (f) { ctx.beginPath(); ctx.moveTo(box.x, ax.Y(f)); ctx.lineTo(box.x + box.w, ax.Y(f)); ctx.stroke(); });
    ctx.setLineDash([]);
    ctx.strokeStyle = G.css('--accent'); ctx.lineWidth = 2.5; ctx.beginPath();
    for (var k = 0; k <= 240; k++) {
      var t = -T + 2 * T * k / 240, y = ax.Y(DL.dopplerCurve(t, [p.f, p.v, p.d, 0], C));
      if (k) ctx.lineTo(ax.X(t), y); else ctx.moveTo(ax.X(t), y);
    }
    ctx.stroke();
    if (D.t >= -T && D.t <= T) {
      var fy = DL.dopplerCurve(D.t, [p.f, p.v, p.d, 0], C);
      ctx.fillStyle = G.css('--pin'); ctx.beginPath(); ctx.arc(ax.X(D.t), ax.Y(fy), 5, 0, 7); ctx.fill();
      ctx.fillStyle = G.css('--ink'); ctx.font = '600 12px ' + G.css('--sans'); ctx.textAlign = D.t > 0 ? 'right' : 'left'; ctx.textBaseline = 'bottom';
      ctx.fillText('hearing ' + fy.toFixed(1) + ' Hz', ax.X(D.t) + (D.t > 0 ? -9 : 9), ax.Y(fy) - 6);
    }
  }
  function stat(k, v) { return '<div><span>' + k + '</span><b>' + v + '</b></div>'; }
  function startAnim() {
    cancelAnimationFrame(D.raf); D.last = 0;
    var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function frame(now) {
      if (current !== 'l-doppler') return;
      var p = dp(), T = span(p);
      if (D.last && !still) D.t += Math.min(0.05, (now - D.last) / 1000) * 7;
      D.last = now;
      if (still) D.t = 0;
      if (D.t > T + 4 || D.t < -T) D.t = -T;
      drawAnim(p, T); drawDopChart();
      if (!still) D.raf = requestAnimationFrame(frame);
    }
    D.raf = requestAnimationFrame(frame);
  }
  function drawAnim(p, T) {
    var cv = $('cv-d-anim'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, sc = g.w / 11000, gy = g.h - 22, mx = g.w / 2;
    ctx.fillStyle = G.css('--map'); ctx.fillRect(0, 0, g.w, g.h);
    ctx.fillStyle = G.css('--panel-2'); ctx.fillRect(0, gy, g.w, g.h - gy);
    // D.t is the time at the microphone; wavefronts were emitted every 1.2 s
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, g.w, gy); ctx.clip();
    ctx.strokeStyle = G.css('--accent'); ctx.lineWidth = 1;
    var first = Math.ceil((D.t - 26) / 1.2) * 1.2;
    for (var te = first; te <= D.t; te += 1.2) {
      var r = C * (D.t - te); if (r <= 0) continue;
      ctx.globalAlpha = Math.max(0.06, 0.6 - r / 15000);
      ctx.beginPath(); ctx.arc(mx + p.v * te * sc, gy - p.d * sc, r * sc, 0, 7); ctx.stroke();
    }
    ctx.restore(); ctx.globalAlpha = 1;
    var px = mx + p.v * D.t * sc, py = gy - p.d * sc;
    ctx.strokeStyle = G.css('--muted'); ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(g.w, py); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = G.css('--ink');
    ctx.beginPath(); ctx.moveTo(px + 12, py); ctx.lineTo(px - 8, py - 5); ctx.lineTo(px - 5, py); ctx.lineTo(px - 8, py + 5); ctx.closePath(); ctx.fill();
    ctx.fillStyle = G.css('--pin'); ctx.beginPath(); ctx.arc(mx, gy, 5, Math.PI, 0); ctx.fill();
    ctx.fillStyle = G.css('--ink-2'); ctx.font = '11px ' + G.css('--mono'); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText('microphone', mx, gy + 5);
    ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    ctx.fillText('crests bunch up ahead of the aircraft, spread out behind', 8, 16);
  }

  // ================= 2. Spectrogram =================
  var SP = { x: null };
  function clip() {
    if (SP.x) return SP.x;
    var n = 60 * DL.FS, x = new Float32Array(n), R = DL.rng(77), v = 85, d = 500, f0 = 95, k = C * C - v * v;
    for (var i = 0; i < n; i++) {
      var t = i / DL.FS, tau = t - 30;
      var s = (C * C * tau - Math.sqrt(C * C * v * v * tau * tau + k * d * d)) / k, r = Math.sqrt(d * d + v * v * s * s) / 1000;
      var ph = 2 * Math.PI * f0 * (s + 100);
      x[i] = R.gauss() + 0.9 * Math.sin(2 * Math.PI * 50 * t) + 0.5 * Math.sin(2 * Math.PI * 150 * t) +
        1.1 / r * Math.exp(-r / 2.2) * (Math.sin(ph) + 0.5 * Math.sin(2 * ph));
    }
    return (SP.x = x);
  }
  ['s-win', 's-norm', 's-ridge'].forEach(function (id) { $(id).addEventListener('input', drawSpecLesson); });
  function drawSpecLesson() {
    var x = clip(), win = 1 << +$('s-win').value, norm = $('s-norm').checked;
    $('s-win-o').textContent = (win / DL.FS * 1000).toFixed(0) + ' ms';
    var sg = DL.spectrogram(x, DL.FS, { win: win, hop: Math.max(8, win >> 3), normalize: true });
    var show = norm ? sg : DL.spectrogram(x, DL.FS, { win: win, hop: Math.max(8, win >> 3), normalize: false });
    var lo = 2, hi = 26;
    if (!norm) { var m = median(show.P); lo = m - 2; hi = m + 30; }
    $('s-read').innerHTML = stat('Frequency resolution', (DL.FS / win).toFixed(2) + ' Hz') + stat('Time resolution', (win / DL.FS).toFixed(2) + ' s') + stat('Slices', String(sg.nf));
    // waveform
    var cw = $('cv-s-wave'); if (!cw.clientWidth) return;
    var g = G.fit(cw), ctx = g.ctx, bx = 50, bw = g.w - 62;
    ctx.fillStyle = G.css('--muted'); ctx.font = '11px ' + G.css('--mono'); ctx.textBaseline = 'top'; ctx.textAlign = 'left';
    ctx.fillText('waveform: the aircraft is in here, but you cannot see it', bx, 2);
    ctx.strokeStyle = G.css('--ink-2'); ctx.lineWidth = 1; ctx.beginPath();
    for (var px = 0; px < bw; px++) {
      var a = Math.floor(px / bw * x.length), b = Math.floor((px + 1) / bw * x.length), mn = 1e9, mxv = -1e9;
      for (var i = a; i < b; i += 7) { if (x[i] < mn) mn = x[i]; if (x[i] > mxv) mxv = x[i]; }
      var mid = (g.h + 14) / 2, sc = (g.h - 18) / 12;
      ctx.moveTo(bx + px + 0.5, mid - mxv * sc); ctx.lineTo(bx + px + 0.5, mid - mn * sc);
    }
    ctx.stroke();
    // spectrogram
    var cs = $('cv-s-spec'); g = G.fit(cs); ctx = g.ctx;
    var box = { x: bx, y: 8, w: bw, h: g.h - 36 }, F0 = 30, F1 = 260;
    ctx.fillStyle = '#08080f'; ctx.fillRect(box.x, box.y, box.w, box.h);
    var ax = G.axes(ctx, box, [0, 60], [F0, F1], { gridLines: false, xfmt: function (v) { return v + ' s'; }, yfmt: function (v) { return v + ' Hz'; } });
    var img = G.specImage(show, 0, show.nf, Math.round(F0 / show.df), Math.round(F1 / show.df), 1400, lo, hi);
    if (img) { ctx.imageSmoothingEnabled = win >= 512; ctx.drawImage(img, ax.X(show.t0), box.y, ax.X(show.t0 + show.nf * show.dt) - ax.X(show.t0), box.h); }
    if ($('s-ridge').checked) {
      var rg = DL.detectRidges(sg, { fmax: F1 });
      ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
      ctx.strokeStyle = '#5fd6e8'; ctx.lineWidth = 1.5;
      rg.forEach(function (r) {
        ctx.beginPath();
        r.pts.forEach(function (p, i) { if (i) ctx.lineTo(ax.X(p.t), ax.Y(p.f) - 5); else ctx.moveTo(ax.X(p.t), ax.Y(p.f) - 5); });
        ctx.stroke();
      });
      ctx.restore();
      ctx.fillStyle = '#5fd6e8'; ctx.font = '11px ' + G.css('--mono'); ctx.textAlign = 'right'; ctx.textBaseline = 'top';
      ctx.fillText(rg.length ? rg.length + ' falling ridge' + (rg.length > 1 ? 's' : '') + ' traced (drawn just above)' : 'no ridge could be traced at this slice length', box.x + box.w - 6, box.y + 5);
    }
  }
  function median(P) {
    var a = []; for (var i = 0; i < P.length; i += 53) a.push(P[i]);
    a.sort(function (u, v) { return u - v; }); return a[a.length >> 1];
  }

  // ================= 3. Fit =================
  var F = { seed: 3, pts: null, truth: null, show: false };
  function newCurve() {
    var R = DL.rng(F.seed++ * 911 + 1);
    F.truth = [R.range(75, 125), R.range(55, 115), R.range(350, 2200), R.range(45, 75)];
    F.pts = []; F.show = false;
    for (var t = 2; t <= 118; t += 0.6) F.pts.push({ t: t, f: DL.dopplerCurve(t, F.truth, C) + 0.45 * R.gauss() });
  }
  function fp() { return [+$('f-f').value, +$('f-v').value, +$('f-d').value, +$('f-t').value]; }
  ['f-f', 'f-v', 'f-d', 'f-t'].forEach(function (id) { $(id).addEventListener('input', drawFit); });
  $('f-new').addEventListener('click', function () { newCurve(); drawFit(); });
  $('f-show').addEventListener('click', function () { F.show = !F.show; drawFit(); });
  $('f-auto').addEventListener('click', function () {
    var r = DL.fitDoppler(F.pts, C);
    $('f-f').value = r.f0; $('f-v').value = r.v; $('f-d').value = r.d; $('f-t').value = r.t0;
    F.auto = r; drawFit();
  });
  function drawFit() {
    if (!F.pts) newCurve();
    var p = fp();
    $('f-f-o').textContent = p[0].toFixed(1) + ' Hz'; $('f-v-o').textContent = p[1].toFixed(1) + ' m/s';
    $('f-d-o').textContent = p[2].toFixed(0) + ' m'; $('f-t-o').textContent = p[3].toFixed(1) + ' s';
    var ss = 0; F.pts.forEach(function (q) { var e = DL.dopplerCurve(q.t, p, C) - q.f; ss += e * e; });
    var rms = Math.sqrt(ss / F.pts.length);
    var html = stat('Miss (RMS)', rms.toFixed(2) + ' Hz') + stat('Verdict', rms < 0.55 ? 'as good as the noise allows' : rms < 1.5 ? 'close' : 'keep going');
    if (F.show) html += stat('True tone', F.truth[0].toFixed(1) + ' Hz') + stat('True speed', F.truth[1].toFixed(1) + ' m/s') + stat('True distance', F.truth[2].toFixed(0) + ' m') + stat('True time', F.truth[3].toFixed(1) + ' s');
    $('f-read').innerHTML = html;
    $('f-show').textContent = F.show ? 'Hide true values' : 'Show true values';
    var cv = $('cv-f-chart'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, box = { x: 50, y: 12, w: g.w - 64, h: g.h - 46 };
    var lo = 1e9, hi = -1e9; F.pts.forEach(function (q) { if (q.f < lo) lo = q.f; if (q.f > hi) hi = q.f; });
    var ax = G.axes(ctx, box, [0, 120], [lo - 6, hi + 6], { xfmt: function (v) { return v + ' s'; }, yfmt: function (v) { return v.toFixed(0) + ' Hz'; }, xlabel: 'time in recording' });
    ctx.fillStyle = G.css('--ink-2');
    F.pts.forEach(function (q) { ctx.beginPath(); ctx.arc(ax.X(q.t), ax.Y(q.f), 1.8, 0, 7); ctx.fill(); });
    ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
    if (F.show) curve(ctx, ax, F.truth, G.css('--truth'), 1.5, [5, 4]);
    curve(ctx, ax, p, G.css('--accent'), 2.5);
    ctx.restore();
  }
  function curve(ctx, ax, p, col, lw, dash) {
    ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.setLineDash(dash || []); ctx.beginPath();
    for (var k = 0; k <= 240; k++) { var t = k / 2, y = ax.Y(DL.dopplerCurve(t, p, C)); if (k) ctx.lineTo(ax.X(t), y); else ctx.moveTo(ax.X(t), y); }
    ctx.stroke(); ctx.setLineDash([]);
  }

  // ================= 4. Cross-reference =================
  var X = { L: 12000, mic: { x: 7300, y: 4300 }, drag: false, box: null,
    fl: [mk(0, 2600, 74, 20, 800, 0, 'A'), mk(3300, 12000, 96, -68, 1200, 150, 'B')] };
  function mk(x0, y0, speed, deg, h, ts, name) {
    var a = deg * Math.PI / 180;
    return { x0: x0, y0: y0, vx: speed * Math.cos(a), vy: speed * Math.sin(a), speed: speed, h: h, ts: ts, name: name };
  }
  function heard(f, x, y) { var q = DL.cpa(f, x, y); return { D: q.D, t: q.T + q.D / C }; }
  var COL = ['#2a9bb0', '#7c9a1c'];
  function drawCross() {
    var cv = $('cv-c-map'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, size = Math.min(g.w, g.h) - 2, box = { x: (g.w - size) / 2, y: 1, w: size, h: size };
    X.box = box;
    var PX = function (v) { return box.x + v / X.L * box.w; }, PY = function (v) { return box.y + box.h - v / X.L * box.h; };
    ctx.fillStyle = G.css('--map'); ctx.fillRect(box.x, box.y, box.w, box.h);
    ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
    ctx.strokeStyle = G.css('--grid'); ctx.lineWidth = 1;
    for (var v = 2000; v < X.L; v += 2000) { ctx.beginPath(); ctx.moveTo(PX(v), box.y); ctx.lineTo(PX(v), box.y + box.h); ctx.moveTo(box.x, PY(v)); ctx.lineTo(box.x + box.w, PY(v)); ctx.stroke(); }
    var m = X.fl.map(function (f) { return heard(f, X.mic.x, X.mic.y); });
    var gap = m[1].t - m[0].t, lines = [];
    X.fl.forEach(function (f, i) {
      var ux = f.vx / f.speed, uy = f.vy / f.speed, nx = -uy, ny = ux, rho = Math.sqrt(Math.max(0, m[i].D * m[i].D - f.h * f.h));
      // the track itself
      ctx.strokeStyle = COL[i]; ctx.lineWidth = 1.2; ctx.setLineDash([6, 5]);
      ctx.beginPath(); ctx.moveTo(PX(f.x0 - ux * 30000), PY(f.y0 - uy * 30000)); ctx.lineTo(PX(f.x0 + ux * 30000), PY(f.y0 + uy * 30000)); ctx.stroke(); ctx.setLineDash([]);
      [1, -1].forEach(function (sg) {
        var ox = f.x0 + nx * rho * sg, oy = f.y0 + ny * rho * sg;
        ctx.lineWidth = 2.2; ctx.beginPath(); ctx.moveTo(PX(ox - ux * 30000), PY(oy - uy * 30000)); ctx.lineTo(PX(ox + ux * 30000), PY(oy + uy * 30000)); ctx.stroke();
        lines.push({ i: i, ox: ox, oy: oy, ux: ux, uy: uy });
      });
      var lx = f.x0 + ux * (i ? 1500 : 1300), ly = f.y0 + uy * (i ? 1500 : 1300);
      ctx.fillStyle = G.css('--ink'); ctx.font = '600 12px ' + G.css('--sans'); ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
      ctx.fillText('flight ' + f.name + ' →', PX(lx) + 4, PY(ly) - 4);
    });
    // four crossings
    var n = 0;
    lines.filter(function (l) { return l.i === 0; }).forEach(function (a) {
      lines.filter(function (l) { return l.i === 1; }).forEach(function (b) {
        var det = a.ux * (-b.uy) + b.ux * a.uy; if (Math.abs(det) < 1e-9) return;
        var rx = b.ox - a.ox, ry = b.oy - a.oy, s = (rx * (-b.uy) + b.ux * ry) / det;
        var x = a.ox + a.ux * s, y = a.oy + a.uy * s;
        var h = X.fl.map(function (f) { return heard(f, x, y); }), gp = h[1].t - h[0].t, ok = Math.abs(gp - gap) < 0.5;
        ctx.strokeStyle = ok ? G.css('--pin') : G.css('--ink-2'); ctx.lineWidth = ok ? 3 : 1.8;
        ctx.beginPath(); ctx.arc(PX(x), PY(y), ok ? 11 : 7, 0, 7); ctx.stroke();
        if (x > 0 && x < X.L && y > 0 && y < X.L) {
          var txt = 'gap ' + gp.toFixed(0) + ' s ' + (ok ? '✓' : '✗'), tx = PX(x) + 14, ty = PY(y) + (n++ % 2 ? 16 : -16);
          ctx.font = '11px ' + G.css('--mono'); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          ctx.fillStyle = G.css('--panel'); ctx.globalAlpha = 0.85; ctx.fillRect(tx - 3, ty - 8, ctx.measureText(txt).width + 6, 16); ctx.globalAlpha = 1;
          ctx.fillStyle = ok ? G.css('--ink') : G.css('--ink-2'); ctx.fillText(txt, tx, ty);
        }
      });
    });
    ctx.fillStyle = G.css('--pin'); ctx.strokeStyle = G.css('--panel'); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(PX(X.mic.x), PY(X.mic.y), 6, 0, 7); ctx.fill(); ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = G.css('--rule'); ctx.lineWidth = 1; ctx.strokeRect(box.x + 0.5, box.y + 0.5, box.w - 1, box.h - 1);
    $('c-read').innerHTML = stat('Flight A passes at', Math.round(m[0].D) + ' m') + stat('Flight B passes at', Math.round(m[1].D) + ' m') +
      stat('B heard after A by', gap.toFixed(0) + ' s') + stat('Crossings that match all three', '1 of 4');
  }
  (function () {
    var cv = $('cv-c-map');
    function move(ev) {
      if (!X.drag || !X.box) return;
      var r = cv.getBoundingClientRect(), x = (ev.clientX - r.left - X.box.x) / X.box.w * X.L, y = (1 - (ev.clientY - r.top - X.box.y) / X.box.h) * X.L;
      X.mic.x = Math.min(X.L - 300, Math.max(300, x)); X.mic.y = Math.min(X.L - 300, Math.max(300, y));
      drawCross();
    }
    cv.addEventListener('pointerdown', function (ev) { X.drag = true; cv.setPointerCapture(ev.pointerId); move(ev); });
    cv.addEventListener('pointermove', move);
    cv.addEventListener('pointerup', function () { X.drag = false; });
    cv.addEventListener('pointercancel', function () { X.drag = false; });
  })();
})();
