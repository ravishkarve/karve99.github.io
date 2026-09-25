# Gas Turbine Design Studio

An interactive, browser-based course in gas turbine engine design, built on
[NASA pyCycle](https://github.com/OpenMDAO/pyCycle) and [OpenMDAO](https://openmdao.org).
The real pyCycle code runs in the browser via [Pyodide](https://pyodide.org) (Python compiled
to WebAssembly), so the site needs no server and works on GitHub Pages.

## The design flow

The app follows the order of a real engine design process:

| Step | Phase | What you do |
|------|-------|-------------|
| 1. Mission & requirements | Define | Top-level objectives: cruise condition and thrust, TSFC target, takeoff thrust (hot day), max diameter, surge margin |
| 2. Architecture | Define | Choose a single-spool turbojet or a two-spool separate-flow turbofan (guided by flight Mach) |
| 3. Technology level | Define | Component efficiencies, T4/T3 limits, losses (1970s / 1990s / 2020s presets) |
| 4. Cycle selection | Design | Evaluate a candidate cycle and run parametric trade studies and carpet plots (OPR, T4, BPR, FPR) |
| 5. Design point & sizing | Design | pyCycle sizes the engine: airflow, station data, component powers, T–s diagram, scaled compressor maps |
| 6. Off-design performance | Analyse | Takeoff, top-of-climb and part-power points; throttle sweep (thrust hook) and operating lines on the maps |
| 7. Requirements check | Analyse | Pass/fail against the requirements, with suggestions for the next iteration; export as JSON or CSV |

## Files

```
gas-turbine/
  index.html          page shell
  css/style.css       styles (light and dark)
  js/app.js           UI, design-process steps, units (SI or Imperial), charts
  js/schematic.js     engine half-section SVG with station numbers
  js/worker.js        Web Worker: loads Pyodide + OpenMDAO + pyCycle, runs the models
  py/engines.py       pyCycle models (turbojet, 2-spool turbofan; design and off-design points)
  py/studio.py        JSON API called from JavaScript (design, trade, off-design, maps)
```

The models use pyCycle's tabular air/Jet-A thermodynamics for speed. The first visit downloads
about 40 MB (Pyodide, NumPy, SciPy, OpenMDAO, pyCycle), and the browser caches it afterwards.

## Running locally

Any static file server works:

```bash
python -m http.server 8000
# open http://localhost:8000/gas-turbine/
```

The Python models can also be used directly with CPython (`pip install om-pycycle==4.4.0 openmdao==3.45.1`):

```python
import json, sys
sys.path.insert(0, 'gas-turbine/py')
import studio
res = studio.design_point('turbojet', json.dumps(dict(alt=0, MN=0, Fn=11800, T4=2370, OPR=13.5,
                                                      comp_eff=0.83, turb_eff=0.86)))
print(json.loads(res)['data']['perf']['TSFC'])
```
