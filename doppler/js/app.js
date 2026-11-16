/* Locator tab: drives the worker and draws the spectrogram, curve detail, table and map. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var EV_COL = ['#5fd6e8', '#b9e769', '#ffb454', '#f08fc0', '#c3a6ff'];
  var S = { world: null, sg: null, events: [], loc: null, sel: 0, reveal: false, zoom: false, mode: 'sim', seed: 6, recLen: 0, busy: false };
  var worker = new Worker('js/worker.js');

  // ---------- tabs ----------
  document.querySelectorAll('.tabs button').forEach(function (b) {
    b.addEventListener('click', function () {
      document.querySelectorAll('.tabs button').forEach(function (o) { o.setAttribute('aria-selected', o === b ? 'true' : 'false'); });
      document.querySelectorAll('.tab').forEach(function (t) { t.classList.toggle('active', t.id === 'tab-' + b.dataset.tab); });
      window.dispatchEvent(new CustomEvent('tabshow', { detail: b.dataset.tab }));
      if (b.dataset.tab === 'locator') drawAll();
    });
  });

  // ---------- pipeline status ----------
  var ORDER = ['rec', 'spec', 'detect', 'fit', 'cross', 'pin'];
  function setStep(done, active, skipFrom) {
    document.querySelectorAll('#steps li').forEach(function (li) {
      var i = ORDER.indexOf(li.dataset.step);
      li.className = i < done ? 'done' : i === active ? 'active' : '';
      if (skipFrom != null && i >= skipFrom) li.className = 'skip';
    });
  }
  function status(t) { $('status').textContent = t; }

  // ---------- run ----------
  function runSim(seed) {
    S.mode = 'sim'; S.seed = seed; reset();
    setStep(0, 0); status('Simulating flights and synthesising the recording…');
    worker.postMessage({ cmd: 'sim', seed: seed, imperfect: $('opt-imperfect').checked, clock: $('opt-clock').checked, clockErr: (seed * 37 % 81) - 40 });
  }
  function reset() {
    S.world = null; S.sg = null; S.events = []; S.loc = null; S.sel = 0; S.reveal = false; S.zoom = false; S.busy = true;
    $('btn-reveal').disabled = true; $('btn-reveal').textContent = 'Reveal true location';
    $('result').innerHTML = ''; $('funnel').innerHTML = ''; $('cands').innerHTML = '';
    $('ev-table').querySelector('tbody').innerHTML = '';
    $('panel-map').classList.toggle('off', S.mode !== 'sim');
    drawAll();
  }
  worker.onmessage = function (ev) {
    var m = ev.data;
    if (m.type === 'world') { S.world = m.world; drawMap(); }
    else if (m.type === 'recorded') {
      S.recLen = m.seconds; setStep(1, 1);
      status('Recorded ' + G.mmss(m.seconds) + '. Computing the spectrogram…');
    } else if (m.type === 'spec') {
      S.sg = m.sg; S.img = null; setStep(2, 2); status('Tracing ridges and fitting Doppler curves…'); drawSpec();
    } else if (m.type === 'events') {
      S.events = m.events; S.sel = 0;
      setStep(4, S.mode === 'sim' && m.events.length ? 4 : -1, S.mode === 'sim' ? null : 4);
      var n = m.events.length;
      $('spec-note').textContent = m.nRidges + ' falling ridge' + (m.nRidges === 1 ? '' : 's') + ' traced, ' + n + ' aircraft pass' + (n === 1 ? '' : 'es') + ' fitted';
      status(n ? 'Found ' + n + ' Doppler curve' + (n === 1 ? '' : 's') + '.' + (S.mode === 'sim' ? ' Testing every 200 m grid point against every flight…' : '') : 'No Doppler curves found in this recording.');
      drawSpec(); drawDetail(); fillTable();
    } else if (m.type === 'located') {
      S.loc = m.loc; S.stageImg = null; setStep(6, -1);
      fillResult(); fillTable(); drawMap();
      $('btn-reveal').disabled = false;
    } else if (m.type === 'done') {
      S.busy = false;
      if (S.mode !== 'sim') {
        status(S.events.length ? 'Curves fitted. Locating needs flight tracks for the time and place, which only the simulated world has.' : 'No Doppler curves found. The method needs a tonal aircraft (propeller or helicopter) audible for 20 s or more.');
      } else if (!m.located) status('No curves were detected, so there is nothing to cross-reference. Try a new recording.');
    } else if (m.type === 'error') { S.busy = false; status('Something went wrong: ' + m.message); }
  };

  $('btn-new').addEventListener('click', function () { runSim(1 + Math.floor(Math.random() * 9998)); });
  $('opt-imperfect').addEventListener('change', function () { runSim(S.seed); });
  $('opt-clock').addEventListener('change', function () { runSim(S.seed); });
  $('btn-reveal').addEventListener('click', function () {
    S.reveal = !S.reveal; $('btn-reveal').textContent = S.reveal ? 'Hide true location' : 'Reveal true location';
    fillResult(); drawMap();
  });

  // ---------- own audio ----------
  $('file').addEventListener('change', function () {
    var f = this.files[0]; this.value = '';
    if (!f) return;
    S.mode = 'audio'; reset(); setStep(0, 0, 4); status('Decoding ' + f.name + '…');
    $('spec-note').textContent = '';
    var AC = window.AudioContext || window.webkitAudioContext;
    f.arrayBuffer().then(function (buf) { return new AC().decodeAudioData(buf); }).then(function (ab) {
      var n = Math.min(ab.length, Math.floor(ab.sampleRate * 1800)), x = new Float32Array(n);
      for (var c = 0; c < ab.numberOfChannels; c++) {
        var d = ab.getChannelData(c);
        for (var i = 0; i < n; i++) x[i] += d[i] / ab.numberOfChannels;
      }
      if (ab.length > n) $('spec-note').textContent = 'Only the first 30 minutes are analysed.';
      worker.postMessage({ cmd: 'audio', x: x, sr: ab.sampleRate }, [x.buffer]);
    }).catch(function () { S.busy = false; status('That file could not be decoded as audio.'); });
  });

  // ---------- spectrogram overview ----------
  var F_LO = 30, F_HI = 300, specBox = null;
  function drawSpec() {
    var cv = $('cv-spec'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, box = { x: 46, y: 8, w: g.w - 56, h: g.h - 34 };
    specBox = box;
    ctx.fillStyle = '#08080f'; ctx.fillRect(box.x, box.y, box.w, box.h);
    var sg = S.sg, dur = S.recLen || 1200;
    var ax = G.axes(ctx, box, [0, dur], [F_LO, F_HI], { gridLines: false, xfmt: G.mmss, nx: Math.max(3, Math.floor(box.w / 90)), yfmt: function (v) { return v + ' Hz'; } });
    if (!sg) return;
    if (!S.img) S.img = G.specImage(sg, 0, sg.nf, Math.round(F_LO / sg.df), Math.round(F_HI / sg.df), 1800, 2, 24);
    if (S.img) {
      ctx.imageSmoothingEnabled = true;
      var x0 = ax.X(sg.t0), x1 = ax.X(sg.t0 + sg.nf * sg.dt);
      ctx.drawImage(S.img, x0, box.y, x1 - x0, box.h);
    }
    ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
    S.events.forEach(function (e, i) {
      var col = EV_COL[i % EV_COL.length];
      [e].concat(e.harmonics).forEach(function (h) {
        var pts = h.pts, pad = 5;
        ctx.strokeStyle = col; ctx.lineWidth = i === S.sel ? 2 : 1.2; ctx.setLineDash(i === S.sel ? [] : [4, 3]);
        var xa = ax.X(pts[0].t) - pad, xb = ax.X(pts[pts.length - 1].t) + pad;
        var lo = 1e9, hi = -1e9; pts.forEach(function (p) { if (p.f < lo) lo = p.f; if (p.f > hi) hi = p.f; });
        ctx.strokeRect(xa, ax.Y(hi) - pad, Math.max(8, xb - xa), ax.Y(lo) - ax.Y(hi) + 2 * pad);
      });
      ctx.setLineDash([]);
      ctx.fillStyle = col; ctx.font = '600 12px ' + G.css('--sans'); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText(String(i + 1), ax.X(e.tArr), box.y + 4);
    });
    ctx.restore();
  }
  $('cv-spec').addEventListener('click', function (ev) {
    if (!S.events.length || !specBox) return;
    var r = this.getBoundingClientRect(), t = (ev.clientX - r.left - specBox.x) / specBox.w * S.recLen, best = 0;
    S.events.forEach(function (e, i) { if (Math.abs(e.tArr - t) < Math.abs(S.events[best].tArr - t)) best = i; });
    select(best);
  });
  function select(i) { S.sel = i; drawSpec(); drawDetail(); fillTable(); }

  // ---------- one curve ----------
  function drawDetail() {
    var cv = $('cv-detail'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, box = { x: 50, y: 10, w: g.w - 62, h: g.h - 40 };
    var e = S.events[S.sel], sg = S.sg;
    ctx.fillStyle = '#08080f'; ctx.fillRect(box.x, box.y, box.w, box.h);
    if (!e || !sg) { $('detail-title').textContent = 'Curve detail'; return; }
    var col = EV_COL[S.sel % EV_COL.length];
    $('detail-title').textContent = 'Curve ' + (S.sel + 1) + ' in detail';
    var half = Math.max(40, Math.min(110, 2.2 * e.d / e.v + 25));
    var ta = Math.max(0, e.tArr - half), tb = Math.min(S.recLen, e.tArr + half);
    var asym = e.f0 * e.v / DL.C_REF, fa = e.f0 - asym * 1.25 - 2, fb = e.f0 + asym * 1.35 + 2;
    var ax = G.axes(ctx, box, [ta, tb], [fa, fb], { gridLines: false, xfmt: G.mmss, nx: 5, yfmt: function (v) { return v.toFixed(0) + ' Hz'; }, xlabel: 'time in recording' });
    var f0 = Math.max(0, Math.floor((ta - sg.t0) / sg.dt)), f1 = Math.min(sg.nf, Math.ceil((tb - sg.t0) / sg.dt));
    var b0 = Math.max(0, Math.floor(fa / sg.df)), b1 = Math.min(sg.nb, Math.ceil(fb / sg.df));
    var img = G.specImage(sg, f0, f1, b0, b1, 1200, 2, 26);
    if (img) ctx.drawImage(img, ax.X(sg.t0 + f0 * sg.dt), ax.Y(b1 * sg.df), ax.X(sg.t0 + f1 * sg.dt) - ax.X(sg.t0 + f0 * sg.dt), ax.Y(b0 * sg.df) - ax.Y(b1 * sg.df));
    ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
    // true tone and arrival of the closest-approach sound
    ctx.strokeStyle = 'rgba(255,255,255,.45)'; ctx.setLineDash([3, 4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(box.x, ax.Y(e.f0)); ctx.lineTo(box.x + box.w, ax.Y(e.f0));
    ctx.moveTo(ax.X(e.tArr), box.y); ctx.lineTo(ax.X(e.tArr), box.y + box.h); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,255,255,.8)'; ctx.font = '11px ' + G.css('--mono'); ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
    ctx.fillText('true tone ' + e.f0.toFixed(1) + ' Hz', box.x + box.w - 6, ax.Y(e.f0) - 3);
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText('closest approach heard', ax.X(e.tArr) + 5, box.y + 5);
    ctx.fillStyle = '#fff';
    e.pts.forEach(function (p, i) { if (i % 2 === 0) ctx.fillRect(ax.X(p.t) - 1, ax.Y(p.f) - 1, 2, 2); });
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath();
    for (var k = 0; k <= 200; k++) {
      var t = ta + (tb - ta) * k / 200, y = ax.Y(DL.dopplerCurve(t, [e.f0, e.v, e.d, e.t0], DL.C_REF));
      if (k) ctx.lineTo(ax.X(t), y); else ctx.moveTo(ax.X(t), y);
    }
    ctx.stroke(); ctx.restore();
  }

  // ---------- table ----------
  function fillTable() {
    var tb = $('ev-table').querySelector('tbody'), best = S.loc && S.loc.solutions[0];
    tb.innerHTML = '';
    S.events.forEach(function (e, i) {
      var tr = document.createElement('tr'); if (i === S.sel) tr.className = 'sel';
      var fl = best && S.world ? S.world.flights[best.asg[i]] : null;
      var cells = [
        '<i class="dot" style="background:' + EV_COL[i % EV_COL.length] + '"></i>' + (i + 1),
        G.mmss(e.tArr),
        e.v.toFixed(1) + ' <small>± ' + pm(e.sd[1], 1) + ' m/s</small>',
        Math.round(e.d) + ' <small>± ' + pm(e.sd[2], 0) + ' m</small>',
        e.fund.toFixed(1) + ' Hz' + (e.harmonics.length ? ' <small>+' + e.harmonics.length + ' more</small>' : ''),
        e.rms.toFixed(2) + ' Hz',
        fl ? '<b>' + fl.callsign + '</b> <small>' + fl.speed.toFixed(0) + ' m/s, ' + Math.round(fl.h) + ' m</small>' : (S.mode === 'sim' ? '…' : '<small>no flight data</small>')
      ];
      tr.innerHTML = cells.map(function (c) { return '<td>' + c + '</td>'; }).join('');
      tr.addEventListener('click', function () { select(i); });
      tb.appendChild(tr);
    });
    if (!S.events.length && S.sg) tb.innerHTML = '<tr><td colspan="7" class="muted">No Doppler curves detected.</td></tr>';
  }
  function pm(v, d) { return isFinite(v) ? v.toFixed(d) : '?'; }

  // ---------- result, funnel, candidates ----------
  function km(v) { return (v / 1000).toFixed(2); }
  function fillResult() {
    var loc = S.loc, w = S.world; if (!loc || !w) return;
    var sols = loc.solutions, s = sols[0], html = '';
    if (!s) {
      html = '<p class="verdict bad">No location is consistent with these curves.</p><p class="muted">A curve was probably fitted poorly or belongs to something that is not in the flight data.</p>';
      status('Cross-reference finished without a consistent location.');
    } else {
      var amb = sols[1] && sols[1].rms < 1.25 * s.rms, single = S.events.length < 2 && !$('opt-clock').checked;
      html += '<p class="verdict ' + (amb ? 'warn' : 'good') + '">' + (amb ? 'Ambiguous: ' + (sols.length > 3 ? 'several places fit' : 'two places fit') + ' almost equally well' : 'Location found') + '</p>';
      html += '<p class="coord">' + km(s.x) + ' km E, ' + km(s.y) + ' km N</p>';
      html += '<p class="muted">Recording started at ' + G.clock(s.T0) + '. Matched ' + s.asg.map(function (k) { return w.flights[k].callsign; }).join(' and ') + '. Curves fit to ' + s.rms.toFixed(2) + ' Hz.</p>';
      if (single) html += '<p class="muted">Only one flyover and no clock: nothing ties the curve to one flight, so this is a guess.</p>';
      if (S.reveal) {
        var err = Math.hypot(s.x - w.mic.x, s.y - w.mic.y);
        var right = s.asg.join('-') === w.truth.map(function (t) { return t.id; }).join('-');
        html += '<p class="truth">True location: ' + km(w.mic.x) + ' km E, ' + km(w.mic.y) + ' km N. The estimate is <b>' + (err < 1000 ? Math.round(err) + ' m' : (err / 1000).toFixed(1) + ' km') + '</b> off' + (right ? '.' : ', because it matched the wrong flights.') + '</p>';
      }
      html += '<div class="row"><button class="btn small" id="btn-zoom">' + (S.zoom ? 'Show whole area' : 'Zoom to estimate') + '</button></div>';
      status(amb ? 'Done, but more than one place explains the recording.' : 'Done. The recording was pinned to one place.');
    }
    $('result').innerHTML = html;
    var z = $('btn-zoom'); if (z) z.addEventListener('click', function () { S.zoom = !S.zoom; fillResult(); drawMap(); });

    var names = ['Timing fits', '+ speed matches', '+ distance matches', '+ nothing else nearby'];
    var cell = loc.step * loc.step / 1e6, area = loc.total * cell;
    $('funnel').innerHTML = '<div class="frow"><span>Whole area</span><div class="fbar"><i style="width:100%;background:var(--rule)"></i></div><b>' + Math.round(area) + ' km²</b></div>' +
      names.map(function (n, i) {
        var a = loc.counts[i] * cell, pct = 100 * loc.counts[i] / loc.total;
        return '<div class="frow"><span>' + n + '</span><div class="fbar"><i style="width:' + Math.max(pct, loc.counts[i] ? 0.8 : 0) + '%;background:var(--st' + (i + 1) + ')"></i></div><b>' + (a >= 10 ? Math.round(a) : a.toFixed(1)) + ' km²</b></div>';
      }).join('');
    $('cands').innerHTML = sols.length ? sols.slice(0, 5).map(function (c, i) {
      return '<div class="cand' + (i === 0 ? ' top' : '') + '"><b>' + (i + 1) + '</b><span>' + c.asg.map(function (k) { return w.flights[k].callsign; }).join(' + ') + '<small>' + km(c.x) + ' E, ' + km(c.y) + ' N</small></span><em>' + c.rms.toFixed(2) + ' Hz</em></div>';
    }).join('') + (sols.length > 5 ? '<p class="muted">and ' + (sols.length - 5) + ' more</p>' : '') : '<p class="muted">None survived.</p>';
  }

  // ---------- map ----------
  function drawMap() {
    var cv = $('cv-map'); if (!cv.clientWidth) return;
    var g = G.fit(cv), ctx = g.ctx, w = S.world, pad = 30;
    var size = Math.min(g.w - pad - 8, g.h - pad - 8), box = { x: pad, y: 8, w: size, h: size };
    ctx.fillStyle = G.css('--map'); ctx.fillRect(box.x, box.y, box.w, box.h);
    if (!w) return;
    var L = w.L, best = S.loc && S.loc.solutions[0], view = { x: 0, y: 0, s: L };
    if (S.zoom && best) { var sp = 5000; view = { x: best.x - sp / 2, y: best.y - sp / 2, s: sp }; }
    var X = function (v) { return box.x + (v - view.x) / view.s * box.w; };
    var Y = function (v) { return box.y + box.h - (v - view.y) / view.s * box.h; };
    ctx.save(); ctx.beginPath(); ctx.rect(box.x, box.y, box.w, box.h); ctx.clip();
    // grid
    ctx.strokeStyle = G.css('--grid'); ctx.lineWidth = 1;
    var gs = S.zoom ? 1000 : 10000;
    for (var v = Math.ceil(view.x / gs) * gs; v <= view.x + view.s; v += gs) { ctx.beginPath(); ctx.moveTo(X(v), box.y); ctx.lineTo(X(v), box.y + box.h); ctx.stroke(); }
    for (v = Math.ceil(view.y / gs) * gs; v <= view.y + view.s; v += gs) { ctx.beginPath(); ctx.moveTo(box.x, Y(v)); ctx.lineTo(box.x + box.w, Y(v)); ctx.stroke(); }
    // filter stages
    if (S.loc) {
      if (!S.stageImg) S.stageImg = stageImage(S.loc);
      ctx.imageSmoothingEnabled = false;
      var st = S.loc.step, n = S.loc.nx;
      ctx.drawImage(S.stageImg, X(-st / 2), Y((n - 0.5) * st), X((n - 0.5) * st) - X(-st / 2), Y(-st / 2) - Y((n - 0.5) * st));
    }
    // flight tracks
    var matched = best ? best.asg : [];
    ctx.lineWidth = 1; ctx.strokeStyle = G.css('--track');
    w.flights.forEach(function (f) {
      if (matched.indexOf(f.id) >= 0) return;
      var d = f.te - f.ts;
      ctx.beginPath(); ctx.moveTo(X(f.x0), Y(f.y0)); ctx.lineTo(X(f.x0 + f.vx * d), Y(f.y0 + f.vy * d)); ctx.stroke();
    });
    matched.forEach(function (id, i) {
      var f = w.flights[id], d = f.te - f.ts, col = EV_COL[i % EV_COL.length];
      ctx.strokeStyle = G.css('--ink'); ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(X(f.x0), Y(f.y0)); ctx.lineTo(X(f.x0 + f.vx * d), Y(f.y0 + f.vy * d)); ctx.stroke();
      ctx.strokeStyle = col; ctx.lineWidth = 2.2; ctx.stroke();
      // label near closest approach, with a heading arrow
      var q = DL.cpa(f, best.x, best.y), px = X(f.x0 + f.vx * q.s), py = Y(f.y0 + f.vy * q.s);
      var ux = f.vx / f.speed, uy = -f.vy / f.speed;
      ctx.fillStyle = col; ctx.strokeStyle = G.css('--ink'); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px + ux * 9, py + uy * 9); ctx.lineTo(px - ux * 6 - uy * 6, py - uy * 6 + ux * 6); ctx.lineTo(px - ux * 6 + uy * 6, py - uy * 6 - ux * 6); ctx.closePath(); ctx.fill(); ctx.stroke();
      // label a little way back along the track so the two labels do not sit on the pin
      var back = view.s * (0.14 + 0.07 * i);
      label(ctx, (i + 1) + ' ' + f.callsign, X(f.x0 + f.vx * q.s - f.vx / f.speed * back) + 8, Y(f.y0 + f.vy * q.s - f.vy / f.speed * back) - 10, col);
    });
    // other candidates
    if (S.loc) S.loc.solutions.slice(1, 8).forEach(function (s, i) {
      ctx.strokeStyle = G.css('--ink-2'); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(X(s.x), Y(s.y), 5, 0, 7); ctx.stroke();
      ctx.fillStyle = G.css('--ink-2'); ctx.font = '11px ' + G.css('--mono'); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText(String(i + 2), X(s.x) + 8, Y(s.y));
    });
    if (S.reveal) {
      var mx = X(w.mic.x), my = Y(w.mic.y);
      ctx.fillStyle = G.css('--truth'); ctx.strokeStyle = G.css('--panel'); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(mx, my, 6, 0, 7); ctx.fill(); ctx.stroke();
      label(ctx, 'true', mx + 10, my + 12, G.css('--truth'));
    }
    if (best) {
      var bx = X(best.x), by = Y(best.y);
      ctx.strokeStyle = G.css('--panel'); ctx.lineWidth = 5; cross(ctx, bx, by);
      ctx.strokeStyle = G.css('--pin'); ctx.lineWidth = 2.5; cross(ctx, bx, by);
    }
    ctx.restore();
    ctx.strokeStyle = G.css('--rule'); ctx.strokeRect(box.x + 0.5, box.y + 0.5, box.w - 1, box.h - 1);
    // axis labels
    ctx.fillStyle = G.css('--muted'); ctx.font = '11px ' + G.css('--mono');
    for (v = Math.ceil(view.x / gs) * gs; v <= view.x + view.s + 1; v += gs) { ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText((v / 1000) + (v === Math.ceil(view.x / gs) * gs ? ' km' : ''), X(v), box.y + box.h + 5); }
    for (v = Math.ceil(view.y / gs) * gs; v <= view.y + view.s + 1; v += gs) { ctx.textAlign = 'right'; ctx.textBaseline = 'middle'; ctx.fillText(String(v / 1000), box.x - 5, Y(v)); }
  }
  function cross(ctx, x, y) {
    ctx.beginPath(); ctx.arc(x, y, 9, 0, 7);
    ctx.moveTo(x - 16, y); ctx.lineTo(x - 4, y); ctx.moveTo(x + 4, y); ctx.lineTo(x + 16, y);
    ctx.moveTo(x, y - 16); ctx.lineTo(x, y - 4); ctx.moveTo(x, y + 4); ctx.lineTo(x, y + 16); ctx.stroke();
  }
  function label(ctx, text, x, y, col) {
    ctx.font = '600 11px ' + G.css('--sans'); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    var w = ctx.measureText(text).width;
    ctx.fillStyle = G.css('--panel'); ctx.globalAlpha = 0.88; ctx.fillRect(x - 3, y - 8, w + 6, 16); ctx.globalAlpha = 1;
    ctx.fillStyle = G.css('--ink'); ctx.fillText(text, x, y);
    ctx.fillStyle = col; ctx.fillRect(x - 3, y - 8, 2, 16);
  }
  function stageImage(loc) {
    var n = loc.nx, cv = document.createElement('canvas'); cv.width = n; cv.height = n;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(n, n), d = img.data;
    var cols = [null, rgb(G.css('--st1')), rgb(G.css('--st2')), rgb(G.css('--st3')), rgb(G.css('--st4'))], al = [0, 70, 120, 190, 255];
    for (var iy = 0; iy < n; iy++) for (var ix = 0; ix < n; ix++) {
      var s = loc.stage[iy * n + ix]; if (!s) continue;
      var o = ((n - 1 - iy) * n + ix) * 4, c = cols[s];
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = al[s];
    }
    ctx.putImageData(img, 0, 0); return cv;
  }
  function rgb(hex) { var v = parseInt(hex.replace('#', ''), 16); return [v >> 16 & 255, v >> 8 & 255, v & 255]; }

  function drawAll() { S.stageImg = null; drawSpec(); drawDetail(); drawMap(); }
  G.onResize(drawAll);
  runSim(S.seed);
})();
