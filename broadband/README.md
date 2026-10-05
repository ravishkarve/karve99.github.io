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
| Trailing-edge self noise | same | same | 9 wall-pressure models, BPM / flat-plate / user / file boundary layers, Corcos coherence |
| Trailing-edge self noise, thesis form | thesis eq. 3.18 (`eq3.18`) | thesis eq. 5.7 (`eq5.7`) | coded as printed in the thesis; medium at rest |
| Rotor-wake interaction, thesis form | — | thesis eq. 2.73 (`eq2.73`) | coded as printed; Gaussian wake train of eqs. 2.12–2.15; medium at rest |

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

**Thesis equations 3.18 and 5.7** (`bbnoise/thesis.py`). Blandeau's own trailing-edge models are
coded exactly as printed, as two more formulations (`"formulations": ["eq3.18", "eq5.7"]`, CLI
`--formulation eq3.18`). Eq. 3.18 is the exact model:

```
S_pp = B/(2π) (k₀b/r₀)² Δr Σ_l D_l |ℒ_TE(0, K_X,l, κ_l)|² S_qq(0, K_X,l)
D_l  = strip average of (l cos α/(k₀r) + cos θ sin α)² J_l²(k₀ r sin θ)            (3.15)
κ_l  = (l/r) sin α − k₀ cos α cos θ,   K_X,l = (ω + lΩ)/U_c                        (3.17, 3.8)
```

Eq. 5.7 is Amiet's approximate model in the same notation: ω_φ = ω(1 + M_φ cos φ sin θ),
κ_φ = k₀(sin θ sin α cos φ − cos θ cos α), and D_φ = (cos θ sin α + sin θ cos α cos φ)².

Both use:

* ℒ_TE from eqs. 3.19–3.20 (no back-scattering), with 1/Θ_b replaced by 1/(b|k_X| + b|κ|).
* S_qq = (1/π)(l₂/π) Φ_pp, where l₂ = ζ₂U_c/ω, ζ₂ = 1.6 and U_c = 0.8 U_X.
* A double-sided Φ_pp, summed over both sides of the blade.
* θ measured from the downstream axis, and α (stagger) measured from the rotor axis.

The medium is at rest, as in the thesis. A warning is added when the case has flight speed. In
the combined totals these self-noise curves are paired with the thesis' interaction model
(eq. 2.73, below) when it is run, as in the thesis' chapter 4. Otherwise they are paired with the
full (eq. 3.18) or simplified (eq. 5.7) interaction noise. Eq. 3.18 is summed over (frequency, mode) pairs in one vectorised
pass with 4-point Gauss averaging across each strip. That matches 8 points to 0.001 dB, and a
10-strip, 40-frequency spectrum takes about 1 s.

What the implementation shows:

* **Eqs. 3.18 and 5.7 agree** to 0.002 dB above ~15 shaft orders, which reproduces the chapter 5
  conclusion.
* **Doppler pairing.** As printed, the Doppler shift in eqs. 3.8 / 5.1 is paired with the
  chordwise coupling in the opposite sense to an independent derivation (the full formulation
  above). Evaluated literally (`options.thesis_doppler_sign = 1`, the default), eq. 3.18 is 2–8 dB
  below the full formulation at high frequency. With the pairing mirrored (`-1`, i.e. ω − lΩ) it
  agrees within 0.9 dB; the residual comes from the 1/(b|k_X|+b|κ|) factor. Both options are in
  the dashboard.

**Thesis equation 2.73** (`bbnoise/thesis.py`, formulation `eq2.73`) is Blandeau's simplified
model for rotor-wake/rotor interaction (BRWI), which the thesis uses in chapter 4:

