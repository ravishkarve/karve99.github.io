# Doppler Locator

A static web app that reads a spectrogram, detects the Doppler curves that passing
propeller aircraft leave in it, cross-references them with flight tracks and pinpoints
where the recording was made. Five learning tabs explain each step with interactive figures.

The method follows colsto's video
["I discovered a sound that leaks your exact location"](https://www.youtube.com/watch?v=UytYrhYLOKI).

## What runs where

- `js/core.js` – all the maths, no DOM: world simulation, audio synthesis from propagation
  delay, STFT spectrogram with per-bin median normalisation, ridge tracking, Levenberg–Marquardt
  fit of the exact straight-pass Doppler model, grid search with the timing / speed / distance /
  silence filter cascade, and refinement of each surviving flight combination against the ridge.
- `js/worker.js` – runs the chain off the main thread.
- `js/app.js`, `js/draw.js` – the Locator tab.
- `js/learn.js` – the lesson figures.

## Scope

The full chain runs on a simulated 40 × 40 km world (about 170 flights over three hours).
Your own audio can be loaded to trace curves and get each aircraft's speed and closest
distance, but no real flight data is connected, so real recordings are not placed on a map.

## Check

    node doppler/tests/run.js 25

On 25 simulated worlds: all 25 solved with the ideal model (median error 4 m, worst 116 m);
24 of 25 with a 1.6 % sound-speed error and a 45 m altitude bias (median 40 m, worst 974 m).
