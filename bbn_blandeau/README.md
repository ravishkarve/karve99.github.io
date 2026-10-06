# BlandeauSouthamptonBBN

Broadband noise of rotors and contra-rotating open rotors after

> V. P. Blandeau, *Aerodynamic broadband noise from contra-rotating open rotors*, PhD thesis,
> Institute of Sound and Vibration Research, University of Southampton (2011).

The `bbn` package computes three sources:

- **Rotor-wake interaction noise (BRWI)** of the rear rotor. The front-rotor wakes and the
  background turbulence are cut by the rear blades. It uses the full rotational formulation
  (thesis ch. 2) with a von Kármán or Liepmann spectrum.
- **Trailing-edge self noise (BRTE)** of either or both rotors. It uses the full rotational
  formulation (thesis eq. 3.18) or Amiet's simplified rotational formulation (eq. 5.7), and six
  wall-pressure models, including VKI's.
- **Boundary-layer ingestion noise** of the front rotor next to a hard wall. It uses Amiet's
  simplified formulation and gives the free-field term, the image source and the two interference
  terms. Partial loading and blade-to-blade correlation are optional.

It comes with a command line and a web dashboard. The dashboard runs the same Python in the
browser through Pyodide, or natively through `bbn serve`.

## Install and run

```bash
pip install -e .                       # numpy, scipy (and tomli on Python < 3.11)
bbn template case case.json            # a complete case to start from
bbn run examples/cror.toml -o out      # results.json, spectra.csv, directivity.csv, sound_power.csv, strips_*.csv
bbn template bl bl_front_top.txt       # templates for the tables: blade, bl, wake, ingestion
bbn serve                              # dashboard at http://127.0.0.1:8000
python -m pytest                       # 23 tests
```

From Python:

```python
import bbn
case = bbn.default_case()                          # or bbn.load("examples/cror.toml")
case["spectra"]["wall_pressure"]["model"] = "vki"
res = bbn.run(case)
print(res.summary())                               # OASPL and PWL per source
res.curves[0].psd                                  # [theta, f] one-sided PSD, Pa^2/Hz
```

## The three input sections

A case is a TOML or JSON file, or a dict, with three sections. `examples/cror.toml` documents
every key, and `bbn/config.py` has the full schema. Tables can be inline, text, or file paths
relative to the case file.

### 1. `rotor`: what the rotor is

| key | meaning |
|---|---|
| `stages` | 1 = single rotor, 2 = contra-rotating pair |
| `mach`, `c0`, `rho` | flight Mach number, speed of sound [m/s], air density [kg/m³] |
| `gap`, `scale` | axial gap between the rotors [m], model scale factor |
| `front`, `rear` | `blades`, `rpm` (or `omega` [rad/s]) and `blade`, the blade table |

The blade table has columns `r` [m], `chord` [m] and `stagger_deg`, measured from the rotor axis
and running hub to tip. `sweep` and `aoa_deg` are optional. The radial strips are placed at equal
fractions of each column. Rotor speeds are magnitudes, and the rotors turn in opposite directions.
You can give axial velocities per station (`axial_velocity`) instead of using the velocity
triangles.

### 2. `noise_model`: which sources, how, and where to listen

| key | meaning |
|---|---|
| `interaction` | rotor-wake interaction noise of the rear rotor (needs `stages = 2`) |
| `self_noise` | `["front"]`, `["rear"]` or both: trailing-edge noise of these rotors |
| `bl_ingestion` | the front rotor ingesting a wall boundary layer |
| `formulation` | trailing-edge noise: `"full"` or `"simplified"` (Amiet). Interaction noise always uses the full formulation, BL ingestion the simplified one |
| `strips`, `azimuth_points` | radial strips; azimuthal integration points of the simplified formulation |
| `frequency` | `{min, max, n}` [Hz], log-spaced |
| `observers` | `{theta_deg, radius}`: polar angles θ* from the upstream flight axis, radius [m] |
| `chapman`, `emission_angle`, `contraction_percent` | mean-flow correction, emission co-ordinates, rear stream-tube contraction (0 or 100 %) |
| `ingestion` | `wall_distance` (from the hub centre) [m], `bl_height` [m], `hard_wall`, `partial_loading`, `blade_correlation` |

### 3. `spectra`: the source spectra

**`interaction`**, the turbulence that the rear rotor cuts:

- `turbulence`: `von_karman` or `liepmann`.
- `length_scale`: a factor C on the tabulated scales, `pope`, or `bw` (0.42 b_w, wake only).
- `wake`: one row per strip with columns `bw` (wake half-width [m]), `wrms_bg`, `wrms_wake` (rms
  velocities [m/s]), `L_bg` and `L_wake` (integral length scales [m]).

**`wall_pressure`**, the boundary layers at the trailing edge:

