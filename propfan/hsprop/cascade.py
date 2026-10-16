"""Linear theory of a compressible blade row (the blade element of a high-solidity propeller).

The blade element at radius r is one blade of an infinite row: the B blades cut by the
cylinder r = const and unwrapped (the pitch is s = 2 pi r / B), seen in the plane normal to
the blade's sweep (see :mod:`hsprop.section`).  This module solves the linearised flow
through that row.

Formulation
-----------
Flow-aligned coordinates, chord 1 and speed 1: x along the vector-mean velocity W_m (the
mean of the far-upstream and far-downstream velocities), y normal to it; the reference
blade lies on 0 <= x <= 1.  The other blades sit at z + m P, m = +-1, +-2, ..., with the
pitch vector P = s (sin xi + i cos xi): xi is the angle between W_m and the normal to the
row (the stagger of linear theory).

* Lift.  A vortex sheet gamma = 2 [A0 (1 + cos t)/sin t + sum_n An sin n t],
  x = (1 - cos t)/2, satisfies flow tangency on the camber line,
      v(x) = eta'(x) - alpha.
  The blade's own sheet gives Glauert's v = -(A0 - sum An cos n t); the other blades add
  the regular part of the row kernel,
      u - i v = i/(2P) [cot(pi z / P) - P/(pi z)],
  (clockwise unit vortices; the subtracted term is the blade's own).  The tangency
  condition is projected on cos(m t) (Galerkin), so isolated mean lines are reproduced
  exactly (no aliasing of the log-singular a = 1.0 mean line).
  Lift on the vector-mean velocity (Kutta-Joukowski for a row): CL = 2 pi (A0 + A1/2).
* Thickness.  A source sheet m = 2 dy_t/dx.  Its own speed is the principal-value integral
  (evaluated through a cosine series of G(t) = y_t' sin t); the other blades' source rows
  add speed and, in a staggered row, turn the flow, so they enter the lift equation.
* Compressibility.  The linearised potential equation (1-M^2) phi_xx + phi_yy = 0 becomes
  Laplace's equation with y' = beta y.  The map sends the lattice of blades into another
  lattice,
      s' = s sqrt(sin^2 xi + beta^2 cos^2 xi),     tan xi' = tan xi / beta,
  and the compressible perturbation speeds are the incompressible perturbation speeds of
  the *physical* blade slopes placed in the mapped lattice, divided by beta.  For an
  isolated aerofoil this is the Prandtl-Glauert rule; for a dense row it adds the growth
  of blade-to-blade interference with Mach number (the row looks denser and more staggered).
  Local non-linearity is added with the Karman-Tsien rule on the mapped-lattice Cp, and the
  leading-edge singularity of linear theory is removed with Lighthill's (Riegels') factor
  sqrt(x / (x + r_le/2)).

Everything is vectorised over a batch of S blade elements (all radial stations at once).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import airfoil
from .gas import GAMMA

# ---------------------------------------------------------------------------
# kernels
# ---------------------------------------------------------------------------


def _cot(z):
    """cot(z) for complex z, stable for large |Im z|."""
    z = np.asarray(z, dtype=complex)
    pos = z.imag >= 0.0
    e_pos = np.exp(2j * np.where(pos, z, 0.0))           # |.| <= 1 where Im z >= 0
    e_neg = np.exp(-2j * np.where(pos, 0.0, z))          # |.| <= 1 where Im z < 0
    with np.errstate(divide="ignore", invalid="ignore"):
        c_pos = 1j * (e_pos + 1.0) / (e_pos - 1.0)
        c_neg = 1j * (1.0 + e_neg) / (1.0 - e_neg)
    return np.where(pos, c_pos, c_neg)


def row_kernel_regular(zeta, P):
    """R(zeta) = cot(pi zeta / P) - P / (pi zeta): the row kernel without its m = 0 term.

    ``zeta`` (real or complex) and ``P`` (complex) broadcast.  R(0) = 0.
    """
    u = np.pi * np.asarray(zeta, dtype=complex) / np.asarray(P, dtype=complex)
    small = np.abs(u) < 0.2
    us = np.where(small, u, 0.0)
    u2 = us * us
    series = -us / 3.0 * (1.0 + u2 / 15.0 * (1.0 + 2.0 * u2 / 21.0 * (1.0 + u2 / 10.0)))
    ul = np.where(small, 1.0, u)
    with np.errstate(divide="ignore", invalid="ignore"):
        big = _cot(ul) - 1.0 / ul
    return np.where(small, series, big)


def map_lattice(sigma, xi, beta):
    """Prandtl-Glauert image of a blade row.

    Returns the solidity and stagger (radians) of the incompressible row that is
    equivalent to a row of solidity ``sigma`` and stagger ``xi`` at compressibility factor
    ``beta`` = sqrt(1 - M^2).
    """
    sigma = np.asarray(sigma, dtype=float)
    xi = np.asarray(xi, dtype=float)
    beta = np.asarray(beta, dtype=float)
    sx, cx = np.sin(xi), np.cos(xi)
    s_ratio = np.sqrt(sx * sx + beta * beta * cx * cx)
    return sigma / s_ratio, np.arctan2(sx, beta * cx)


# ---------------------------------------------------------------------------
# section shape terms (geometry only, computed once per blade)
# ---------------------------------------------------------------------------


@dataclass
class ShapeTerms:
    """Per-station shape data on the solver grids, for unit thickness and unit camber."""

    thickness: list          # thickness form per station
    mean: list               # mean line per station
    camber_proj: np.ndarray  # (S, N)   Galerkin projections of eta' (unit cl_d)
    G_q: np.ndarray          # (S, K)   y_t'(x) sin(t) at the quadrature nodes (unit tau)
    u_thick_e: np.ndarray    # (S, E)   own thickness speed at the surface points (unit tau)
    yt_e: np.ndarray         # (S, E)   half thickness at the surface points (unit tau)
    eta_e: np.ndarray        # (S, E)   mean line at the surface points (unit cl_d)
    rle: np.ndarray          # (S,)     leading-edge radius / tau^2


@dataclass
class CascadeSolution:
    """Linear solution of a batch of blade rows (chord 1, vector-mean speed 1).

    Lift coefficients are on the vector-mean dynamic pressure.  Superposition components
    are kept so that angle of attack, camber and thickness can be varied cheaply.
    """

    beta: np.ndarray         # (S,) compressibility factor used
    sigma_m: np.ndarray      # (S,) mapped solidity
    xi_m: np.ndarray         # (S,) mapped stagger [rad]
    A: np.ndarray            # (S, N, 3) Glauert coefficients for unit alpha / cl_d / tau
    cl_unit: np.ndarray      # (S, 3)  incompressible (mapped-lattice) lift per unit input
    u_img_e: np.ndarray      # (S, E, 3) other-blade speed on the surface per unit input
    halfgam_e: np.ndarray    # (S, E, 3) gamma/2 on the surface per unit input


class ThinCascade:
    """Thin-aerofoil solver for rows of blades (vectorised over stations)."""

    def __init__(self, n_modes=24, n_quad=96, n_surface=121):
        self.N = int(n_modes)
        self.K = int(n_quad)
        xg, wg = np.polynomial.legendre.leggauss(self.K)
        self.phi = 0.5 * np.pi * (xg + 1.0)           # quadrature nodes on (0, pi)
        self.w = 0.5 * np.pi * wg
        self.xq = 0.5 * (1.0 - np.cos(self.phi))
        n = np.arange(self.N)
        # gamma dx / dphi basis at the quadrature nodes:  b0 = 1 + cos, bn = sin(n phi) sin(phi)
        B = np.sin(np.outer(self.phi, n)) * np.sin(self.phi)[:, None]
        B[:, 0] = 1.0 + np.cos(self.phi)
        self.Bq = B                                     # (K, N)
        self.Cq = np.cos(np.outer(self.phi, n))         # (K, N) projection functions
        self.Sdiag = np.full(self.N, 0.5 * np.pi)
        self.Sdiag[0] = -np.pi
        # surface evaluation points (open cosine grid), Lanczos-smoothed series
        te = np.linspace(0.0, np.pi, n_surface + 2)[1:-1]
        self.theta_e = te
        self.xe = 0.5 * (1.0 - np.cos(te))
        lan = np.sinc(n / self.N)
        He = np.sin(np.outer(te, n)) * lan[None, :]
        He[:, 0] = (1.0 + np.cos(te)) / np.sin(te)
        self.He = He                                    # (E, N): gamma/2 = He @ A
        self._zeta_qq = self.xq[:, None] - self.xq[None, :]      # (K, K)
        self._zeta_eq = self.xe[:, None] - self.xq[None, :]      # (E, K)
        self._cache = {}

    # ------------------------------------------------------------------ shapes
    def _shape_single(self, form, mean):
        key = (form, mean)
        if key in self._cache:
            return self._cache[key]
        N = self.N
        # mean line projections  int cos(m t) eta'(t) dt  (analytic for the standard lines)
        proj = np.zeros(N)
        if mean == "a1":
            m = np.arange(1, N, 2)
            proj[m] = 1.0 / (2.0 * m)
        elif mean == "parabolic":
            proj[1] = 0.5
        else:
            raise ValueError(f"unknown mean line {mean!r}")
        # thickness: G(t) = y_t'(x) sin t, with sin t = 2 sqrt(x (1-x))
        def G(t):
            x = 0.5 * (1.0 - np.cos(t))
            return airfoil.half_thickness_slope_times_sqrt(x, form) * 2.0 * np.sqrt(np.maximum(1.0 - x, 0.0))
        Gq = G(self.phi)
        # cosine series of G on a fine grid -> own thickness speed u = sum g_n sin(n t)/sin t
        nf = 400
        xf, wf = np.polynomial.legendre.leggauss(nf)
        tf = 0.5 * np.pi * (xf + 1.0)
        wf = 0.5 * np.pi * wf
        nn = np.arange(0, 160)
        g = (2.0 / np.pi) * (np.cos(np.outer(nn, tf)) * (G(tf) * wf)[None, :]).sum(axis=1)
        sig = np.sinc(nn / nn.size)
        u_e = (np.sin(np.outer(self.theta_e, nn[1:])) * (g[1:] * sig[1:])[None, :]).sum(axis=1) / np.sin(self.theta_e)
        out = (proj, Gq, u_e, airfoil.half_thickness(self.xe, form), airfoil.mean_line(self.xe, mean),
               float(airfoil.leading_edge_radius(1.0, form)))
        self._cache[key] = out
        return out

    def shape_terms(self, thickness, mean):
        """Shape data for S stations (lists of thickness forms and mean lines)."""
        thickness = list(thickness)
        mean = list(mean)
        rows = [self._shape_single(f, m) for f, m in zip(thickness, mean)]
        return ShapeTerms(thickness=thickness, mean=mean,
                          camber_proj=np.array([r[0] for r in rows]),
                          G_q=np.array([r[1] for r in rows]),
                          u_thick_e=np.array([r[2] for r in rows]),
                          yt_e=np.array([r[3] for r in rows]),
                          eta_e=np.array([r[4] for r in rows]),
                          rle=np.array([r[5] for r in rows]))

    # ------------------------------------------------------------------ solve
    def solve(self, sigma, xi, beta, shapes: ShapeTerms) -> CascadeSolution:
        """Solve S rows: physical solidity ``sigma``, stagger ``xi`` [rad], factor ``beta``."""
        sigma = np.atleast_1d(np.asarray(sigma, dtype=float))
        xi = np.atleast_1d(np.asarray(xi, dtype=float))
        beta = np.atleast_1d(np.asarray(beta, dtype=float))
        sm, xm = map_lattice(sigma, xi, beta)
        S = sm.size
        isolated = sm < 1e-6
        s_pitch = 1.0 / np.where(isolated, 1.0, sm)
        P = s_pitch * (np.sin(xm) + 1j * np.cos(xm))               # (S,)
        P = P[:, None, None]
        Rq = row_kernel_regular(self._zeta_qq[None, :, :], P) / (2.0 * P)   # (S, K, K)
        Rq = np.where(isolated[:, None, None], 0.0, Rq)
        Kv_vort = -Rq.real              # v of clockwise vortex rows
        Kv_src = -Rq.imag               # v of source rows
        # Galerkin matrix  M[m, n] = S_mn + sum_j w_j cos(m phi_j) sum_k w_k b_n(phi_k) Kv[j, k]
        WB = self.w[:, None] * self.Bq                              # (K, N)
        WC = self.w[:, None] * self.Cq                              # (K, N)
        V = Kv_vort @ WB                                            # (S, K, N)
        M = np.einsum("km,skn->smn", WC, V) + np.diag(self.Sdiag)[None, :, :]
        # right-hand sides: alpha (unit), camber (unit cl_d), thickness (unit tau)
        rhs = np.zeros((S, self.N, 3))
        rhs[:, 0, 0] = -np.pi
        rhs[:, :, 1] = shapes.camber_proj
        v_src = np.einsum("sjk,sk->sj", Kv_src, self.w[None, :] * shapes.G_q)   # (S, K)
        rhs[:, :, 2] = -np.einsum("km,sk->sm", WC, v_src)
        A = np.linalg.solve(M, rhs)                                 # (S, N, 3)
        cl_unit = 2.0 * np.pi * (A[:, 0, :] + 0.5 * A[:, 1, :])     # (S, 3)
        # surface speeds of the other blades (vortex rows: all components; source rows: tau)
        Re = row_kernel_regular(self._zeta_eq[None, :, :], P) / (2.0 * P)       # (S, E, K)
        Re = np.where(isolated[:, None, None], 0.0, Re)
        Ku_vort = -Re.imag
        Ku_src = Re.real
        gam_q = np.einsum("kn,snc->skc", WB, A)                     # (S, K, 3): w_k gamma dx/dphi
        u_img = np.einsum("sek,skc->sec", Ku_vort, gam_q)
        u_img[:, :, 2] += np.einsum("sek,sk->se", Ku_src, self.w[None, :] * shapes.G_q)
        halfgam = np.einsum("en,snc->sec", self.He, A)
        return CascadeSolution(beta=beta, sigma_m=sm, xi_m=xm, A=A, cl_unit=cl_unit,
                               u_img_e=u_img, halfgam_e=halfgam)


# ---------------------------------------------------------------------------
# convenience: lift-slope and camber factors of a row
# ---------------------------------------------------------------------------

_DEFAULT = None


def default_solver():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ThinCascade()
    return _DEFAULT


def row_factors(sigma, xi, mach=0.0, mean="a1", thickness="naca16"):
    """Lift-slope and camber factors of a row relative to the isolated aerofoil.

    Returns ``(k_alpha, k_camber)``: CL = 2 pi (k_alpha alpha) / beta + k_camber cl_d / beta,
    both on the vector-mean velocity, for the compressible row (mapped lattice).
    """
    sigma = np.atleast_1d(np.asarray(sigma, dtype=float))
    xi = np.broadcast_to(np.asarray(xi, dtype=float), sigma.shape)
    mach = np.broadcast_to(np.asarray(mach, dtype=float), sigma.shape)
    beta = np.sqrt(1.0 - mach ** 2)
    tc = default_solver()
    shapes = tc.shape_terms([thickness] * sigma.size, [mean] * sigma.size)
    sol = tc.solve(sigma, xi, beta, shapes)
    return sol.cl_unit[:, 0] / (2.0 * np.pi), sol.cl_unit[:, 1]


# ---------------------------------------------------------------------------
# universal table of the mapped-lattice solution (speed)
# ---------------------------------------------------------------------------

class LatticeTable:
    """Tabulated incompressible row solution for one section shape.

    The mapped-lattice solution depends only on the mapped solidity and stagger (and on the
    shape), not on Mach number or angle of attack, so it is computed once on a grid in
    u = ln(sigma' + 0.05) and xi' and interpolated with tensor-product Catmull-Rom cubics
    (C1, which keeps the Newton iteration of the propeller solver smooth).
    """

    SIG_MAX = 12.0
    XI_MIN = np.radians(-80.0)
    XI_MAX = np.radians(88.0)

    def __init__(self, solver: ThinCascade, thickness, mean, n_sigma=44, n_xi=85):
        self.solver = solver
        self.u = np.linspace(np.log(0.05), np.log(self.SIG_MAX + 0.05), n_sigma)
        self.xi = np.linspace(self.XI_MIN, self.XI_MAX, n_xi)
        sig = np.exp(self.u) - 0.05
        sig[0] = 0.0
        SG, XI = np.meshgrid(sig, self.xi, indexing="ij")
        shapes = solver.shape_terms([thickness] * SG.size, [mean] * SG.size)
        # the table is built directly in the mapped lattice: beta = 1
        sol = solver.solve(SG.ravel(), XI.ravel(), np.ones(SG.size), shapes)
        E = solver.xe.size
        self.cl = sol.cl_unit.reshape(n_sigma, n_xi, 3)
        self.a0 = sol.A[:, 0, :].reshape(n_sigma, n_xi, 3)
        self.uimg = sol.u_img_e.reshape(n_sigma, n_xi, E, 3)
        self.hg = sol.halfgam_e.reshape(n_sigma, n_xi, E, 3)

    @staticmethod
    def _cr_weights(t):
        t2, t3 = t * t, t * t * t
        return np.stack([-0.5 * t3 + t2 - 0.5 * t,
                         1.5 * t3 - 2.5 * t2 + 1.0,
                         -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                         0.5 * t3 - 0.5 * t2], axis=-1)

    def _stencil(self, grid, q):
        h = grid[1] - grid[0]
        s = (np.clip(q, grid[0], grid[-1]) - grid[0]) / h
        i = np.clip(np.floor(s).astype(int), 0, grid.size - 2)
        t = s - i
        idx = np.clip(i[:, None] + np.arange(-1, 3)[None, :], 0, grid.size - 1)
        return idx, self._cr_weights(t)

    def lookup(self, sigma_m, xi_m):
        u = np.log(np.clip(sigma_m, 0.0, self.SIG_MAX) + 0.05)
        iu, wu = self._stencil(self.u, u)
        ix, wx = self._stencil(self.xi, xi_m)
        W = wu[:, :, None] * wx[:, None, :]                       # (S, 4, 4)
        I = iu[:, :, None]
        J = ix[:, None, :]
        cl = np.einsum("sab,sabc->sc", W, self.cl[I, J])
        a0 = np.einsum("sab,sabc->sc", W, self.a0[I, J])
        uimg = np.einsum("sab,sabec->sec", W, self.uimg[I, J])
        hg = np.einsum("sab,sabec->sec", W, self.hg[I, J])
        return cl, a0, uimg, hg


@dataclass
class TableSolution:
    """Same fields as :class:`CascadeSolution` used by the section model."""

    beta: np.ndarray
    sigma_m: np.ndarray
    xi_m: np.ndarray
    A: np.ndarray            # only A[:, 0, :] (the leading-edge coefficient) is filled
    cl_unit: np.ndarray
    u_img_e: np.ndarray
    halfgam_e: np.ndarray


_TABLES = {}


def get_table(solver: ThinCascade, thickness, mean, cache_dir=None):
    """Lattice table for a shape, from memory, the disk cache or built (about 25 s)."""
    import os
    from pathlib import Path
    key = (thickness, mean, solver.N, solver.K, solver.xe.size)
    if key in _TABLES:
        return _TABLES[key]
    cache = Path(cache_dir or os.environ.get("HSPROP_CACHE", Path.home() / ".cache" / "hsprop"))
    fname = cache / ("lattice_%s_%s_%d_%d_%d_v1.npz" % key)
    tab = None
    if fname.exists():
        try:
            d = np.load(fname)
            tab = LatticeTable.__new__(LatticeTable)
            tab.solver = solver
            for k in ("u", "xi", "cl", "a0", "uimg", "hg"):
                setattr(tab, k, d[k])
        except Exception:
            tab = None
    if tab is None:
        tab = LatticeTable(solver, thickness, mean)
        try:
            cache.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(fname, u=tab.u, xi=tab.xi, cl=tab.cl, a0=tab.a0, uimg=tab.uimg, hg=tab.hg)
        except OSError:
            pass
    _TABLES[key] = tab
    return tab


def solve_tabulated(tables, keys, sigma, xi, beta):
    """Mapped-lattice solution for S stations from per-shape tables (``keys`` per station)."""
    sigma = np.atleast_1d(np.asarray(sigma, dtype=float))
    xi = np.atleast_1d(np.asarray(xi, dtype=float))
    beta = np.atleast_1d(np.asarray(beta, dtype=float))
    sm, xm = map_lattice(sigma, xi, beta)
    S = sm.size
    first = tables[keys[0]]
    E = first.solver.xe.size
    cl = np.empty((S, 3))
    a0 = np.empty((S, 3))
    uimg = np.empty((S, E, 3))
    hg = np.empty((S, E, 3))
    keys = list(keys)
    for k in set(keys):
        sel = np.array([kk == k for kk in keys])
        c, a, ui, h = tables[k].lookup(sm[sel], xm[sel])
        cl[sel], a0[sel], uimg[sel], hg[sel] = c, a, ui, h
    A = np.zeros((S, 1, 3))
    A[:, 0, :] = a0
    return TableSolution(beta=beta, sigma_m=sm, xi_m=xm, A=A, cl_unit=cl, u_img_e=uimg, halfgam_e=hg)
