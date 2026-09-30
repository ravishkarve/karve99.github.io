r"""Rotor trailing-edge (self) noise exactly as formulated in Blandeau's thesis.

V. P. Blandeau, "Aerodynamic broadband noise from contra-rotating open rotors",
PhD thesis, ISVR, University of Southampton (2011):

* eq. 3.18, the exact (FW-H based) model for Broadband Rotor Trailing-Edge noise:

      S_pp(r0, theta, w) = B/(2 pi) (k0 b / r0)^2 dr  sum_l  D_l(theta, alpha, w)
                           |L_TE(0, K_Xl, kappa_l)|^2  S_qq(0, K_Xl)

      D_l      = 1/dr int_strip ( l/(k0 r) cos(alpha) + cos(theta) sin(alpha) )^2 J_l^2(k0 r sin(theta)) dr   (3.15)
      kappa_l  = l/r sin(alpha) - k0 cos(alpha) cos(theta)                                                     (3.17)
      K_Xl     = w_l / Uc,  w_l = w + l Omega                                                                  (3.8)

* eq. 5.7, Amiet's approximate model in the thesis' notation (medium at rest):

      S_pp = B/(2 pi) (k0 b / r0)^2 dr/(2 pi) int_0^2pi D_phi |L_TE(0, K_Xphi, kappa_phi)|^2 S_qq(0, K_Xphi) dphi
      w_phi/w  = 1 + M_phi cos(phi) sin(theta)                                                                (5.1)
      K_Xphi   = w_phi / Uc,  kappa_phi = k0 (sin(theta) sin(alpha) cos(phi) - cos(theta) cos(alpha))          (5.8)
      D_phi    = (cos(theta) sin(alpha) + sin(theta) cos(alpha) cos(phi))^2                                   (5.9)

Common ingredients:

* L_TE (eq. 3.19-3.20, Roger & Moreau, no leading-edge back-scattering), with
  1/Theta_b replaced by 1/(b|k_X| + b|kappa|) for negative wavenumbers:

      L_TE = e^{2i Tb}/(i Tb) { e^{-2i Tb} sqrt(Ta/(Ta - Tb)) erf(sqrt(2i (Ta - Tb))) - erf(sqrt(2i Ta)) + 1 }
      Ta = b (k_X + mu_inf + mu M_X),  Tb = b (k_X + kappa),  mu = k_X M_c / beta_X^2,  mu_inf = |mu| (k_r = 0)

* S_qq(0, k_X) = (1/pi) l_r(k_X Uc, 0) Phi_pp(k_X Uc)     (3.12)
  l_r(w, 0) = l_2(w)/pi,  l_2 = zeta_2 Uc / w,  zeta_2 = 1.6  (Brooks & Hodgson)     (3.13)
* Phi_pp double-sided, summed over the two sides of the blade; Uc = 0.8 U_X.
* alpha is the stagger angle measured from the rotor axis (alpha = 90 deg - inflow
  angle from the rotor plane) and theta is measured from the *downstream* axis
  (the thesis' convention, Fig. 4.8).  Both formulations assume a medium at rest.

The PSDs returned here are double-sided per rad/s (the thesis' convention);
``spectral_factor`` = 4 pi converts them to one-sided per hertz.
"""
from __future__ import annotations

import numpy as np
from scipy.special import erf, jv

from .wallpressure import wps

__all__ = ["l_te", "s_qq", "eq318_spectrum", "eq57_spectrum", "eq273_spectrum", "wake_fm2", "SPECTRAL_FACTOR", "ZETA2", "UC_OVER_UX"]

ZETA2 = 1.6
UC_OVER_UX = 0.8
SPECTRAL_FACTOR = 4.0 * np.pi       # double-sided per rad/s -> one-sided per Hz


