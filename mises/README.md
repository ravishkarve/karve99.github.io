# pymises: a pythonic MISES-style cascade solver

`pymises` analyses the blade-to-blade flow through a linear cascade the way
Drela and Youngren's **MISES** does: an inviscid solution coupled to an
integral boundary layer, with e^N transition and a mixed-out loss. It is
written in plain Python (NumPy/SciPy), runs from a configuration file or the
command line, ships with a verification suite, and powers an online dashboard
that can run the solver in the browser.

This is an independent re-implementation, not a port of the MISES Fortran
source, which is licensed separately by MIT. The boundary-layer model follows
the published Drela–Giles formulation used by XFOIL and MISES. The inviscid
solvers differ from MISES's streamline-grid Newton Euler method; the table
below shows how.

| | MISES | pymises |
|---|---|---|
| Inviscid flow | steady Euler on an intrinsic streamline grid, global Newton | **panel**: periodic linear-vorticity panel method + Karman–Tsien; **euler**: finite-volume Euler on a periodic H-grid (JST, RK4, residual smoothing) |
| Streamtube thickness (AVDR) | yes | yes (Euler) |
| Boundary layer | two-equation integral, lag-dissipation, e^N | same closures (Drela–Giles / XFOIL), lag equation, e^N envelope, forced transition |
| Viscous coupling | simultaneous Newton | panel: simultaneous Newton with the exact source interaction matrix; Euler: wall transpiration + quasi-Newton cycles |
| Loss | mixed-out | mixed-out control volume (mass, both momenta, energy) incl. trailing-edge base blockage |
| Input | `blade.xxx`, `ises.xxx` | MISES `blade.xxx`, Selig / Lednicer aerofoil files, parametric blades, TOML / JSON / YAML configs |

## Install and run

```bash
cd mises
pip install -e ".[plot,yaml,test]"

pymises example compressor .        # writes compressor.toml
pymises run compressor.toml         # solve; writes JSON, CSV and PNG plots
pymises run compressor_sweep.toml   # a [sweep] section gives a loss bucket
pymises verify -o report/           # verification suite -> report/verification.md
pymises blade compressor.toml -w blade.c4   # export the blade as a MISES blade file
pymises blade compressor.toml -w c4.dat     # ... or as Selig coordinates (.dat)
python -m pytest                    # unit tests (add --runslow for the Euler tests)
```

Python API:

```python
from pymises import Blade, FlowConditions, ViscousOptions, CascadeSolver

blade = Blade.from_parameters(inlet_metal_angle=45, exit_metal_angle=15,
                              max_thickness=0.08, thickness_form="c4", pitch=0.9)
# or: blade = Blade.read_mises("blade.xxx")
# or: blade = Blade.read_airfoil("naca4412.dat", stagger=30.0, solidity=1.2)
flow = FlowConditions(inlet_mach=0.5, inlet_angle=43.0, reynolds=5e5)
result = CascadeSolver(blade, flow, ViscousOptions(ncrit=9)).solve()   # method="euler"
print(result.summary())
result.save("results/")          # result.json, *_surface.csv, *_boundary_layer.csv, plots
```

## Configuration files

```toml
[case]
name = "C4 compressor cascade"
method = "panel"              # or "euler"
output_dir = "results/compressor"

[geometry]
type = "parametric"           # parametric | mises | selig | naca4 | coordinates
inlet_metal_angle = 45.0      # deg from axial
exit_metal_angle = 15.0
max_thickness = 0.08
thickness_form = "c4"         # naca65 | naca4 | c4
camber = "circular"           # circular | bezier (le_camber_fraction = 0.5 .. 0.9)
pitch = 0.9                   # s/c (or solidity = c/s)
te_thickness = 0.004

[flow]
inlet_mach = 0.5
inlet_angle = 43.0            # deg from axial
reynolds = 5.0e5              # rho1 V1 c / mu1
# gamma = 1.4, t01 = 288.15, avdr = 1.0

[viscous]
ncrit = 9.0
xtr_upper = 1.0               # forced transition x/c (1 = free)
xtr_lower = 1.0

[sweep]                       # optional
parameter = "flow.inlet_angle"
start = 35.0
stop = 51.0
step = 2.0
```

`[panel]` (`n_panels`, `cosine_fraction`) and `[euler]` (grid size, CFL,
dissipation, coupling cycles) hold numerical settings. Unknown sections or
keys are rejected with the list of valid ones. See `examples/` for
compressor, turbine, sweep, Euler, MISES-blade-file and aerofoil-file cases.

### Aerofoil coordinates (Selig or Lednicer)

Any aerofoil from the UIUC database, XFOIL or a CAD export can be placed in a
cascade. The section is scaled to the chord, rotated by the stagger angle and
spaced at the pitch:

```toml
[geometry]
type = "selig"
file = "naca4412.dat"   # relative to the config file; or coordinates = '''...'''
stagger = 30.0          # chord angle from axial [deg]
solidity = 1.2          # c/s, or pitch = s/c
# chord = 1.0           # scale factor
# flip = false          # mirror the section, swapping suction and pressure sides
```

- **Selig order**: an optional name line, then `x y` from the trailing edge
  over the upper surface to the leading edge and back along the lower surface.
  Clockwise files are reversed automatically.
- **Lednicer**: a name line, a line with the upper and lower point counts, then
  each surface from the leading edge to the trailing edge.
- Commas, tabs and `#` comment lines are accepted. Blunt trailing edges are
  handled as for any other blade. Coarse files are re-panelled with a spline,
  and a 69-point file solves within 1 % of a 481-point one.
