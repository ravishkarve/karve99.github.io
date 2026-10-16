# hsprop: performance of very-high-solidity propellers and propfans to Mach 0.8+

`hsprop` predicts the thrust, power and efficiency of propellers whose blades are so wide and
so many that the blade row behaves like a compressor cascade. It covers the regimes where
ordinary blade-element methods fail. At transonic cruise the sections are swept, closely
spaced and near or past Mach 1, and the root passages can choke. At take-off and low speed
the thin sections run at high incidence with leading-edge separation. It runs any geometry
in a few seconds per operating point, from a TOML or JSON file, the command line or Python.

It is validated against the NASA SR-3 and SR-2 propfan wind-tunnel tests. Mean error is 1.6
points of efficiency and maximum error 2.7, from take-off to Mach 0.85 (tables below).

## The model

A load-adapted lifting line carries compressible, swept **cascade** blade elements. Each
element is a blade of an infinite row seen in the plane normal to its sweep. Every
ingredient is in `hsprop/`, and the ones marked ★ are new.

| Physics | Method |
|---|---|
| Blade-to-blade interference | Exact linear periodic thin-aerofoil row theory: Glauert series with Galerkin projection, kernel cot(πζ/P) − P/(πζ), source rows for thickness (`cascade.py`) |
| Compressibility of a dense row ★ | **Prandtl–Glauert lattice map**: the compressible row is the incompressible row of a mapped lattice, s' = s√(sin²ξ + β²cos²ξ), tan ξ' = tan ξ/β, with perturbations scaled by 1/β. It is verified against Euler solutions (table below), where the usual "divide by β" rule is off by up to 29 % |
| Sweep | Independence principle in the normal plane; Küchemann unsweeping of the isobars near the tip |
| 3-D transonic relief ★ | **Spanwise-wavenumber Mach relief**: a disturbance exp(i(k_x x + k_z z)) obeys k_y² = (1 − M²)k_x² + k_z², so it behaves as 2-D flow at M_eff² = M² − (k_z/k_x)². The blade ends at the tip (the hub is a mirror), which gives κ = c_n/(2d + c_n) for the chord-scale field. The leading-edge region, of scale ~x, keeps the actual Mach number. This bounds the 2-D singularity at M_n = 1 and recovers the compressible finite-wing lift slope |
| Non-linear compressibility | Kármán–Tsien with the Lighthill/Riegels nose correction |
| Shock losses ★ | Pocket integral of the **exact normal-shock entropy rise** ln(p₀₁/p₀₂)(M) over the supersonic regions. It reduces to Lock's fourth-power law near drag divergence. A smooth bound by the low-supersonic (Ackeret) section models the terminal shock turning into oblique trailing-edge shocks as M_n → 1. Shock-induced separation follows the equivalent shock Mach number |
| Leading-edge stall at high power ★ | Attainable leading-edge suction (Carlson/Polhamus): the suction the nose cannot carry is drag. When the short bubble bursts, a thick section stalls at the nose. A thin one forms a **long bubble** that keeps the normal force and decambers it progressively (McCullough & Gault). On a swept edge the shear layer rolls up into a **leading-edge vortex** that holds the normal force and returns the lost suction as **vortex lift** (Polhamus analogy) |
| Passage choke at low power ★ | Sonic-throat choke of the dense root sections as a **complementarity condition solved inside Newton**: a strip either passes its flow (χ < 1) or spills just enough to keep its throat sonic (χ = 1). This is the smoothed Fischer–Burmeister function φ(s, 1 − χ) = 0. The spilled flow goes round the strip and its spillage drag is charged |
| Boundary layer ★ | Thwaites / Head integral method with compressibility; Squire–Young drag. **Transition as a random process** (Emmons, Dhawan–Narasimha): spots are born at rates set by Michel's criterion and by laminar separation, and x_tr = ∫ exp(−B) dx is the expected transition point. It is smooth in the edge-speed distribution, so Newton stays quadratic. The default trip is near the leading edge, as on swept rotating blades |
| Thermodynamics | Rothalpy-consistent relative state along the blade |
| Spinner and nacelle | Compressible axisymmetric line-source method (Göthert's rule in the kernel), chord-averaged at each strip. Net thrust includes the body's reaction, so a spinner earns only its real benefit: a lower root Mach number |
| Wake | Load-adapted prescribed helicoidal wake (Theodorsen far-wake pitch, compressible contraction), hub images, chord-scaled filament cores that remove the swept lifting line's near-field artefact |
| Numerics | Newton on circulation and spillage together, with exact local section derivatives, line search and a trust region on incidence; attached-flow homotopy; a pitch trim that brackets from the attached branch (stall hysteresis) |
| Inverse design | Betz–Prandtl optimum loading, every section at ideal (shock-free entry) incidence in its compressible swept row (`design.py`) |

The loss bookkeeping is exact: P − T·V = induced axial + induced swirl + profile + wave +
separation/leading edge + choke + spillage, with the nacelle interaction balanced by the
body reaction.

## Install and run

```bash
cd propfan
pip install -e ".[plot,test]"

hsprop run examples/sr3_cruise_map.toml        # a power sweep; writes ...results.json
hsprop run examples/my_propeller.toml          # your own geometry
hsprop point sr3_class --mach 0.8 --altitude 10668 --J 3.06 --CP 1.7 --radial
hsprop design my_prop.json --mach 0.8 --altitude 10668 --tip-speed 243.8 --CP 1.7 -o designed.json
python tools/validate.py                       # NASA validation + ablation -> data/validation.json
python -m pytest --runslow                     # verification and validation tests
```

A point is either trimmed to a power or thrust coefficient (`CP` / `CT`) or run at a fixed
pitch (`beta75`). The first solve builds a universal lattice table, which takes about 25 s
and is cached in `~/.cache/hsprop`. After that a point takes 2–10 s.

```python
from hsprop import OperatingPoint, PropellerSolver, cases
from hsprop.gas import Atmosphere

prop = cases.reference("sr3_class")             # or Propeller.load("my_prop.json")
sv = PropellerSolver(prop)
op = OperatingPoint(mach=0.8, atmosphere=Atmosphere.from_total(288.15, 101325.0, 0.8), J=3.06)
res = sv.solve_for(op, CP=1.7)
print(res.summary())                             # CT, CP, eta, itemised losses, warnings
res.radial["mach_n"], res.radial["f_attached"]   # radial distributions
```

Geometry is a table of `r_R`, `chord_D`, `beta_deg`, `t_c`, `cl_design` and `mca_D` (sweep as
mid-chord alignment along the chord), with NACA 16/65/4-digit thickness and a = 1 or
parabolic mean lines. Add a spinner or any axisymmetric nacelle (see
`examples/my_propeller.toml`). Every model switch in the tables above can be set in a
`[model]` section, for example `relief_3d = false`, `choke_spill = false`,
`xtr_upper = 1.0` or `vortex_lift = false`.

## Verification

| Check | Result |
|---|---|
| Weinig's exact flat-plate cascade | reproduced to 4 digits |
| Lattice map vs Euler (5 rows, M 0.3 → 0.6–0.75) | lift-slope change within −8.7 … +1.4 % (naive PG: −18 … +29 %) |
| Panel method (pymises) | within 1 % |
| Spheroid surface speed, Göthert's rule | within 0.6 % / 5 % |
| Blasius; turbulent flat plate | within 2 %; 6 % below Schlichting |
| Drag divergence of a 6 % section | equivalent to Korn κ_A ≈ 0.90 |
| Weak-shock entropy law | within 8 % at M = 1.01–1.02 |
| Many-bladed rotor → actuator disk | swirl and axial velocity within 1–3 % |
| Loss bookkeeping | P − T·V equals the itemised losses to 10⁻⁹ |
| Smoothness | transition location, choke and stall are continuous: Newton converges quadratically through all of them |

Lattice-map check against Euler solutions of the same rows (lift-slope ratio between the two
Mach numbers):

| σ | stagger | M | Euler | lattice map | naive PG |
|---|---|---|---|---|---|
| 1.0 | 0° | 0.3 → 0.7 | 1.037 | 1.051 (+1.4 %) | 1.336 (+28.8 %) |
| 1.2 | 20° | 0.3 → 0.7 | 1.168 | 1.134 (−2.8 %) | 1.337 (+14.5 %) |
| 2.0 | 10° | 0.3 → 0.6 | 1.019 | 1.017 (−0.3 %) | 1.193 (+17.0 %) |
| 0.6 | 60° | 0.3 → 0.75 | 1.760 | 1.637 (−7.0 %) | 1.442 (−18.1 %) |
| 1.5 | 40° | 0.3 → 0.65 | 1.390 | 1.269 (−8.7 %) | 1.258 (−9.5 %) |

## Validation against the NASA propfan tests

Two eight-bladed propfans tested at NASA Lewis were reconstructed from their published
descriptions. **SR-3** has 45° tip sweep, activity factor 235, an area-ruled spinner and
design point M 0.8 / J 3.06 / CP 1.7. **SR-2** is straight, with activity factor 203 and a
conventional spinner. The published blade tables were not available, so planform, thickness
and sweep are smooth curves with the published integral properties. Camber and twist come
from `design.py`. Cruise is run at the tunnel's Reynolds number and take-off at sea level.

| Case | Measured | hsprop | Error |
|---|---|---|---|
| SR-3, M 0.80, CP 1.70 (design) | 78.7 % | 77.3 % | −1.4 |
| SR-3, M 0.85, design power loading | 74.3 % | 73.3 % | −1.0 |
| SR-2, M 0.80, CP 1.70 | 75.8 % | 77.1 % | +1.3 |
| SR-3 take-off, M 0.20, J 0.875, CP 1.0 | 54.9 % | 52.2 % | −2.7 |
| SR-2 take-off, same | 50.2 % | 51.9 % | +1.7 |
| SR-3 at lower power, M 0.80 | "above 80 %" | 80.0 % at CP 1.2 | |

SR-3 at its design power loading gives 82.2, 81.4, 79.9, 77.3 and 73.3 % at M 0.6, 0.7,
0.75, 0.8 and 0.85. That is the measured shape: flat to M 0.7, then a steep fall. All
operating points from CP 0.6 to 2.6 at cruise and at take-off converge.

**Ablation** at the SR-3 design point and take-off (efficiency change when one model is
switched off): no 3-D relief +1.8 / +2.2 points; free (Michel) transition +2.1 / +0.4;
isolated aerofoils instead of the cascade +1.1 / 0; no choke spillage −1.1 / 0; cylindrical
instead of swept sections −1.1 / 0; naive Prandtl–Glauert +0.3 / 0; no leading-edge suction
limit +0.1 / **+5.6**.

## Limitations

* The reconstructed geometries are the largest single uncertainty. The model does not
  resolve the measured 3–5 point advantage of the swept SR-3 over the straight SR-2: it
  places both within ±3 points of their data.
* Strip-wise physics: the 3-D relief, Küchemann unsweeping and vortex lift are local models
  of 3-D effects, not a lifting-surface or CFD solution. Strongly supersonic normal Mach
  numbers (M_n > 1.15) use linear (Ackeret) theory.
* Net efficiency includes the body's reaction to the propeller field. Blade-only efficiency
  is reported as `eta_blade`.
* Steady, axisymmetric inflow (no angle of attack), single rotation.

## References

* Jeracki, Mikkelson & Blaha, *Wind tunnel performance of four energy efficient propellers
  designed for Mach 0.8 cruise*, NASA TM-79124 (1979).
* Rohrbach, Metzger, Black & Ladden, *Wind tunnel performance of an advanced 45° swept
  eight-bladed propeller*, NASA CR-3505 (1982).
* Stefko & Jeracki, *Wind tunnel results of advanced high speed propellers in the
  take-off, climb and landing operating regimes*, NASA TM-87030 (1985).
* Mikkelson, Mitchell & Bober, *Summary of recent NASA propeller research*,
  NASA TM-83733 (1984); NASA TM-88969 (1988).
* Weinig (1935); Küchemann, *The aerodynamic design of aircraft* (1978); Polhamus,
  NASA TN D-3767 (1966); McCullough & Gault, NACA TN 2502 (1951); Carlson & Mack, NASA
  TP-1270 (1978); Thwaites (1949); Head (1958); Michel (1951); Emmons (1951); Dhawan &
  Narasimha (1958); Lock (1986); Adkins & Liebeck (1994); Fischer (1992).