def l_te(kX, kappa, b, MX, Mc):
    """Chordwise aeroacoustic coupling integral L_TE(0, k_X, kappa), thesis eq. 3.19-3.20."""
    kX = np.asarray(kX, float)
    kappa = np.asarray(kappa, float)
    beta2 = 1.0 - MX * MX
    mu = kX * Mc / beta2
    mu_inf = np.abs(mu)
    Ta = (b * (kX + mu_inf + mu * MX)).astype(complex)
    Tb = (b * (kX + kappa)).astype(complex)
    dTab = Ta - Tb
    dTab = np.where(np.abs(dTab) < 1e-12, 1e-12, dTab)
    denom = b * np.abs(kX) + b * np.abs(kappa)          # thesis: 1/Theta_b -> 1/(b|kX| + b|kappa|)
    denom = np.where(denom < 1e-12, 1e-12, denom)
    brace = (np.exp(-2j * Tb) * np.sqrt(Ta / dTab) * erf(np.sqrt(2j * dTab))
             - erf(np.sqrt(2j * Ta)) + 1.0)
    return np.exp(2j * Tb) / (1j * denom) * brace


def s_qq(kX, Uc, bls, model, zeta2=ZETA2):
    """Wavenumber cross-spectrum S_qq(0, k_X) (eq. 3.12-3.13), both sides summed, double-sided Phi_pp."""
    w = np.abs(np.asarray(kX, float)) * Uc
    w = np.where(w < 1e-9, 1e-9, w)
    phi2 = sum(wps(model, w, bl) for bl in bls) / 2.0     # one-sided -> double-sided
    l2 = zeta2 * Uc / w
    return (1.0 / np.pi) * (l2 / np.pi) * phi2


def _strip_quantities(strip, c0):
    b = 0.5 * strip.chord
    alpha = 0.5 * np.pi - strip.psi          # stagger from the rotor axis
    UX = strip.U
    Uc = UC_OVER_UX * UX
    return b, alpha, UX, Uc, UX / c0, Uc / c0


def eq318_spectrum(rotor, bl_for_strip, model, omega, r0, theta_down_deg, n_gauss=4, extra_modes=None,
                   per_strip=False, doppler_sign=1.0):
    """Thesis eq. 3.18: exact rotor trailing-edge noise PSD (double-sided, per rad/s).

    ``bl_for_strip(strip)`` returns {'suction': BoundaryLayer, 'pressure': BoundaryLayer};
    ``theta_down_deg`` is the observer polar angle from the downstream axis.
    """
    omega = np.atleast_1d(np.asarray(omega, float))
    th = np.radians(theta_down_deg)
    c0 = rotor.c0
    xg, wg = np.polynomial.legendre.leggauss(n_gauss)
    total = np.zeros_like(omega)
    parts = []
    for st in rotor.strips():
        b, alpha, UX, Uc, MX, Mc = _strip_quantities(st, c0)
        bls = list(bl_for_strip(st).values())
        rq = st.r + 0.5 * st.dr * xg                 # Gauss points across the strip
        # all (frequency, mode) pairs of the strip at once
        idx, ls = [], []
        for i, w in enumerate(omega):
            arg_max = w / c0 * rq.max() * np.sin(th)
            N = int(np.ceil(arg_max)) + (extra_modes if extra_modes is not None else int(12 + 4 * arg_max ** (1 / 3)))
            ls.append(np.arange(-N, N + 1, dtype=float))
            idx.append(np.full(2 * N + 1, i))
        l = np.concatenate(ls)
        i_f = np.concatenate(idx)
        w = omega[i_f]
        k0 = w / c0
        # D_l: strip average of (l/(k0 r) cos a + cos th sin a)^2 J_l^2(k0 r sin th)      (3.15)
        D = np.zeros_like(l)
        for xq, wq in zip(rq, wg):
            D += 0.5 * wq * (l / (k0 * xq) * np.cos(alpha) + np.cos(th) * np.sin(alpha)) ** 2 \
                * jv(l, k0 * xq * np.sin(th)) ** 2
        keep = D > 1e-16 * max(D.max(), 1e-300)
        terms = np.zeros_like(l)
        if np.any(keep):
            lk, k0k, wk = l[keep], k0[keep], w[keep]
            kappa = lk / st.r * np.sin(alpha) - k0k * np.cos(alpha) * np.cos(th)          # (3.17)
            KX = (wk + doppler_sign * lk * rotor.Omega) / Uc                             # (3.8)
            terms[keep] = D[keep] * np.abs(l_te(KX, kappa, b, MX, Mc)) ** 2 * s_qq(KX, Uc, bls, model)
        S = np.bincount(i_f, weights=terms, minlength=omega.size)
        S *= rotor.B / (2 * np.pi) * (omega / c0 * b / r0) ** 2 * st.dr
        total += S
        parts.append(S)
    return (total, parts) if per_strip else total


