/* Web Worker hosting Python (Pyodide) + bbnoise for the Broadband Rotor Noise Lab.
 *
 * in : {type:'call', id, fn, args:[...]}
 * out: {type:'status', text, progress, ready} | {type:'progress', id, text}
 *      {type:'result', id, payload} | {type:'fatal', error}
 */
const PYODIDE_VERSION = '0.29.3';
const ASSET_VERSION = '8';  // bump to bypass browser caches after an update
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PY_FILES = ['__init__.py', 'special.py', 'airfoil.py', 'turbulence.py', 'wallpressure.py',
  'boundarylayer.py', 'tables.py', 'rotor.py', 'sources.py', 'thesis.py', 'thesis_cases.py', 'model.py', 'cases.py',
  'mcode/__init__.py', 'mcode/mlab.py', 'mcode/inputs.py', 'mcode/models.py', 'mcode/installation.py', 'mcode/options.py',
  'mcode/launch.py', 'mcode/pp.py', 'mcode/run.py', 'mcode/case.py', 'mcode/synthetic.py', 'mcode/io_mat.py', 'verification.py', 'webapi.py'];

const status = (text, progress, ready = false) => postMessage({ type: 'status', text, progress, ready });
let py = null;
let api = null;

async function init() {
  const t0 = performance.now();
  status('Loading the Python runtime (Pyodide)…', 0.05);
  importScripts(PYODIDE_URL + 'pyodide.js');
  py = await loadPyodide({ indexURL: PYODIDE_URL, stdout: () => {}, stderr: () => {} });
  status('Loading NumPy and SciPy…', 0.35);
  await py.loadPackage(['numpy', 'scipy']);
  status('Loading bbnoise…', 0.85);
  py.FS.mkdirTree('/home/pyodide/app/bbnoise/mcode');
  for (const f of PY_FILES) {
    const r = await fetch(`../bbnoise/${f}?v=${ASSET_VERSION}`);
    if (!r.ok) throw new Error(`could not load bbnoise/${f} (HTTP ${r.status})`);
    py.FS.writeFile(`/home/pyodide/app/bbnoise/${f}`, await r.text());
  }
  py.runPython(`
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/pyodide/app')
import bbnoise.webapi
`);
  api = py.pyimport('bbnoise.webapi');
  status(`In-browser Python ready (${((performance.now() - t0) / 1000).toFixed(0)} s)`, 1, true);
}

const ready = init().catch((e) => {
  postMessage({ type: 'fatal', error: String(e && e.message ? e.message : e).split('\n').slice(-4).join(' ') });
  throw e;
});

let chain = Promise.resolve();
self.onmessage = (ev) => {
  const msg = ev.data;
  if (msg.type !== 'call') return;
  chain = chain.then(async () => {
    try {
      await ready;
      const progress = (text) => postMessage({ type: 'progress', id: msg.id, text: String(text) });
      let out;
      if (msg.fn === 'run') out = api.run.callKwargs(msg.args[0], { progress });
      else out = api[msg.fn](...msg.args);
      postMessage({ type: 'result', id: msg.id, payload: JSON.parse(out) });
    } catch (e) {
      postMessage({ type: 'result', id: msg.id, payload: { ok: false, error: String(e && e.message ? e.message : e).split('\n').slice(-3).join(' ') } });
    }
  });
};
