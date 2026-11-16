/* Doppler Locator core: world simulation, spectrogram, ridge tracking,
   Doppler curve fitting and the cross-reference / location solver.
   Pure functions, no DOM. Loads in the browser (window.DL) and in node. */
(function (root) {
  'use strict';

  var FS = 1000;            // analysis sample rate, Hz
  var C_REF = 343;          // assumed speed of sound, m/s

  // ---------- seeded random ----------
  function rng(seed) {
    var a = seed >>> 0;
    var f = function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    f.range = function (lo, hi) { return lo + (hi - lo) * f(); };
    f.gauss = function () {
      var u = 1 - f(), v = f();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    };
    return f;
  }

  // ---------- Doppler model for a straight, constant-speed pass ----------
  // tau: reception time minus the time the aircraft is at closest approach.
  // Returns the factor g such that f_received = f0 * g.
  function dopplerFactor(tau, v, d, c) {
    var k = c * c - v * v;
    var s = (c * c * tau - Math.sqrt(c * c * v * v * tau * tau + k * d * d)) / k; // emission time rel. to CPA
    var r = Math.sqrt(d * d + v * v * s * s);
    var vr = v * v * s / r;                 // radial speed, + = receding
    return 1 / (1 + vr / c);
  }
  // p = [f0, v, d, t0]
  function dopplerCurve(t, p, c) { return p[0] * dopplerFactor(t - p[3], p[1], p[2], c); }

  // ---------- flights ----------
  // A flight: start (x0,y0) at absolute time ts, velocity (vx,vy), altitude h, tone f0.
  function cpa(fl, px, py, hBias) {
    var dx = px - fl.x0, dy = py - fl.y0;
    var v2 = fl.vx * fl.vx + fl.vy * fl.vy;
    var s = (dx * fl.vx + dy * fl.vy) / v2;           // seconds after ts
    var cx = fl.x0 + fl.vx * s - px, cy = fl.y0 + fl.vy * s - py;
    var h = fl.h + (hBias || 0);
    return { T: fl.ts + s, D: Math.sqrt(cx * cx + cy * cy + h * h), s: s };
  }

  function makeWorld(seed, opts) {
    opts = opts || {};
    var L = 40000, SPAN = 3 * 3600, REC = opts.recLen || 1200;
    var nFlights = opts.nFlights || 170;
    for (var attempt = 0; attempt < 4000; attempt++) {
      var R = rng(seed * 7919 + attempt * 104729 + 13);
      var flights = [];
      for (var i = 0; i < nFlights; i++) {
        // random chord across the square
        var ang = R.range(0, 2 * Math.PI);
        var off = R.range(-0.62, 0.62) * L;
        var nx = Math.cos(ang), ny = Math.sin(ang);          // direction
        var mx = L / 2 - ny * off, my = L / 2 + nx * off;    // a point on the line
        var half = L * 0.85;
        var speed = R.range(48, 112);
        var tMid = R.range(-600, SPAN + 600);
        flights.push({
          id: i,
          callsign: callsign(R),
          x0: mx - nx * half, y0: my - ny * half,
          vx: nx * speed, vy: ny * speed, speed: speed,
          h: R.range(450, 2600),
          ts: tMid - half / speed, te: tMid + half / speed,
          f0: R.range(62, 138),
          hdg: (90 - ang * 180 / Math.PI + 360) % 360
        });
      }
      var mic = { x: R.range(0.22, 0.78) * L, y: R.range(0.22, 0.78) * L };
      var T0 = R.range(1500, SPAN - 1500 - REC);
      var clear = [], bad = false;
      for (var j = 0; j < flights.length; j++) {
        var q = cpa(flights[j], mic.x, mic.y);
        var tr = q.T + q.D / C_REF - T0;
        if (tr > -150 && tr < REC + 150) {
          if (q.D < 2200 && tr > 90 && tr < REC - 90) clear.push({ id: j, tr: tr, D: q.D });
          else if (q.D < 4600) { bad = true; break; }
        }
      }
      if (bad || clear.length < 2 || clear.length > 3) continue;
      clear.sort(function (a, b) { return a.tr - b.tr; });
      var ok = true;
      for (var m = 1; m < clear.length; m++) if (clear[m].tr - clear[m - 1].tr < 100) ok = false;
      if (!ok) continue;
      return { seed: seed, L: L, span: SPAN, recLen: REC, flights: flights, mic: mic, T0: T0, truth: clear };
    }
    throw new Error('could not build a scenario for seed ' + seed);
  }
  function callsign(R) {
    var A = 'ABCDEFGHJKLMNPRSTUVWXYZ';
    var s = 'N' + (1 + Math.floor(R() * 9)) + Math.floor(R() * 10) + Math.floor(R() * 10);
    return s + A[Math.floor(R() * A.length)] + A[Math.floor(R() * A.length)];
  }

  // Synthesise what the hidden microphone records. The tone is built from the
  // propagation delay alone (phase = 2*pi*f0*t_emit); Doppler falls out of that.
  // imperfect: true air is colder (slower sound) and reported altitudes are biased.
  function synthesize(world, imperfect) {
    var n = Math.round(world.recLen * FS);
    var x = new Float32Array(n);
    var R = rng(world.seed * 31 + 5);
    var c = imperfect ? 337.5 : C_REF;
    var hTrue = imperfect ? 45 : 0;     // true altitude = reported + 45 m
    var sigma = 1.0;
    for (var i = 0; i < n; i += 2) {
      var u = 1 - R(), w = R(), m = Math.sqrt(-2 * Math.log(u));
      x[i] = sigma * m * Math.cos(2 * Math.PI * w);
      if (i + 1 < n) x[i + 1] = sigma * m * Math.sin(2 * Math.PI * w);
    }
    // steady mains hum and a slow rumble: lines with no Doppler drop
    for (i = 0; i < n; i++) {
      var t = i / FS;
      x[i] += 0.25 * Math.sin(2 * Math.PI * 50 * t) + 0.12 * Math.sin(2 * Math.PI * 100 * t + 1);
    }
    var harm = [1, 0.55, 0.3, 0.16];
    world.flights.forEach(function (fl) {
      var q = cpa(fl, world.mic.x, world.mic.y, hTrue);
      var d = q.D, v = fl.speed, k = c * c - v * v;
      var tc = q.T - world.T0;                       // CPA time on the recording clock
      var win = 9000 / v + 30;
      var i0 = Math.max(0, Math.floor((tc - win) * FS)), i1 = Math.min(n, Math.ceil((tc + win) * FS));
      if (i1 <= i0) return;
      for (var i = i0; i < i1; i++) {
        var tau = i / FS - tc;
        var s = (c * c * tau - Math.sqrt(c * c * v * v * tau * tau + k * d * d)) / k;
        var r = Math.sqrt(d * d + v * v * s * s);
        var rk = r / 1000;
        var amp = 3.2 / rk * Math.exp(-rk / 2.2);  // spreading + absorption / ground effect
        var ph = 2 * Math.PI * fl.f0 * (s + 1000);
        var y = 0;
        for (var hh = 0; hh < harm.length; hh++) {
          if (fl.f0 * (hh + 1) > 470) break;
          y += harm[hh] * Math.sin((hh + 1) * ph);
        }
        x[i] += amp * y;
      }
    });
    return x;
  }

  // ---------- FFT / spectrogram ----------
  function fft(re, im) {
    var n = re.length, i, j, k;
    for (i = 1, j = 0; i < n; i++) {
      var bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { var t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (var len = 2; len <= n; len <<= 1) {
      var ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang), h = len >> 1;
      for (i = 0; i < n; i += len) {
        var cr = 1, ci = 0;
        for (k = 0; k < h; k++) {
          var a = i + k, b = a + h;
          var xr = re[b] * cr - im[b] * ci, xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
          var nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr;
        }
      }
    }
  }

  // Returns power in dB relative to the per-bin median (so steady background is ~0 dB).
  function spectrogram(x, fs, opts) {
    opts = opts || {};
    var win = opts.win || 1024, hop = opts.hop || 256;
    var nfft = 1; while (nfft < win * 2) nfft <<= 1;
    var nb = nfft / 2, nf = Math.max(0, Math.floor((x.length - win) / hop) + 1);
    var w = new Float32Array(win);
    for (var i = 0; i < win; i++) w[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (win - 1));
    var P = new Float32Array(nf * nb);
    var re = new Float64Array(nfft), im = new Float64Array(nfft);
    for (var f = 0; f < nf; f++) {
      var o = f * hop;
      for (i = 0; i < win; i++) { re[i] = x[o + i] * w[i]; im[i] = 0; }
      for (i = win; i < nfft; i++) { re[i] = 0; im[i] = 0; }
      fft(re, im);
      for (i = 0; i < nb; i++) P[f * nb + i] = 10 * Math.log10(re[i] * re[i] + im[i] * im[i] + 1e-12);
    }
    if (opts.normalize !== false) {
      // per-bin median over time: removes hum lines and the microphone's colouring
      var step = Math.max(1, Math.floor(nf / 200)), col = [];
      for (i = 0; i < nb; i++) {
        col.length = 0;
        for (f = 0; f < nf; f += step) col.push(P[f * nb + i]);
        col.sort(function (a, b) { return a - b; });
        var med = col[col.length >> 1] || 0;
        for (f = 0; f < nf; f++) P[f * nb + i] -= med;
      }
    }
    return { P: P, nf: nf, nb: nb, df: fs / nfft, dt: hop / fs, t0: win / 2 / fs, fs: fs, win: win, hop: hop };
  }

  // ---------- ridge tracking ----------
  function detectRidges(sg, opts) {
    opts = opts || {};
    var thr = opts.thr || 10, fmin = opts.fmin || 40, fmax = opts.fmax || Math.min(480, sg.fs / 2 - 10);
    var b0 = Math.max(2, Math.round(fmin / sg.df)), b1 = Math.min(sg.nb - 2, Math.round(fmax / sg.df));
    var maxGap = Math.round(2.5 / sg.dt), tracks = [], active = [], P = sg.P, nb = sg.nb;
    for (var f = 0; f < sg.nf; f++) {
      var peaks = [], o = f * nb;
      for (var b = b0; b <= b1; b++) {
        var p = P[o + b];
        if (p > thr && p >= P[o + b - 1] && p > P[o + b + 1]) {
          var a = P[o + b - 1], c2 = P[o + b + 1], den = a - 2 * p + c2;
          var dl = den < 0 ? 0.5 * (a - c2) / den : 0;
          peaks.push({ f: (b + dl) * sg.df, p: p, used: false });
        }
      }
      // extend the longest tracks first
      active.sort(function (u, v) { return v.pts.length - u.pts.length; });
      for (var k = 0; k < active.length; k++) {
        var tr = active[k], gap = f - tr.last;
        var pred = tr.f + tr.slope * gap;
        var tol = 1.6 + 1.2 * gap, best = -1, bd = tol;
        for (var j = 0; j < peaks.length; j++) {
          if (peaks[j].used) continue;
          var dd = Math.abs(peaks[j].f - pred);
          if (dd < bd) { bd = dd; best = j; }
        }
        if (best >= 0) {
          var pk = peaks[best]; pk.used = true;
          var sl = (pk.f - tr.f) / gap;
          tr.slope = tr.pts.length > 3 ? 0.7 * tr.slope + 0.3 * sl : sl * 0.5;
          tr.f = pk.f; tr.last = f;
          tr.pts.push({ t: sg.t0 + f * sg.dt, f: pk.f, p: pk.p });
        }
      }
      for (j = 0; j < peaks.length; j++) if (!peaks[j].used) {
        active.push({ f: peaks[j].f, slope: 0, last: f, pts: [{ t: sg.t0 + f * sg.dt, f: peaks[j].f, p: peaks[j].p }] });
      }
      for (k = active.length - 1; k >= 0; k--) if (f - active[k].last > maxGap) {
        if (active[k].pts.length >= 40) tracks.push(active[k]);
        active.splice(k, 1);
      }
    }
    active.forEach(function (t) { if (t.pts.length >= 40) tracks.push(t); });
    // keep long, falling ridges: the Doppler signature
    var out = [];
    tracks.forEach(function (t) {
      var p = t.pts, n = p.length, dur = p[n - 1].t - p[0].t;
      if (dur < 18) return;
      var m = Math.max(3, Math.floor(n * 0.1)), fa = 0, fb = 0;
      for (var i = 0; i < m; i++) { fa += p[i].f; fb += p[n - 1 - i].f; }
      fa /= m; fb /= m;
      if (fa - fb < 2.5) return;
      out.push({ pts: p, fHi: fa, fLo: fb, dur: dur });
    });
    return out;
  }

  // ---------- least squares ----------
  function solveLinear(A, b) {
    var n = b.length, i, j, k;
    A = A.map(function (r) { return r.slice(); }); b = b.slice();
    for (i = 0; i < n; i++) {
      var piv = i;
      for (j = i + 1; j < n; j++) if (Math.abs(A[j][i]) > Math.abs(A[piv][i])) piv = j;
      var t = A[i]; A[i] = A[piv]; A[piv] = t; var tb = b[i]; b[i] = b[piv]; b[piv] = tb;
      if (Math.abs(A[i][i]) < 1e-300) return null;
      for (j = i + 1; j < n; j++) {
        var m = A[j][i] / A[i][i];
        for (k = i; k < n; k++) A[j][k] -= m * A[i][k];
        b[j] -= m * b[i];
      }
    }
    var x = new Array(n);
    for (i = n - 1; i >= 0; i--) {
      var s = b[i];
      for (j = i + 1; j < n; j++) s -= A[i][j] * x[j];
      x[i] = s / A[i][i];
    }
    return x;
  }

  // Levenberg-Marquardt; resid(p) returns an array, clamp(p) keeps p physical.
  function levmar(resid, p0, clamp, iters) {
    var p = p0.slice(), n = p.length, r = resid(p), cost = dot(r, r), lam = 1e-2, JtJ = null;
    for (var it = 0; it < (iters || 60); it++) {
      var J = [], j, i;
      for (j = 0; j < n; j++) {
        var h = Math.max(1e-4, Math.abs(p[j]) * 1e-5), q = p.slice(); q[j] += h;
        var r2 = resid(q), colj = new Array(r.length);
        for (i = 0; i < r.length; i++) colj[i] = (r2[i] - r[i]) / h;
        J.push(colj);
      }
      JtJ = []; var g = [];
      for (j = 0; j < n; j++) {
        JtJ.push([]);
        for (var k = 0; k < n; k++) JtJ[j].push(dot(J[j], J[k]));
        g.push(-dot(J[j], r));
      }
      var improved = false;
      for (var tries = 0; tries < 8; tries++) {
        var A = JtJ.map(function (row, a) { var c = row.slice(); c[a] *= 1 + lam; return c; });
        var dx = solveLinear(A, g);
        if (dx) {
          var pn = p.map(function (v, a) { return v + dx[a]; });
          if (clamp) clamp(pn);
          var rn = resid(pn), cn = dot(rn, rn);
          if (cn < cost) {
            var rel = (cost - cn) / cost; p = pn; r = rn; cost = cn; lam = Math.max(lam / 5, 1e-9); improved = true;
            if (rel < 1e-10) it = 1e9;
            break;
          }
        }
        lam *= 6;
      }
      if (!improved) break;
    }
    return { p: p, cost: cost, r: r, JtJ: JtJ };
  }
  function dot(a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }

  function invert(A) {
    var n = A.length, cols = [];
    for (var j = 0; j < n; j++) {
      var e = new Array(n).fill(0); e[j] = 1;
      var x = solveLinear(A, e); if (!x) return null; cols.push(x);
    }
    return cols; // symmetric, so column/row order does not matter
  }

  // ---------- fit one Doppler curve ----------
  function fitDoppler(pts, c) {
    c = c || C_REF;
    var n = pts.length, i;
    var m = Math.max(3, Math.floor(n * 0.08)), fa = 0, fb = 0;
    for (i = 0; i < m; i++) { fa += pts[i].f; fb += pts[n - 1 - i].f; }
    fa /= m; fb /= m;
    var f0i = 2 * fa * fb / (fa + fb), vi = c * (fa - fb) / (fa + fb);
    // steepest part of the curve marks closest approach
    var tsteep = pts[n >> 1].t, bestS = 0, w = Math.max(4, Math.floor(n / 25));
    for (i = w; i < n - w; i++) {
      var s = (pts[i - w].f - pts[i + w].f) / (pts[i + w].t - pts[i - w].t);
      if (s > bestS) { bestS = s; tsteep = pts[i].t; }
    }
    function clamp(p) {
      p[1] = Math.min(Math.max(p[1], 8), 0.8 * c);
      p[2] = Math.min(Math.max(p[2], 30), 20000);
    }
    var use = pts, best = null;
    for (var pass = 0; pass < 2; pass++) {
      var resid = function (p) {
        var r = new Array(use.length);
        for (var q = 0; q < use.length; q++) r[q] = dopplerCurve(use[q].t, p, c) - use[q].f;
        return r;
      };
      best = null;
      [1, 1.4, 2].forEach(function (vm) {
        [250, 800, 2000, 4500].forEach(function (d0) {
          var v0 = Math.min(vi * vm, 0.7 * c);
          var res = levmar(resid, [f0i, v0, d0, tsteep - d0 / c], clamp, 60);
          if (!best || res.cost < best.cost) best = res;
        });
      });
      var rms = Math.sqrt(best.cost / use.length);
      if (pass === 0) {
        var lim = Math.max(3 * rms, 0.6);
        var kept = use.filter(function (pt, q) { return Math.abs(best.r[q]) < lim; });
        if (kept.length < 30 || kept.length === use.length) break;
        use = kept;
      }
    }
    var p = best.p, rmsF = Math.sqrt(best.cost / Math.max(1, use.length - 4));
    var cov = invert(best.JtJ), sd = [NaN, NaN, NaN, NaN];
    if (cov) sd = cov.map(function (row, a) { return Math.sqrt(Math.max(0, row[a])) * rmsF * 2; }); // x2: ridge points are correlated
    return { f0: p[0], v: p[1], d: p[2], t0: p[3], tArr: p[3] + p[2] / c, rms: rmsF, sd: sd, pts: use, n: use.length };
  }

  // Full detection chain: ridges -> fits -> merge harmonics of the same aircraft.
  function detectEvents(sg, c) {
    var ridges = detectRidges(sg);
    var fits = [];
    ridges.forEach(function (rg) {
      var ft = fitDoppler(rg.pts, c);
      if (ft.rms > 1.2 || ft.v < 15 || ft.v > 200 || ft.d < 60 || ft.d > 7000) return;
      if (ft.t0 < rg.pts[0].t - 20 || ft.t0 > rg.pts[rg.pts.length - 1].t + 20) return;
      fits.push(ft);
    });
    fits.sort(function (a, b) { return b.n - a.n; });
    var events = [];
    fits.forEach(function (ft) {
      for (var i = 0; i < events.length; i++) {
        var e = events[i];
        if (Math.abs(e.tArr - ft.tArr) < 10) {   // same pass: a harmonic or a broken piece of the ridge
          e.harmonics.push(ft); return;
        }
      }
      ft.harmonics = [];
      events.push(ft);
    });
    events.forEach(function (e) {
      // the tone's true fundamental is the lowest of the merged ridges
      var lo = e.f0; e.harmonics.forEach(function (h) { lo = Math.min(lo, h.f0); });
      e.fund = lo;
    });
    events.sort(function (a, b) { return a.t0 - b.t0; });
    return { ridges: ridges, events: events };
  }

  // ---------- cross-reference against flight tracks ----------
  // events: fitted curves. world.flights: the "ADS-B" tracks. Unknown: mic (x,y) and T0.
  function locate(world, events, opts) {
    opts = opts || {};
    var c = opts.c || C_REF, step = opts.step || 200, L = world.L;
    var nx = Math.floor(L / step) + 1, fl = world.flights, nF = fl.length, nE = events.length;
    var R_AUD = 4600, R_SIL = 2000;
    var tolT = 5, recLen = world.recLen;
    var tolV = events.map(function (e) { return Math.max(3 * e.sd[1], 0) + 3; });
    var tolD = events.map(function (e) { return Math.max(3 * e.sd[2], 0) + 170 + 0.05 * e.d; });
    var stage = new Uint8Array(nx * nx);      // 0 none, 1 timing, 2 +speed, 3 +distance, 4 +silence
    var counts = [0, 0, 0, 0];
    var cands = {};                           // assignment -> best grid candidate
    var T = new Float64Array(nF), D = new Float64Array(nF), aud = [];
    var known = opts.clock != null ? opts.clock : null, clockTol = opts.clockTol || 60;

    function tryStage(level, px, py) {
      // hypotheses for T0 come from every flight that could be event 0
      var e0 = events[0], best = null;
      for (var a = 0; a < aud.length; a++) {
        var k = aud[a];
        if (level >= 2 && Math.abs(fl[k].speed - e0.v) > tolV[0]) continue;
        if (level >= 3 && Math.abs(D[k] - e0.d) > tolD[0]) continue;
        var T0 = T[k] + D[k] / c - e0.tArr;
        if (known != null && Math.abs(T0 - known) > clockTol) continue;
        var asg = [k], cost = sq((D[k] - e0.d) / tolD[0]) + sq((fl[k].speed - e0.v) / tolV[0]), okAll = true;
        for (var i = 1; i < nE && okAll; i++) {
          var ei = events[i], bj = -1, bc = 1e9;
          for (var b = 0; b < aud.length; b++) {
            var j = aud[b];
            if (asg.indexOf(j) >= 0) continue;
            var dt = T[j] + D[j] / c - T0 - ei.tArr;
            if (Math.abs(dt) > tolT) continue;
            if (level >= 2 && Math.abs(fl[j].speed - ei.v) > tolV[i]) continue;
            if (level >= 3 && Math.abs(D[j] - ei.d) > tolD[i]) continue;
            var cj = sq(dt / tolT) + sq((D[j] - ei.d) / tolD[i]) + sq((fl[j].speed - ei.v) / tolV[i]);
            if (cj < bc) { bc = cj; bj = j; }
          }
          if (bj < 0) okAll = false; else { asg.push(bj); cost += bc; }
        }
        if (!okAll) continue;
        if (level >= 4) {
          // silence: nothing else may pass close by while the recorder was running
          var quiet = true;
          for (b = 0; b < aud.length && quiet; b++) {
            j = aud[b];
            if (asg.indexOf(j) >= 0 || D[j] > R_SIL) continue;
            var ta = T[j] + D[j] / c - T0;
            if (ta > 30 && ta < recLen - 30) quiet = false;
          }
          if (!quiet) continue;
        }
        if (!best || cost < best.cost) best = { asg: asg, T0: T0, cost: cost, x: px, y: py };
        if (level < 3) return best;   // existence is enough for the early stages
      }
      return best;
    }

    for (var iy = 0; iy < nx; iy++) {
      for (var ix = 0; ix < nx; ix++) {
        var px = ix * step, py = iy * step;
        aud.length = 0;
        for (var k = 0; k < nF; k++) {
          var q = cpa(fl[k], px, py);
          T[k] = q.T; D[k] = q.D;
          if (q.D < R_AUD && q.T >= fl[k].ts && q.T <= fl[k].te) aud.push(k);
        }
        if (aud.length < nE) continue;
        var lv = 0, hit = null;
        if (tryStage(1, px, py)) { lv = 1;
          if (tryStage(2, px, py)) { lv = 2;
            if (tryStage(3, px, py)) { lv = 3;
              hit = tryStage(4, px, py);
              if (hit) lv = 4;
            } } }
        stage[iy * nx + ix] = lv;
        for (var s = 0; s < lv; s++) counts[s]++;
        if (hit) {
          // one candidate per flight combination and per ~1.6 km cell: mirror solutions stay separate
          var key = hit.asg.join('-') + '@' + (ix >> 3) + ',' + (iy >> 3);
          if (!cands[key] || hit.cost < cands[key].cost) cands[key] = hit;
        }
      }
    }

    // refine every surviving flight combination against the measured curve itself
    var list = Object.keys(cands).map(function (k) { return cands[k]; });
    list.sort(function (a, b) { return a.cost - b.cost; });
    list = list.slice(0, 60);
    var all = list.map(function (cd) { return refine(world, events, cd, c); });
    all.sort(function (a, b) { return a.rms - b.rms; });
    var sols = [];
    all.forEach(function (s) {
      if (!(s.x > -2000 && s.x < L + 2000 && s.y > -2000 && s.y < L + 2000)) return;
      for (var i = 0; i < sols.length; i++) {
        if (Math.abs(sols[i].x - s.x) < 150 && Math.abs(sols[i].y - s.y) < 150) return;
      }
      sols.push(s);
    });
    return { stage: stage, nx: nx, step: step, counts: counts, total: nx * nx, solutions: sols, tolV: tolV, tolD: tolD };
  }
  function sq(x) { return x * x; }

  // Score a candidate (x, y, T0): RMS mismatch in Hz between every ridge point and the
  // curve predicted from the matched flight's track. Each tone's f0 is solved in closed form.
  function curveResiduals(world, events, asg, x, y, T0, c, out) {
    var n = 0;
    for (var i = 0; i < events.length; i++) {
      var e = events[i], f = world.flights[asg[i]], q = cpa(f, x, y);
      var tc = q.T - T0, sg = 0, gg = 0, pts = e.pts, g = new Array(pts.length), j;
      for (j = 0; j < pts.length; j++) {
        g[j] = dopplerFactor(pts[j].t - tc, f.speed, q.D, c);
        sg += g[j] * pts[j].f; gg += g[j] * g[j];
      }
      var f0 = sg / gg;
      for (j = 0; j < pts.length; j++) out[n++] = f0 * g[j] - pts[j].f;
    }
    return n;
  }

  function refine(world, events, cd, c) {
    var total = 0; events.forEach(function (e) { total += e.pts.length; });
    var buf = new Array(total);
    function resid(p) {
      curveResiduals(world, events, cd.asg, p[0], p[1], p[2], c, buf);
      return buf.slice();
    }
    var best = null;
    best = levmar(resid, [cd.x, cd.y, cd.T0], null, 40);
    var rms = Math.sqrt(best.cost / total);
    var cov = invert(best.JtJ), sx = NaN, sy = NaN;
    if (cov) { sx = Math.sqrt(Math.max(0, cov[0][0])) * rms * 2; sy = Math.sqrt(Math.max(0, cov[1][1])) * rms * 2; }
    return { asg: cd.asg, x: best.p[0], y: best.p[1], T0: best.p[2], rms: rms, sx: sx, sy: sy, grid: cd };
  }

  // ---------- prepare uploaded audio: mono float -> ~1 kHz ----------
  function decimate(x, sr) {
    var fac = Math.max(1, Math.round(sr / FS));
    if (fac === 1) return { x: x, fs: sr };
    // two cascaded moving averages as the anti-alias filter
    var y = boxcar(boxcar(x, fac), fac);
    var n = Math.floor(y.length / fac), out = new Float32Array(n);
    for (var i = 0; i < n; i++) out[i] = y[i * fac];
    return { x: out, fs: sr / fac };
  }
  function boxcar(x, w) {
    var n = x.length, y = new Float32Array(n), s = 0;
    for (var i = 0; i < n; i++) {
      s += x[i]; if (i >= w) s -= x[i - w];
      y[i] = s / w;
    }
    return y;
  }

  var DL = {
    FS: FS, C_REF: C_REF, rng: rng, dopplerFactor: dopplerFactor, dopplerCurve: dopplerCurve, cpa: cpa,
    makeWorld: makeWorld, synthesize: synthesize, spectrogram: spectrogram, detectRidges: detectRidges,
    fitDoppler: fitDoppler, detectEvents: detectEvents, locate: locate, decimate: decimate, levmar: levmar
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = DL; else root.DL = DL;
})(typeof self !== 'undefined' ? self : this);
