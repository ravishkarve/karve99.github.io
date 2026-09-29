# pymises verification report

12 of 12 cases passed.

| case | metric | value | tolerance | result |
|---|---|---|---|---|
| panel_manufactured | max |q - q_exact| / V1 | 2.165e-03 | 5.0e-03 | pass |
| panel_convergence | observed order of accuracy | 2.138e+00 | 1.5e+00 | pass |
| panel_isolated_joukowski | max |q - q_exact| / V (excluding the cusp) | 4.524e-03 | 2.0e-02 | pass |
| bl_blasius | max relative error (theta, Cf, H) | 8.857e-03 | 3.0e-02 | pass |
| bl_hiemenz | max relative error (theta, H) | 6.096e-03 | 5.0e-02 | pass |
| bl_turbulent_flatplate | max relative error in Cf | 3.924e-02 | 8.0e-02 | pass |
| bl_transition_michel | relative difference in Re_theta at transition | 3.328e-02 | 2.0e-01 | pass |
| loss_mixing | max relative difference | 2.007e-05 | 2.0e-03 | pass |
| loss_conservation | max error | 3.405e-16 | 1.0e-09 | pass |
| euler_freestream | max residual after 50 steps | 8.934e-17 | 1.0e-12 | pass |
| euler_nozzle_shock | max(shock position error / length, p0 error) | 1.506e-03 | 2.0e-02 | pass |
| euler_vs_panel | RMS difference in Mis / mean Mis | 3.811e-03 | 3.0e-02 | pass |

## panel_manufactured

Cascade panel method against an exact periodic potential flow: uniform stream plus periodic rows of a source, a sink and a point vortex; the blade is the dividing streamline, so the exact surface speed and exit angle are known.

Reference: Analytic solution (method of manufactured solutions)

- exit_angle_error_deg: 0.00039291114472561617
- beta1: 43.28341316306672
- beta2_exact: 28.4490962338957
- beta2: 28.449489145040424
- circulation_error: 6.457612914623212e-06
- n_panels: 240
- rms_error: 0.0003571781168988635

## panel_convergence

Grid convergence of the panel method on the manufactured cascade: RMS error of the surface speed for 60, 120 and 240 panels; a second-order method should show an observed order close to 2.

Reference: Richardson analysis against the exact solution

- n_panels: [60, 120, 240]
- rms_errors: [0.006427465011947397, 0.0015716178018785616, 0.0003571781168988635]
- orders: [2.0319994371780914, 2.137534815349247]
- exit_angle_errors_deg: [0.001035768871428644, 0.0012353489309546717, 0.00039291114472561617]

## panel_isolated_joukowski

Isolated cambered Joukowski aerofoil at 5 deg incidence (pitch = 10^4 chords) against the exact conformal-mapping solution: surface speed and lift.

Reference: Exact Joukowski / Kutta-Joukowski solution

- cl_exact: 1.0939559319268986
- cl_panel: 1.0912994979618544
- cl_rel_error: 0.002428282426665085
- rms_error: 0.0012261353081154864

## bl_blasius

Laminar flat-plate boundary layer at Re_x = 10^6 (transition suppressed): momentum thickness, skin friction and shape factor against Blasius.

Reference: Blasius similarity solution (theta = 0.664 x/sqrt(Re_x), H = 2.591)

- theta_ratio: 1.0030856854651349
- cf_ratio: 1.0028985080069783
- H: 2.5680504893084652

## bl_hiemenz

Stagnation-point (similarity) station for ue = a x against the Hiemenz plane stagnation-point flow.

Reference: Hiemenz solution (theta sqrt(a/nu) = 0.2923, H = 2.216)

- theta_ratio: 0.9963571220198558
- H: 2.2295077590552768
- theta_constant_along_xi: 3.722771909958564e-16

## bl_turbulent_flatplate

Turbulent flat-plate boundary layer (Re_L = 10^7, transition forced at the leading edge): skin friction against the Coles-Fernholz correlation for Re_theta between about 2000 and 13000, plus the equilibrium shape factor.

