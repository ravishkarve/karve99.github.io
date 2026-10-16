"""Fast integral boundary layer for blade sections, vectorised over many surfaces.

Each surface is marched from the leading-edge stagnation point to the trailing edge on a
common chordwise grid, with the edge speed ``ue`` (in units of the vector-mean speed) given
by the inviscid row solution of :mod:`hsprop.cascade`.

* Laminar: Thwaites' method,  theta^2 ue^6 = 0.45/Re int ue^5 dx,  with the Cebeci-Bradshaw
  fits for H(lambda) and the laminar-separation limit lambda = -0.09.
* Transition: Michel's criterion  Re_theta = 1.174 (1 + 22400/Re_x) Re_x^0.46, laminar
  separation (short bubble), or a forced location, whichever comes first.
* Turbulent: Head's entrainment method with the Ludwieg-Tillmann skin friction,
      d theta/dx = Cf/2 - (H + 2 - Me^2) theta ue'/ue
      d(ue theta H1)/dx = ue 0.0306 (H1 - 3)^-0.6169,
  the compressible momentum equation with an Eckert reference-temperature factor on Cf.
  The shape factor is bounded by H_MAX so that the march continues through separated
  regions; a leading-edge bubble (separation followed by reattachment) therefore thickens
  the layer without ending it, and the separation point reported is the start of the
  separated region that reaches the trailing edge (turbulent trailing-edge stall).
* Drag: Squire-Young, cd = 2 theta_TE ue_TE^((H_TE + 5)/2), summed over both surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

H_SEP = 2.6           # turbulent separation shape factor
H_MAX = 4.0           # bound on the shape factor inside separated regions
H_START = 1.4         # turbulent shape factor just after transition
LAMBDA_SEP = -0.09    # Thwaites laminar separation


@dataclass
class BLResult:
    theta_te: np.ndarray     # (C,) momentum thickness / chord at the trailing edge
    H_te: np.ndarray         # (C,) shape factor at the trailing edge
    dstar_te: np.ndarray     # (C,) displacement thickness / chord
    ue_te: np.ndarray        # (C,) edge speed at the trailing edge
    x_tr: np.ndarray         # (C,) transition location
    x_sep: np.ndarray        # (C,) turbulent separation location (1 = attached)
    cd: np.ndarray           # (C,) Squire-Young drag contribution of the surface
    cf_mean: np.ndarray      # (C,) chord-averaged skin friction (friction-drag share)


def _H1_of_H(H):
    H = np.asarray(H, dtype=float)
    lo = 3.3 + 0.8234 * np.maximum(H - 1.1, 1e-6) ** -1.287
    hi = 3.3 + 1.5501 * np.maximum(H - 0.6778, 1e-6) ** -3.064
    return np.where(H <= 1.6, lo, hi)


_H1_AT_16 = float(_H1_of_H(1.6))


def _H_of_H1(H1):
    H1 = np.maximum(np.asarray(H1, dtype=float), 3.3 + 1e-6)
    lo = 1.1 + ((H1 - 3.3) / 0.8234) ** (-1.0 / 1.287)        # H <= 1.6  <->  H1 >= H1(1.6)
    hi = 0.6778 + ((H1 - 3.3) / 1.5501) ** (-1.0 / 3.064)
    return np.where(H1 >= _H1_AT_16, lo, hi)


def _entrainment(H1):
    return 0.0306 * np.maximum(H1 - 3.0, 1e-3) ** -0.6169


def _cf_turb(H, re_theta, mach):
    cf = 0.246 * 10.0 ** (-0.678 * H) * np.maximum(re_theta, 50.0) ** -0.268
    return cf * (1.0 + 0.1352 * mach ** 2) ** -0.66


def _thwaites_H(lam):
    lam = np.asarray(lam, dtype=float)
    pos = 2.61 - 3.75 * lam + 5.24 * lam ** 2
    neg = 2.088 + 0.0731 / np.maximum(lam + 0.14, 1e-3)
    return np.where(lam >= 0.0, np.minimum(pos, 2.61), neg)


def _thwaites_l(lam):
    lam = np.asarray(lam, dtype=float)
    pos = 0.22 + 1.57 * lam - 1.8 * lam ** 2
    neg = 0.22 + 1.402 * lam + 0.018 * lam / np.maximum(lam + 0.107, 1e-3)
    return np.maximum(np.where(lam >= 0.0, pos, neg), 0.0)


def march(x, ue, reynolds, mach, xtr_forced=None, h_sep=H_SEP):
    """March C surfaces on the common grid ``x`` (E,), edge speeds ``ue`` (C, E).

    ``reynolds`` (C,) is the chord Reynolds number on the reference speed, ``mach`` (C, E) or
    (C,) the local edge Mach number, ``xtr_forced`` (C,) a forced transition location.
    """
    x = np.asarray(x, dtype=float)
    ue = np.maximum(np.asarray(ue, dtype=float), 1e-6)
    C, E = ue.shape
    Re = np.broadcast_to(np.asarray(reynolds, dtype=float), (C,))
    Me = np.broadcast_to(np.asarray(mach, dtype=float), (C, E)) if np.ndim(mach) == 2 else \
        np.broadcast_to(np.asarray(mach, dtype=float)[:, None], (C, E))
    xtr_f = np.ones(C) if xtr_forced is None else np.broadcast_to(np.asarray(xtr_forced, float), (C,))
    dx = np.diff(x)
    dudx = np.gradient(ue, x, axis=1)

    # ---------------- laminar (Thwaites), whole surface
    # int ue^5 dx with ue linear on each interval (exact at a stagnation point, ue ~ k x)
    ua, ub = ue[:, :-1], ue[:, 1:]
    dU = ub - ua
    near = np.abs(dU) < 1e-6 * np.maximum(ub, 1e-12)
    seg = np.where(near, 0.5 * (ua ** 5 + ub ** 5),
                   (ub ** 6 - ua ** 6) / (6.0 * np.where(near, 1.0, dU))) * dx
    integ = np.concatenate([np.zeros((C, 1)), np.cumsum(seg, axis=1)], axis=1)
    theta_l2 = 0.45 / Re[:, None] * integ / ue ** 6
    theta_l2[:, 0] = 0.075 / (Re * np.maximum(dudx[:, 0], 1e-3))
    theta_l = np.sqrt(np.maximum(theta_l2, 0.0))
    lam = Re[:, None] * theta_l2 * dudx
    re_x = Re[:, None] * ue * x[None, :]
    re_th = Re[:, None] * ue * theta_l
    michel = 1.174 * (1.0 + 22400.0 / np.maximum(re_x, 1.0)) * np.maximum(re_x, 1.0) ** 0.46
    # transition: the first zero of each criterion is located between grid nodes so that
    # the transition point, and everything downstream of it, moves smoothly.  Natural
    # (Michel) and forced transition give x_n; a laminar separation bubble gives x_b.  A
    # bubble appears abruptly as the pressure gradient grows, which would make x_tr jump
    # from x_n to the nose; the bubble is therefore phased in over a small range of the
    # minimum Thwaites parameter (an intermittency), keeping the solution differentiable.
    def first_zero(m):
        m = m.copy()
        m[:, 0] = np.minimum(m[:, 0], -1e-12)
        hit = m >= 0.0
        any_hit = hit.any(axis=1)
        i = np.argmax(hit, axis=1)
        i = np.where(any_hit, i, E - 1)
        rr = np.arange(C)
        m0, m1 = m[rr, np.maximum(i - 1, 0)], m[rr, i]
        fr = np.clip(-m0 / np.where(m1 - m0 > 1e-15, m1 - m0, 1.0), 0.0, 1.0)
        x0n = x[np.maximum(i - 1, 0)]
        return np.where(any_hit, x0n + fr * (x[i] - x0n), 1.0)

    m_nat = np.maximum(re_th / michel - 1.0, (x[None, :] - xtr_f[:, None]) / 0.01)
    # bubble transition: the laminar layer separates (lambda -> LAMBDA_SEP) and the bubble
    # trips it.  The bubble point is where lambda first falls below lam_on, and its weight
    # rises from zero as min(lambda) falls through lam_on, so x_tr stays continuous when a
    # suction peak first produces a bubble.
    lam_on = LAMBDA_SEP + 0.01
    m_bub = (lam_on - lam) / 0.09
    x_nat = first_zero(m_nat)
    x_bub = first_zero(m_bub)
    lam_min = lam[:, 1:].min(axis=1)
    zb = np.clip((lam_on - lam_min) / 0.02, 0.0, 1.0)
    w_bub = zb * zb * (3.0 - 2.0 * zb)
    x_tr = (1.0 - w_bub) * x_nat + w_bub * np.minimum(x_nat, x_bub)
    laminar_to_te = x_tr >= 1.0 - 1e-9
    i_tr = np.clip(np.searchsorted(x, x_tr, side="right"), 1, E - 1)    # first node after x_tr
    rows = np.arange(C)
    xa_, xb_ = x[i_tr - 1], x[i_tr]
    frac = np.clip((x_tr - xa_) / (xb_ - xa_), 0.0, 1.0)
    th_tr = theta_l[rows, i_tr - 1] * (1.0 - frac) + theta_l[rows, i_tr] * frac

    # laminar skin friction (Thwaites l(lambda)) for the friction integral
    cf_lam = 2.0 * _thwaites_l(lam) / np.maximum(re_th, 1e-6)

    # ---------------- turbulent (Head), marched from x_tr
    theta = np.where(laminar_to_te, theta_l[:, -1], th_tr)
    H = np.where(laminar_to_te, _thwaites_H(lam[:, -1]), H_START)
    H1 = _H1_of_H(H)
    h1_min = float(_H1_of_H(H_MAX))
    sep = np.zeros(C, dtype=bool)
    x_sep = np.ones(C)
    cf_int = np.zeros(C)
    lam_mask = np.arange(E)[None, :] < i_tr[:, None]
    cf_l = np.where(lam_mask, cf_lam * ue ** 2, 0.0)
    cf_int += np.sum(0.5 * (cf_l[:, 1:] + cf_l[:, :-1]) * dx, axis=1)
    lam_sep = laminar_to_te & (lam[:, -1] < LAMBDA_SEP)

    def rhs(th, h1, i):
        h = _H_of_H1(h1)
        uu = ue[:, i]
        g = dudx[:, i] / uu
        cf = _cf_turb(h, Re * uu * th, Me[:, i])
        dth = 0.5 * cf - (h + 2.0 - Me[:, i] ** 2) * th * g
        dh1 = _entrainment(h1) / th - h1 * (g + dth / th)
        return dth, dh1, cf

    H_prev = _H_of_H1(H1)
    for i in range(1, E):
        active = (~laminar_to_te) & (i >= i_tr)
        if not active.any():
            continue
        # the interval containing the transition point is only partly turbulent
        h = np.where(i == i_tr, x[i] - x_tr, dx[i - 1])
        k1t, k1h, cf1 = rhs(theta, H1, i - 1)
        th_p = np.maximum(theta + h * k1t, 1e-8)
        h1_p = np.maximum(H1 + h * k1h, h1_min)
        k2t, k2h, cf2 = rhs(th_p, h1_p, i)
        th_n = np.maximum(theta + 0.5 * h * (k1t + k2t), 1e-8)
        h1_n = np.maximum(H1 + 0.5 * h * (k1h + k2h), h1_min)
        theta = np.where(active, th_n, theta)
        H1 = np.where(active, h1_n, H1)
        Hn = _H_of_H1(H1)
        now_sep = Hn >= h_sep
        # separation point interpolated between nodes
        fs = np.clip((h_sep - H_prev) / np.where(Hn - H_prev > 1e-9, Hn - H_prev, 1.0), 0.0, 1.0)
        xs_i = x[i - 1] + fs * dx[i - 1]
        x_sep = np.where(active & now_sep & ~sep, xs_i, x_sep)         # start of a separated run
        x_sep = np.where(active & ~now_sep, 1.0, x_sep)                # reattached: forget it
        sep = np.where(active, now_sep, sep)
        H_prev = np.where(active, Hn, H_prev)
        cf_int += np.where(active, 0.5 * h * (cf1 * ue[:, i - 1] ** 2 + cf2 * ue[:, i] ** 2), 0.0)
    x_sep = np.where(lam_sep, x[np.argmax(lam < LAMBDA_SEP, axis=1)], x_sep)

    H_te = np.minimum(_H_of_H1(H1), H_MAX)
    # a layer that has only just become turbulent keeps its laminar shape factor: blend over
    # a short development length so that the trailing-edge state is continuous in x_tr
    w_turb = 1.0 - np.exp(-(1.0 - x_tr) / 0.03)
    H_te = w_turb * H_te + (1.0 - w_turb) * np.minimum(_thwaites_H(lam[:, -1]), H_MAX)
    u_te = ue[:, -1]
    cd = 2.0 * theta * u_te ** (0.5 * (H_te + 5.0))
    return BLResult(theta_te=theta, H_te=H_te, dstar_te=theta * H_te, ue_te=u_te, x_tr=x_tr,
                    x_sep=x_sep, cd=cd, cf_mean=cf_int)
