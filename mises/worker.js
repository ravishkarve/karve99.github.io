/* Web Worker hosting Python (Pyodide) + pymises for the Cascade Lab dashboard.
 *
 * Messages in :  {type:'call', id, fn, args:[...]}
 * Messages out:  {type:'status', text, progress, ready}
 *                {type:'progress', id, text}
 *                {type:'result', id, payload}
 *                {type:'fatal', error}
 */
const PYODIDE_VERSION = '0.29.3';
const ASSET_VERSION = '2';  // bump to bypass browser caches after an update
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PY_FILES = ['__init__.py', 'gas.py', 'geometry.py', 'panel.py', 'boundary_layer.py', 'euler.py',
  'losses.py', 'solver.py', 'config.py', 'io.py', 'examples.py', 'verification.py', 'webapi.py', 'cli.py'];

const status = (text, progress, ready = false) => postMessage({ type: 'status', text, progress, ready });
let py = null;
let api = null;

async function init() {
  const t0 = performance.now();
  status('Loading Python runtime (Pyodide)…', 0.05);
  importScripts(PYODIDE_URL + 'pyodide.js');
  py = await loadPyodide({ indexURL: PYODIDE_URL, stdout: () => {}, stderr: () => {} });
  status('Loading NumPy and SciPy…', 0.35);
  await py.loadPackage(['numpy', 'scipy', 'pyyaml']);
  status('Loading pymises…', 0.8);
  py.FS.mkdirTree('/home/pyodide/app/pymises');
  for (const f of PY_FILES) {
    const r = await fetch(`pymises/${f}?v=${ASSET_VERSION}`);
    if (!r.ok) throw new Error(`could not load pymises/${f} (HTTP ${r.status})`);
    py.FS.writeFile(`/home/pyodide/app/pymises/${f}`, await r.text());
  }
  py.runPython(`
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/pyodide/app')
import pymises.webapi as webapi
`);
  api = py.pyimport('pymises.webapi');
  status(`Live Python solver ready (${((performance.now() - t0) / 1000).toFixed(0)} s)`, 1, true);
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
      if (msg.fn === 'run_config_json') {
        const fn = api.run_config_json;
        out = fn.callKwargs(msg.args[0], msg.args[1] || '.toml', { progress });
      } else {
        out = api[msg.fn](...msg.args);
      }
      postMessage({ type: 'result', id: msg.id, payload: JSON.parse(out) });
    } catch (e) {
      postMessage({ type: 'result', id: msg.id, payload: { ok: false, error: String(e && e.message ? e.message : e).split('\n').slice(-3).join(' ') } });
    }
  });
};
