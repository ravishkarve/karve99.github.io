"""Amiet's flat-plate response theory for leading-edge (turbulence-interaction)
and trailing-edge (self) noise.

All response functions are written in terms of the dimensionless chordwise
*radiation* wavenumber

    qbar = mubar * (M - x1/sigma)          (stationary airfoil, Amiet)

rather than in terms of the observer position.  For a stationary airfoil the
two are identical.  For a rotating blade (the "full" formulation of Blandeau &
Joseph) the chordwise radiation wavenumber of the n-th azimuthal mode is
qbar_n = -b (n cos(psi)/R + K_z sin(psi)), which is fed straight into the same
functions.  Semi-chord b = c/2 is the length scale throughout.

Notation (Amiet 1975, 1976; Roger & Moreau 2005; Moreau & Roger 2009):

    Kbar  = omega b / U               gust/aerodynamic reduced frequency
    mubar = Kbar M / beta^2           (= kbar / beta^2)
    kappa = sqrt(mubar^2 - kybar^2 / beta^2)

Leading edge:  L = L1 (+ L2 second-order trailing-edge correction), Amiet's
high-frequency solution, or Amiet's low-frequency (compressible Sears)
approximation.
Trailing edge: I = I1 (+ I2 leading-edge back-scattering correction).

Far-field PSDs (Amiet's large-span results, span d, two-sided in omega if the
input spectra are two-sided):

    LE:  S_pp = (rho0 k c x3 / (2 sigma^2))^2  pi U (d/2) |L|^2 Phi_ww(K1, ky)
    TE:  S_pp = (k c x3 / (4 pi sigma^2))^2    (d/2) |I|^2 Phi_pp(omega) l_y(omega)

Both are written here as S_pp = (K_n / (4 pi sigma))^2 * S_F where K_n is the
component of the acoustic wave vector normal to the plate and S_F is an
"effective force spectrum" that already contains chordwise non-compactness:

    S_F(LE) = 2 pi^3 rho0^2 c^2 U d |L|^2 Phi_ww(K1, ky)
    S_F(TE) = c^2 (d/2) |I|^2 Phi_pp(omega) l_y(omega)

The same S_F feeds the rotating-dipole (full) and the azimuthally averaged
(simplified) rotor formulations, which guarantees that the two only differ
by the treatment of rotation.
"""
from __future__ import annotations

import numpy as np

from .special import E, Estar, Estar_over_sqrt, sears

__all__ = [
    "le_response", "te_response", "le_force_spectrum", "te_force_spectrum",
    "stationary_le_spl", "stationary_te_spl", "amiet_qbar",
]


def amiet_qbar(kbar, M, x1_over_sigma):
    """Chordwise radiation wavenumber of a stationary airfoil: mubar (M - x1/sigma)."""
    beta2 = 1.0 - M * M
    return kbar / beta2 * (M - x1_over_sigma)


# ---------------------------------------------------------------------------
# Leading-edge (turbulence interaction) response
# ---------------------------------------------------------------------------

def _le_high_frequency(Kx, kappa, beta2, qbar, mubar, M, second_order=True):
    """Amiet's high-frequency LE response with Roger's trailing-edge correction."""
    theta1 = kappa + qbar - mubar * M          # kappa - mubar x1/sigma
    theta2 = qbar - np.pi / 4.0                # mubar (M - x1/sigma) - pi/4
    theta3 = kappa - qbar + mubar * M          # kappa + mubar x1/sigma
    denom = Kx + beta2 * kappa
    L1 = (1.0 / np.pi) * np.sqrt(2.0 / denom) * Estar_over_sqrt(theta1) * np.exp(1j * theta2)
    if not second_order:
        return L1
    # L2 = e^{i th2} / (pi th1 sqrt(2 pi denom)) *
    #      { i (1 - e^{-2 i th1}) + (1-i)[E*(4 kappa) - sqrt(2 kappa/th3) e^{-2i th1} E*(2 th3)] }
    th1 = np.where(np.abs(theta1) < 1e-9, 1e-9, theta1)
    bracket = (1j * (1.0 - np.exp(-2j * th1))
               + (1.0 - 1j) * (Estar(4.0 * kappa)
                               - np.sqrt(2.0 * kappa) * np.exp(-2j * th1) * Estar_over_sqrt(theta3)))
    L2 = np.exp(1j * theta2) / (np.pi * th1 * np.sqrt(2.0 * np.pi * denom)) * bracket
    return L1 + L2