| `model` | wall-pressure spectrum |
|---|---|
| `willmarth_amiet` | Willmarth & Roos as fitted by Amiet (1976) |
| `chase_howe` | Chase–Howe (Howe 1998) |
| `goody` | Goody (2004); the correlation-length models then use δ = 8δ* |
| `kim_george` | Kim & George (1982) |
| `rozenberg` | Rozenberg, Robert & Moreau (2012), adverse pressure gradient |
| `vki` | VKI gene-expression-programming model: Dominique, Christophe, Schram & Sandberg, *J. Sound Vib.* 506, 116162 (2021) |

The VKI model is

```
Φ Uₑ/(τ_w² δ*) = (5.41 + C_f (β_C+1)^5.41) ω̃ / (ω̃² + ω̃ + (β_C+1) M + (ω̃ + 3.6) ω̃^4.76 / (C_f R_T^5.83))
ω̃ = ω δ*/Uₑ,  C_f = τ_w/(½ρUₑ²),  β_C = (θ/τ_w) dp/dx,  R_T = (δ*/Uₑ)/(ν/u_τ²),  M = Uₑ/c₀
```

The solver uses it, like every other wall-pressure model, as a double-sided spectrum: half the
one-sided value above.

- `convection`: `constant` (0.8 U), `gliebe`, `del_alamo` or `del_alamo_fit`.
- `correlation_length`: `corcos`, `corcos_delta`, `roger`, `roger_delta`, `roger_a110`,
  `efimtsov` or `salze`. The simplified formulation offers `constant`, `gliebe` and `del_alamo`
  convection and `corcos`, `roger` and `roger_delta` correlation lengths.
- `bad_strips`: what to do with strips flagged in the discard column: `ignore`, `replace` (by a
  neighbour) or `discard`.
- `boundary_layers`: `front_top`, `front_bottom`, `rear_top`, `rear_bottom` (top = suction side).
  Each table has one header line, then one row per strip with 13 columns:

  | R | δ | δ* | θ | unused | τ_max | dp/dx | ρ_wall | Uₑ | Π (wake parameter) | ν_wall | τ_wall | discard |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|

  Inline tables use the column names `R, delta, delta_star, theta, tau_max, dpdx, rho_wall, U_inf,
  Pi, nu_wall, tau_wall, discard`.

**`ingestion`**, the turbulence ingested from the wall boundary layer:

- `turbulence`: `von_karman` or `liepmann`.
- `table`: rows of `z ua la ut lt` (wall-normal distance [m], axial and transverse rms velocities
  [m/s] and length scales [m]).
- Or `constants = {ua, la, ut, lt}` instead of the table.

## Results

The results are:

- for each source, the one-sided far-field PSD per hertz at every observer angle;
- OASPL directivity;
- sound power spectral density (rotor sources);
- 1/3-octave levels, for bands wholly inside the computed range;
- strip contributions;
- the strip table (radius, chord, stagger, relative speed, Mach number).

The total is the energy sum of the selected sources. For BL ingestion only the "total" term counts,
which includes the wall.

## Dashboard

`index.html`. The inputs follow the three sections:

1. **Rotor**: operating point, and front and rear rotors with editable blade tables (load a file or
   download a template).
2. **Noise model**: sources, formulation and strips, observers and frequencies, and the
   BL-ingestion wall.
3. **Spectra**: the interaction-noise turbulence and wake table; the wall-pressure model,
   convection and correlation length with the four boundary-layer tables; and the ingested
   turbulence.

**Results** shows the spectra (narrowband, 1/3 octave or table, at any θ*), directivity, sound
power, strip contributions and the strip table. The case can be saved and loaded as JSON. Your
browser keeps the last case.

## Notes

- Arrays are indexed `[strip, rotor, azimuth]`. Spectra are kept double-sided internally;
  results report one-sided values (4π |S_pp|).
- The hard-wall BL-ingestion model uses c₀ = 350 m/s.
- `tests/` checks the solver against stored reference spectra for seven cases built from the
  three input sections:
  - interaction noise with von Kármán and Liepmann spectra;
  - trailing-edge noise, full and simplified, with several wall-pressure, convection and
    correlation models;
  - BL ingestion with and without blade correlation and partial loading.

  The tests also cover the VKI formula, the CLI, the web API and input validation.

## Layout

```
bbn/config.py        the three input sections -> solver runs
bbn/run.py           solver driver
bbn/inputs.py        strips, velocity triangles, boundary-layer and wake tables, observers, frequencies
bbn/models.py        BRWI, BRTE (full and simplified), wall-pressure and correlation-length models
bbn/installation.py  boundary-layer ingestion with a hard wall
bbn/numerics.py      complex error function, index interpolation, root finding
bbn/levels.py        sound power, 1/3-octave bands
bbn/results.py       curves, totals, directivity
bbn/output.py        CSV / JSON output
bbn/examples.py      default case and templates (made-up rotor)
bbn/cli.py           command line;  bbn/webapi.py, bbn/server.py  dashboard back end
index.html, web/     dashboard
examples/            cror.toml with table files, case.json
tests/               pytest suite and reference spectra
```
