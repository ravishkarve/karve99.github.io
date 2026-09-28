"""Linear-vorticity stream-function panel method for a linear cascade.

This is the inviscid initialiser of MISES (ISET uses a panel solution to
build its streamline grid) turned into a full incompressible cascade solver.

Formulation
-----------
* The blade surface carries a linearly varying vortex sheet ``gamma`` (the
  tangential surface velocity, positive along the contour direction).
* The kernel is the periodic one for an infinite row of blades with pitch
  ``s``:  psi = -(G/2pi) ln|(s/pi) sinh(pi (z - z0)/s)|.  It is split into the
  isolated-vortex kernel, integrated analytically, plus a smooth periodic
  remainder integrated with Gauss-Legendre quadrature.
* Unknowns: node values of gamma, the surface stream function ``Psi0`` and
  the tangential component of the vector-mean velocity ``v_m``.
* Equations: psi(node) = Psi0 at every node, the Kutta condition
  gamma_first + gamma_last = 0, and the prescribed inlet flow angle
  v_1 = v_m - Gamma/(2s).
* Viscous displacement is represented by surface source panels whose
  strength is the streamwise gradient of the mass defect m = ue*delta*.
  The stream function is enforced on the *inner* side of the sheet so the
  blade interior stays at rest; the response of gamma to m is linear, which
  gives the XFOIL/MISES-style interaction matrix ``dUe/dm`` used by the
  Newton viscous coupling.

Velocities are normalised by the inlet speed V1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.linalg import lu_factor, lu_solve

from .geometry import Blade

_GL_X, _GL_W = np.polynomial.legendre.leggauss(4)


# ---------------------------------------------------------------------------
# periodic-kernel helpers
# ---------------------------------------------------------------------------

def _log_sinh_over_w(w):
    """ln|sinh(w)/w| for complex w, stable for small and large |Re w|."""
    w = np.asarray(w, dtype=complex)
    out = np.empty(w.shape)
    small = np.abs(w) < 1.0
    ws = w[small]
    w2 = ws * ws
    series = 1.0 + w2 / 6.0 * (1.0 + w2 / 20.0 * (1.0 + w2 / 42.0 * (
        1.0 + w2 / 72.0 * (1.0 + w2 / 110.0 * (1.0 + w2 / 156.0)))))
    out[small] = np.log(np.abs(series))
    wl = w[~small]
    ax = np.abs(wl.real)
    arg = 1.0 + np.exp(-4.0 * ax) - 2.0 * np.cos(2.0 * wl.imag) * np.exp(-2.0 * ax)
    ln_sinh = ax - math.log(2.0) + 0.5 * np.log(np.maximum(arg, 1e-300))
    out[~small] = ln_sinh - np.log(np.abs(wl))
    return out


def _coth_minus_inv(w):
    """coth(w) - 1/w for complex w (smooth, zero at w = 0)."""
    w = np.asarray(w, dtype=complex)
    out = np.empty(w.shape, dtype=complex)
    small = np.abs(w) < 0.5
    ws = w[small]
    w2 = ws * ws
    out[small] = ws * (1.0 / 3.0 - w2 * (1.0 / 45.0 - w2 * (2.0 / 945.0 - w2 * (
        1.0 / 4725.0 - w2 * (2.0 / 93555.0 - w2 * 1382.0 / 638512875.0)))))
    wl = w[~small]
    sgn = np.where(wl.real >= 0.0, 1.0, -1.0)
    e = np.exp(-2.0 * sgn * wl)
    out[~small] = sgn * (1.0 + e) / (1.0 - e) - 1.0 / wl
    return out


def _vortex_psi_isolated(a, b, L):
    """Analytic stream-function integrals for a linear vortex panel.

    Returns (I0, I1) with I0 = int_0^L ln r dt and I1 = int_0^L t ln r dt
    for a field point at panel-local coordinates (a, b).
    """

    def f0(u):
        r2 = u * u + b * b
        lr = np.where(r2 > 0.0, np.log(np.where(r2 > 0.0, r2, 1.0)), 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = np.where(b != 0.0, b * np.arctan(u / np.where(b != 0.0, b, 1.0)), 0.0)
        return 0.5 * (u * lr - 2.0 * u + 2.0 * at), r2, lr

    def g(u, r2, lr):
        return 0.25 * (r2 * lr - u * u)

    u2 = L - a
    u1 = -a
    F2, r22, lr2 = f0(u2)
    F1, r21, lr1 = f0(u1)
    I0 = F2 - F1
    I1 = g(u2, r22, lr2) - g(u1, r21, lr1) + a * I0
    return I0, I1


def _vortex_psi_coeffs(xf, yf, xa, ya, xb, yb, s):
    """Stream function at field points from linear vortex panels (a -> b).

    Returns (c0, c1) of shape (n_field, n_panels): psi = c0*g_a + c1*g_b,
    periodic kernel with pitch s.
    """
    dx, dy = xb - xa, yb - ya
    L = np.hypot(dx, dy)
    tx, ty = dx / L, dy / L
    px = xf[:, None] - xa[None, :]
    py = yf[:, None] - ya[None, :]
    a = px * tx[None, :] + py * ty[None, :]
    b = -px * ty[None, :] + py * tx[None, :]
    Lm = L[None, :]
    I0, I1 = _vortex_psi_isolated(a, b, Lm)
    c0 = I0 - I1 / Lm
    c1 = I1 / Lm
    tau = 0.5 * (1.0 + _GL_X)[None, :] * L[:, None]
    wq = 0.5 * _GL_W[None, :] * L[:, None]
    zq = (xa[:, None] + tau * tx[:, None]) + 1j * (ya[:, None] + tau * ty[:, None])
    d = (xf + 1j * yf)[:, None, None] - zq[None, :, :]
    R = _log_sinh_over_w(np.pi * d / s)
    frac = tau / L[:, None]
    c0 = c0 + np.sum(R * (wq * (1.0 - frac))[None], axis=2)
    c1 = c1 + np.sum(R * (wq * frac)[None], axis=2)
    k = -1.0 / (2.0 * np.pi)
    return k * c0, k * c1


def _source_velocity(xf, yf, xa, ya, xb, yb, s):
    """Velocity (ux, uy) at field points from unit constant-source panels.

    Points lying exactly on a panel get the value on its left side (the
    blade interior for a counter-clockwise contour).
    """
    dx, dy = xb - xa, yb - ya
    L = np.hypot(dx, dy)
    tx, ty = dx / L, dy / L
    px = xf[:, None] - xa[None, :]
    py = yf[:, None] - ya[None, :]
    a = px * tx[None, :] + py * ty[None, :]
    b = -px * ty[None, :] + py * tx[None, :]
    Lm = L[None, :]
    # points on a panel (self-induced term): force b = +0 so that arctan2 picks
    # the left (inner) side consistently despite round-off
    b = np.where(np.abs(b) < 1e-12 * Lm, 0.0, b)
    r0 = a * a + b * b
    rL = (a - Lm) ** 2 + b * b
    ok = (r0 > 0) & (rL > 0)
    vt = np.where(ok, np.log(np.where(ok, r0, 1.0) / np.where(ok, rL, 1.0)), 0.0) / (4 * np.pi)
    vn = (np.arctan2(b, a - Lm) - np.arctan2(b, a)) / (2 * np.pi)
    ux = vt * tx[None, :] - vn * ty[None, :]
    uy = vt * ty[None, :] + vn * tx[None, :]
    tau = 0.5 * (1.0 + _GL_X)[None, :] * L[:, None]
    wq = 0.5 * _GL_W[None, :] * L[:, None]
    zq = (xa[:, None] + tau * tx[:, None]) + 1j * (ya[:, None] + tau * ty[:, None])
    d = (xf + 1j * yf)[:, None, None] - zq[None, :, :]
    W = (1.0 / (2.0 * s)) * _coth_minus_inv(np.pi * d / s)
    Wp = np.sum(W * wq[None], axis=2)
    return ux + Wp.real, uy - Wp.imag


# ---------------------------------------------------------------------------
# solution container
# ---------------------------------------------------------------------------

@dataclass
class PanelSolution:
    """Inviscid (possibly displacement-corrected) panel solution."""

    gamma: np.ndarray          # signed tangential velocity at nodes / V1
    beta1: float               # inlet flow angle [deg]
    beta2: float               # exit flow angle [deg]
    u1: float
    v1: float
    u2: float
    v2: float
    circulation: float         # CCW circulation per blade / (V1 * 1)
    stag_panel: int            # index k of the panel (k, k+1) holding the stagnation point
    stag_frac: float           # fractional position of the stagnation point on that panel
    psi0: float

    @property
    def ue(self):
        return np.abs(self.gamma)

    @property
    def cp(self):
        """Incompressible pressure coefficient based on inlet dynamic pressure."""
        return 1.0 - self.gamma ** 2


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------

class CascadePanelMethod:
    """Incompressible potential flow through a linear cascade.

    Parameters
    ----------
    blade
        Blade section (use :meth:`Blade.repanel` first for a good node
        distribution).
    """

    def __init__(self, blade: Blade):
        self.blade = blade
        x = np.asarray(blade.x, float)
        y = np.asarray(blade.y, float)
        self.x, self.y = x, y
        self.N = N = x.size
        self.s = s = float(blade.pitch)
        dx, dy = np.diff(x), np.diff(y)
        L = np.hypot(dx, dy)
        if np.any(L <= 0):
            raise ValueError("zero-length panel in blade contour")
        self.L = L
        self.closed_te = blade.te_gap < 1e-9 * max(blade.axial_chord, 1e-12)
        xa, ya, xb, yb = x[:-1], y[:-1], x[1:], y[1:]

        # ---- vortex stream-function influence (N nodes x N nodes) ----------
        c0, c1 = _vortex_psi_coeffs(x, y, xa, ya, xb, yb, s)
        A = np.zeros((N, N))
        A[:, :-1] += c0
        A[:, 1:] += c1
        w = np.zeros(N)                      # trapezoid weights -> circulation
        w[:-1] += 0.5 * L
        w[1:] += 0.5 * L

        # ---- source-panel stream function on the inner side (N x Np) -----
        xm, ym = 0.5 * (xa + xb), 0.5 * (ya + yb)
        noutx, nouty = dy / L, -dx / L

        def inner_psi(ux, uy):
            flux = L[:, None] * (ux * noutx[:, None] + uy * nouty[:, None])
            out = np.zeros((N, ux.shape[1]))
            out[1:] = np.cumsum(flux, axis=0)
            return out

        ux, uy = _source_velocity(xm, ym, xa, ya, xb, yb, s)
        B = inner_psi(ux, uy)

        # ---- trailing-edge gap panel (XFOIL treatment) -------------------
        # The gap panel (lower TE -> upper TE) carries a constant vortex and
        # source sheet equal to the tangential/normal components of the mean
        # TE velocity q_te = (gamma_last - gamma_first)/2 along the bisector.
        self.h_te = 0.0
        self.te_sds = self.te_scs = 0.0
        if not self.closed_te:
            xt0, yt0, xt1, yt1 = x[-1], y[-1], x[0], y[0]
            h = math.hypot(xt1 - xt0, yt1 - yt0)
            tgx, tgy = (xt1 - xt0) / h, (yt1 - yt0) / h
            bx = -dx[0] / L[0] + dx[-1] / L[-1]
            by = -dy[0] / L[0] + dy[-1] / L[-1]
            bn = math.hypot(bx, by)
            bx, by = bx / bn, by / bn
            sds = bx * tgx + by * tgy            # tangential part -> vortex
            scs = bx * tgy - by * tgx            # outward-normal part -> source
            cv0, cv1 = _vortex_psi_coeffs(x, y, np.array([xt0]), np.array([yt0]),
                                          np.array([xt1]), np.array([yt1]), s)
            psi_v = (cv0 + cv1)[:, 0]            # constant-strength vortex
            uxs, uys = _source_velocity(xm, ym, np.array([xt0]), np.array([yt0]),
                                        np.array([xt1]), np.array([yt1]), s)
            psi_s = inner_psi(uxs, uys)[:, 0]
            col = 0.5 * (sds * psi_v + scs * psi_s - scs * h / (2.0 * s) * y)
            A[:, N - 1] += col
            A[:, 0] -= col
            w[N - 1] += 0.5 * sds * h
            w[0] -= 0.5 * sds * h
            self.h_te, self.te_sds, self.te_scs = h, sds, scs
        self.A_psi = A
        self.B_psi = B
        self.w_circ = w

        # ---- assemble and factor the system ------------------------------
        M = np.zeros((N + 2, N + 2))
        M[:N, :N] = A
        M[:N, N] = -1.0
        M[:N, N + 1] = -x
        M[N, 0] = 1.0
        M[N, N - 1] = 1.0
        M[N + 1, :N] = -w / (2.0 * s)
        M[N + 1, N + 1] = 1.0
        if self.closed_te:
            M[N - 1, :] = 0.0
            M[N - 1, [0, 1, 2]] = [1.0, -2.0, 1.0]
            M[N - 1, [N - 3, N - 2, N - 1]] += [-1.0, 2.0, -1.0]
        self.M = M
        self.lu = lu_factor(M)

        # basis solutions: unit u1, unit v1
        self._sol_u = lu_solve(self.lu, self._rhs(1.0, 0.0, None))
        self._sol_v = lu_solve(self.lu, self._rhs(0.0, 1.0, None))
        # response to unit source strengths
        Rs = np.zeros((N + 2, N - 1))
        Rs[:N] = -(L[None, :] / (2.0 * s)) * y[:, None] - B
        if self.closed_te:
            Rs[N - 1] = 0.0
        self._sol_sigma = lu_solve(self.lu, Rs)

    # ------------------------------------------------------------------
    def _rhs(self, u1, v1, sigma):
        N = self.N
        r = np.zeros(N + 2)
        uinf = u1
        if sigma is not None:
            uinf = u1 + float(np.dot(sigma, self.L)) / (2.0 * self.s)
            r[:N] -= self.B_psi @ sigma
        r[:N] -= uinf * self.y
        r[N + 1] = v1
        if self.closed_te:
            r[N - 1] = 0.0
        return r

    def solve(self, inlet_angle_deg: float, sigma=None) -> PanelSolution:
        """Solve for an inlet flow angle (deg from axial), unit inlet speed.

        ``sigma`` optionally gives source strengths on each panel.
        """
        b1 = math.radians(inlet_angle_deg)
        u1, v1 = math.cos(b1), math.sin(b1)
        sol = u1 * self._sol_u + v1 * self._sol_v
        Q = 0.0
        if sigma is not None:
            sigma = np.asarray(sigma, float)
            sol = sol + self._sol_sigma @ sigma
            Q = float(np.dot(sigma, self.L))
        return self._package(sol, u1, v1, Q, inlet_angle_deg)

    def _package(self, sol, u1, v1, Q, beta1):
        N = self.N
        g = sol[:N]
        psi0, vm = sol[N], sol[N + 1]
        circ = float(np.dot(self.w_circ, g))
        v2 = vm + circ / (2.0 * self.s)
        q_te = 0.5 * (g[-1] - g[0])
        u2 = u1 + (Q + self.te_scs * q_te * self.h_te) / self.s
        k, f = self.stagnation(g)
        return PanelSolution(g, beta1, math.degrees(math.atan2(v2, u2)), u1, v1, u2, v2,
                             circ, k, f, psi0)

    def stagnation(self, g):
        """Locate the stagnation point: gamma changes from - (upper) to + (lower)."""
        return self.stagnation_static(g, self.blade.i_le)

    @staticmethod
    def stagnation_static(g, i_le):
        """Stagnation panel k and fraction f for signed contour velocities ``g``."""
        g = np.asarray(g)
        n = g.size
        cand = np.where((g[:-1] < 0.0) & (g[1:] >= 0.0))[0]
        if cand.size == 0:
            k = int(np.clip(i_le, 1, n - 3))
            return k, 0.5
        k = int(cand[np.argmin(np.abs(cand - i_le))])
        f = g[k] / (g[k] - g[k + 1])
        return k, float(np.clip(f, 0.0, 1.0))

    # ------------------------------------------------------------------
    def mass_defect_operator(self, stag_panel: int):
        """Matrix G with sigma = G @ m for node mass defects m >= 0.

        Upper-surface nodes (index <= stag_panel) carry flow towards node 0,
        lower-surface nodes towards node N-1.
        """
        N = self.N
        G = np.zeros((N - 1, N))
        for j in range(N - 1):
            if j < stag_panel:
                G[j, j], G[j, j + 1] = 1.0, -1.0
            elif j == stag_panel:
                G[j, j], G[j, j + 1] = 1.0, 1.0
            else:
                G[j, j], G[j, j + 1] = -1.0, 1.0
        return G / self.L[:, None]

    def ue_sensitivity(self, stag_panel: int):
        """dUe/dm (N x N): change of edge speed per unit mass defect at each node."""
        G = self.mass_defect_operator(stag_panel)
        dg = self._sol_sigma[: self.N] @ G
        sgn = np.where(np.arange(self.N) <= stag_panel, -1.0, 1.0)
        return sgn[:, None] * dg

    def solve_with_mass_defect(self, inlet_angle_deg, m, stag_panel):
        """Panel solution with the displacement effect of node mass defects m."""
        sigma = self.mass_defect_operator(stag_panel) @ np.asarray(m, float)
        return self.solve(inlet_angle_deg, sigma)