def _le_low_frequency(Kx, beta, qbar, mubar, M):
    """Amiet's low-frequency (compact, compressible Sears) LE response.

    |L| = |S(Kx/beta^2)| / beta * sqrt(J0(a)^2 + J1(a)^2) with a = mubar x1/sigma,
    a = -(qbar - mubar M).  The phase is only indicative.
    """
    from scipy.special import j0, j1
    a = np.real(qbar - mubar * M)
    S = sears(Kx / beta ** 2)
    return S / beta * (j0(a) + 1j * j1(a))


def le_response(Kx, ky, M, qbar, method="auto", second_order=True):
    """Amiet leading-edge response L(Kx, ky, qbar).

    Parameters
    ----------
    Kx : array  reduced chordwise gust wavenumber omega b / U (> 0)
    ky : array  reduced spanwise gust wavenumber (K2 b)
    M  : float  Mach number of the flow over the plate
    qbar : array  reduced chordwise radiation wavenumber (see module doc)
    method : 'auto' | 'high' | 'low'
        'auto' uses Amiet's switch: high-frequency solution when
        mubar = Kx M / beta^2 > pi/4, low-frequency (Sears) otherwise.
    second_order : include Roger's second-order (trailing-edge) correction L2
    """
    Kx, ky, qbar = np.broadcast_arrays(np.asarray(Kx, float), np.asarray(ky, float),
                                       np.asarray(qbar, complex))
    beta2 = 1.0 - M * M
    beta = np.sqrt(beta2)
    mubar = Kx * M / beta2
    kappa = np.sqrt(mubar ** 2 - (ky / beta) ** 2 + 0j)
    Kx_safe = np.maximum(Kx, 1e-12)
    if method == "high":
        return _le_high_frequency(Kx_safe, kappa, beta2, qbar, mubar, M, second_order)
    if method == "low":
        return _le_low_frequency(Kx_safe, beta, qbar, mubar, M)
    hf = mubar > np.pi / 4.0
    out = np.empty(Kx.shape, dtype=complex)
    if np.any(hf):
        out[hf] = _le_high_frequency(Kx_safe[hf], kappa[hf], beta2, qbar[hf], mubar[hf], M,
                                     second_order)
    if np.any(~hf):
        lf = ~hf
        out[lf] = _le_low_frequency(Kx_safe[lf], beta, qbar[lf], mubar[lf], M)
    return out


# ---------------------------------------------------------------------------
# Trailing-edge (turbulent boundary layer) response
# ---------------------------------------------------------------------------

