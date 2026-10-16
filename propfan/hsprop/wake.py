"""Lifting-line vortex system of a B-bladed propeller with a prescribed, load-adapted wake.

Each blade carries a swept bound vortex on its quarter-chord line, divided into N panels.
Trailing filaments leave the panel edges, run along the chord to the trailing edge and then
follow helices whose kinematics come from the blade loading:

* axial velocity  V(1 + u_n) + u_a0 g(x),   g = 1 + x / sqrt(x^2 + R^2)
  (the induced velocity grows from its disk value to twice that value far downstream, as for an
  actuator disk; this is Theodorsen's far wake: pitch (V + w)/Omega with w = 2 u_a0),
* swirl  u_t0 g(x) r0/r (angular momentum conserved in the slipstream),
* radius from mass conservation in each streamtube, including the density change of the
  compressible slipstream, outside the nacelle.

Here u_a0, u_t0 are the circumferential-mean induced velocities at the disk, so the wake
shape is that of a heavily loaded propeller: it contracts, and its pitch increases with x.
Image filaments at r_h^2 / r (opposite strength) keep the trailing vortices out of the hub.

Compressibility of the induced field: the far wake (Trefftz plane) of a helical vortex
system is frozen in the fluid, so its potential obeys Laplace's equation exactly even at
high Mach number.  Compressibility of the blade-to-blade near field is carried by the section
model (the Prandtl-Glauert-mapped row); the wake is therefore evaluated with the
incompressible Biot-Savart law, which is the compressible lifting-line theory of wings
(Prandtl-Glauert sections, incompressible downwash) extended to propellers.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def biot_savart(P, A, B, core=1e-6):
    """Velocity at points P (Np, 3) from unit-strength straight segments A -> B (Ns, 3).

    A Rankine-like core of radius ``core`` (same units) regularises points close to a
    segment.  Returns (Np, Ns, 3).
    """
    r1 = P[:, None, :] - A[None, :, :]
    r2 = P[:, None, :] - B[None, :, :]
    r0 = (B - A)[None, :, :]
    c = np.cross(r1, r2)
    c2 = np.einsum("pnk,pnk->pn", c, c)
    n1 = np.sqrt(np.einsum("pnk,pnk->pn", r1, r1))
    n2 = np.sqrt(np.einsum("pnk,pnk->pn", r2, r2))
    l2 = np.einsum("pnk,pnk->pn", r0, r0)
    core = np.asarray(core, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        dot = np.einsum("pnk,pnk->pn", r0, r1 / n1[..., None] - r2 / n2[..., None])
        fac = dot / (4.0 * np.pi * (c2 + core * core * l2))
    fac = np.where(np.isfinite(fac), fac, 0.0)
    return c * fac[..., None]


def polyline_influence(P, pts, core, chunk=20000):
    """Velocity at P (Np, 3) from unit circulation along polylines.

    ``pts`` (F, K, 3): F polylines of K points each, circulation running along increasing K;
    ``core`` a scalar or one core radius per polyline.  Returns (Np, F, 3).
    """
    F, K, _ = pts.shape
    A = pts[:, :-1, :].reshape(-1, 3)
    B = pts[:, 1:, :].reshape(-1, 3)
    out = np.zeros((P.shape[0], F, 3))
    owner = np.repeat(np.arange(F), K - 1)
    core_s = np.broadcast_to(np.asarray(core, dtype=float), (F,))[owner]
    for s in range(0, A.shape[0], chunk):
        v = biot_savart(P, A[s:s + chunk], B[s:s + chunk], core_s[s:s + chunk])          # (Np, n, 3)
        o = owner[s:s + chunk]
        # sum segments into their polyline (owners are contiguous runs)
        idx = np.flatnonzero(np.diff(o)) + 1
        starts = np.concatenate([[0], idx])
        sums = np.add.reduceat(v, starts, axis=1)
        out[:, o[starts], :] += sums
    return out


@dataclass
class WakeSettings:
    n_first: int = 60            # wake points per revolution near the blade
    dpsi_max_deg: float = 30.0   # coarsest angular step far downstream
    growth: float = 1.06         # geometric growth of the step after the first revolution
    length_D: float = 12.0       # axial extent of the helices (diameters)
    max_revs: float = 60.0
    chord_points: int = 4        # points from quarter chord to trailing edge
    hub_images: bool = True
    other_bound: bool = False    # include other blades' bound vortices (cascade does the near field)
    core_R: float = 2e-3         # vortex core radius / R (bound vortices, minimum)
    core_chord: float = 0.25     # trailing-filament core radius / local chord


class VortexSystem:
    """Geometry of all filaments for given blade lines and mean induced velocities."""

    def __init__(self, B, R, settings: WakeSettings | None = None):
        self.B = int(B)
        self.R = float(R)
        self.s = settings or WakeSettings()

    # ------------------------------------------------------------------
    def psi_grid(self, adv_per_rad):
        """Wake age angles; ``adv_per_rad`` is the axial advance per radian near the disk."""
        s = self.s
        d0 = 2.0 * np.pi / s.n_first
        dmax = np.radians(s.dpsi_max_deg)
        psi = [0.0]
        d = d0
        L = s.length_D * 2.0 * self.R
        while True:
            if psi[-1] > 2.0 * np.pi:
                d = min(d * s.growth, dmax)
            psi.append(psi[-1] + d)
            if psi[-1] * max(adv_per_rad, 1e-9) > L or psi[-1] > s.max_revs * 2 * np.pi:
                break
        return np.array(psi)

    def filaments(self, start, ua0, ut0, V, Omega, mach, hub_radius_fn, nacelle_u=None):
        """Helical wake polylines from trailing-edge points.

        start   : (F, 3) cylindrical (x, r, theta) trailing-edge points of blade 0
        ua0, ut0: (F,) mean axial / swirl induced velocity at the disk for each filament
        Returns Cartesian points (F, K, 3).
        """
        x0, r0, th0 = start[:, 0], start[:, 1], start[:, 2]
        R = self.R
        Vx0 = V + ua0
        adv = max(float(np.median(Vx0)) / Omega, 1e-3 * R)
        psi = self.psi_grid(adv)
        K = psi.size
        F = x0.size
        x = np.empty((F, K))
        r = np.empty((F, K))
        th = np.empty((F, K))
        x[:, 0], r[:, 0], th[:, 0] = x0, r0, th0
        rh0 = hub_radius_fn(x0)
        a0 = ua0 / max(V, 1e-9) if V > 0 else np.zeros(F)
        flux0 = (V + ua0) * (1.0 - mach ** 2 * a0)
        ann0 = np.maximum(r0 ** 2 - rh0 ** 2, 0.0)

        def g(xx):
            return 1.0 + xx / np.sqrt(xx * xx + R * R)

        for k in range(1, K):
            dpsi = psi[k] - psi[k - 1]
            gx = g(x[:, k - 1])
            vx = V + ua0 * gx
            if nacelle_u is not None:
                vx = vx + V * nacelle_u(x[:, k - 1], r[:, k - 1])
            vth = ut0 * gx * r0 / np.maximum(r[:, k - 1], 1e-6)
            x[:, k] = x[:, k - 1] + dpsi * np.maximum(vx, 1e-3 * Omega * R) / Omega
            th[:, k] = th[:, k - 1] - dpsi * (1.0 - vth / (Omega * np.maximum(r[:, k - 1], 1e-6)))
            gk = g(x[:, k])
            flux = (V + ua0 * gk) * (1.0 - mach ** 2 * a0 * (2.0 - gk))
            rh = hub_radius_fn(x[:, k])
            r[:, k] = np.sqrt(rh ** 2 + ann0 * flux0 / np.maximum(flux, 1e-9))
        return cyl_to_cart(x, r, th), (x, r, th)


def cyl_to_cart(x, r, th):
    return np.stack([x, r * np.cos(th), r * np.sin(th)], axis=-1)


def rotate_x(pts, angle):
    """Rotate Cartesian points about the x axis by ``angle`` (rotation sense +theta)."""
    c, s = np.cos(angle), np.sin(angle)
    out = pts.copy()
    out[..., 1] = c * pts[..., 1] - s * pts[..., 2]
    out[..., 2] = s * pts[..., 1] + c * pts[..., 2]
    return out


def local_frames(P):
    """Axial, tangential and radial unit vectors at Cartesian points P (N, 3)."""
    th = np.arctan2(P[:, 2], P[:, 1])
    ex = np.tile([1.0, 0.0, 0.0], (P.shape[0], 1))
    er = np.stack([np.zeros_like(th), np.cos(th), np.sin(th)], axis=1)
    et = np.stack([np.zeros_like(th), -np.sin(th), np.cos(th)], axis=1)
    return ex, et, er