- With positive camber and positive stagger the blade turns flow of positive
  inlet angle towards axial, like a compressor. For a blade that turns flow the
  other way, use `flip = true` with a negative stagger.
- On the dashboard, choose **Airfoil** on the Analyze tab, then paste
  coordinates or open a `.dat` file. The cascade preview updates as you type,
  and **Run solver** analyses it in the browser.

Outputs: loss `omega = (p01 - p02)/(p01 - p1)` and the exit-based loss,
mixed-out exit angle and Mach number, deviation, incidence, diffusion
factor, Zweifel coefficient, surface isentropic Mach number and Cp, and
boundary-layer distributions (theta, delta*, H, Cf, Re_theta, N or
sqrt(C_tau)) with transition and separation locations.

## Verification

`pymises verify` runs 12 cases; all pass (report in `data/verification.md`).

| Case | Reference | Result |
|---|---|---|
| panel_manufactured | exact periodic potential flow (source/sink/vortex rows; blade = dividing streamline) | max surface-speed error 0.22 % of V1, exit angle within 0.0004° |
| panel_convergence | same, 60/120/240 panels | observed order 2.1 |
| panel_isolated_joukowski | exact Joukowski aerofoil | lift within 0.25 %, surface speed within 0.45 % |
| bl_blasius | Blasius | theta, Cf, H within 0.9 % |
| bl_hiemenz | Hiemenz stagnation flow | within 0.6 % |
| bl_turbulent_flatplate | Coles–Fernholz Cf | within 4 % |
| bl_transition_michel | Michel's criterion (validation) | Re_theta,tr within 3.3 % |
| loss_mixing | exact incompressible mixing (Lieblein leading term) | within 0.002 % |
| loss_conservation | conservation laws | machine precision |
| euler_freestream | free-stream preservation on a skewed grid | machine precision |
| euler_nozzle_shock | quasi-1-D Laval nozzle, normal shock | shock position and p0 ratio within 0.15 % |
| euler_vs_panel | panel method at M1 = 0.2 (inviscid) | Mis RMS difference 0.4 %, exit angle within 0.002°, Euler numerical loss 0.18 % of q |

The unit tests (`tests/`, 104 tests) cover every module, including the
configuration runner and the command line.

## Dashboard

`index.html` is the Cascade Lab dashboard: operating-point analysis, loss
buckets, Euler Mach fields, the verification report, configuration files and
the Python source. It loads a precomputed case library (`data/`, generated by
`tools/precompute.py`). When it is served over the web (for example GitHub
Pages), `worker.js` loads Pyodide and runs pymises itself in the browser, so
any blade and operating point can be solved live, including an aerofoil pasted
or opened in Selig or Lednicer format. The site ships a `.nojekyll` file so
GitHub Pages publishes `pymises/__init__.py`.

## Known limitations

- The panel model is incompressible with a Karman–Tsien correction. It is
  meant for subsonic surface Mach numbers; runs with a peak Mis above 1 carry a
  warning, and the Euler solver should be used instead.
- The Euler solver uses an algebraic H-grid. Its spurious total-pressure loss
  is about 0.1–0.3 % of the inlet dynamic head at default resolution. The
  default convergence tolerance (`[euler] tol = 1e-3`, `mass_tol = 2e-4`) adds
  up to about 0.3 % more; tighten both by a factor of ten for inviscid runs
  that need an accurate loss. With transpiration (viscous) coupling, very long
  runs at tight tolerance can diverge, so keep the defaults there. Strongly
  cambered turbine passages use milder wall clustering and converge more
  slowly. A viscous Euler case takes two to seven minutes natively.
- Panel and Euler losses agree within about 0.004 for the compressor at
  M1 = 0.5, but differ by a factor of about 1.7 for the turbine example
  (inlet-q loss 0.164 panel against 0.094 Euler). The two inviscid solutions
  load the turbine suction surface differently, which moves transition and
  the trailing-edge boundary layer; treat turbine loss levels as indicative.
- Blunt trailing edges are closed over the last 8 % of chord for the
  inviscid solution; the original thickness enters the mixed-out loss as base
  blockage. There is no wake boundary-layer march: the loss is mixed out from
  the trailing-edge integrals.
- Transition is located inside the transition interval (sub-interval
  treatment), but massive separation and stall are outside the model's range.
  About 5 % of the library points (near stall or with supersonic leading-edge
  spikes) do not fully converge and are flagged.

## Layout

```
pymises/        solver package
  geometry.py   blades, MISES blade files, parametric sections
  panel.py      periodic panel method and interaction matrix
  boundary_layer.py  closures, march, Newton coupling, transition
  euler.py      finite-volume Euler solver and H-grid
  losses.py     mixed-out analysis
  solver.py     coupled cascade analysis (CascadeSolver)
  config.py     TOML / JSON / YAML runner      io.py  outputs and plots
  cli.py        command line                   verification.py  verification suite
  webapi.py     JSON API used by the dashboard
tests/          pytest suite
examples/       example configuration files and a MISES blade file
tools/precompute.py   builds data/ for the dashboard
data/           case library, Euler solutions, verification report
index.html, worker.js   dashboard
```

## References

- M. Drela and M. B. Giles, "Viscous-inviscid analysis of transonic and low
  Reynolds number airfoils", AIAA Journal 25(10), 1987.
- M. Drela and H. Youngren, *A User's Guide to MISES 2.63*, MIT, 2008.
- M. Drela, *XFOIL 6.9* source (boundary-layer closures, BLPAR constants).
- A. Jameson, W. Schmidt and E. Turkel, AIAA Paper 81-1259, 1981.
- S. Lieblein and W. H. Roudebush, NACA TN 3662, 1956.