def eq57_spectrum(rotor, bl_for_strip, model, omega, r0, theta_down_deg, n_phi=180, per_strip=False,
                  doppler_sign=1.0):
    """Thesis eq. 5.7: Amiet's approximate rotor trailing-edge noise PSD (double-sided, per rad/s)."""
    omega = np.atleast_1d(np.asarray(omega, float))
    th = np.radians(theta_down_deg)
    c0 = rotor.c0
    phi = (np.arange(n_phi) + 0.5) * 2 * np.pi / n_phi
    total = np.zeros_like(omega)
    parts = []
    for st in rotor.strips():
        b, alpha, UX, Uc, MX, Mc = _strip_quantities(st, c0)
        bls = list(bl_for_strip(st).values())
        Mphi = st.r * rotor.Omega / c0
        k0 = omega[:, None] / c0
        wphi = omega[:, None] * (1 + doppler_sign * Mphi * np.cos(phi)[None, :] * np.sin(th))   # (5.1)
        KX = wphi / Uc
        kappa = k0 * (np.sin(th) * np.sin(alpha) * np.cos(phi)[None, :] - np.cos(th) * np.cos(alpha))   # (5.8)
        D = (np.cos(th) * np.sin(alpha) + np.sin(th) * np.cos(alpha) * np.cos(phi)) ** 2    # (5.9)
        L2 = np.abs(l_te(KX, kappa, b, MX, Mc)) ** 2
        Sq = s_qq(KX, Uc, bls, model)
        S = rotor.B / (2 * np.pi) * (omega / c0 * b / r0) ** 2 * st.dr * np.mean(D[None, :] * L2 * Sq, axis=1)
        total += S
        parts.append(S)
    return (total, parts) if per_strip else total


# ---------------------------------------------------------------------------
# Rotor-wake/rotor interaction (BRWI): thesis eq. 2.73 (simplified model)
# ---------------------------------------------------------------------------

WAKE_A = 0.637          # Gaussian wake-profile constant a (Wygnanski et al.), thesis eq. 2.12


def wake_fm2(m, r, B1, bW, a=WAKE_A):
    """|f_m(r)|^2 of the Gaussian wake train, thesis eq. 2.15 (sigma = r sqrt(2a)/(B1 bW))."""
    sigma = r * np.sqrt(2.0 * a) / (B1 * bW)
    return (np.exp(-0.5 * (m / sigma) ** 2) / (B1 * sigma * np.sqrt(2.0 * np.pi))) ** 2, sigma


