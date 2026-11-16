/* Runs the analysis chain off the main thread and reports each stage. */
importScripts('core.js');
var world = null;
onmessage = function (ev) {
  var m = ev.data;
  try {
    if (m.cmd === 'sim') {
      world = DL.makeWorld(m.seed);
      postMessage({ type: 'world', world: world });
      var x = DL.synthesize(world, m.imperfect);
      analyse(x, DL.FS, m, true);
    } else if (m.cmd === 'audio') {
      world = null;
      var d = DL.decimate(m.x, m.sr);
      analyse(d.x, d.fs, m, false);
    }
  } catch (e) {
    postMessage({ type: 'error', message: String(e && e.message || e) });
  }
};
function analyse(x, fs, m, sim) {
  postMessage({ type: 'recorded', seconds: x.length / fs, fs: fs });
  var sg = DL.spectrogram(x, fs);
  var det = DL.detectEvents(sg);
  var copy = new Float32Array(sg.P);     // keep ours, hand a copy to the page
  postMessage({ type: 'spec', sg: { P: copy, nf: sg.nf, nb: sg.nb, df: sg.df, dt: sg.dt, t0: sg.t0, fs: sg.fs } }, [copy.buffer]);
  postMessage({ type: 'events', events: det.events, nRidges: det.ridges.length });
  if (!sim) { postMessage({ type: 'done', located: false }); return; }
  if (!det.events.length) { postMessage({ type: 'done', located: false }); return; }
  var loc = DL.locate(world, det.events, { clock: m.clock ? world.T0 + m.clockErr : null });
  postMessage({ type: 'located', loc: loc }, [loc.stage.buffer]);
  postMessage({ type: 'done', located: true });
}
