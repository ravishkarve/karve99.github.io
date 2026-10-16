"""Compressible potential flow about the spinner and nacelle.

The body of revolution is represented by line sources on its axis (piecewise-constant
strength on K segments), the Karman method, with the compressible kernel: for the linearised
equation  beta^2 phi_xx + phi_rr + phi_r / r = 0  a segment [a, b] of source density m gives

    phi = -(m / 4 pi) [asinh((x - a)/(beta r)) - asinh((x - b)/(beta r))],
    u   = -(m / 4 pi) [1/d_a - 1/d_b],        v = (m / 4 pi r) [(x - a)/d_a - (x - b)/d_b],
    d   = sqrt((x - .)^2 + beta^2 r^2).

The strengths follow from flow tangency, (1 + u) r_b' = v, at surface points, solved in least
squares with a small smoothness penalty.  Velocities are per unit free-stream speed.  This is
Goethert's rule built into the kernel: no geometric stretching of the body is needed.
"""
from __future__ import annotations

import numpy as np

from .geometry import Nacelle


class NacelleFlow:
    def __init__(self, nacelle: Nacelle, diameter, mach, n_sources=120, smooth=1e-6):
        self.beta = float(np.sqrt(max(1.0 - mach ** 2, 1e-4)))
        D = float(diameter)
        xb = nacelle.x_D * D
        rb = nacelle.r_D * D
        self.length_scale = D
        x0, x1 = xb[0], xb[-1]
        L = x1 - x0
        # source segments slightly inside the body ends, clustered towards both ends
        t = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, n_sources + 1)))
        rmax = float(rb.max())
        e0 = min(0.25 * rmax, 0.05 * L)
        self.edges = x0 + e0 + (L - 2 * e0) * t
        # collocation on the body (excluding the very ends)
        s = np.linspace(0.0, 1.0, 4 * n_sources + 1)[1:-1]
        xc = x0 + L * 0.5 * (1.0 - np.cos(np.pi * s))
        rc = np.interp(xc, xb, rb)
        drc = np.gradient(rc, xc)
        keep = rc > 1e-3 * rmax
        xc, rc, drc = xc[keep], rc[keep], drc[keep]
        U, Vr = self._kernels(xc, rc)                  # (Nc, K)
        A = U * drc[:, None] - Vr
        b = -drc
        K = n_sources
        Dm = np.diff(np.eye(K), axis=0)                # smoothness of the strength distribution
        lam = smooth * np.linalg.norm(A) ** 2 / K
        lhs = A.T @ A + lam * Dm.T @ Dm
        self.m = np.linalg.solve(lhs, A.T @ b)
        self.residual = float(np.sqrt(np.mean((A @ self.m - b) ** 2)))
        self.body = nacelle

    def _kernels(self, x, r):
        x = np.asarray(x, dtype=float)[:, None]
        r = np.maximum(np.asarray(r, dtype=float)[:, None], 1e-9)
        a = self.edges[None, :-1]
        b = self.edges[None, 1:]
        br = self.beta * r
        da = np.sqrt((x - a) ** 2 + br ** 2)
        db = np.sqrt((x - b) ** 2 + br ** 2)
        U = -(1.0 / (4.0 * np.pi)) * (1.0 / da - 1.0 / db)
        Vr = (1.0 / (4.0 * np.pi * r)) * ((x - a) / da - (x - b) / db)
        return U, Vr

    def velocity(self, x, r):
        """Perturbation velocities (u, v) / V at points (x, r) in metres."""
        x = np.asarray(x, dtype=float)
        r = np.asarray(r, dtype=float)
        shp = np.broadcast(x, r).shape
        xx, rr = np.broadcast_arrays(x, r)
        U, Vr = self._kernels(xx.ravel(), rr.ravel())
        return (U @ self.m).reshape(shp), (Vr @ self.m).reshape(shp)

    def axial(self, x, r):
        return self.velocity(x, r)[0]
