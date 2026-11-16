// Headless check of the whole chain on simulated worlds:  node doppler/tests/run.js [nSeeds]
const DL = require('../js/core.js');
const N = +process.argv[2] || 12;

function run(seed, imperfect) {
  const w = DL.makeWorld(seed);
  const x = DL.synthesize(w, imperfect);
  const sg = DL.spectrogram(x, DL.FS);
  const det = DL.detectEvents(sg);
  const out = { seed, truth: w.truth.length, found: det.events.length, ok: false, err: NaN };
  // each fit against the true pass
  out.fits = det.events.map(e => {
    let best = null;
    w.truth.forEach(t => { if (!best || Math.abs(t.tr - e.tArr) < Math.abs(best.tr - e.tArr)) best = t; });
    const f = w.flights[best.id];
    return `v ${e.v.toFixed(1)}/${f.speed.toFixed(1)} d ${e.d.toFixed(0)}/${best.D.toFixed(0)}`;
  }).join(' | ');
  if (!det.events.length) return out;
  const loc = DL.locate(w, det.events);
  out.counts = loc.counts.join('/');
  out.nsol = loc.solutions.length;
  const s = loc.solutions[0];
  if (s) {
    out.err = Math.hypot(s.x - w.mic.x, s.y - w.mic.y);
    const ids = w.truth.map(t => t.id).join('-');
    out.ok = s.asg.join('-') === ids;
    out.rms = s.rms;
    out.rms2 = loc.solutions[1] ? loc.solutions[1].rms : NaN;
  }
  return out;
}

for (const imperfect of [false, true]) {
  let ok = 0; const errs = [];
  console.log(imperfect ? '\n== with model errors ==' : '== ideal ==');
  for (let s = 1; s <= N; s++) {
    const t = Date.now();
    const r = run(s, imperfect);
    if (r.ok) { ok++; errs.push(r.err); }
    console.log(`seed ${s}: events ${r.found}/${r.truth} ${r.ok ? 'OK ' : 'MISS'} err ${r.err.toFixed(0)} m  rms ${(r.rms || 0).toFixed(3)} next ${(r.rms2 || 0).toFixed(3)}  stages ${r.counts} sols ${r.nsol}  [${r.fits}] ${Date.now() - t} ms`);
  }
  errs.sort((a, b) => a - b);
  console.log(`right flights ${ok}/${N}, median error ${errs.length ? errs[errs.length >> 1].toFixed(0) : '-'} m, worst ${errs.length ? errs[errs.length - 1].toFixed(0) : '-'} m`);
}
