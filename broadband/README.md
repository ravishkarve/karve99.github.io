# bbnoise — Broadband Rotor Noise Lab

A Python implementation of the aerodynamic broadband noise models in

> V. P. Blandeau, *Aerodynamic broadband noise from contra-rotating open rotors*, PhD thesis,
> Institute of Sound and Vibration Research, University of Southampton (2011)

with a command-line interface and a web dashboard (live at
<https://karve99.github.io/broadband/>, running the same Python code in the browser through Pyodide).

## What is implemented

| Mechanism | Full formulation | Simplified formulation | Options |
|---|---|---|---|
| Rotor-wake interaction (rear rotor of a CROR) | exact rotating dipole, Bessel series over azimuthal modes | Amiet's azimuthal average | von Kármán or Liepmann spectrum; periodic Gaussian wakes or passage-averaged turbulence |
| Turbulence ingestion (homogeneous inflow) | same | same | von Kármán or Liepmann |
| Trailing-edge self noise | same | same | 7 wall-pressure models, BPM / flat-plate / user boundary layers, Corcos coherence |

**Blade-element response.** Each strip is an Amiet flat plate. The leading-edge response uses
Amiet's high-frequency solution with Roger's second-order trailing-edge correction, or Amiet's
low-frequency compressible Sears solution (automatic switch at μ̄ = π/4). The trailing-edge
response uses Amiet's solution with Roger & Moreau's leading-edge back-scattering term. Both are
written in terms of a general chordwise radiation wavenumber q̄, so the stationary, full and
simplified models share one code path (`bbnoise/airfoil.py`).

**Full formulation** (`bbnoise/rotor.py`). For B independent blades, the far-field PSD is

```
S_pp(x, ω) = B/(4πσ)² Σₙ Jₙ²(K_r R) Dₙ² S_F(ω + nΩ; q̄ₙ, k_y,n)
Dₙ = K_z cos ψ − (n/R) sin ψ,   q̄ₙ = −b (n cos ψ/R + K_z sin ψ),   k_y,n = K_r √(1 − (n/K_r R)²)
```

with K the convected far-field wave vector (uniform axial flow Mx).

**Simplified formulation.** The blade is an airfoil in rectilinear motion at each azimuth Ψ. The
observer is placed in the blade frame at the reception time, and the result is averaged over one
revolution with the Doppler factor (ω_s/ω)^p.

**Rotor-wake interaction** (`bbnoise/turbulence.py`). The front-rotor wakes carry turbulence with
a Gaussian intensity profile (semi-width L_w) repeated with the front pitch. The modulated field is
frozen in the fluid, so the rear-rotor upwash spectrum is a sum of shifted spectra weighted by the
envelope's Fourier coefficients. It is centred on multiples of the wake-passing frequency
B₁(Ω₁+Ω₂)/2π. The passage-averaged option keeps only the mean square.

**Wall-pressure models** (`bbnoise/wallpressure.py`): Amiet (1976), Chase–Howe (Howe 1998),
Goody (2004), Rozenberg, Robert & Moreau (2012), Kamruzzaman et al. (2015), Lee (2018), and VKI's
gene-expression-programming model (Dominique, Christophe, Schram & Sandberg, *J. Sound Vib.* 506,
116162, 2021):

```
Φ Uₑ/(τ_w² δ*) = (5.41 + C_f(β_C+1)^5.41) ω̃ / (ω̃² + ω̃ + (β_C+1) M + (ω̃+3.6) ω̃^4.76 / (C_f R_T^5.83))
ω̃ = ω δ*/Uₑ,   R_T = (δ*/Uₑ)/(ν/u_τ²),   M = edge Mach number
```

## Install and use

```bash
cd broadband
pip install -e .            # numpy, scipy; add [plot] for PNG output, [test] for pytest

bbnoise list                                   # literature cases
bbnoise case cror_takeoff -o out               # run one; CSV, JSON and PNG in out/
bbnoise case bpm_naca0012_te --set airfoil.U=39.6 --set self_noise.boundary_layer.alpha_deg=4
bbnoise run examples/propeller.toml -o out     # your own case file (TOML or JSON)
bbnoise run examples/cror_files.toml -o out    # chord and boundary layers read from table files
bbnoise template blade blade.csv               # blank blade table (r_over_R, chord)
bbnoise template bl bl.csv                     # blank boundary-layer table
bbnoise example cror_takeoff my_case.json      # start from a literature case
bbnoise wps --Ue 50 --delta-star 0.002 --beta-c 2   # compare the wall-pressure models
bbnoise verify -o data                         # verification suite
bbnoise serve                                  # dashboard at http://127.0.0.1:8000
python -m pytest                               # 66 tests
```

The case format is documented in `examples/propeller.toml`, `examples/user_inputs.toml` and the
module docstring of `bbnoise/model.py`. Every setting can also be edited as JSON in the dashboard.

## User inputs

**Interaction noise.** Homogeneous turbulence (`turbulence` for an airfoil, `ingestion` for a rotor)
takes the turbulent kinetic energy `tke` [m²/s²] or an `intensity`, and the integral length scale
`Lambda` [m]. For isotropic turbulence k = 3 w_rms²/2. Front-rotor wakes (`rwi.wake`) take one of:

- `tke_c`, the wake-centreline TKE [m²/s²].
- `tke_mean`, the TKE averaged over a front-rotor passage. It equals k_c (L_w/s₁)√(π/ln2).
- `tu_c`, the centreline intensity relative to the front-blade speed.

They also take the wake semi-width `Lw_over_s`, and `Lambda` [m] or `Lambda_over_Lw`.

**Self noise.** Set `self_noise.boundary_layer.method = "user"` and give `suction`, `pressure`
(or `both`) with any of:

- `delta_star_over_c`, `delta_over_c` and `theta_over_c`, or the same without `_over_c` in metres.
- `H`, `cf` and `beta_c` (or `dpdx`), `Pi`, and `Ue_over_U`.

Only δ* is required, or θ with H. The rest is estimated with Ludwieg–Tillmann (C_f), Drela (δ)
and Durbin–Reif (Π).

**Radial variation.** On rotors, the chord and any of these values may vary along the blade as
`{"r_over_R": [...], "value": [...]}`. Values are interpolated linearly between the given radii and
held constant beyond them. Wake quantities use r/R of the front rotor. Each rotor can have its own
boundary layers under `self_noise.boundary_layers.<rotor>`, which overrides the shared
`self_noise.boundary_layer`.

**Table files.** Chord and boundary layers can be read from CSV, TSV or whitespace-separated tables
(the format is described in `bbnoise/tables.py`):

- **Blade table,** `rotors[i].blade_file`: columns `r_over_R` (or `r` in metres) and `chord` [m], and
  optionally `Ux` [m/s].
- **Boundary-layer table,** `self_noise.boundary_layer = {method = "file", path = "bl.csv"}`: one row
  per radius and side, with a `side` column (suction or pressure). The wide format with column
  prefixes such as `suction_H` and `pressure_delta_star_over_c` also works. Any quantity listed
  above can be a column, and blank cells are estimated. Without a radius column the table has one
  row per side, for a stationary airfoil.

Paths are relative to the case file. `examples/cror_files.toml` uses a different table for each rotor.

**Per-strip contributions.** Every rotor spectrum keeps the contribution of each radial strip at the
main observer. The strip energies add up to the total. The CLI writes `*_strips.csv` (strip OASPL
and energy share), `*_strip_psd.csv` (the PSD of every strip) and `*_strips.png`.

**Outputs.** Every spectrum is tagged as interaction or self noise. The results add, for each
formulation, the total interaction noise, the total self noise and their sum. Each total uses the
first listed spectrum or wall-pressure model of every mechanism.

## Dashboard

- **Inputs:** geometry and operating point, with an editable chord table per rotor and blade-file
  upload. Interaction-noise inputs are set by TKE or intensity with Λ. Self-noise inputs cover the
  wall-pressure models and BPM, flat-plate or user boundary layers. User boundary layers are uniform
  or vary along the blade, can be loaded from a file, and can be shared or set per rotor. Buttons
  fill them from the BPM correlations and download templates.
- **Interaction noise:** spectra, directivity, the contribution of each radial strip and the
  turbulence actually used, including the wake TKE along the rear blade.
- **Self noise:** spectra, directivity, the contribution of each radial strip, the boundary-layer
  parameters along the blade, and the mid-span boundary layers and wall-pressure spectra.
- **Strip contributions:** three views: OASPL of each strip along the blade for every spectrum, a
  radius × frequency map of the strip PSDs, and a table with each strip's share of the energy.
- **Interaction + self noise:** pick one spectrum or model per mechanism and see the interaction,
  self and total spectra and directivity for each formulation.
- **Verification** and **Theory.**

## Literature cases

| Key | Source | What it checks |
|---|---|---|
| `paterson_amiet_1976` | Paterson & Amiet, NASA CR-2733 (1976) | NACA 0012 in a turbulent jet; LE noise with both spectra, U⁵–U⁶ scaling |
| `bpm_naca0012_te` | Brooks, Pope & Marcolini, NASA RP-1218 (1989) | TE noise with all seven wall-pressure models |
| `rozenberg_apg_te` | Rozenberg (2012), Kamruzzaman (2015), Lee (2018), Dominique (2021) | pressure-gradient-aware models under APG |
| `blandeau_joseph_2011` | Blandeau & Joseph, AIAA J. 49(5) (2011) | full vs simplified rotating TE noise |
| `rotor_turbulence_ingestion` | Amiet, AIAA J. 15(3) (1977) | rotor in homogeneous turbulence |
| `cror_takeoff`, `cror_wake_models` | Blandeau (2011); Blandeau, Joseph, Kingan & Parry, IJA 12(3) (2013) | CROR RWI + self noise, periodic vs averaged wakes |

Geometries and operating points follow the cited papers. The two CROR cases use an illustrative
1/5-scale 12 × 10 geometry and wake parameters, not rig data. Measured spectra are not bundled.

## Verification (`bbnoise verify`, 13/13 pass)

* Turbulence spectra integrate to w_rms², and the wake envelope conserves the passage mean square.
* E*(x) matches quadrature. The closed-form TE integral I₁ equals the chord integral of Amiet's
  scattered pressure plus the incident field continued into the wake (−1/(iC)), to 10⁻¹².
* The LE response tends to the compressible Sears limit. Amiet's two branches differ by 1.6 dB at
  the switch.
* The GEP model reproduces Goody within 0.7 dB at zero pressure gradient. Rozenberg reduces to
  Goody within 0.5 dB.
* Velocity scaling is 51 dB/decade for LE noise (Paterson & Amiet) and 45 dB/decade for BPM TE noise.
* **Full vs simplified** at relative Mach 0.6, static and in flight, for LE and TE noise: within
  0.12 dB above ~15 shaft orders, reproducing Blandeau & Joseph's conclusion. Below ~3 shaft orders
  the formulations differ by 1–3 dB.
* Doppler kinematics: with power-law source spectra the simplified model matches the exact Bessel
  series to 0.1 dB when p = 2.

## Modelling notes and choices

* **Doppler exponent.** With the observer at the reception time, Amiet's stationary formula
  already contains the moving-dipole amplification (1 − M_r)⁻². Averaging over observer time then
  needs (ω_s/ω)², and the verification confirms it against the exact series. The default is
  p = 2. Set `options.doppler_exponent = 1` for Amiet's original factor.
* **Spanwise wavenumber in the full model.** Each azimuthal mode uses the local radial wavenumber
  of Jₙ. Using k_y = 0 instead (`spanwise=False` in `full_spectrum`) leaves up to about 7 dB of disagreement
  with the simplified model near the rotor plane.
* **Evanescent modes** (|n| > K_r R) have their chordwise wavenumber clipped to the range reachable
  by real radiation directions. Otherwise the trailing-edge response hits a spurious hydrodynamic
  coincidence (αK̄ + q̄ = 0).
* **Trailing-edge low-frequency limit.** Amiet's TE response grows as 1/K̄ for K̄ = ωb/U → 0. Source
  frequencies with K̄ < 0.05 (`self_noise.k_min`) are dropped. This removes spikes near shaft
  harmonics in the full model.
* **Spectral conventions.** Outputs are one-sided PSDs per hertz. The upwash spectra are two-sided
  in wavenumber (G = 4π S). The wall-pressure models are one-sided in ω (G = 2π S). The TE formula
  uses Amiet's span/2 factor, as in the published MATLAB implementations cross-checked here.
* **Not included:** blade-to-blade correlation (haystacking), the Hu & Herr and Catlett
  wall-pressure models, VKI's neural-network wall-pressure model (it needs TensorFlow, which cannot
  run in the browser), and Efimtsov coherence.

## Layout

```
bbnoise/special.py        Fresnel integrals E*, entire E*(2z)/√z, Sears/Theodorsen
bbnoise/airfoil.py        Amiet LE (L1, L2, low frequency) and TE (I1, I2) responses, force spectra
bbnoise/turbulence.py     von Kármán, Liepmann, periodic/averaged front-rotor wake turbulence
bbnoise/wallpressure.py   boundary-layer state and the seven wall-pressure models, Corcos
bbnoise/boundarylayer.py  BPM NACA 0012 correlations, flat plate, user and file boundary layers
bbnoise/tables.py         blade and boundary-layer table files
bbnoise/rotor.py          rotor geometry, full and simplified formulations, sound power
bbnoise/sources.py        LE and TE blade-element sources
bbnoise/model.py          case runner, results, 1/3-octave bands, directivity
bbnoise/cases.py          literature cases
bbnoise/verification.py   verification suite
bbnoise/cli.py            command-line interface
bbnoise/webapi.py         JSON API (Pyodide worker and local server)
bbnoise/server.py         local dashboard server
index.html, web/          dashboard (SVG charts, Pyodide worker)
```
