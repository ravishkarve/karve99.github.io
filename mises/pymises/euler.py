"""Steady 2-D (quasi-3-D) Euler solver for a blade-to-blade cascade passage.

MISES solves the steady Euler equations on an intrinsic streamline grid
with a global Newton method.  This module solves the same equations, in
conservation form with a variable streamtube thickness ``b(x)`` (MISES'
quasi-3-D / AVDR capability), using a robust and simple method:

* structured periodic H-grid (algebraic, clustered at LE and TE),
* cell-centred finite volumes, central fluxes with Jameson-Schmidt-Turkel
  scalar artificial dissipation (2nd-difference shock capturing switched by
  a pressure sensor, 4th-difference background),
* 4-stage Runge-Kutta pseudo-time marching with local time steps and
  implicit residual smoothing,
* characteristic boundary conditions: inlet total pressure, total
  temperature and flow angle (outgoing Riemann invariant extrapolated);
  exit static pressure (entropy, tangential velocity and incoming
  Riemann invariant extrapolated); a controller adjusts the exit pressure to
  match a prescribed inlet Mach number, as in MISES,
* slip walls via mirror ghost cells, with optional wall transpiration used
  to impose boundary-layer displacement effects.

Units: rho0 = a0 = 1 (p0 = 1/gamma, T0 = 1, R = 1/gamma).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import solve_banded
from scipy.linalg.lapack import dgtsv as _gtsv

from . import gas
from .geometry import Blade


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------

@dataclass
class EulerOptions:
    ni_inlet: int = 24
    ni_blade: int = 72
    ni_exit: int = 28
    nj: int = 28
    inlet_length: float = 0.8      # axial chords upstream of the LE
    exit_length: float = 1.2       # axial chords downstream of the TE
    blade_cluster: float = 0.9     # 0 = uniform, 1 = full cosine clustering
    cfl: float = 3.5
    irs: float = 0.6               # implicit residual smoothing coefficient
    k2: float = 0.6
    k4: float = 1.0 / 48.0
    shock_switch_mach: float = 0.85  # 2nd-difference dissipation only above this local Mach
    max_steps: int = 8000
    tol: float = 1e-3              # target RMS density-residual drop (relative)
    control_interval: int = 300    # steps between exit-pressure corrections
    control_gain: float = 1.0
    isoenergetic: bool = True      # impose uniform total enthalpy (steady adiabatic flow)
    mass_tol: float = 2e-4         # inlet/exit mass-flow balance required for convergence
    grid_smoothing: int = 300      # Laplace-type smoothing sweeps of interior grid lines
    wall_cluster: float | None = None  # 0 uniform .. 1 strong wall clustering; None = automatic
    coupling_cycles: int = 8
    coupling_steps: int = 1000
    coupling_relax: float = 1.0

    def to_dict(self):
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------

def _geometric(n, length, first):
    """n spacings summing to length, starting with 'first' and growing geometrically."""
    if first * n >= length:
        return np.full(n, length / n)
    lo, hi = 1.0 + 1e-9, 3.0
    for _ in range(200):
        r = 0.5 * (lo + hi)
        tot = first * (r ** n - 1.0) / (r - 1.0)
        if tot > length:
            hi = r
        else:
            lo = r
    r = 0.5 * (lo + hi)
    d = first * r ** np.arange(n)
    return d * length / d.sum()


@dataclass
class HGrid:
    """Structured H-grid for one periodic blade passage (or a channel)."""

    X: np.ndarray                  # node x (ni+1, nj+1)
    Y: np.ndarray                  # node y (ni+1, nj+1)
    wall_lo: np.ndarray            # bool per cell column: j=0 face is a wall
    wall_hi: np.ndarray            # bool per cell column: j=nj face is a wall
    pitch: float | None = None
    b_nodes: np.ndarray | None = None    # streamtube thickness at node columns
    i_le: int = 0
    i_te: int = 0
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        X, Y = self.X, self.Y
        self.ni = X.shape[0] - 1
        self.nj = X.shape[1] - 1
        # i-faces (ni+1, nj, 2) pointing +i ; j-faces (ni, nj+1, 2) pointing +j
        self.Si = np.stack([Y[:, 1:] - Y[:, :-1], -(X[:, 1:] - X[:, :-1])], axis=-1)
        self.Sj = np.stack([-(Y[1:, :] - Y[:-1, :]), X[1:, :] - X[:-1, :]], axis=-1)
        x1, y1 = X[:-1, :-1], Y[:-1, :-1]
        x2, y2 = X[1:, :-1], Y[1:, :-1]
        x3, y3 = X[1:, 1:], Y[1:, 1:]
        x4, y4 = X[:-1, 1:], Y[:-1, 1:]
        self.area = 0.5 * ((x3 - x1) * (y4 - y2) - (y3 - y1) * (x4 - x2))
        if np.any(self.area <= 0):
            raise ValueError("H-grid has non-positive cell areas (check geometry / pitch)")
        self.xc = 0.25 * (x1 + x2 + x3 + x4)
        self.yc = 0.25 * (y1 + y2 + y3 + y4)
        if self.b_nodes is None:
            self.b_nodes = np.ones(self.ni + 1)
        b = self.b_nodes
        self.bi = b[:, None] * np.ones((1, self.nj))                   # at i-faces
        bc = 0.5 * (b[:-1] + b[1:])
        self.bj = bc[:, None] * np.ones((1, self.nj + 1))             # at j-faces
        self.bc = bc[:, None] * np.ones((1, self.nj))                 # at cells
        # b-weighted outward face-vector sum (momentum source p * grad b)
        Si, Sj = self.Si, self.Sj
        src = (self.bi[1:, :, None] * Si[1:] - self.bi[:-1, :, None] * Si[:-1]
               + self.bj[:, 1:, None] * Sj[:, 1:] - self.bj[:, :-1, None] * Sj[:, :-1])
        self.src = np.moveaxis(src, -1, 0)
        self.vol = self.area * self.bc
        nlo = Sj[:, 0]
        nhi = Sj[:, -1]
        self.n_lo = nlo / np.linalg.norm(nlo, axis=-1)[:, None]
        self.n_hi = nhi / np.linalg.norm(nhi, axis=-1)[:, None]

    # ------------------------------------------------------------ builders
    @classmethod
    def for_blade(cls, blade: Blade, opts: EulerOptions, beta1_deg: float, beta2_deg: float,
                  avdr: float = 1.0):
        x_le, x_te, fu, fl = blade.axial_surfaces()
        cax = x_te - x_le
        s = blade.pitch
        t = np.linspace(0.0, 1.0, opts.ni_blade + 1)
        w = opts.blade_cluster
        g = w * 0.5 * (1.0 - np.cos(np.pi * t)) + (1.0 - w) * t
        xb = x_le + cax * g
        d_le = xb[1] - xb[0]
        d_te = xb[-1] - xb[-2]
        du = _geometric(opts.ni_inlet, opts.inlet_length * cax, d_le)
        dd = _geometric(opts.ni_exit, opts.exit_length * cax, d_te)
        xu = x_le - np.concatenate([[0.0], np.cumsum(du)])[::-1]
        xd = x_te + np.cumsum(dd)
        xn = np.concatenate([xu[:-1], xb, xd])
        i_le = opts.ni_inlet
        i_te = opts.ni_inlet + opts.ni_blade
        y_le = float(fu(x_le))
        y_te = float(fu(x_te))
        t1, t2 = math.tan(math.radians(beta1_deg)), math.tan(math.radians(beta2_deg))
        ylo = np.empty_like(xn)
        yhi = np.empty_like(xn)
        up = xn <= x_le
        dn = xn >= x_te
        bl = ~(up | dn)
        ylo[up] = y_le + (xn[up] - x_le) * t1
        yhi[up] = ylo[up] + s
        ylo[dn] = y_te + (xn[dn] - x_te) * t2
        yhi[dn] = ylo[dn] + s
        ylo[bl] = fu(xn[bl])
        yhi[bl] = fl(xn[bl]) + s
        ylo[i_le], yhi[i_le] = y_le, y_le + s
        ylo[i_te], yhi[i_te] = y_te, y_te + s
        wc = opts.wall_cluster
        if wc is None:
            # strong clustering minimises spurious entropy for moderate turning;
            # highly cambered (turbine) passages need milder, less skewed wall cells
            a1, a2 = blade.estimated_metal_angles()
            wc = 0.9 if abs(a1 - a2) <= 60.0 else 0.6
        eta = _wall_clustered(opts.nj, wc)
        X = np.repeat(xn[:, None], opts.nj + 1, axis=1)
        Y = ylo[:, None] + (yhi - ylo)[:, None] * eta[None, :]
        Y = _smooth_interior(xn, Y, opts.grid_smoothing, eta=eta)
        ni = xn.size - 1
        wall = np.zeros(ni, dtype=bool)
        wall[i_le:i_te] = True
        # streamtube thickness: 1 upstream, linear to 1/avdr at the TE
        bn = np.ones_like(xn)
        if abs(avdr - 1.0) > 1e-12:
            b_te = 1.0 / avdr
            ramp = np.clip((xn - x_le) / cax, 0.0, 1.0)
            bn = 1.0 + (b_te - 1.0) * ramp
        return cls(X, Y, wall, wall.copy(), s, bn, i_le, i_te,
                   {"x_le": x_le, "x_te": x_te, "cax": cax, "y_le": y_le, "y_te": y_te})

    @classmethod
    def channel(cls, x_nodes, y_lower, y_upper, nj, b_nodes=None):
        """All-wall channel (used for verification, e.g. a quasi-1-D nozzle)."""
        eta = np.linspace(0.0, 1.0, nj + 1)
        X = np.repeat(np.asarray(x_nodes, float)[:, None], nj + 1, axis=1)
        Y = np.asarray(y_lower)[:, None] + (np.asarray(y_upper) - np.asarray(y_lower))[:, None] * eta
        ni = X.shape[0] - 1
        wall = np.ones(ni, dtype=bool)
        return cls(X, Y, wall, wall.copy(), None, b_nodes, 0, ni)

    # ------------------------------------------------------------ helpers
    def contour(self):
        """Blade contour from the wall nodes (CCW from TE: suction side, LE, pressure side)."""
        i_le, i_te = self.i_le, self.i_te
        s = self.pitch
        xs = self.X[i_le:i_te + 1, 0]
        ys = self.Y[i_le:i_te + 1, 0]
        xp = self.X[i_le:i_te + 1, -1]
        yp = self.Y[i_le:i_te + 1, -1] - s
        x = np.concatenate([xs[::-1], xp[1:]])
        y = np.concatenate([ys[::-1], yp[1:]])
        return x, y


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------

@dataclass
class EulerState:
    U: np.ndarray
    p_exit: float
    steps: int = 0
    history: list = field(default_factory=list)


class EulerSolver:
    """Finite-volume Euler solver on an :class:`HGrid`."""

    def __init__(self, grid: HGrid, beta1_deg: float, mach1: float, gamma=gas.GAMMA_AIR,
                 opts: EulerOptions | None = None, p_exit=None, target_mach=True):
        self.g = grid
        self.gamma = gamma
        self.opts = opts or EulerOptions()
        self.beta1 = math.radians(beta1_deg)
        self.mach1 = mach1
        self.target_mach = target_mach and p_exit is None
        self.p0 = 1.0 / gamma
        self.h0 = 1.0 / (gamma - 1.0)
        ni, nj = grid.ni, grid.nj
        self.mw_lo = np.zeros(ni)      # transpiration mass flux per wall face (into flow)
        self.mw_hi = np.zeros(ni)
        self._irs_i = self._irs_matrix(ni)
        self._irs_j = self._irs_matrix(nj)
        self.p_exit = p_exit if p_exit is not None else self.p0 * float(gas.p_ratio(mach1, gamma))
        self.U = None
        self._ctrl_gain = self.opts.control_gain
        self._ctrl_err = None

    # ------------------------------------------------------------ setup
    def _irs_matrix(self, n):
        e = self.opts.irs
        ab = np.zeros((3, n))
        ab[0, 1:] = -e
        ab[1, :] = 1.0 + 2.0 * e
        ab[2, :-1] = -e
        return ab

    def initialise(self, beta2_deg=None, mach2=None):
        """Uniform-axial-velocity initial guess with a linear angle change."""
        g = self.g
        gam = self.gamma
        m1 = self.mach1
        rho, V, p, _ = _uniform(m1, gam)
        b1 = self.beta1
        u = V * math.cos(b1)
        b2 = math.radians(beta2_deg) if beta2_deg is not None else b1
        x_le = g.meta.get("x_le", g.xc.min())
        x_te = g.meta.get("x_te", g.xc.max())
        f = np.clip((g.xc - x_le) / max(x_te - x_le, 1e-12), 0.0, 1.0)
        tb = math.tan(b1) + f * (math.tan(b2) - math.tan(b1))
        v = u * tb
        U = np.empty((4, g.ni, g.nj))
        U[0] = rho
        U[1] = rho * u
        U[2] = rho * v
        U[3] = p / (gam - 1.0) + 0.5 * rho * (u * u + v * v)
        self.U = U
        if mach2 is not None and self.target_mach:
            # start from a slightly higher back pressure (lower mass flow): the
            # controller then approaches the inlet Mach number from below, which
            # avoids choking transients in transonic cascades
            self.p_exit = self.p0 * float(gas.p_ratio(0.85 * mach2, gam))

    # ------------------------------------------------------------ BCs
    def _ghosts(self, U):
        g = self.g
        gam = self.gamma
        ni, nj = g.ni, g.nj
        P = np.pad(U, ((0, 0), (2, 2), (2, 2)), mode="edge")
        # --- j ghosts (lower / upper) -----------------------------------
        per = ~g.wall_lo
        if np.any(per):
            cols = np.where(per)[0] + 2
            P[:, cols, 0:2] = U[:, per, nj - 2:nj]
            P[:, cols, nj + 2:nj + 4] = U[:, per, 0:2]
        wl = g.wall_lo
        if np.any(wl):
            cols = np.where(wl)[0] + 2
            n = g.n_lo[wl]
            for gj, ij in ((1, 0), (0, 1)):
                P[:, cols, gj] = _mirror(U[:, wl, ij], n)
        wh = g.wall_hi
        if np.any(wh):
            cols = np.where(wh)[0] + 2
            n = g.n_hi[wh]
            for gj, ij in ((nj + 2, nj - 1), (nj + 3, nj - 2)):
                P[:, cols, gj] = _mirror(U[:, wh, ij], n)
        # --- inlet (characteristic) --------------------------------------
        rho, u, v, p = _prim(U[:, 0, :], gam)
        a = np.sqrt(np.maximum(gam * p / rho, 1e-12))
        Rm = u - 2.0 * a / (gam - 1.0)
        c = math.cos(self.beta1)
        A = (gam - 1.0) * c * c / 4.0 + 0.5
        B = (gam - 1.0) * c * Rm / 2.0
        C = (gam - 1.0) * Rm * Rm / 4.0 - self.h0
        V = (B + np.sqrt(np.maximum(B * B - 4.0 * A * C, 0.0))) / (2.0 * A)
        a2 = np.maximum((gam - 1.0) * (self.h0 - 0.5 * V * V), 1e-8)
        pin = self.p0 * a2 ** (gam / (gam - 1.0))
        rin = gam * pin / a2
        uin, vin = V * c, V * math.sin(self.beta1)
        Gin = np.array([rin, rin * uin, rin * vin, pin / (gam - 1.0) + 0.5 * rin * V * V])
        P[:, 0, 2:nj + 2] = Gin
        P[:, 1, 2:nj + 2] = Gin
        # --- exit ----------------------------------------------------------
        rho, u, v, p = _prim(U[:, -1, :], gam)
        a = np.sqrt(np.maximum(gam * p / rho, 1e-12))
        sup = u > a
        ent = p / rho ** gam
        Rp = u + 2.0 * a / (gam - 1.0)
        pe = np.full_like(p, self.p_exit)
        re = (pe / ent) ** (1.0 / gam)
        ae = np.sqrt(gam * pe / re)
        ue = np.maximum(Rp - 2.0 * ae / (gam - 1.0), 1e-3)
        Gout = np.array([re, re * ue, re * v, pe / (gam - 1.0) + 0.5 * re * (ue * ue + v * v)])
        Gout[:, sup] = U[:, -1, sup]
        P[:, ni + 2, 2:nj + 2] = Gout
        P[:, ni + 3, 2:nj + 2] = Gout
        return P

    # ------------------------------------------------------------ residual
    def residual(self, U, with_dt=False):
        g = self.g
        gam = self.gamma
        o = self.opts
        ni, nj = g.ni, g.nj
        P = self._ghosts(U)
        rho = P[0]
        u = P[1] / rho
        v = P[2] / rho
        p = np.maximum((gam - 1.0) * (P[3] - 0.5 * rho * (u * u + v * v)), 1e-9)
        a = np.sqrt(gam * p / rho)
        W = np.array([P[0], P[1], P[2], P[3] + p])      # rho, rho u, rho v, rho H
        # dissipation stencils at walls: linear extrapolation instead of mirror ghosts
        # (JST boundary closure), so the fourth difference does not act on the
        # sign-flipped normal momentum of the mirror cells
        Wd = W.copy()
        if np.any(g.wall_lo):
            cols = np.where(g.wall_lo)[0] + 2
            Wd[:, cols, 1] = 2.0 * W[:, cols, 2] - W[:, cols, 3]
            Wd[:, cols, 0] = 2.0 * Wd[:, cols, 1] - W[:, cols, 2]
        if np.any(g.wall_hi):
            cols = np.where(g.wall_hi)[0] + 2
            Wd[:, cols, nj + 2] = 2.0 * W[:, cols, nj + 1] - W[:, cols, nj]
            Wd[:, cols, nj + 3] = 2.0 * Wd[:, cols, nj + 2] - W[:, cols, nj + 1]
        # shock switch: second-difference dissipation only where the flow is near sonic
        mach = np.sqrt((u * u + v * v)) / a
        msw = np.clip((mach - o.shock_switch_mach) / 0.15, 0.0, 1.0)

        # ---- i-direction fluxes (faces 0..ni, rows 2..nj+1) -------------
        js = slice(2, nj + 2)
        Sx, Sy = g.Si[..., 0], g.Si[..., 1]
        Smag = np.hypot(Sx, Sy)
        L, R = slice(1, ni + 2), slice(2, ni + 3)
        Fi = self._flux(P, W, rho, u, v, p, a, (L, js), (R, js), Sx, Sy, Smag)
        nu = _sensor(p[:, js], axis=0) * np.maximum(msw[:-2, js], np.maximum(msw[1:-1, js], msw[2:, js]))
        e2 = o.k2 * np.maximum(nu[:-1], nu[1:])          # faces 0..ni
        e4 = np.maximum(0.0, o.k4 - e2)
        lam = self._lam
        Wr = W[:, :, js]
        d = lam * (e2 * (Wr[:, 2:ni + 3] - Wr[:, 1:ni + 2])
                   - e4 * (Wr[:, 3:ni + 4] - 3.0 * Wr[:, 2:ni + 3] + 3.0 * Wr[:, 1:ni + 2]
                           - Wr[:, 0:ni + 1]))
        Fi = (Fi - d) * g.bi

        # ---- j-direction fluxes (faces 0..nj, columns 2..ni+1) ----------
        is_ = slice(2, ni + 2)
        Sx, Sy = g.Sj[..., 0], g.Sj[..., 1]
        Smag = np.hypot(Sx, Sy)
        L, R = slice(1, nj + 2), slice(2, nj + 3)
        Fj = self._flux(P, W, rho, u, v, p, a, (is_, L), (is_, R), Sx, Sy, Smag)
        nu = _sensor(p[is_, :], axis=1) * np.maximum(msw[is_, :-2], np.maximum(msw[is_, 1:-1], msw[is_, 2:]))
        e2 = o.k2 * np.maximum(nu[:, :-1], nu[:, 1:])
        e4 = np.maximum(0.0, o.k4 - e2)
        lamj = self._lam
        Wc = Wd[:, is_, :]
        d = lamj * (e2 * (Wc[:, :, 2:nj + 3] - Wc[:, :, 1:nj + 2])
                    - e4 * (Wc[:, :, 3:nj + 4] - 3.0 * Wc[:, :, 2:nj + 3]
                            + 3.0 * Wc[:, :, 1:nj + 2] - Wc[:, :, 0:nj + 1]))
        d[:, g.wall_lo, 0] = 0.0
        d[:, g.wall_hi, -1] = 0.0
        Fj = (Fj - d) * g.bj
        # ---- wall transpiration -----------------------------------------
        if np.any(self.mw_lo) or np.any(self.mw_hi):
            self._transpiration(Fj, U, gam)

        Res = (Fi[:, 1:] - Fi[:, :-1]) + (Fj[:, :, 1:] - Fj[:, :, :-1])
        pin = p[2:ni + 2, 2:nj + 2]
        Res[1] -= pin * g.src[0]
        Res[2] -= pin * g.src[1]
        if not with_dt:
            return Res
        # local time step
        uc, vc, ac = u[is_, js], v[is_, js], a[is_, js]
        Sbi = 0.5 * (g.Si[1:] + g.Si[:-1])
        Sbj = 0.5 * (g.Sj[:, 1:] + g.Sj[:, :-1])
        li = np.abs(uc * Sbi[..., 0] + vc * Sbi[..., 1]) + ac * np.hypot(Sbi[..., 0], Sbi[..., 1])
        lj = np.abs(uc * Sbj[..., 0] + vc * Sbj[..., 1]) + ac * np.hypot(Sbj[..., 0], Sbj[..., 1])
        dt = o.cfl * g.area / (li + lj)
        self._lij = (li, lj)
        return Res, dt

    def _flux(self, P, W, rho, u, v, p, a, iL, iR, Sx, Sy, Smag):
        rl, ul, vl, pl, al = rho[iL], u[iL], v[iL], p[iL], a[iL]
        rr, ur, vr, pr, ar = rho[iR], u[iR], v[iR], p[iR], a[iR]
        unl = ul * Sx + vl * Sy
        unr = ur * Sx + vr * Sy
        Hl = W[3][iL] / rl
        Hr = W[3][iR] / rr
        F = np.empty((4,) + Sx.shape)
        F[0] = 0.5 * (rl * unl + rr * unr)
        F[1] = 0.5 * (rl * ul * unl + rr * ur * unr + (pl + pr) * Sx)
        F[2] = 0.5 * (rl * vl * unl + rr * vr * unr + (pl + pr) * Sy)
        F[3] = 0.5 * (rl * Hl * unl + rr * Hr * unr)
        self._lam = 0.5 * (np.abs(unl + unr) + (al + ar) * Smag)
        return F

    def _transpiration(self, Fj, U, gam):
        g = self.g
        for mw, jf, jc, n in ((self.mw_lo, 0, 0, g.n_lo), (self.mw_hi, -1, -1, g.n_hi)):
            sel = np.abs(mw) > 0
            if not np.any(sel):
                continue
            rho, u, v, p = _prim(U[:, sel, jc], gam)
            nn = n[sel]
            vn = u * nn[:, 0] + v * nn[:, 1]
            ut, vt = u - vn * nn[:, 0], v - vn * nn[:, 1]
            H = (U[3, sel, jc] + p) / rho
            sign = 1.0 if jf == 0 else -1.0
            m = sign * mw[sel] * g.bj[sel, jf]
            Fj[0, sel, jf] += m
            Fj[1, sel, jf] += m * ut
            Fj[2, sel, jf] += m * vt
            Fj[3, sel, jf] += m * H

    # ------------------------------------------------------------ iteration
    def _smooth(self, D):
        """Implicit residual smoothing with Martinelli's variable coefficients."""
        o = self.opts
        if o.irs <= 0:
            return D
        li, lj = self._lij
        r = lj / li
        ratio = o.cfl / 2.5
        ei = np.maximum(0.0, 0.25 * (ratio * (1.0 + np.sqrt(r)) / (1.0 + r)) ** 2 - 0.25)
        ej = np.maximum(0.0, 0.25 * (ratio * (1.0 + np.sqrt(1.0 / r)) / (1.0 + 1.0 / r)) ** 2 - 0.25)
        ei = np.minimum(ei, o.irs * 4.0)
        ej = np.minimum(ej, o.irs * 4.0)
        D = _thomas(D, ei, axis=1)
        D = _thomas(D, ej, axis=2)
        return D

    def step(self):
        U0 = self.U
        Res, dt = self.residual(U0, with_dt=True)
        fac = dt / self.g.vol
        Uk = U0
        r0 = None
        for k, alpha in enumerate((0.25, 1.0 / 3.0, 0.5, 1.0)):
            if k > 0:
                Res = self.residual(Uk)
            else:
                r0 = Res
            D = self._smooth(Res * fac)
            Uk = U0 - alpha * D
        # positivity safeguard: cells whose update would give (near) negative
        # density or pressure keep their previous state for this step
        rho_n = Uk[0]
        p_n = (self.gamma - 1.0) * (Uk[3] - 0.5 * (Uk[1] ** 2 + Uk[2] ** 2) / np.maximum(rho_n, 1e-12))
        bad = (rho_n < 0.02) | (p_n < 0.02 * self.p0) | ~np.isfinite(p_n)
        if np.any(bad):
            Uk[:, bad] = U0[:, bad]
        Uk[0] = np.maximum(Uk[0], 1e-6)
        if self.opts.isoenergetic:
            # steady adiabatic cascade flow has uniform total enthalpy: impose it
            # (replaces the slowly converging energy equation, exact at steady state)
            rho = Uk[0]
            ke = 0.5 * (Uk[1] ** 2 + Uk[2] ** 2) / rho
            gam = self.gamma
            Uk[3] = (rho * self.h0 + (gam - 1.0) * ke) / gam
        self.U = Uk
        return float(np.sqrt(np.mean((r0[0] / self.g.vol) ** 2)))

    def inlet_state(self):
        """Face-weighted average inlet static pressure and Mach number (first cell column)."""
        g = self.g
        rho, u, v, p = _prim(self.U[:, 0, :], self.gamma)
        w = np.hypot(g.Si[0, :, 0], g.Si[0, :, 1])
        pm = float(np.sum(p * w) / np.sum(w))
        M = float(gas.mach_from_p_ratio(pm / self.p0, self.gamma))
        return pm, M

    def run(self, max_steps=None, tol=None, verbose=False, callback=None):
        o = self.opts
        max_steps = max_steps or o.max_steps
        tol = tol if tol is not None else o.tol
        if self.U is None:
            self.initialise()
        hist = []
        # residuals are measured relative to the start of the whole computation, so a
        # restart from a nearly converged state (coupling cycles, final pass) does not
        # demand a further 1/tol drop from an already small residual
        r_ref = getattr(self, "_r_ref", None)
        fixed_ref = r_ref is not None
        p1_target = self.p0 * float(gas.p_ratio(self.mach1, self.gamma))
        t0 = time.time()
        converged = False
        last_ctrl = 0
        n = 0
        for n in range(1, max_steps + 1):
            r = self.step()
            if not np.isfinite(r):
                raise FloatingPointError("Euler solver diverged (NaN residual)")
            if not fixed_ref and (r_ref is None or n <= 5):
                r_ref = max(r_ref or 0.0, r)
                self._r_ref = r_ref
            hist.append(r / r_ref)
            if self.target_mach and n - last_ctrl >= o.control_interval:
                pm, _ = self.inlet_state()
                err = p1_target - pm
                # adaptive gain: halve on overshoot (sign change), recover slowly
                if self._ctrl_err is not None and err * self._ctrl_err < 0:
                    self._ctrl_gain = max(0.1, 0.5 * self._ctrl_gain)
                else:
                    self._ctrl_gain = min(o.control_gain, 1.2 * self._ctrl_gain)
                self._ctrl_err = err
                dp = self._ctrl_gain * err
                self.p_exit += float(np.clip(dp, -0.03 * self.p0, 0.03 * self.p0))
                self.p_exit = min(max(self.p_exit, 0.05 * self.p0), 0.9999 * self.p0)
                last_ctrl = n
            if self.target_mach and self.p_exit < 0.35 * self.p0:
                pm, M = self.inlet_state()
                if M < self.mach1 - 0.02:
                    self.choked = True
                    break
            if callback is not None and n % 50 == 0:
                callback(n, hist[-1])
            if verbose and n % 200 == 0:
                pm, M = self.inlet_state()
                print(f"  Euler step {n:5d}  res {hist[-1]:.3e}  M1 {M:.4f}  p_exit {self.p_exit:.5f}")
            if n > 50 and hist[-1] < tol and n % 25 == 0:
                m_in = self.plane_fluxes(1)[0]
                m_out = self.plane_fluxes(self.g.ni - 2)[0]
                # wall transpiration (viscous displacement) adds mass between the planes
                if abs(m_out - m_in - self.transpiration_mass()) > o.mass_tol * abs(m_in):
                    continue
                if not self.target_mach:
                    converged = True
                    break
                pm, M = self.inlet_state()
                if abs(M - self.mach1) < 5e-4:
                    converged = True
                    break
                # converged at the wrong inlet Mach number: correct now
                dp = self._ctrl_gain * (p1_target - pm)
                self.p_exit += float(np.clip(dp, -0.03 * self.p0, 0.03 * self.p0))
                self.p_exit = min(max(self.p_exit, 0.05 * self.p0), 0.9999 * self.p0)
                last_ctrl = n
        self.last_run = {"steps": n, "converged": converged, "history": hist,
                         "seconds": time.time() - t0, "choked": getattr(self, "choked", False)}
        return self.last_run

    # ------------------------------------------------------------ outputs
    def primitives(self):
        rho, u, v, p = _prim(self.U, self.gamma)
        return rho, u, v, p

    def mach_field(self):
        rho, u, v, p = self.primitives()
        return np.hypot(u, v) / np.sqrt(self.gamma * p / rho)

    def plane_fluxes(self, i_face):
        """Mass, x- and y-momentum and energy fluxes across i-face column i_face (per unit span)."""
        g = self.g
        gam = self.gamma
        ic = min(max(i_face, 1), g.ni - 1)
        UL = self.U[:, ic - 1, :]
        UR = self.U[:, ic, :]
        Ua = 0.5 * (UL + UR)
        rho, u, v, p = _prim(Ua, gam)
        S = g.Si[ic]
        un = u * S[:, 0] + v * S[:, 1]
        b = g.bi[ic]
        mdot = float(np.sum(rho * un * b))
        fx = float(np.sum((rho * u * un + p * S[:, 0]) * b))
        fy = float(np.sum((rho * v * un + p * S[:, 1]) * b))
        H = (Ua[3] + p) / rho
        fe = float(np.sum(rho * H * un * b))
        return mdot, fx, fy, fe, float(np.sum(S[:, 0] * b))

    def wall_data(self):
        """Wall pressure, tangential velocity and density at contour nodes.

        Returns dict with contour (x, y), p, q (signed along contour
        direction, CCW from the TE), rho and indices of the LE node.
        """
        g = self.g
        gam = self.gamma
        rho, u, v, p = self.primitives()
        i_le, i_te = g.i_le, g.i_te

        def wall_side(jc, jn):
            # extrapolate cell values to the wall (linear in j), then to nodes
            pw = 1.5 * p[:, jc] - 0.5 * p[:, jn]
            uw = 1.5 * u[:, jc] - 0.5 * u[:, jn]
            vw = 1.5 * v[:, jc] - 0.5 * v[:, jn]
            rw = 1.5 * rho[:, jc] - 0.5 * rho[:, jn]
            cols = np.arange(i_le, i_te + 1)
            lft = np.clip(cols - 1, 0, g.ni - 1)
            rgt = np.clip(cols, 0, g.ni - 1)
            # at LE/TE use only the wall cell
            lft[0] = rgt[0]
            rgt[-1] = lft[-1]
            avg = lambda f: 0.5 * (f[lft] + f[rgt])
            return avg(pw), avg(uw), avg(vw), avg(rw)

        ps, us, vs, rs = wall_side(0, 1)
        pp, up, vp, rp = wall_side(-1, -2)
        # stagnation pressure of the core flow a few cells off the wall, used to
        # evaluate isentropic edge speeds that are free of the numerical entropy
        # layer generated at the leading edge
        p0f = p * (1.0 + 0.5 * (gam - 1.0) * (u * u + v * v) * rho / (gam * p)) ** (gam / (gam - 1.0))
        joff = max(2, g.nj // 5)
        cols = np.arange(i_le, i_te + 1)
        cl = np.clip(cols - 1, 0, g.ni - 1)
        cr = np.clip(cols, 0, g.ni - 1)
        cl[0] = cr[0]
        cr[-1] = cl[-1]
        p0s = 0.5 * (p0f[cl, joff] + p0f[cr, joff])
        p0p = 0.5 * (p0f[cl, -1 - joff] + p0f[cr, -1 - joff])
        xc, yc = g.contour()
        # contour tangent (central differences)
        tx = np.gradient(xc)
        ty = np.gradient(yc)
        tn = np.hypot(tx, ty)
        tx, ty = tx / tn, ty / tn
        p_c = np.concatenate([ps[::-1], pp[1:]])
        u_c = np.concatenate([us[::-1], up[1:]])
        v_c = np.concatenate([vs[::-1], vp[1:]])
        r_c = np.concatenate([rs[::-1], rp[1:]])
        # at the LE both sides meet: average
        n_s = i_te - i_le
        p_c[n_s] = 0.5 * (ps[0] + pp[0])
        u_c[n_s] = 0.5 * (us[0] + up[0])
        v_c[n_s] = 0.5 * (vs[0] + vp[0])
        q = u_c * tx + v_c * ty
        p0_c = np.concatenate([p0s[::-1], p0p[1:]])
        p0_c[n_s] = 0.5 * (p0s[0] + p0p[0])
        pr = np.clip(p_c / p0_c, 1e-6, 1.0)
        m_is = gas.mach_from_p_ratio(pr, gam)
        q_is = m_is * np.sqrt(gas.t_ratio(m_is, gam))
        rho_is = gam * p0_c * pr ** (1.0 / gam)
        return {"x": xc, "y": yc, "p": p_c, "q": q, "rho": r_c, "i_le": n_s, "p0": p0_c,
                "q_is": np.sign(q) * q_is, "rho_is": rho_is}

    def mass_averaged_p0(self, i_col):
        """Mass-averaged stagnation pressure across cell column ``i_col``."""
        g = self.g
        gam = self.gamma
        rho, u, v, p = _prim(self.U[:, i_col, :], gam)
        p0 = p * (1.0 + 0.5 * (gam - 1.0) * (u * u + v * v) * rho / (gam * p)) ** (gam / (gam - 1.0))
        S = 0.5 * (g.Si[i_col] + g.Si[i_col + 1])
        mflux = rho * (u * S[:, 0] + v * S[:, 1])
        return float(np.sum(p0 * mflux) / np.sum(mflux))

    def transpiration_mass(self):
        """Net mass flow injected through the walls by transpiration (per unit span)."""
        g = self.g
        return float(np.sum(self.mw_lo * g.bj[:, 0]) + np.sum(self.mw_hi * g.bj[:, -1]))

    def set_transpiration(self, flux_contour):
        """Set wall transpiration from per-contour-panel mass fluxes (into the flow)."""
        g = self.g
        n_s = g.i_te - g.i_le
        f = np.asarray(flux_contour, float)
        self.mw_lo[:] = 0.0
        self.mw_hi[:] = 0.0
        # contour panel j < n_s : suction face at column i_te - j - 1
        cols_s = g.i_te - np.arange(n_s) - 1
        self.mw_lo[cols_s] = f[:n_s] / np.maximum(g.bj[cols_s, 0], 1e-12)
        cols_p = g.i_le + np.arange(f.size - n_s)
        self.mw_hi[cols_p] = f[n_s:] / np.maximum(g.bj[cols_p, -1], 1e-12)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _prim(U, gam):
    rho = U[0]
    u = U[1] / rho
    v = U[2] / rho
    p = (gam - 1.0) * (U[3] - 0.5 * rho * (u * u + v * v))
    return rho, u, v, p


def _uniform(mach, gam):
    tr = float(gas.t_ratio(mach, gam))
    rho = float(gas.rho_ratio(mach, gam))
    V = mach * math.sqrt(tr)
    p = (1.0 / gam) * tr ** (gam / (gam - 1.0))
    return rho, V, p, tr


def _mirror(Uc, n):
    """Mirror cell states (4, m) about walls with unit normals n (m, 2)."""
    rho = Uc[0]
    mx, my = Uc[1], Uc[2]
    mn = mx * n[:, 0] + my * n[:, 1]
    G = Uc.copy()
    G[1] = mx - 2.0 * mn * n[:, 0]
    G[2] = my - 2.0 * mn * n[:, 1]
    return G


def _sensor(p, axis):
    """JST pressure sensor on interior points along an axis (drops the end points)."""
    if axis == 0:
        pm, pc, pp = p[:-2], p[1:-1], p[2:]
    else:
        pm, pc, pp = p[:, :-2], p[:, 1:-1], p[:, 2:]
    return np.abs(pp - 2.0 * pc + pm) / (pp + 2.0 * pc + pm)


def _smooth_interior(xn, Y, sweeps, w=0.5, eta=None):
    """Smooth interior node y-coordinates (x fixed per column), boundaries fixed.

    Each Jacobi sweep blends the linear interpolant along i (non-uniform x)
    with the linear interpolant along j in the pitchwise coordinate ``eta``,
    which removes the grid-line kinks an algebraic H-grid develops at the
    leading and trailing edges while keeping the wall clustering.
    """
    if sweeps <= 0:
        return Y
    Y = Y.copy()
    nj = Y.shape[1] - 1
    if eta is None:
        eta = np.linspace(0.0, 1.0, nj + 1)
    xm, xc, xp = xn[:-2], xn[1:-1], xn[2:]
    a = ((xp - xc) / (xp - xm))[:, None]
    b = ((xc - xm) / (xp - xm))[:, None]
    em, ec, ep = eta[:-2], eta[1:-1], eta[2:]
    c = ((ep - ec) / (ep - em))[None, :]
    d = ((ec - em) / (ep - em))[None, :]
    for _ in range(sweeps):
        yi = a * Y[:-2, 1:-1] + b * Y[2:, 1:-1]
        yj = c * Y[1:-1, :-2] + d * Y[1:-1, 2:]
        Y[1:-1, 1:-1] = w * yi + (1.0 - w) * yj
    return Y


def _wall_clustered(nj, strength):
    """Pitchwise node distribution on [0, 1] clustered towards both walls."""
    t = np.linspace(0.0, 1.0, nj + 1)
    if strength <= 0:
        return t
    return strength * 0.5 * (1.0 - np.cos(np.pi * t)) + (1.0 - strength) * t


def _thomas(D, e, axis):
    """Solve (1 - e d2) x = D along an axis (1: i, 2: j) for all lines at once.

    All lines are stacked into one tridiagonal system (with zero coupling
    between lines) and solved by LAPACK ``gtsv``.
    """
    X = np.moveaxis(D, axis, 2)                   # (4, m, n): lines along last axis
    E = e.T if axis == 1 else e                   # (m, n)
    m, n = E.shape
    diag = (1.0 + 2.0 * E).ravel()
    lo = -E[:, 1:]
    up = -E[:, :-1]
    dl = np.concatenate([lo, np.zeros((m, 1))], axis=1).ravel()[:-1]
    du = np.concatenate([up, np.zeros((m, 1))], axis=1).ravel()[:-1]
    rhs = X.reshape(4, m * n).T.copy()
    _, _, _, sol, info = _gtsv(dl, diag, du, rhs)
    return np.moveaxis(sol.T.reshape(4, m, n), 2, axis)
