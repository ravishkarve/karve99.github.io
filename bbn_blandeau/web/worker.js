/* Web Worker hosting Python (Pyodide) and the bbn package.
 *
 * in : {type:'call', id, fn, args:[...]}
 * out: {type:'status', text, progress, ready} | {type:'result', id, payload} | {type:'fatal', error}
 */
const PYODIDE_VERSION = '0.29.3';
const ASSET_VERSION = '1';  // bump to bypass browser caches after an update
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PY_FILES = ['__init__.py', 'numerics.py', 'inputs.py', 'models.py', 'installation.py', 'defaults.py', 'run.py',
  'levels.py', 'config.py', 'results.py', 'examples.py', 'output.py', 'webapi.py'];

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
  status('Loading the solver…', 0.85);
  py.FS.mkdirTree('/home/pyodide/app/bbn');
  for (const f of PY_FILES) {
    const r = await fetch(`../bbn/${f}?v=${ASSET_VERSION}`);
    if (!r.ok) throw new Error(`could not load bbn/${f} (HTTP ${r.status})`);
    py.FS.writeFile(`/home/pyodide/app/bbn/${f}`, await r.text());
  }
  py.runPython(`
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/pyodide/app')
import bbn.webapi
`);
  api = py.pyimport('bbn.webapi');
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
      postMessage({ type: 'result', id: msg.id, payload: JSON.parse(api[msg.fn](...msg.args)) });
    } catch (e) {
      postMessage({ type: 'result', id: msg.id, payload: { ok: false, error: String(e && e.message ? e.message : e).split('\n').slice(-3).join(' ') } });
    }
  });
};
