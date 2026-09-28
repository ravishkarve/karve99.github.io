"""Integral boundary-layer model of MISES / XFOIL.

Implements Drela's two-equation integral formulation:

* von Karman momentum equation and kinetic-energy shape-parameter equation,
* laminar closures from Falkner-Skan profiles,
* turbulent closures (Swafford skin friction, H* correlation) with the
  lag-entrainment equation for the maximum shear-stress coefficient,
* e^N envelope transition prediction (amplification-rate correlation of
  Drela & Giles 1987) plus optional forced transition,
* compressibility through Hk, H** and density/viscosity (Sutherland) terms.

The discrete equations follow XFOIL's logarithmic two-point formulation
(BLDIF).  Two solution modes are provided:

``march``
    Station-by-station solution for a prescribed edge velocity, switching
    to inverse mode (prescribed Hk) when the flow approaches separation.
``solve_coupled``
    Simultaneous Newton solution of all BL equations of both surfaces
    together with a linear interaction law ``ue = F(ue0 + D (m - m_ref))``
    for the mass defect ``m = ue * delta*`` (XFOIL / MISES strong coupling).

Lengths are normalised by the chord, velocities by the inlet speed V1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import gas

# XFOIL BLPAR constants
GACON = 6.70
GBCON = 0.75
GCCON = 18.0
DLCON = 0.9
CTRCON = 1.8
CTRCEX = 3.3
SCCON = 5.6
DUXCON = 1.0
CTCON = 0.5 / (GACON ** 2 * GBCON)
HLMAX = 3.8      # laminar Hk limit for inverse march
HTMAX = 2.5      # turbulent Hk limit for inverse march

LAM, TURB = 1, 2


# ---------------------------------------------------------------------------
# closure relations (vectorised)
# ---------------------------------------------------------------------------

def hkin(h, msq):
    """Kinematic shape parameter Hk(H, Me^2) (Whitfield)."""
    return (h - 0.29 * msq) / (1.0 + 0.113 * msq)


def h_from_hk(hk, msq):
    return hk * (1.0 + 0.113 * msq) + 0.29 * msq


def hs_lam(hk):
    """Laminar kinetic-energy shape parameter H*(Hk)."""
    tmp = hk - 4.35
    a = (0.0111 * tmp ** 2 / (hk + 1.0) - 0.0278 * tmp ** 3 / (hk + 1.0) + 1.528
         - 0.0002 * (tmp * hk) ** 2)
    b = 0.015 * tmp ** 2 / hk + 1.528
    return np.where(hk < 4.35, a, b)


def hs_turb(hk, rt, msq):
    """Turbulent H*(Hk, Re_theta, Me^2)."""
    hsmin, dhsinf = 1.5, 0.015
    big = rt > 400.0
    ho = np.where(big, 3.0 + 400.0 / np.maximum(rt, 1e-9), 4.0)
    rtz = np.where(big, rt, 400.0)
    hr = (ho - hk) / (ho - 1.0)
    att = (2.0 - hsmin - 4.0 / rtz) * hr ** 2 * 1.5 / (hk + 0.5) + hsmin + 4.0 / rtz
    grt = np.log(rtz)
    rtmp = hk - ho + 4.0 / grt
    htmp = 0.007 * grt / rtmp ** 2 + dhsinf / hk
    sep = (hk - ho) ** 2 * htmp + hsmin + 4.0 / rtz
    hs = np.where(hk < ho, att, sep)
    return (hs + 0.028 * msq) / (1.0 + 0.014 * msq)


def cf_lam(hk, rt):
    """Laminar skin friction coefficient (Falkner-Skan fit)."""
    a = (0.0727 * (5.5 - hk) ** 3 / (hk + 1.0) - 0.07) / rt
    tmp = 1.0 - 1.0 / np.where(hk > 5.0, hk - 4.5, 1.0)
    b = (0.015 * tmp ** 2 - 0.07) / rt
    return np.where(hk < 5.5, a, b)


def cf_turb(hk, rt, msq, gm1=0.4):
    """Turbulent skin friction coefficient (Swafford profile fit)."""
    fc = np.sqrt(1.0 + 0.5 * gm1 * msq)
    grt = np.maximum(np.log(np.maximum(rt / fc, 1e-9)), 3.0)
    gex = -1.74 - 0.31 * hk
    arg = np.maximum(-1.33 * hk, -20.0)
    thk = np.tanh(4.0 - hk / 0.875)
    cfo = 0.3 * np.exp(arg) * (grt / 2.3026) ** gex
    return (cfo + 1.1e-4 * (thk - 1.0)) / fc


def di_lam(hk, rt):
    """Laminar dissipation 2 CD / H*."""
    a = (0.00205 * np.abs(4.0 - hk) ** 5.5 + 0.207) / rt
    hkb = hk - 4.0
    b = (-0.0016 * hkb ** 2 / (1.0 + 0.02 * hkb ** 2) + 0.207) / rt
    return np.where(hk < 4.0, a, b)


def hc_dens(hk, msq):
    """Density shape parameter H**."""
    return msq * (0.064 / (hk - 0.8) + 0.251)


def ampl_rate(hk, th, rt):
    """Envelope e^N amplification rate dN/dxi (Drela & Giles 1987)."""
    dgr = 0.08
    hmi = 1.0 / (hk - 1.0)
    grcrit = 2.492 * hmi ** 0.43 + 0.7 * (np.tanh(14.0 * hmi - 9.24) + 1.0)
    gr = np.log10(np.maximum(rt, 1e-9))
    rnorm = (gr - (grcrit - dgr)) / (2.0 * dgr)
    rfac = np.where(rnorm >= 1.0, 1.0, 3.0 * rnorm ** 2 - 2.0 * rnorm ** 3)
    arg = 3.87 * hmi - 2.52
    dadr = 0.028 * (hk - 1.0) - 0.0345 * np.exp(-arg ** 2)
    af = -0.05 + 2.7 * hmi - 5.5 * hmi ** 2 + 3.0 * hmi ** 3
    ax = rfac * af * dadr / th
    return np.where(gr < grcrit - dgr, 0.0, ax)


def critical_re_theta(hk):
    """Critical Re_theta for the onset of amplification (log10 form inverted)."""
    hmi = 1.0 / (np.asarray(hk) - 1.0)
    return 10.0 ** (2.492 * hmi ** 0.43 + 0.7 * (np.tanh(14.0 * hmi - 9.24) + 1.0))


# ---------------------------------------------------------------------------
# environment: compressibility and Reynolds number
# ---------------------------------------------------------------------------

@dataclass
class BLEnvironment:
    """Flow environment of the boundary layer.

    reynolds : Re based on inlet velocity V1 and chord.
    mach1    : inlet Mach number (sets the V1/a0 scale for edge Mach numbers).
    """

    reynolds: float
    mach1: float = 0.0
    gamma: float = gas.GAMMA_AIR
    chord: float = 1.0
    t01: float = 288.15
    ncrit: float = 9.0

    def __post_init__(self):
        self.gm1 = self.gamma - 1.0
        self.q1 = float(gas.speed_over_a0(self.mach1, self.gamma))
        self.t1 = float(gas.t_ratio(self.mach1, self.gamma))
        self.rho1 = float(gas.rho_ratio(self.mach1, self.gamma))
        self.re_len = self.reynolds / self.chord

    def msq(self, ue):
        qa2 = (np.asarray(ue) * self.q1) ** 2
        return qa2 / np.maximum(1.0 - 0.5 * self.gm1 * qa2, 1e-6)

    def re_theta(self, ue, th, msq):
        tr = 1.0 / (1.0 + 0.5 * self.gm1 * msq)
        rho = tr ** (1.0 / self.gm1)
        mu = gas.sutherland_ratio(tr / self.t1, tref=self.t01 * self.t1)
        return self.re_len * (rho / self.rho1) * np.abs(ue) * th / mu


# ---------------------------------------------------------------------------
# station and interval evaluation
# ---------------------------------------------------------------------------

class Station(dict):
    __getattr__ = dict.__getitem__


def station_vars(A, th, m, ue, typ, env: BLEnvironment):
    """Secondary BL variables at stations (arrays)."""
    with np.errstate(all="ignore"):
        ue = np.maximum(np.abs(ue), 1e-10)
        th = np.maximum(th, 1e-12)
        msq = env.msq(ue)
        ds = m / ue
        h = ds / th
        hk = np.maximum(hkin(h, msq), 1.05)
        h = np.maximum(h, h_from_hk(1.05, msq))
        rt = np.maximum(env.re_theta(ue, th, msq), 1.0)
        turb = typ == TURB
        hs = np.where(turb, hs_turb(hk, rt, msq), hs_lam(hk))
        hc = hc_dens(hk, msq)
        cfl = cf_lam(hk, rt)
        cft = cf_turb(hk, rt, msq, env.gm1)
        cf = np.where(turb, np.maximum(cft, cfl), cfl)
        us = np.minimum(0.5 * hs * (1.0 - (hk - 1.0) / (GBCON * h)), 0.98)
        hkc = np.maximum(hk - 1.0 - GCCON / rt, 0.01)
        cq = np.sqrt(np.maximum(CTCON * hs * (hk - 1.0) * hkc ** 2 / ((1.0 - us) * h * hk ** 2),
                                1e-20))
        dil = di_lam(hk, rt)
        S = np.maximum(A, 1e-7)
        dit = (0.5 * cft * us + S ** 2 * (0.995 - us) + 0.15 * (0.995 - us) ** 2 / rt) * 2.0 / hs
        di = np.where(turb, np.maximum(dit, dil), dil)
        de = np.minimum((3.15 + 1.72 / (hk - 1.0)) * th + ds, 12.0 * th)
        ax = np.where(turb, 0.0, ampl_rate(hk, th, rt))
    return Station(A=A, th=th, ds=ds, m=m, ue=ue, msq=msq, h=h, hk=hk, rt=rt, hs=hs, hc=hc,
                   cf=cf, us=us, cq=cq, di=di, de=de, ax=ax, S=S)


def interval_residuals(s1, s2, xi1, xi2, kind, env: BLEnvironment):
    """XFOIL BLDIF residuals for intervals 1 -> 2.

    kind : 0 laminar, 1 transition (laminar -> turbulent), 2 turbulent.
    Returns an array (3, n): momentum, shape-parameter, third equation.
    """
    with np.errstate(all="ignore"):
        xlog = np.log(xi2 / xi1)
        ulog = np.log(s2.ue / s1.ue)
        tlog = np.log(s2.th / s1.th)
        hlog = np.log(s2.hs / s1.hs)
        hl = np.log(np.maximum((s2.hk - 1.0) / (s1.hk - 1.0), 1e-12))
        upw = 1.0 - 0.5 * np.exp(-hl ** 2 * 5.0 / s2.hk ** 2)
        ha = 0.5 * (s1.h + s2.h)
        ma = 0.5 * (s1.msq + s2.msq)
        xa = 0.5 * (xi1 + xi2)
        ta = 0.5 * (s1.th + s2.th)
        hka = 0.5 * (s1.hk + s2.hk)
        rta = 0.5 * (s1.rt + s2.rt)
        cfm_l = cf_lam(hka, rta)
        cfm_t = np.maximum(cf_turb(hka, rta, ma, env.gm1), cfm_l)
        cfm = np.where(kind == 0, cfm_l, np.where(kind == 2, cfm_t, 0.5 * (s1.cf + s2.cf)))
        cfx = 0.5 * cfm * xa / ta + 0.25 * (s1.cf * xi1 / s1.th + s2.cf * xi2 / s2.th)
        rez_t = tlog + (ha + 2.0 - ma) * ulog - xlog * 0.5 * cfx

        xot1, xot2 = xi1 / s1.th, xi2 / s2.th
        dix = (1.0 - upw) * s1.di * xot1 + upw * s2.di * xot2
        cfxh = (1.0 - upw) * s1.cf * xot1 + upw * s2.cf * xot2
        hca = 0.5 * (s1.hc + s2.hc)
        hsa = 0.5 * (s1.hs + s2.hs)
        rez_h = hlog + (2.0 * hca / hsa + 1.0 - ha) * ulog + xlog * (0.5 * cfxh - dix)

        dxi = xi2 - xi1
        # laminar amplification
        axa = np.sqrt(0.5 * (s1.ax ** 2 + s2.ax ** 2))
        arg = np.minimum(20.0 * (env.ncrit - 0.5 * (s1.A + s2.A)), 20.0)
        exn = np.where(arg <= 0.0, 1.0, np.exp(-np.maximum(arg, 0.0)))
        dax = exn * 0.002 / (s1.th + s2.th)
        rez_lam = s2.A - s1.A - (axa + dax) * dxi
        # turbulent lag equation
        sa = (1.0 - upw) * s1.S + upw * s2.S
        cqa = (1.0 - upw) * s1.cq + upw * s2.cq
        cfa = (1.0 - upw) * s1.cf + upw * s2.cf
        hku = (1.0 - upw) * s1.hk + upw * s2.hk
        usa = 0.5 * (s1.us + s2.us)
        dea = 0.5 * (s1.de + s2.de)
        da = 0.5 * (s1.ds + s2.ds)
        hkc = np.maximum(hku - 1.0 - GCCON / rta, 0.01)
        hr = hkc / (GACON * hku)
        uq = (0.5 * cfa - hr ** 2) / (GBCON * da)
        scc = SCCON * 1.333 / (1.0 + usa)
        slog = np.log(s2.S / s1.S)
        rez_turb = (scc * (cqa - sa) * dxi - dea * 2.0 * slog
                    + dea * 2.0 * (uq * dxi - ulog) * DUXCON)
        # transition: initial shear stress
        ctr = CTRCON * np.exp(-CTRCEX / (s2.hk - 1.0))
        rez_tr = s2.S - ctr * s2.cq
        rez_c = np.where(kind == 0, rez_lam, np.where(kind == 2, rez_turb, rez_tr))
        # kind 3: frozen interval (last panel into a closed TE): A, theta, delta* held
        frozen = kind == 3
        if np.any(frozen):
            rez_t = np.where(frozen, np.log(s2.th / s1.th), rez_t)
            rez_h = np.where(frozen, np.log(s2.ds / s1.ds), rez_h)
            rez_c = np.where(frozen, s2.A - s1.A, rez_c)
    return np.array([rez_t, rez_h, rez_c])


def similarity_residuals(s, xi):
    """Stagnation-point similarity station residuals (ue ~ xi)."""
    with np.errstate(all="ignore"):
        xot = xi / s.th
        rez_t = (s.h + 2.0 - s.msq) - 0.5 * s.cf * xot
        rez_h = (2.0 * s.hc / s.hs + 1.0 - s.h) + (0.5 * s.cf * xot - s.di * xot)
        rez_c = s.A
    return np.array([rez_t, rez_h, rez_c])


# ---------------------------------------------------------------------------
# surface description
# ---------------------------------------------------------------------------

@dataclass
class Surface:
    """One blade side as a sequence of BL stations, starting next to the stagnation point."""

    name: str
    nodes: np.ndarray       # indices into the blade node arrays
    xi: np.ndarray          # arclength from the stagnation point
    x: np.ndarray
    y: np.ndarray
    xc: np.ndarray          # chordwise position x/c from the LE
    itr_forced: int         # first station forced turbulent (n = none)

    @property
    def n(self):
        return self.nodes.size

    def drop_last(self):
        """Surface without its last (trailing-edge) station."""
        srf = Surface(self.name, self.nodes[:-1], self.xi[:-1], self.x[:-1], self.y[:-1],
                      self.xc[:-1], min(self.itr_forced, self.nodes.size - 1))
        srf.__dict__.update({k: v for k, v in self.__dict__.items()
                             if k in ("stag_panel", "stag_node", "freeze_last")})
        return srf


def build_surfaces(x, y, stag_panel, stag_frac, xtr_upper=1.0, xtr_lower=1.0, le=None,
                   chord_dir=None, chord=1.0):
    """Split blade nodes at the stagnation point into upper and lower surfaces.

    If the stagnation point lies within 25 % of a panel end, that node is
    taken as the stagnation node: it carries zero mass defect and is not a
    BL station (avoids a degenerate first station with ue ~ 0).  The
    returned surfaces carry ``stag_panel``, the panel index to use for the
    mass-defect operator of the panel method.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    N = x.size
    L = np.hypot(np.diff(x), np.diff(y))
    k, f = int(stag_panel), float(stag_frac)
    if f < 0.25 and k >= 1:
        s_node = k                         # node k is the stagnation node
        nodes_u = np.arange(k - 1, -1, -1)
        nodes_l = np.arange(k + 1, N)
        xi_u = np.cumsum(L[:k][::-1])
        xi_l = np.cumsum(L[k:])
        k_eff = k
    elif f > 0.75 and k + 1 <= N - 2:
        s_node = k + 1
        nodes_u = np.arange(k, -1, -1)
        nodes_l = np.arange(k + 2, N)
        xi_u = np.cumsum(L[:k + 1][::-1])
        xi_l = np.cumsum(L[k + 1:])
        k_eff = k + 1
    else:
        s_node = None
        nodes_u = np.arange(k, -1, -1)
        nodes_l = np.arange(k + 1, N)
        xi_u = f * L[k] + np.concatenate([[0.0], np.cumsum(L[:k][::-1])])
        xi_l = (1.0 - f) * L[k] + np.concatenate([[0.0], np.cumsum(L[k + 1:])])
        k_eff = k
    if le is None:
        le = (x[np.argmin(x)], y[np.argmin(x)])
    if chord_dir is None:
        te = 0.5 * (x[0] + x[-1]), 0.5 * (y[0] + y[-1])
        cd = np.array([te[0] - le[0], te[1] - le[1]])
        chord = float(np.hypot(*cd))
        chord_dir = cd / chord
    out = []
    for name, nodes, xi, xtr in (("upper", nodes_u, xi_u, xtr_upper),
                                 ("lower", nodes_l, xi_l, xtr_lower)):
        xc = ((x[nodes] - le[0]) * chord_dir[0] + (y[nodes] - le[1]) * chord_dir[1]) / chord
        forced = np.where(xc >= xtr)[0]
        # never force transition at the similarity station
        itr_f = int(max(forced[0], 1)) if (xtr < 1.0 and forced.size) else nodes.size
        srf = Surface(name, nodes, xi, x[nodes], y[nodes], xc, itr_f)
        srf.stag_panel = k_eff
        srf.stag_node = s_node
        out.append(srf)
    return out[0], out[1]


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