Reference: Coles-Fernholz: Cf = 2 / (ln(Re_theta)/0.384 + 4.127)^2

- re_theta_range: [2153.0846771792, 14494.083616946022]
- H_end: 1.310913900598434

## bl_transition_michel

Natural transition on a flat plate predicted by the e^N envelope method (N_crit = 9) compared with Michel's empirical transition criterion (a validation check: the two models are independent).

Reference: Michel (1951): Re_theta,tr = 1.174 (1 + 22400/Re_x) Re_x^0.46

- re_x_transition: 4012005.0125313285
- re_theta_transition: 1329.991339071429
- re_theta_michel: 1287.159598126033

## loss_mixing

Mixed-out loss of the compressible control-volume analysis in the incompressible limit (M1 = 0.01) against the exact closed-form solution of incompressible constant-area wake mixing (its first-order term is the Lieblein & Roudebush expression 2 (theta/c) (sigma/cos b2) (cos b1/cos b2)^2).

Reference: Closed-form incompressible mixing analysis; Lieblein & Roudebush (1956)

- cases: [{'theta_c': 0.002, 'H': 1.8, 'solidity': 1.1, 'beta1': 45.0, 'beta2': 20.0, 'omega': 0.0026837186623839705, 'omega_exact_incompressible': 0.0026837363737432962, 'omega_lieblein_H1': 0.002670048233833084}, {'theta_c': 0.004, 'H': 2.0, 'solidity': 1.2, 'beta1': 50.0, 'beta2': 25.0, 'omega': 0.005497937512415379, 'omega_exact_incompressible': 0.00549801222464579, 'omega_lieblein_H1': 0.005413744796187196}, {'theta_c': 0.003, 'H': 1.5, 'solidity': 1.0, 'beta1': 30.0, 'beta2': 10.0, 'omega': 0.004771172417138351, 'omega_exact_incompressible': 0.004771084540977308, 'omega_lieblein_H1': 0.0047548097217776815}, {'theta_c': 0.006, 'H': 2.5, 'solidity': 1.4, 'beta1': 55.0, 'beta2': 30.0, 'omega': 0.009184758963048848, 'omega_exact_incompressible': 0.009184943296517688, 'omega_lieblein_H1': 0.008761913754636912}]

## loss_conservation

Mixed-out state of an already uniform flow must reproduce it exactly, and a cascade without boundary layers must have zero mixed-out loss.

Reference: Conservation of mass, momentum and energy

- uniform_error: 3.404683942183813e-16
- zero_bl_loss: 0.0

## euler_freestream

Free-stream preservation of the finite-volume Euler scheme on a skewed, non-uniform periodic grid (uniform flow must remain an exact steady state).

Reference: Discrete conservation / geometric conservation law

- grid: [60, 20]

## euler_nozzle_shock

Quasi-one-dimensional Laval nozzle A(x) = 1 + 2.2 (x - 1.5)^2 with exit pressure p_e/p0 = 0.6784, solved with the 2-D Euler code using the MISES streamtube-thickness term; normal-shock position and total-pressure loss against the exact quasi-1-D solution.

Reference: Exact quasi-1-D isentropic + Rankine-Hugoniot solution

- x_shock_exact: 2.099330576099744
- x_shock_euler: 2.1
- M_preshock_exact: 2.070005751090422
- p0_ratio_exact: 0.6881709726878739
- p0_ratio_euler: 0.6871345763428833
- steps: 8000

## euler_vs_panel

Code-to-code comparison at low Mach number (M1 = 0.2, inviscid): the finite-volume Euler solution against the independent panel method on the C4 compressor cascade (surface isentropic Mach number and exit angle); also reports the spurious (numerical) total-pressure loss of the Euler scheme.

Reference: Panel method (verified against exact solutions above)

- exit_angle_difference_deg: 0.001991960464351905
- euler_numerical_loss: 0.0018897472620785039
- euler_steps: 4225
