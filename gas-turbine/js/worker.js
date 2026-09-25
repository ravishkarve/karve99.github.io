/* Web Worker that hosts Python (Pyodide) + OpenMDAO + pyCycle.
 *
 * Messages in :  {type:'call', id, fn, args:[...]}   (args are JSON-able; objects are stringified)
 * Messages out:  {type:'status', text, progress, ready}
 *                {type:'result', id, payload}         (payload = {ok, data | error})
 */
const PYODIDE_VERSION = '0.29.3';
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

// Pinned, pure-Python wheels straight from PyPI (CORS-enabled).
const WHEELS = [
  'https://files.pythonhosted.org/packages/b9/54/dd730b32ea14ea797530a4479b2ed46a6fb250f682a9cfb997e968bf0261/networkx-3.4.2-py3-none-any.whl',
  'https://files.pythonhosted.org/packages/3d/12/373995de37a7509106536db43d5779b50f49d3ec4b2b6865835f6ff793a0/openmdao-3.45.1-py3-none-any.whl',
  'https://files.pythonhosted.org/packages/ed/8f/599cc4bfaf284bf2f5080b9e5a4687ee0cbcd3bd7fe00b0a1d1781e6c798/om_pycycle-4.4.0-py3-none-any.whl',
];
const PY_FILES = ['engines.py', 'studio.py'];

importScripts(PYODIDE_URL + 'pyodide.js');

let studio = null;
const status = (text, progress, ready = false) => postMessage({ type: 'status', text, progress, ready });

async function init() {
  const t0 = performance.now();
  status('Loading Python runtime (Pyodide)…', 0.05);
  const py = await loadPyodide({ indexURL: PYODIDE_URL, stdout: () => {}, stderr: () => {} });

  status('Loading NumPy & SciPy…', 0.25);
  await py.loadPackage(['numpy', 'scipy', 'requests', 'packaging', 'micropip', 'sqlite3']);

  status('Installing OpenMDAO & pyCycle…', 0.55);
  const micropip = py.pyimport('micropip');
  await micropip.install(WHEELS, { deps: false });

  status('Loading engine models…', 0.8);
  py.FS.mkdirTree('/home/pyodide/app');
  for (const f of PY_FILES) {
    const src = await (await fetch(`../py/${f}?v=4`)).text();
    py.FS.writeFile(`/home/pyodide/app/${f}`, src);
  }
  py.runPython(`
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/pyodide/app')
import studio
`);
  studio = py.pyimport('studio');
  const secs = ((performance.now() - t0) / 1000).toFixed(0);
  status(`Python ready (${secs}s)`, 1, true);
}

const ready = init().catch((e) => {
  status('Failed to start Python: ' + (e && e.message ? e.message.split('\n')[0] : e), 0, false);
  postMessage({ type: 'fatal', error: String(e) });
  throw e;
});

// Calls are processed strictly in order.
let chain = Promise.resolve();
self.onmessage = (ev) => {
  const msg = ev.data;
  if (msg.type !== 'call') return;
  chain = chain.then(async () => {
    try {
      await ready;
      const args = msg.args.map((a) => (typeof a === 'object' ? JSON.stringify(a) : a));
      const t = performance.now();
      const out = studio[msg.fn](...args);
      const payload = JSON.parse(out);
      payload.ms = performance.now() - t;
      postMessage({ type: 'result', id: msg.id, payload });
    } catch (e) {
      postMessage({ type: 'result', id: msg.id, payload: { ok: false, error: String(e && e.message ? e.message : e).split('\n').slice(-2).join(' ') } });
    }
  });
};