@dataclass
class SurfaceBL:
    name: str
    xi: np.ndarray
    x: np.ndarray
    xc: np.ndarray
    ue: np.ndarray
    theta: np.ndarray
    dstar: np.ndarray
    H: np.ndarray
    Hk: np.ndarray
    cf: np.ndarray
    re_theta: np.ndarray
    msq: np.ndarray
    ampl: np.ndarray        # N for laminar stations, sqrt(Ctau) for turbulent
    turbulent: np.ndarray
    xtr_c: float            # transition location x/c (1.0 = laminar to TE)
    xi_tr: float
    forced: bool
    separated: list = field(default_factory=list)   # list of (x/c start, x/c end)

    @property
    def te(self):
        return {"theta": float(self.theta[-1]), "dstar": float(self.dstar[-1]),
                "H": float(self.H[-1]), "ue": float(self.ue[-1]), "msq": float(self.msq[-1])}

    def to_dict(self):
        d = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in self.__dict__.items()}
        d["turbulent"] = [bool(t) for t in self.turbulent]
        return d


# ---------------------------------------------------------------------------
# solver
# ---------------------------------------------------------------------------

class BoundaryLayerSolver:
    """Integral BL on both blade surfaces."""

    def __init__(self, env: BLEnvironment):
        self.env = env

    # ------------------------------------------------------------ helpers
    def _typ_kind(self, typ, surf=None):
        kind = np.where(typ[1:] == TURB, np.where(typ[:-1] == TURB, 2, 1), 0)
        if surf is not None and getattr(surf, "freeze_last", False) and kind.size > 2:
            kind = kind.copy()
            kind[-1] = 3
        return kind

    @staticmethod
    def _xi_eff(s, ue):
        """Stagnation-anchored arclength: shift xi so that ue ~ xi near the stagnation point.

        The viscous displacement moves the stagnation point slightly; the shift
        (lagged, recomputed every Newton iteration) keeps the similarity station
        consistent with the current edge velocity.
        """
        xi = s.xi
        u0, u1 = float(ue[0]), float(ue[1])
        if u1 > u0 > 0.0:
            x0 = u0 * (xi[1] - xi[0]) / (u1 - u0)
            x0 = min(max(x0, 0.05 * xi[0]), 4.0 * xi[0])
        else:
            x0 = xi[0]
        return xi + (x0 - xi[0])

    # ------------------------------------------------------------ march
    def march(self, surf: Surface, ue, init=None, allow_inverse=True):
        """Direct/inverse march along one surface for prescribed edge speed ``ue``.

        ``init`` optionally gives (theta, dstar) at the first station, which is
        then not treated as a similarity station (e.g. Blasius start for a flat
        plate).  Returns (A, theta, m, ue_bl, typ).
        """
        env = self.env
        n = surf.n
        xi = surf.xi
        ue = np.maximum(np.asarray(ue, float), 1e-8).copy()
        A = np.zeros(n)
        th = np.zeros(n)
        ds = np.zeros(n)
        typ = np.full(n, LAM)
        ue_bl = ue.copy()

        # --- first station
        if init is None:
            th0 = math.sqrt(0.075 * xi[0] / (ue[0] * env.re_len))
            x0 = np.array([th0, 2.2 * th0])

            def f0(V):
                npt = V.shape[1]
                u = np.full(npt, ue[0])
                st0 = station_vars(np.zeros(npt), V[0], V[1] * u, u, np.full(npt, LAM), env)
                return similarity_residuals(st0, np.full(npt, xi[0]))[:2]

            def lim0(x, dx):
                r = _limit(1.0, x[0], dx[0], 0.5, 1.0)
                return max(_limit(r, x[1], dx[1], 0.5, 1.0), 1e-3)

            sol, _ = _newton_bounded(f0, x0, lim0)
            th[0], ds[0] = sol
        else:
            th[0], ds[0] = init
        A[0] = 0.0

        for k in range(1, n):
            typ_k = typ[k - 1]
            if typ_k == LAM and k >= surf.itr_forced:
                typ_k = TURB
            s1 = station_vars(A[k - 1:k], th[k - 1:k], ds[k - 1:k] * ue_bl[k - 1:k],
                              ue_bl[k - 1:k], typ[k - 1:k], env)
            hk_prev = float(s1.hk[0])
            th_guess = th[k - 1] * math.sqrt(max(xi[k] / xi[k - 1], 1.0))
            xi12 = (xi[k - 1:k], xi[k:k + 1])
            for attempt in range(2):
                kind = 0 if (typ[k - 1] == LAM and typ_k == LAM) else (
                    1 if typ[k - 1] == LAM else 2)
                a0 = 0.03 if kind == 1 else A[k - 1]
                if kind == 1:
                    st = station_vars(np.array([0.03]), np.array([th_guess]),
                                      np.array([hk_prev * th_guess * ue_bl[k]]), ue_bl[k:k + 1],
                                      np.array([TURB]), env)
                    a0 = float(CTRCON * math.exp(-CTRCEX / max(hk_prev - 1.0, 0.05)) * st.cq[0])
                turb_k = typ_k == TURB

                def fdir(V, kind=kind, typ_k=typ_k):
                    npt = V.shape[1]
                    u2 = np.full(npt, ue_bl[k])
                    hh = h_from_hk(V[2], env.msq(u2))
                    s2 = station_vars(V[0], V[1], hh * V[1] * u2, u2, np.full(npt, typ_k), env)
                    return interval_residuals(s1, s2, *xi12, np.full(npt, kind), env)

                def lim_dir(x, dx, turb_k=turb_k):
                    r = 1.0
                    r = _limit(r, x[1], dx[1], 0.3, 0.5)
                    if dx[2] != 0.0:
                        r = min(r, 0.5 / abs(dx[2]))
                        if x[2] + r * dx[2] < 1.02:
                            r = min(r, 0.8 * (x[2] - 1.02) / max(-dx[2], 1e-300))
                    if turb_k:
                        r = _limit(r, x[0], dx[0], 0.5, 1.0)
                    elif dx[0] != 0.0:
                        r = min(r, 2.0 / abs(dx[0]))
                    return max(r, 1e-3)

                sol, ok = _newton_bounded(fdir, np.array([a0, th_guess, hk_prev]), lim_dir)
                hmax = HLMAX if typ_k == LAM else HTMAX
                if allow_inverse and (not ok or sol[2] > hmax):
                    dx = (xi[k] - xi[k - 1]) / th[k - 1]
                    htar = hk_prev + 0.03 * dx if typ_k == LAM else hk_prev - 0.15 * dx
                    htar = max(htar, hmax)

                    def finv(V, kind=kind, typ_k=typ_k, htar=htar):
                        npt = V.shape[1]
                        u2 = np.maximum(V[2], 1e-8)
                        hh = h_from_hk(htar, env.msq(u2))
                        s2 = station_vars(V[0], V[1], hh * V[1] * u2, u2,
                                          np.full(npt, typ_k), env)
                        return interval_residuals(s1, s2, *xi12, np.full(npt, kind), env)

                    def lim_inv(x, dx, turb_k=turb_k):
                        r = 1.0
                        r = _limit(r, x[1], dx[1], 0.3, 0.5)
                        r = _limit(r, x[2], dx[2], 0.1, 0.1)
                        if turb_k:
                            r = _limit(r, x[0], dx[0], 0.5, 1.0)
                        elif dx[0] != 0.0:
                            r = min(r, 2.0 / abs(dx[0]))
                        return max(r, 1e-3)

                    sv, ok = _newton_bounded(finv, np.array([a0, th_guess, ue_bl[k]]), lim_inv)
                    ue_bl[k] = sv[2]
                    sol = np.array([sv[0], sv[1], htar])
                if typ_k == LAM and sol[0] >= env.ncrit:
                    typ_k = TURB
                    continue
                break
            hh = float(h_from_hk(sol[2], env.msq(ue_bl[k])))
            A[k], th[k], ds[k] = sol[0], sol[1], hh * sol[1]
            typ[k] = typ_k
        return A, th, ds * ue_bl, ue_bl, typ

    # ------------------------------------------------------------ Newton
    def solve_coupled(self, surfaces, ue0, D, m_ref=None, F=None, X0=None, typs=None,
                      max_iter=40, tol=1e-6, verbose=False, fix_transition=False):
        """Simultaneous Newton solution of both surfaces with viscous-inviscid coupling.

        Parameters
        ----------
        surfaces : (upper, lower) :class:`Surface` objects covering all nodes.
        ue0      : baseline linear edge speed at the blade nodes.
        D        : dUe_lin/dm interaction matrix (nodes x nodes).
        m_ref    : mass defect at which ue0 was evaluated (default 0).
        F        : optional callable mapping linear speed -> edge speed,
                   returning (ue, due/dlin).
        X0       : initial (A, theta, m) per surface (list of arrays of shape (3, n)).
        typs     : initial station types per surface.
        """
        env = self.env
        Nn = ue0.size
        m_ref = np.zeros(Nn) if m_ref is None else np.asarray(m_ref, float)
        if F is None:
            def F(u):
                return u, np.ones_like(u)
        sizes = [s.n for s in surfaces]
        offs = np.cumsum([0] + sizes)
        nodes_all = np.concatenate([s.nodes for s in surfaces])
        if X0 is None or typs is None:
            ue_i, _ = F(ue0)
            X0, typs = [], []
            for s in surfaces:
                A, th, m, _, tp = self.march(s, ue_i[s.nodes])
                X0.append(np.array([A, th, m]))
                typs.append(tp)
        X = [x.copy() for x in X0]
        typs = [t.copy() for t in typs]
        hist = []
        converged = False
        ctx = (surfaces, ue0, D, m_ref, F, offs, nodes_all)
        visited = [[] for _ in surfaces]
        frozen = [bool(fix_transition) for _ in surfaces]
        ue_nodes = self._assemble(ctx, X, typs, jacobian=False)[2]
        for s in surfaces:
            s.xi_cur = self._xi_eff(s, ue_nodes[s.nodes])
        R, J, ue_nodes = self._assemble(ctx, X, typs, jacobian=True)
        rnorm = float(np.linalg.norm(R))
        for it in range(max_iter):
            try:
                dX = np.linalg.solve(J, -R)
            except np.linalg.LinAlgError:
                dX = np.linalg.lstsq(J, -R, rcond=None)[0]
            rlx = self._relaxation(surfaces, X, typs, dX, offs)
            # backtracking line search on the residual norm
            X_old = [x.copy() for x in X]
            for _ls in range(8):
                X = [x.copy() for x in X_old]
                self._apply_step(surfaces, X, dX, rlx, offs)
                R_new = self._assemble(ctx, X, typs, jacobian=False)[0]
                rn = float(np.linalg.norm(R_new))
                if np.isfinite(rn) and (rn < 1.2 * rnorm or rn < 1e-10):
                    break
                rlx *= 0.5
            rmax = 0.0
            for si, (s, x) in enumerate(zip(surfaces, X_old)):
                o = 3 * offs[si]
                n = s.n
                d = rlx * dX[o:o + 3 * n].reshape(n, 3).T
                rmax = max(rmax, float(np.max(np.abs(d[1] / x[1]))),
                           float(np.max(np.abs(d[2] / np.maximum(x[2], 1e-12)))))
            # transition update
            moved = False
            ue_nodes = self._assemble(ctx, X, typs, jacobian=False)[2]
            for si, s in enumerate(surfaces):
                if frozen[si]:
                    continue
                before = _itr(typs[si])
                trial_typ = typs[si].copy()
                trial_X = X[si].copy()
                if self._update_transition(s, trial_X, trial_typ, ue_nodes[s.nodes]):
                    after = _itr(trial_typ)
                    if after in visited[si]:
                        frozen[si] = True        # limit cycle: keep current location
                        continue
                    visited[si].append(before)
                    typs[si][:] = trial_typ
                    X[si][:] = trial_X
                    moved = True
            for s in surfaces:
                s.xi_cur = self._xi_eff(s, ue_nodes[s.nodes])
            R, J, ue_nodes = self._assemble(ctx, X, typs, jacobian=True)
            rnorm = float(np.linalg.norm(R))
            hist.append(rmax)
            if verbose:
                print(f"  BL Newton {it:2d}: max rel change {rmax:.3e} rlx {rlx:.3f} |R| {rnorm:.3e}")
                if verbose > 1:
                    Rs = np.abs(R).reshape(-1, 3)
                    for q in np.argsort(Rs.max(1))[::-1][:3]:
                        si = int(np.searchsorted(offs, q, side="right") - 1)
                        kq = q - offs[si]
                        xq = X[si][:, kq]
                        print(f"      {surfaces[si].name} st {kq}/{surfaces[si].n} res {Rs[q]} "
                              f"A {xq[0]:.3g} th {xq[1]:.3g} m {xq[2]:.3g} ue {ue_nodes[surfaces[si].nodes[kq]]:.4g} "
                              f"typ {typs[si][kq]} xi {surfaces[si].xi[kq]:.4g}")
                    dd = np.abs(dX).reshape(-1, 3) / np.maximum(np.abs(np.concatenate([x.T for x in X_old])), 1e-9)
                    q = int(np.argmax(dd.max(1)))
                    si = int(np.searchsorted(offs, q, side="right") - 1)
                    print(f"      largest step at {surfaces[si].name} st {q - offs[si]} rel {dd[q]}")
            if rmax < tol and not moved and rlx > 0.99:
                converged = True
                break
        m_nodes = np.zeros(Nn)
        for s, x in zip(surfaces, X):
            m_nodes[s.nodes] = x[2]
        ulin = ue0 + D @ (m_nodes - m_ref)
        ue_nodes, _ = F(ulin)
        return {"X": X, "typs": typs, "m": m_nodes, "ue": ue_nodes, "converged": converged,
                "history": hist, "iterations": len(hist), "residual": rnorm}

    def _assemble(self, ctx, X, typs, jacobian=True):
        surfaces, ue0, D, m_ref, F, offs, nodes_all = ctx
        Nn = ue0.size
        m_nodes = np.zeros(Nn)
        for s, x in zip(surfaces, X):
            m_nodes[s.nodes] = x[2]
        ulin = ue0 + D @ (m_nodes - m_ref)
        ue_nodes, dF = F(ulin)
        ue_nodes = np.maximum(ue_nodes, 1e-6)
        ntot = offs[-1]
        R = np.zeros(3 * ntot)
        if not jacobian:
            for si, (s, x, tp) in enumerate(zip(surfaces, X, typs)):
                o = 3 * offs[si]
                R[o:o + 3 * s.n] = self._residual(s, x, ue_nodes[s.nodes], tp)
            return R, None, ue_nodes
        J = np.zeros((3 * ntot, 3 * ntot))
        Jue = np.zeros((3 * ntot, Nn))
        for si, (s, x, tp) in enumerate(zip(surfaces, X, typs)):
            r, jd, ju = self._residual_jacobian(s, x, ue_nodes[s.nodes], tp)
            o = 3 * offs[si]
            n = s.n
            R[o:o + 3 * n] = r
            J[o:o + 3 * n, o:o + 3 * n] = jd
            Jue[o:o + 3 * n, s.nodes] = ju
        dUdm = dF[:, None] * D
        m_cols = 3 * np.arange(ntot) + 2
        J[:, m_cols] += Jue @ dUdm[:, nodes_all]
        return R, J, ue_nodes

    def _relaxation(self, surfaces, X, typs, dX, offs):
        rlx = 1.0
        for si, (s, x, tp) in enumerate(zip(surfaces, X, typs)):
            o = 3 * offs[si]
            n = s.n
            d = dX[o:o + 3 * n].reshape(n, 3).T
            for var in (1, 2):
                rel = d[var] / np.maximum(x[var], 1e-12)
                lo, hi = rel.min(), rel.max()
                if hi * rlx > 1.5:
                    rlx = 1.5 / hi
                if lo * rlx < -0.5:
                    rlx = -0.5 / lo
            turb = tp == TURB
            if np.any(turb):
                rel = d[0][turb] / np.maximum(x[0][turb], 1e-6)
                hi, lo = rel.max(), rel.min()
                if hi * rlx > 1.5:
                    rlx = 1.5 / hi
                if lo * rlx < -0.5:
                    rlx = -0.5 / lo
            lam = ~turb
            if np.any(lam):
                dn = np.abs(d[0][lam]).max()
                if dn * rlx > 2.0:
                    rlx = 2.0 / dn
        return rlx

    def _apply_step(self, surfaces, X, dX, rlx, offs):
        for si, (s, x) in enumerate(zip(surfaces, X)):
            o = 3 * offs[si]
            n = s.n
            x += rlx * dX[o:o + 3 * n].reshape(n, 3).T
            x[1] = np.maximum(x[1], 1e-9)
            x[2] = np.maximum(x[2], 1e-12)

    def _residual(self, s: Surface, x, ue, typ):
        env = self.env
        n = s.n
        A, th, m = x
        kind = self._typ_kind(typ, s)
        st = station_vars(A, th, m, ue, typ, env)
        xi = getattr(s, "xi_cur", s.xi)

        def sub(sl):
            return Station({k: val[sl] for k, val in st.items()})

        r_int = interval_residuals(sub(slice(0, n - 1)), sub(slice(1, n)), xi[:-1], xi[1:],
                                   kind, env)
        r_sim = similarity_residuals(sub(slice(0, 1)), xi[:1])
        R = np.zeros((n, 3))
        R[0] = r_sim[:, 0]
        R[1:] = r_int.T
        return R.ravel()

    def _residual_jacobian(self, s: Surface, x, ue, typ):
        """Residuals (3n) and Jacobians w.r.t. (A, theta, m) (3n x 3n) and ue (3n x n)."""
        env = self.env
        n = s.n
        A, th, m = x
        kind = self._typ_kind(typ, s)
        xi = getattr(s, "xi_cur", s.xi)

        def stations(A_, th_, m_, ue_):
            return station_vars(A_, th_, m_, ue_, typ, env)

        base = stations(A, th, m, ue)
        vars0 = [A, th, m, ue]
        eps = [np.where(typ == TURB, 1e-5 * np.maximum(A, 1e-3), 1e-5),
               1e-6 * th, 1e-6 * m, 1e-7 * ue]
        pert = []
        for vi in range(4):
            v = [a.copy() for a in vars0]
            v[vi] = v[vi] + eps[vi]
            pert.append(stations(*v))

        def sub(st, sl):
            return Station({k: val[sl] for k, val in st.items()})

        a_, b_ = slice(0, n - 1), slice(1, n)
        r_int = interval_residuals(sub(base, a_), sub(base, b_), xi[:-1], xi[1:], kind, env)
        r_sim = similarity_residuals(sub(base, slice(0, 1)), xi[:1])
        R = np.zeros((n, 3))
        R[0] = r_sim[:, 0]
        R[1:] = r_int.T
        # derivatives
        d1 = np.zeros((n - 1, 3, 4))
        d2 = np.zeros((n - 1, 3, 4))
        dsim = np.zeros((3, 4))
        for vi in range(4):
            p = pert[vi]
            r1 = interval_residuals(sub(p, a_), sub(base, b_), xi[:-1], xi[1:], kind, env)
            r2 = interval_residuals(sub(base, a_), sub(p, b_), xi[:-1], xi[1:], kind, env)
            d1[:, :, vi] = ((r1 - r_int) / eps[vi][:-1]).T
            d2[:, :, vi] = ((r2 - r_int) / eps[vi][1:]).T
            rs = similarity_residuals(sub(p, slice(0, 1)), xi[:1])
            dsim[:, vi] = (rs[:, 0] - r_sim[:, 0]) / eps[vi][0]
        J = np.zeros((3 * n, 3 * n))
        Ju = np.zeros((3 * n, n))
        J[0:3, 0:3] = dsim[:, :3]
        Ju[0:3, 0] = dsim[:, 3]
        for k in range(1, n):
            r0 = 3 * k
            J[r0:r0 + 3, 3 * (k - 1):3 * k] = d1[k - 1][:, :3]
            J[r0:r0 + 3, 3 * k:3 * k + 3] = d2[k - 1][:, :3]
            Ju[r0:r0 + 3, k - 1] = d1[k - 1][:, 3]
            Ju[r0:r0 + 3, k] = d2[k - 1][:, 3]
        return R.ravel(), J, Ju

    def _update_transition(self, s: Surface, x, typ, ue):
        """Move the transition station by at most one station. Returns True if moved."""
        env = self.env
        n = s.n
        turb = np.where(typ == TURB)[0]
        itr = int(turb[0]) if turb.size else n
        A, th, m = x
        lam_idx = np.arange(1, min(itr, n))
        over = lam_idx[A[lam_idx] >= env.ncrit]
        new = itr
        if over.size:
            new = int(over[0])
        elif itr < n and itr < s.itr_forced:
            st = station_vars(A[itr - 1:itr], th[itr - 1:itr], m[itr - 1:itr], ue[itr - 1:itr],
                              np.array([LAM]), env)
            npred = A[itr - 1] + st.ax[0] * (s.xi[itr] - s.xi[itr - 1])
            if npred < env.ncrit:
                new = itr + 1
        new = min(new, s.itr_forced)
        if new == itr:
            return False
        if new < itr:
            typ[new:] = TURB
            st = station_vars(np.full(1, 0.03), th[new:new + 1], m[new:new + 1],
                              ue[new:new + 1], np.array([TURB]), env)
            ctr = CTRCON * math.exp(-CTRCEX / max(st.hk[0] - 1.0, 0.05))
            A[new:itr] = ctr * st.cq[0]
        else:
            k = itr
            st = station_vars(A[k - 1:k], th[k - 1:k], m[k - 1:k], ue[k - 1:k],
                              np.array([LAM]), env)
            typ[k] = LAM
            A[k] = A[k - 1] + st.ax[0] * (s.xi[k] - s.xi[k - 1])
        return True

    # ------------------------------------------------------------ output
    def package(self, s: Surface, x, ue, typ) -> SurfaceBL:
        env = self.env
        A, th, m = x
        st = station_vars(A, th, m, ue, typ, env)
        turb = typ == TURB
        idx = np.where(turb)[0]
        forced = False
        if idx.size:
            k = int(idx[0])
            if k >= s.itr_forced:
                forced = True
                xi_tr = s.xi[k]
            else:
                s1 = station_vars(A[k - 1:k], th[k - 1:k], m[k - 1:k], ue[k - 1:k],
                                  np.array([LAM]), env)
                npred = A[k - 1] + s1.ax[0] * (s.xi[k] - s.xi[k - 1])
                f = (env.ncrit - A[k - 1]) / max(npred - A[k - 1], 1e-12)
                f = min(max(f, 0.0), 1.0)
                xi_tr = s.xi[k - 1] + f * (s.xi[k] - s.xi[k - 1])
            xtr_c = float(np.interp(xi_tr, s.xi, s.xc))
        else:
            xi_tr = float(s.xi[-1])
            xtr_c = float(s.xc[-1])
        sep = []
        neg = st.cf < 0
        i = 0
        while i < s.n:
            if neg[i]:
                j = i
                while j + 1 < s.n and neg[j + 1]:
                    j += 1
                sep.append((float(s.xc[i]), float(s.xc[j])))
                i = j + 1
            else:
                i += 1
        return SurfaceBL(s.name, s.xi.copy(), s.x.copy(), s.xc.copy(), st.ue.copy(), th.copy(),
                         st.ds.copy(), st.h.copy(), st.hk.copy(), st.cf.copy(), st.rt.copy(),
                         st.msq.copy(), A.copy(), turb.copy(), xtr_c, float(xi_tr), forced, sep)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _limit(r, x, dx, frac_down, frac_up):
    """Limit a relative update of a positive variable."""
    if dx == 0.0 or x <= 0.0:
        return r
    rel = dx / x
    if rel * r < -frac_down:
        r = frac_down / -rel
    if rel * r > frac_up:
        r = frac_up / rel
    return r