def te_response(K, alpha, ky, M, qbar, backscatter=True):
    """Amiet / Roger & Moreau trailing-edge radiation integral I = I1 + I2.

    Parameters
    ----------
    K : reduced frequency omega b / U
    alpha : U / Uc (inverse convection-velocity ratio)
    ky : reduced spanwise wavenumber
    M : Mach number
    qbar : reduced chordwise radiation wavenumber (mubar (M - x1/S0) when stationary)
    backscatter : include the leading-edge back-scattering correction I2
    """
    K, ky, qbar = np.broadcast_arrays(np.asarray(K, float), np.asarray(ky, float),
                                      np.asarray(qbar, complex))
    K = np.maximum(K, 1e-12)
    beta2 = 1.0 - M * M
    mubar = K * M / beta2
    kappa = np.sqrt(mubar ** 2 - ky ** 2 / beta2 + 0j)
    # subcritical gusts (ky^2/beta^2 > mubar^2): kappa = -i kappa', the branch whose
    # pressure field decays upstream of the trailing edge (the other one overflows)
    subcritical = kappa.imag != 0
    kappa = np.where(kappa.imag > 0, np.conj(kappa), kappa)
    aK = alpha * K
    B = aK + mubar * M + kappa
    C = aK + qbar                       # alpha K - mubar (x1/S0 - M)
    C = np.where(np.abs(C) < 1e-9, 1e-9, C)
    # I1 = -(e^{2iC}/(iC)) {(1+i) e^{-2iC} sqrt(B/(B-C)) E*(2(B-C)) - (1+i) E*(2B) + 1}
    I1 = -(np.exp(2j * C) / (1j * C)) * (
        (1 + 1j) * np.exp(-2j * C) * np.sqrt(B) * Estar_over_sqrt(B - C)
        - (1 + 1j) * np.sqrt(B) * Estar_over_sqrt(B) + 1.0)
    if not backscatter or np.all(subcritical):
        return I1
    return _te_backscatter(I1, K, alpha, M, mubar, kappa, qbar, B, subcritical)


def _te_backscatter(I1, K, alpha, M, mubar, kappa, qbar, B, subcritical):
    """Add the leading-edge back-scattering correction I2 (Roger & Moreau 2005).

    It is only evaluated for supercritical gusts; for subcritical ones it is
    negligible (below 0.1 dB where it can be evaluated) and its terms overflow.
    """
    kappa = np.where(subcritical, 1.0 + 0j, kappa)       # placeholder, masked below
    aK = alpha * K
    D = kappa + qbar - mubar * M        # kappa - mubar x1/S0
    eps = (1.0 + 1.0 / (4.0 * kappa)) ** -0.5
    Ek = np.exp(4j * kappa) * (1.0 - (1 + 1j) * Estar(4.0 * kappa))
    Ek = np.real(Ek) + 1j * eps * np.imag(Ek)       # [ . ]^c of Roger & Moreau (2005)
    dm = D - 2.0 * kappa
    dp = D + 2.0 * kappa
    dm = np.where(np.abs(dm) < 1e-7, 1e-7, dm)
    dp = np.where(np.abs(dp) < 1e-7, 1e-7, dp)
    G = ((1 + eps) * np.exp(1j * (2 * kappa + D)) * np.sin(dm) / dm
         + (1 - eps) * np.exp(1j * (-2 * kappa + D)) * np.sin(dp) / dp
         + (1 + eps) * (1 - 1j) / (2 * dm) * np.exp(4j * kappa) * Estar(4 * kappa)
         - (1 - eps) * (1 + 1j) / (2 * dp) * np.exp(-4j * kappa) * E(4 * kappa)
         + np.exp(2j * D) / 2 * np.sqrt(2 * kappa) * Estar_over_sqrt(D)
         * ((1 + 1j) * (1 - eps) / dp - (1 - 1j) * (1 + eps) / dm))
    A = K + mubar * M + kappa
    A1 = aK + mubar * M + kappa
    theta2 = A1 / A
    if abs(alpha - 1.0) < 1e-9:
        alpha = 1.0 + 1e-9
    H = (1 + 1j) * np.exp(-4j * kappa) * (1 - theta2) / (2 * np.sqrt(np.pi) * (alpha - 1) * K * np.sqrt(B))
    I2 = H * (Ek - np.exp(2j * D) + 1j * (D + K + M * mubar - kappa) * G)
    return I1 + np.where(subcritical, 0.0, I2)


# ---------------------------------------------------------------------------
# Effective force spectra and stationary far-field formulas
# ---------------------------------------------------------------------------