```
S_pp = B₂/4 (B₁ρ₀k₀b₂/r₀)² U_X2 Δr Σ_m Σ_h D′_ml Φ_ww(0, K_X,mh) |ℒ_LE(0, K_X,mh, κ_mh)|²
D′_ml  = strip average of f_m²(r) (l cos α₂/(k₀r) + cos θ sin α₂)² J_l²(k₀ r sin θ)          (2.74)
l = mB₁ − h,   K_X,mh = (ω + mB₁Ω₁ + hΩ₂)/U_X2
κ_mh  = k₀ cos α₂ cos θ + mB₁(Ω₁+Ω₂)/U_X2 − (h/r) sin α₂                                 (2.50)
f_m   = exp(−(m/σ)²/2) / (B₁σ√(2π)),   σ = r√(2a)/(B₁b_W),   a = 0.637                   (2.15)
```

The pieces:

* The wake is a train of Gaussian velocity profiles exp(−aη²/b_W²) (eq. 2.12) with centreline
  rms w_rms, and L = 0.42 b_W (eq. 2.78).
* Φ_ww is the 2D von Kármán spectrum (eq. 2.59).
* ℒ_LE is Amiet's response with Roger's second-order term. With the kernel e^{+iκX} of eq. 2.49 it
  is evaluated at q̄ = −κb.
* The sum runs over m = ±4σ and l = ±(1.25 k₀ r sin θ + 3), as in thesis §2.3.

In the homogeneous limit (overlapping wakes, where only m = 0 remains), eq. 2.73 reproduces the
independent full formulation to within 0.6 dB at all angles and frequencies, once two things are
changed:

* the Doppler pairing is mirrored (`thesis_doppler_sign = -1`, the same issue as in eq. 3.18), and
* the result is multiplied by 2π (`options.thesis_brwi_2pi`).

As printed it is 2π (8 dB) lower.

**Rotor-wake interaction** (`bbnoise/turbulence.py`). The front-rotor wakes carry turbulence with
a Gaussian intensity profile (semi-width L_w) repeated with the front pitch. The modulated field is
frozen in the fluid, so the rear-rotor upwash spectrum is a sum of shifted spectra weighted by the
envelope's Fourier coefficients. It is centred on multiples of the wake-passing frequency
B₁(Ω₁+Ω₂)/2π. The passage-averaged option keeps only the mean square.