def _newton_bounded(f, x0, limiter, tol=1e-9, max_iter=40):
    """Newton iteration with a finite-difference Jacobian and a step limiter.

    ``f`` maps an (n, k) array of k trial points to an (m, k) residual array,
    so the base point and all n perturbations are evaluated in one call.
    Returns (x, converged).
    """
    x = np.asarray(x0, float).copy()
    n = x.size
    for _ in range(max_iter):
        h = 1e-7 * np.maximum(np.abs(x), 1e-6)
        V = np.repeat(x[:, None], n + 1, axis=1)
        V[np.arange(n), np.arange(1, n + 1)] += h
        Rm = f(V)
        r = Rm[:, 0]
        if not np.all(np.isfinite(Rm)):
            return x, False
        J = (Rm[:, 1:] - r[:, None]) / h[None, :]
        try:
            dx = np.linalg.solve(J, -r)
        except np.linalg.LinAlgError:
            return x, False
        if not np.all(np.isfinite(dx)):
            return x, False
        rl = limiter(x, dx)
        x = x + rl * dx
        scale = np.maximum(np.abs(x), 1e-6)
        if rl >= 0.999 and np.all(np.abs(dx) <= tol * scale):
            return x, True
    r = f(x[:, None])[:, 0]
    return x, bool(np.all(np.abs(r) < 1e-6))


def _itr(typ):
    """Index of the first turbulent station (n if laminar throughout)."""
    t = np.where(typ == TURB)[0]
    return int(t[0]) if t.size else int(typ.size)