def eq273_spectrum(rear, wake, B1, Omega1, omega, r0, theta_deg, n_gauss=4, per_strip=False,
                   doppler_sign=1.0, spectrum="vonkarman"):
    """Thesis eq. 2.73: simplified BRWI PSD of the rear rotor (double-sided, per rad/s).

        S_pp = B2/4 (B1 rho0 k0 b2 / r0)^2 U_X2 dr  sum_m sum_h  D'_ml Phi_ww(0, K_X,mh) |L_LE(0, K_X,mh, kappa_mh)|^2

    with l = m B1 - h, w_mh = m B1 Omega1 + h Omega2, K_X,mh = (w + w_mh)/U_X2,
    kappa_mh = k0 cos(a2) cos(theta) + m B1 (Omega1 + Omega2)/U_X2 - (h/r) sin(a2)  (eq. 2.50 with n B2 + q = h),
    D'_ml = strip average of f_m^2 (l/(k0 r) cos a2 + cos theta sin a2)^2 J_l^2(k0 r sin theta)  (eq. 2.74).

    ``wake(r)`` returns (w_rms [m/s], L [m], b_W [m]) at the rear-rotor radius r (w_rms is the
    wake-centreline value, eq. 2.11).  theta is measured from the downstream axis and the medium
    is at rest, as in the thesis (Fig. 2.3).  L_LE (eq. 2.49, kernel e^{+i kappa X}) is Amiet's
    response with Roger's second-order term, evaluated with :func:`bbnoise.airfoil.le_response`
    at qbar = -kappa b (Amiet's kernel is e^{-i qbar x}).

    ``doppler_sign`` = -1 reverses the sign of the rotating part of kappa_mh,
    m B1 (Omega1 + Omega2)/U_X2 - (h/r) sin(a2), relative to the Doppler shift in K_X,mh: the
    same pairing issue as in eqs. 3.8 / 3.17.  With it, and with the result multiplied by 2 pi,
    eq. 2.73 reproduces the independent full formulation of :mod:`bbnoise.rotor` (see the
    verification suite); as printed it is 2 pi (8 dB) lower.
    """
    from .airfoil import le_response
    from .turbulence import make_spectrum
    omega = np.atleast_1d(np.asarray(omega, float))
    th = np.radians(theta_deg)
    c0, rho = rear.c0, rear.rho
    Om2 = abs(rear.Omega)
    Om1 = abs(Omega1)
    xg, wg = np.polynomial.legendre.leggauss(n_gauss)
    total = np.zeros_like(omega)
    parts = []
    for st in rear.strips():
        b = 0.5 * st.chord
        a2 = 0.5 * np.pi - st.psi
        U = st.U
        M = U / c0
        w_rms, L, bW = wake(st.r)
        S = np.zeros_like(omega)
        if w_rms > 0 and bW > 0:
            spec = make_spectrum(spectrum, w_rms, L)
            rq = st.r + 0.5 * st.dr * xg
            _, sigma = wake_fm2(0.0, st.r, B1, bW)
            m = np.arange(-int(np.ceil(4 * sigma)), int(np.ceil(4 * sigma)) + 1, dtype=float)   # thesis m_max = 4 sigma
            fm2q = [wake_fm2(m, xq, B1, bW)[0] for xq in rq]          # (n_gauss, n_m)
            for i, w in enumerate(omega):
                k0 = w / c0
                lmax = int(np.ceil(1.25 * k0 * rq.max() * abs(np.sin(th)))) + 3                    # thesis l_max
                l = np.arange(-lmax, lmax + 1, dtype=float)
                # D'_ml = sum over Gauss points of f_m^2(r) x [radiation term](l, r): outer products
                D = np.zeros((m.size, l.size))
                for xq, wq, fm2 in zip(rq, wg, fm2q):
                    rad = (l / (k0 * xq) * np.cos(a2) + np.cos(th) * np.sin(a2)) ** 2 * jv(l, k0 * xq * np.sin(th)) ** 2
                    D += 0.5 * wq * np.outer(fm2, rad)
                if D.max() <= 0:
                    continue
                mi, li = np.nonzero(D > 1e-12 * D.max())
                M_, L_ = m[mi], l[li]
                h = M_ * B1 - L_
                KX = (w + M_ * B1 * Om1 + h * Om2) / U
                DP = D[mi, li] * spec.phi_ww(np.abs(KX), 0.0)
                # |L_LE|^2 varies slowly next to D Phi: skip the negligible terms before evaluating it
                sel = DP > 1e-9 * DP.max()
                M_, h, KX, DP = M_[sel], h[sel], KX[sel], DP[sel]
                kap = k0 * np.cos(a2) * np.cos(th) + doppler_sign * (M_ * B1 * (Om1 + Om2) / U - h / st.r * np.sin(a2))
                # g(-kX) = conj g(kX): |L(-K, kappa)| = |L(K, -kappa)|
                sgn = np.where(KX < 0, -1.0, 1.0)
                K = np.maximum(np.abs(KX) * b, 1e-6)
                Lle = le_response(K, 0.0, M, -sgn * kap * b)
                S[i] = np.sum(DP * np.abs(Lle) ** 2)
            S *= rear.B / 4.0 * (B1 * rho * omega / c0 * b / r0) ** 2 * U * st.dr
        total += S
        parts.append(S)
    return (total, parts) if per_strip else total