def le_force_spectrum(omega, U, c, span, M, qbar, ky, phi_ww, rho0=1.225,
                      method="auto", second_order=True):
    """Effective lift PSD  S_F = 2 pi^3 rho0^2 c^2 U d |L|^2 Phi_ww(K1, ky).

    ``phi_ww`` is the value of the two-wavenumber upwash spectrum at
    (K1 = omega/U, ky) (already evaluated by the caller).  ``ky`` is the
    dimensional spanwise wavenumber.
    """
    b = 0.5 * c
    Kx = np.abs(omega) * b / U
    L = le_response(Kx, ky * b, M, qbar, method=method, second_order=second_order)
    return 2.0 * np.pi ** 3 * rho0 ** 2 * c ** 2 * U * span * np.abs(L) ** 2 * phi_ww


def te_force_spectrum(omega, U, Uc, c, span, M, qbar, ky, phi_pp, l_y, backscatter=True):
    """Effective trailing-edge force PSD  S_F = c^2 (d/2) |I|^2 Phi_pp l_y(ky).

    The spanwise wavenumber dependence follows from the exponential (Corcos)
    coherence exp(-|eta|/l_y): pi Pi(ky) = l_y / (1 + (ky l_y)^2), which reduces
    to Amiet's l_y at ky = 0.
    """
    b = 0.5 * c
    K = np.abs(omega) * b / U
    I = te_response(K, U / Uc, ky * b, M, qbar, backscatter=backscatter)
    ly_eff = l_y / (1.0 + (ky * l_y) ** 2)
    return c ** 2 * 0.5 * span * np.abs(I) ** 2 * phi_pp * ly_eff


def _observer_terms(x, M):
    x1, x2, x3 = x
    beta2 = 1.0 - M * M
    sigma = np.sqrt(x1 ** 2 + beta2 * (x2 ** 2 + x3 ** 2))
    return x1, x2, x3, sigma


def stationary_le_spl(omega, x, U, c, span, M, turbulence, rho0=1.225, c0=340.0,
                      method="auto", second_order=True):
    """Far-field PSD of a stationary flat plate in turbulence (Amiet 1975).

    ``x`` = (x1, x2, x3): observer relative to the mid-chord, x1 downstream,
    x2 spanwise, x3 normal.  ``turbulence`` exposes ``phi_ww(k1, k2)``.
    Returns S_pp(omega) with the spectral convention of ``turbulence``
    (two-sided in omega for the built-in spectra).
    """
    omega = np.asarray(omega, float)
    x1, x2, x3, sigma = _observer_terms(x, M)
    k = omega / c0
    b = 0.5 * c
    qbar = amiet_qbar(k * b, M, x1 / sigma)
    ky = k * x2 / sigma
    phi = turbulence.phi_ww(omega / U, ky)
    SF = le_force_spectrum(omega, U, c, span, M, qbar, ky, phi, rho0, method, second_order)
    Kn = k * x3 / sigma
    return (Kn / (4.0 * np.pi * sigma)) ** 2 * SF


def stationary_te_spl(omega, x, U, c, span, M, phi_pp, l_y, Uc, c0=340.0, backscatter=True):
    """Far-field PSD of trailing-edge noise from a stationary plate (Amiet 1976).

    ``phi_pp`` and ``l_y`` are arrays over ``omega`` (wall-pressure PSD and
    spanwise correlation length).  One-sided input gives one-sided output.
    """
    omega = np.asarray(omega, float)
    x1, x2, x3, sigma = _observer_terms(x, M)
    k = omega / c0
    b = 0.5 * c
    qbar = amiet_qbar(k * b, M, x1 / sigma)
    ky = k * x2 / sigma
    SF = te_force_spectrum(omega, U, Uc, c, span, M, qbar, ky, phi_pp, l_y, backscatter)
    Kn = k * x3 / sigma
    return (Kn / (4.0 * np.pi * sigma)) ** 2 * SF