**Wall-pressure models** (`bbnoise/wallpressure.py`): Amiet (1976), Chase–Howe (Howe 1998),
Goody (2004), Kim & George (thesis eqs. 3.25–3.26), Rozenberg as written in the thesis
(`rozenberg_2010`, eq. 3.27, with Coles' wake parameter from eq. 3.28 and δ = 8δ* if δ is not given),
Rozenberg, Robert & Moreau (2012), Kamruzzaman et al. (2015), Lee (2018), and VKI's
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
bbnoise case bpm_naca0012_te --set airfoil.U=39.6 --set brte.boundary_layer.alpha_deg=4
bbnoise run examples/propeller.toml -o out     # your own case file (TOML or JSON)
bbnoise run examples/cror_files.toml -o out    # chord and boundary layers read from table files
bbnoise template blade blade.csv               # blank blade table (r_over_R, chord, stagger_deg)
bbnoise template bl bl.csv                     # blank boundary-layer table
bbnoise example cror_takeoff my_case.json      # start from a literature case
bbnoise wps --Ue 50 --delta-star 0.002 --beta-c 2   # compare the wall-pressure models
bbnoise mcode path/to/launch.m -o OUTPUT      # MATLAB-code port: same inputs, same output files
bbnoise template mcode_bl bl_1.txt               # boundary-layer file (R, delta, delta*, theta, ...)
bbnoise verify -o data                         # verification suite
bbnoise serve                                  # dashboard at http://127.0.0.1:8000
python -m pytest                               # 123 tests (MATLAB example with MCODE_DIR set)
```

The case format is documented in `examples/propeller.toml`, `examples/user_inputs.toml` and the
module docstring of `bbnoise/model.py`. Every setting can also be edited as JSON in the dashboard.

## User inputs

**Naming.** The case sections follow the thesis: `brwi` (broadband rotor-wake/rotor interaction
noise of the rear rotor) and `brte` (broadband rotor trailing-edge, or self, noise). Spectra,
totals and dashboard tabs use the same names. The earlier section names `rwi` and `self_noise` are
still accepted and renamed on loading.

**Custom rotors.** Each rotor takes a radial distribution of the chord, and optionally of:

- `stagger_deg`: the blade stagger measured from the rotor axis (α in the thesis).
- `U_X`: the chordwise relative speed [m/s].

They can be given as a scalar, a list from hub to tip, `{"r_over_R": [...], "value": [...]}`, or
blade-table columns. Without them, each strip is aligned with the relative inflow (Ωr, Uₓ) and U_X
is the inflow speed. With a stagger, the strip keeps its orientation, and U_X defaults to the
component of the inflow along the chord. The strip table reports the resulting angle of attack.

Stagger and U_X enter every model:

- the chordwise and normal directions of the rotating dipoles (full formulation, eqs. 2.73 / 3.18);
- the blade-frame axes of the simplified formulation;
- the gust convection speed and the wake-passing wavenumber of BRWI;
- the boundary-layer estimates of BRTE.

The rear rotor's strips are the BRWI input. `custom_cror` is a template with strongly varying chord
and stagger on both rotors; the dashboard's blade table edits chord, stagger and U_X side by side.

**Interaction noise (BRWI and ingestion).** Homogeneous turbulence (`turbulence` for an airfoil, `ingestion` for a rotor)
takes the turbulent kinetic energy `tke` [m²/s²] or an `intensity`, and the integral length scale
`Lambda` [m]. For isotropic turbulence k = 3 w_rms²/2. Front-rotor wakes (`brwi.wake`) take one of:

- `tke_c`, the wake-centreline TKE [m²/s²].
- `tke_mean`, the TKE averaged over a front-rotor passage. It equals k_c (L_w/s₁)√(π/ln2).
- `tu_c`, the centreline intensity relative to the front-blade speed.

They also take the wake semi-width `Lw_over_s`, and `Lambda` [m] or `Lambda_over_Lw`.

**Self noise (BRTE).** Set `brte.boundary_layer.method = "user"` and give `suction`, `pressure`
(or `both`) with any of:

- `delta_star_over_c`, `delta_over_c` and `theta_over_c`, or the same without `_over_c` in metres.
- `H`, `cf` and `beta_c` (or `dpdx`), `Pi`, and `Ue_over_U`.

Only δ* is required, or θ with H. The rest is estimated with Ludwieg–Tillmann (C_f), Drela (δ)
and Durbin–Reif (Π).

**Radial variation.** On rotors, the chord and any of these values may vary along the blade as
`{"r_over_R": [...], "value": [...]}`. Values are interpolated linearly between the given radii and
held constant beyond them. Wake quantities use r/R of the front rotor. Each rotor can have its own
boundary layers under `brte.boundary_layers.<rotor>`, which overrides the shared
`brte.boundary_layer`.

**Table files.** Chord and boundary layers can be read from CSV, TSV or whitespace-separated tables
(the format is described in `bbnoise/tables.py`):

- **Blade table,** `rotors[i].blade_file`: columns `r_over_R` (or `r` in metres) and `chord` [m], and
  optionally `Ux` [m/s], `stagger_deg` [deg] and `U_X` [m/s].
- **Boundary-layer table,** `brte.boundary_layer = {method = "file", path = "bl.csv"}`: one row
  per radius and side, with a `side` column (suction or pressure). The wide format with column
  prefixes such as `suction_H` and `pressure_delta_star_over_c` also works. Any quantity listed
  above can be a column, and blank cells are estimated. Without a radius column the table has one
  row per side, for a stationary airfoil.

Paths are relative to the case file. `examples/cror_files.toml` uses a different table for each rotor.

**Per-strip contributions.** Every rotor spectrum keeps the contribution of each radial strip at the
main observer. The strip energies add up to the total. The CLI writes `*_strips.csv` (strip OASPL
and energy share), `*_strip_psd.csv` (the PSD of every strip) and `*_strips.png`.

**Outputs.** Every spectrum is tagged as interaction (BRWI, ingestion) or self noise (BRTE). The results
add, for each formulation, the total BRWI, the total BRTE and their sum. Each total uses the
first listed spectrum or wall-pressure model of every mechanism.

## Dashboard

- **Inputs:** geometry and operating point, with an editable blade table per rotor (chord, stagger,
  chordwise speed) and blade-file upload. Interaction-noise inputs are set by TKE or intensity with Λ. Self-noise inputs cover the
  wall-pressure models and BPM, flat-plate or user boundary layers. User boundary layers are uniform
  or vary along the blade, can be loaded from a file, and can be shared or set per rotor. Buttons
  fill them from the BPM correlations and download templates.
- **BRWI · interaction:** spectra, directivity, the contribution of each radial strip and the
  turbulence actually used, including the wake TKE along the rear blade.
- **BRTE · self noise:** spectra, directivity, the contribution of each radial strip, the boundary-layer
  parameters along the blade, and the mid-span boundary layers and wall-pressure spectra.
- **Strip contributions:** three views: OASPL of each strip along the blade for every spectrum, a
  radius × frequency map of the strip PSDs, and a table with each strip's share of the energy.
- **BRWI + BRTE:** pick one spectrum or model per mechanism and see the interaction,
  self and total spectra and directivity for each formulation.
- **MATLAB-code cases** (`mcode_cror`, `mcode_bl_ingestion`, or a loaded launch file): the Inputs tab
  follows the MATLAB code. It shows the `opt.*` settings (load or download `launch.m`), geometry and conditions
  (load a CaseInputs `.mat`), the four boundary-layer files, the wake table (load `Wake_data.mat`) and
  the BL-ingestion table.
- **Verification** and **Theory.**

## Literature cases

| Key | Source | What it checks |
|---|---|---|
| `paterson_amiet_1976` | Paterson & Amiet, NASA CR-2733 (1976) | NACA 0012 in a turbulent jet; LE noise with both spectra, U⁵–U⁶ scaling |
| `bpm_naca0012_te` | Brooks, Pope & Marcolini, NASA RP-1218 (1989) | TE noise with the original seven wall-pressure models |
| `rozenberg_apg_te` | Rozenberg (2012), Kamruzzaman (2015), Lee (2018), Dominique (2021) | pressure-gradient-aware models under APG |
| `blandeau_joseph_2011` | Blandeau & Joseph, AIAA J. 49(5) (2011) | full vs simplified rotating TE noise |
| `rotor_turbulence_ingestion` | Amiet, AIAA J. 15(3) (1977) | rotor in homogeneous turbulence |
| `garcia_sagrado_naca0012` | Garcia Sagrado (2008) via Blandeau (2011) §3.3, Table 3.1 | measured TE boundary layer (δ*, C_f, dp/dx) of a NACA 0012 at 20 m/s; wall-pressure model ranking of the thesis (Rozenberg best shape, Kim–George high at mid/high frequency) |
| `custom_cror` | template | user rotors: radially varying chord and stagger on both rotors driving BRWI and BRTE (full + thesis eqs.) |
| `blandeau_cror_takeoff`, `_cruise`, `_approach` | Blandeau (2011) §4.2, Table 4.1, Figs. 4.4–4.7 | baseline 10 × 9 CROR (R = 2.0/1.8 m, tip Mach 0.5): chord, U_X, δ*/c and wake w_rms, L digitised from the thesis; thesis pair eq. 3.18 + eq. 2.73, and the full formulation |
| `cror_takeoff`, `cror_wake_models` | Blandeau (2011); Blandeau, Joseph, Kingan & Parry, IJA 12(3) (2013) | CROR RWI + self noise, periodic vs averaged wakes |

Geometries and operating points follow the cited papers. The two CROR cases use an illustrative
1/5-scale 12 × 10 geometry and wake parameters, not rig data. Measured spectra are not bundled.

## MATLAB-code port (`type = "mcode"`, `bbnoise mcode`)

`bbnoise/mcode/` implements the models of Blandeau's thesis as a line-by-line port of a MATLAB
implementation of them. It reads that code's inputs in the same layout and writes the same output
files, so an existing MATLAB run folder works unchanged:

```bash
bbnoise mcode path/to/examples/launch.m                # writes the .dat files and output.mat
bbnoise mcode launch.m -o OUT --set noise_type="'BRTE'" --set f_num=24
```

**Inputs (as in the MATLAB code).**

- `launch.m`: the `opt.*` settings. The MATLAB expressions used there are parsed: `[30 60]*pi/180`,
  `(10:20:170)`, cell arrays and comments. The dashboard loads and saves this file.
- `INPUT/<CaseInputs>.mat`: the `geom` structure (B1, B2, r1, r2, c1, c2, alpha1, alpha2, s1, s2,
  eta, scale, c_pylon) and the `cond` structure (Omega1, Omega2, Mx, c0, rho, AoA1, AoA2, Cd, and Ux1,
  Ux2 for LPC2 inputs). As in the MATLAB code, arrays are resampled onto the strips by index, not by radius.
- **Boundary-layer files** (`opt.BL_folder`, `opt.bl_files`): front top, front bottom, rear top,
  rear bottom. Each has one header line, then one row per strip with 13 columns:

  | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | R [m] | δ | δ* | θ | unused | τ_max | dp/dx | ρ_wall | U_∞ | Π (wake parameter) | ν_wall | τ_wall | discard flag |

  `bbnoise template mcode_bl` writes an example file. In the dashboard each of the four files can be
  loaded, previewed and edited.
- `Wake_data.mat`, holding bw, wrms_bg, wrms_wake, L_bg and L_wake per strip. Like the MATLAB code, the port
  also reads a folder holding `bw.txt`, `urms.txt` and `L.txt`.
- For BL ingestion (`BPRI_BL`), the table `z ua la ut lt` (`bbnoise template mcode_ingestion`).

Case files take the same inputs inline (`options`, `inputs`, `bl_files`, `wake`,
`bl_ingestion`; see `bbnoise/mcode/case.py`). The examples `mcode_cror` and `mcode_bl_ingestion` use
made-up inputs (`bbnoise/mcode/synthetic.py`).

**What is ported.**

- Rotor noise:
  - BRWI and BRTE, both full and Amiet.
  - All the wall-pressure, U_c and l_r options.
  - Chapman, the emission angle, contraction and LPC2 inputs.
  - Wake and background turbulence.
- Installation noise: BPRI_BL (boundary-layer ingestion) with the hard wall, partial loading and
  blade-to-blade correlation.
- Post-processing:
  - SPL, PWL, 1/3-octave PWL and every `.dat` file of `pp.m`;
  - the BPRI_BL files of `pp_pylon.m`;
  - the `results` structure in `output.mat`.

**Agreement.** The MATLAB code was run in GNU Octave 8.4 and compared with the port:

- The MATLAB code's own example (BPRI_BL, hard wall): the port matches the `output.mat` that MATLAB wrote
  (spectra to 2e-14, interference terms to 1.3e-13, and the `results` structure). The `.dat` files
  shipped in `examples/OUTPUT` are left over from an older run: the MATLAB code writes none for this example.
- 27 further reference runs match to 3e-13 or better (most to 2e-14) and give byte-identical `.dat`
  files, apart from the directivity files' first line, which names bbnoise. In 5 more,
  the MATLAB code itself stops with an error, and the port stops at the same point. The runs cover:
  - BRWI with von Kármán, Liepmann and Pope;
  - BRTE, full and Amiet, with the WA/CH/GY/KG/RZ models, 0.8/GLB/DEL/DEL2 convection,
    COR/ROG/LGL/RGS/CORL/EFP/SLZ correlation lengths, the empirical correction and discard;
  - Chapman, the emission angle, directivity and LPC2 inputs;
  - BPRI_BL with and without correlation, with and without partial loading, including the
    `pp_pylon.m` files and `results`.

  `tests/test_mcode.py` checks synthetic references (`tests/data/mcode`) and the CLI file route. With
  `MCODE_DIR` set to the unpacked MATLAB code folder, it also checks that code's own example.

For Octave, the MATLAB code needed three compatibility shims. None of them changes a model:

- `bl = struct()` before a field assignment in `inputs_pylon.m`;
- MATLAB's outward bracket search for `fzero` from a scalar start;
- saving a raw `Spps.mat` before `pp.m`.

**The MATLAB code's behaviour is kept, including its quirks.**

- MATLAB rounding, index interpolation and colon ranges with array operands.
- Complex `log10` and powers.
- The least-squares `/` in the BRTE_amiet CH/KG/RZ models and in BPRI_BL.
- The `erfz` series of the MATLAB code.
- The flipped θ order in BRTE_amiet.
- `c0 = 350` in the hard-wall model.
- With Goody's model (`phi_sw = 'GY'`), `delta = 8 delta*` is overwritten, so the l_r model that
  follows (LGL, CORL, EFP, …) also sees 8δ*.
- `pp.m` writes `BRTE2_directivity.dat` even for a single rotor, and stops there.

Where the MATLAB code itself stops with an error, the port raises `MCodeError` and says why:

- BRWI with `amiet` (`flow.L` undefined);
- BRTE_amiet with `Uc = 'DEL2'`;
- `amiet` with an l_r model other than COR/ROG/LGL;
- the empirical wake model (`CFD_data = false` with BRWI);
- `L = 'BW'` with background turbulence;
- contraction other than 0 % or 100 %;
- 1/3-octave PWL unless f_l ≤ 89 Hz and f_h ≥ 11.3 kHz. For BPRI_BL, `pp_pylon.m` instead warns, sets
  the PWL to -999 and writes no files, as with the MATLAB code's own example (f 300–3000 Hz);
- BPRI_BL PWL files with fewer than three azimuthal observers (`pp_pylon.m` writes
  `PWL_B1(1:3,:,:)`).

When the MATLAB code would stop in post-processing, `bbnoise mcode` prints the reason and still saves
`output.mat` with the spectra.

The XFOIL boundary-layer route (`CFD_data = false` for BRTE) is not available. Supply boundary-layer
files instead.

**Levels.** The `SPL_*.dat` files use 10 log₁₀(8π S_pp / p_ref²). The `*_directivity.dat`
files, and the dashboard PSDs, use 4π |S_pp|, the one-sided PSD per hertz. PWL is
10 log₁₀(4π |P₁| / 10⁻¹²) + 30 log₁₀(scale).

## Verification (`bbnoise verify`, 18/18 pass)

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
* Thesis eq. 3.18 vs eq. 5.7: within 0.002 dB above 15 shaft orders.
* Thesis eq. 3.18, with the Doppler pairing mirrored, vs the full formulation: within 0.9 dB.
* Thesis eq. 2.73 with overlapping wakes, the pairing mirrored and ×2π, vs the full formulation:
  within 0.6 dB.
* `rozenberg_2010` reduces to Goody at zero pressure gradient to 0.1 dB.
* The TE response has no jump across the critical gust k_y = μ̄β, and it stays bounded beyond it.

## Modelling notes and choices

* **Doppler exponent.** With the observer at the reception time, Amiet's stationary formula
  already contains the moving-dipole amplification (1 − M_r)⁻². Averaging over observer time then
  needs (ω_s/ω)², and the verification confirms it against the exact series. The default is
  p = 2. Set `options.doppler_exponent = 1` for Amiet's original factor.
* **Spanwise wavenumber in the full model.** Each azimuthal mode uses the local radial wavenumber
  of Jₙ. Using k_y = 0 instead (`spanwise=False` in `full_spectrum`) leaves up to about 7 dB of disagreement
  with the simplified model near the rotor plane.
* **Subcritical gusts.** In flight, the full formulation reaches modal spanwise wavenumbers with
  k_y > μ̄β. There κ = −iκ′ is taken on the branch whose pressure field decays upstream of the
  trailing edge, and the back-scattering term, which is negligible there and overflows, is dropped.
  The other branch made the front-rotor self noise of the thesis CROR diverge above 5 kHz.
* **Wall-pressure spectrum convention.** The thesis writes Φ_pp double-sided in ω (§3.2.1).
  `bbnoise` stores one-sided spectra. Eq. 3.21 (Amiet) is therefore doubled, and `bbnoise.thesis`
  halves the models again. Evaluated this way for Garcia Sagrado's 20 m/s boundary layer, the
  models sit about 3 dB below the thesis' Fig. 3.6, which suggests that figure is plotted one-sided.
* **Thesis CROR cases (Fig. 4.7).** The wake inputs use the thesis profile (eq. 2.12, a = 0.637)
  with w_rms and L from Fig. 4.6 and b_W = L/0.42. The interaction-noise sound-power peak, relative
  to the total trailing-edge peak:

  | condition | Fig. 4.7 | thesis pair (eqs. 3.18 + 2.73, as printed) | full formulation |
  |---|---|---|---|
  | take-off | ≈ −4 dB (1.6 kHz vs 250 Hz) | +8.7 dB (1.8 kHz vs 170 Hz) | +16.4 dB |
  | cruise | ≈ −20 dB (8 kHz) | −6.8 dB (9.8 kHz) | −0.9 dB |
  | approach | ≈ −24 dB (5.5 kHz) | −14.2 dB (6.1 kHz) | −9.7 dB |

  The thesis pair reproduces the peak frequencies and the trend with operating condition: trailing
  edge dominant at cruise and approach, and interaction noise rising at take-off. However, it puts
  the interaction noise a nearly constant 10–13 dB higher relative to the trailing-edge noise than
  Fig. 4.7 does.

  The two corrections found above (the Doppler pairing and 2π) both raise the interaction noise,
  so they do not explain this offset. Its constancy points to a normalisation or input difference
  in the thesis' own computations, which the printed equations do not show. Two candidates are
  the w_rms actually used and the plotting convention. Thesis p. 68 (eqs. 2.75–2.77, the Gliebe
  correlations for b_W and u₀) was not in the pages used; it is not needed here because Fig. 4.6
  gives w_rms and L directly.
* **Evanescent modes** (|n| > K_r R) have their chordwise wavenumber clipped to the range reachable
  by real radiation directions. Otherwise the trailing-edge response hits a spurious hydrodynamic
  coincidence (αK̄ + q̄ = 0).
* **Trailing-edge low-frequency limit.** Amiet's TE response grows as 1/K̄ for K̄ = ωb/U → 0. Source
  frequencies with K̄ < 0.05 (`brte.k_min`) are dropped. This removes spikes near shaft
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
bbnoise/thesis.py         thesis eqs. 3.18 (exact) and 5.7 (Amiet) rotor TE noise, L_TE, S_qq
bbnoise/thesis_cases.py   thesis baseline CROR (Figs. 4.4-4.6) and Garcia Sagrado NACA 0012 data
bbnoise/wallpressure.py   boundary-layer state and the nine wall-pressure models, Corcos
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
bbnoise/mcode/            MATLAB-code port: options/launch (launch.m), inputs (preprocess, inputs,
                          BL and wake files), models (BRWI, BRTE, BRTE_amiet), installation
                          (BPRI_BL hard wall), pp (SPL, PWL, .dat files), mlab (MATLAB semantics)
index.html, web/          dashboard (SVG charts, Pyodide worker)
```
