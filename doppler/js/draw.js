/* Small canvas helpers shared by the tool and the lessons. */
(function () {
  'use strict';
  var G = {};
  G.css = function (name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); };
  // Size a canvas to its CSS box at device resolution; returns a context in CSS pixels.
  G.fit = function (cv) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    var ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx: ctx, w: w, h: h };
  };
  // magma-like colour map, 256 RGBA entries
  var stops = [[0, 8, 8, 20], [0.18, 40, 17, 85], [0.38, 110, 31, 120], [0.58, 190, 55, 100], [0.76, 245, 115, 70], [0.9, 254, 190, 110], [1, 252, 250, 205]];
  G.lut = new Uint8Array(256 * 3);
  for (var i = 0; i < 256; i++) {
    var u = i / 255, k = 0;
    while (k < stops.length - 2 && u > stops[k + 1][0]) k++;
    var a = stops[k], b = stops[k + 1], t = Math.min(1, Math.max(0, (u - a[0]) / (b[0] - a[0])));
    for (var c = 0; c < 3; c++) G.lut[i * 3 + c] = Math.round(a[c + 1] + (b[c + 1] - a[c + 1]) * t);
  }
  // Render part of a spectrogram into an offscreen canvas (one pixel per frame/bin, pooled in time).
  G.specImage = function (sg, f0, f1, b0, b1, maxCols, lo, hi) {
    var nfr = f1 - f0, pool = Math.max(1, Math.ceil(nfr / maxCols)), cols = Math.floor(nfr / pool), rows = b1 - b0;
    if (cols < 1 || rows < 1) return null;
    var cv = document.createElement('canvas'); cv.width = cols; cv.height = rows;
    var ctx = cv.getContext('2d'), img = ctx.createImageData(cols, rows), d = img.data, P = sg.P, nb = sg.nb;
    for (var x = 0; x < cols; x++) {
      for (var y = 0; y < rows; y++) {
        var b = b1 - 1 - y, m = -1e9;
        for (var q = 0; q < pool; q++) { var v = P[(f0 + x * pool + q) * nb + b]; if (v > m) m = v; }
        var u = Math.round(255 * Math.min(1, Math.max(0, (m - lo) / (hi - lo)))), o = (y * cols + x) * 4;
        d[o] = G.lut[u * 3]; d[o + 1] = G.lut[u * 3 + 1]; d[o + 2] = G.lut[u * 3 + 2]; d[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return cv;
  };
  // Axes for a plot area; returns mapping functions.
  G.axes = function (ctx, box, xr, yr, o) {
    o = o || {};
    var X = function (v) { return box.x + (v - xr[0]) / (xr[1] - xr[0]) * box.w; };
    var Y = function (v) { return box.y + box.h - (v - yr[0]) / (yr[1] - yr[0]) * box.h; };
    ctx.font = '11px ' + (G.css('--mono') || 'monospace');
    ctx.fillStyle = o.ink || G.css('--muted'); ctx.strokeStyle = o.grid || G.css('--grid'); ctx.lineWidth = 1;
    G.ticks(xr[0], xr[1], o.nx || 6).forEach(function (v) {
      var x = Math.round(X(v)) + 0.5;
      if (o.gridLines !== false) { ctx.beginPath(); ctx.moveTo(x, box.y); ctx.lineTo(x, box.y + box.h); ctx.stroke(); }
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText(o.xfmt ? o.xfmt(v) : String(+v.toFixed(2)), x, box.y + box.h + 5);
    });
    G.ticks(yr[0], yr[1], o.ny || 5).forEach(function (v) {
      var y = Math.round(Y(v)) + 0.5;
      if (o.gridLines !== false) { ctx.beginPath(); ctx.moveTo(box.x, y); ctx.lineTo(box.x + box.w, y); ctx.stroke(); }
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(o.yfmt ? o.yfmt(v) : String(+v.toFixed(2)), box.x - 6, y);
    });
    if (o.xlabel) { ctx.textAlign = 'right'; ctx.textBaseline = 'bottom'; ctx.fillText(o.xlabel, box.x + box.w, box.y + box.h + 30); }
    if (o.ylabel) { ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'; ctx.fillText(o.ylabel, box.x - 34, box.y - 6); }
    return { X: X, Y: Y };
  };
  G.ticks = function (a, b, n) {
    var span = b - a, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / mag;
    var step = (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * mag, out = [];
    for (var v = Math.ceil(a / step - 1e-9) * step; v <= b + 1e-9; v += step) out.push(v);
    return out;
  };
  G.mmss = function (s) { s = Math.round(s); var m = Math.floor(s / 60); return m + ':' + ('0' + (s % 60)).slice(-2); };
  G.clock = function (s) {   // simulated time of day, world t=0 is 09:00:00
    s = Math.round(s) + 9 * 3600; var h = Math.floor(s / 3600) % 24, m = Math.floor(s % 3600 / 60), x = s % 60;
    return ('0' + h).slice(-2) + ':' + ('0' + m).slice(-2) + ':' + ('0' + x).slice(-2);
  };
  G.onResize = function (fn) {
    var t; window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(fn, 120); });
    if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', fn);
  };
  window.G = G;
})();
