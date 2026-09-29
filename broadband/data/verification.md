# bbnoise verification

| check | metric | value | tolerance | result | reference |
|---|---|---|---|---|---|
| turbulence_normalisation | max relative error | 0.000403 | 0.002 | PASS | Amiet (1975); Blandeau (2011) ch. 2 |
| wake_envelope_energy | relative error | 3.48e-12 | 1e-09 | PASS | Jurdic, Joseph & Antoni (2009); Blandeau (2011) ch. 5 |
| fresnel_integral | max abs error | 4.34e-15 | 1e-08 | PASS | Abramowitz & Stegun 7.3 |
| te_radiation_integral | max relative error | 1.97e-12 | 1e-06 | PASS | Amiet (1976); Roger & Moreau (2005) JSV 286 |
| le_response_limits | max of |L|beta-1 and dB jump/2 - 1 | 0.000173 | 0.001 | PASS | Amiet (1975) JSV 41; Sears (1941) |
| gep_zero_pressure_gradient | max |dB difference| | 0.697 | 2 | PASS | Dominique et al. (2021) JSV 506; Goody (2004) |
| rozenberg_zpg_limit | max |dB difference| | 0.479 | 1.5 | PASS | Rozenberg, Robert & Moreau (2012) AIAA J 50 |
| le_velocity_scaling | deviation of the slope from [50, 60] dB/decade | 0 | 0 | PASS | Paterson & Amiet (1976) NASA CR-2733 |
| te_velocity_scaling | deviation of the slope from [45, 55] dB/decade | 0 | 0 | PASS | Ffowcs Williams & Hall (1970); Brooks, Pope & Marcolini (1989) |
| doppler_kinematics | max |dB difference| | 0.104 | 0.25 | PASS | Blandeau & Joseph (2011) AIAA J 49; Sinayoko, Kingan & Agarwal (2013) Proc. R. Soc. A 469 |
| full_vs_simplified | max |dB difference| | 0.123 | 0.5 | PASS | Blandeau & Joseph (2011) AIAA J 49(5); Blandeau (2011) ch. 3-4 |
| low_frequency_departure | max |dB difference| inside (0.1, 6) | 0 | 0 | PASS | Blandeau & Joseph (2011) AIAA J 49(5) |
| blade_count | max |dB error| | 0 | 1e-06 | PASS | Blandeau (2011) ch. 4 |
