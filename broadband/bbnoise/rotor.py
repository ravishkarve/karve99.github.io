r"""Broadband noise radiation from rotating blades: the *full* (exact rotating
dipole) and the *simplified* (Amiet's azimuthally averaged) formulations.

Frame and conventions
---------------------
The rotor is fixed at the origin with its axis along z; the fluid moves at the
axial speed Ux in the +z direction (wind-tunnel frame, equivalent to flight
at speed Ux towards -z with the observer moving with the aircraft).  The
observer polar angle ``theta`` is measured from the *upstream* (flight)
direction -z, as is usual for propellers: theta = 0 forward, 90 deg in the
rotor plane, 180 deg aft.

Each radial strip (radius R, width dr, chord c) sees the relative velocity
U = sqrt((Omega R)^2 + Ux^2) at the inflow angle psi = atan(Ux / (Omega R))
(flat plates at zero incidence, chord aligned with the relative flow).  The
blade force acts along the chord normal n = cos(psi) e_z + sin(psi) e_phi.

Convected far-field Green's function (source near the origin):

    G = exp(i k (sigma - Mx z)/beta_x^2) / (4 pi sigma),  sigma^2 = z^2 + beta_x^2 rho^2,
    K = grad(phase) = k (rho_hat rho/sigma, (z/sigma - Mx)/beta_x^2)

Full formulation (Blandeau & Joseph 2011; Blandeau 2011, ch. 3)
---------------------------------------------------------------
Expanding the phase of a point on the rotating chord with the Jacobi-Anger
identity gives, for B statistically independent blades,

    S_pp(x, w) = B/(4 pi sigma)^2 sum_n J_n^2(K_r R) D_n^2 S_F(w + n Omega; q_n)

    D_n = K_z cos(psi) - (n/R) sin(psi)            (dipole projection of mode n)
    q_n = -b (n cos(psi)/R + K_z sin(psi))          (chordwise radiation wavenumber)

Each azimuthal mode n radiates the blade-frame spectrum at the Doppler
shifted source frequency w_s = w + n Omega.  The chordwise non-compactness of
the Amiet loading enters through q_n, so the same effective force spectrum
S_F (see :mod:`bbnoise.airfoil`) is used as for a stationary airfoil.

Simplified formulation (Amiet 1977; Schlinker & Amiet 1981)
-----------------------------------------------------------
The blade is treated as an airfoil in rectilinear motion at every azimuth
Psi.  The observer position is taken in the blade frame at the reception
time, the stationary Amiet PSD is evaluated at the emission frequency w_s,
and the result is averaged over one revolution:

    S_pp(x, w) = B/(2 pi) int_0^{2 pi} (w_s/w)^p S_pp^Amiet(x_b(Psi), w_s(Psi)) dPsi,
    w_s/w = 1 - K.V_b / k

With the observer taken at the *reception* time in the blade frame, the
stationary Amiet formula already contains the moving-dipole amplification
(1 - M_r)^-2; one power of w_s/w converts source-time into observer-time
averaging and one is the spectral Jacobian, so p = 2 (default,
``doppler_exponent``).  Amiet (1977) and several later works used p = 1.
The package's verification shows that with p = 2 the simplified model
reproduces the full formulation to < 0.05 dB for w >> Omega when the source
spectrum is smooth; the full formulation remains exact at low frequency.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.special import jv

__all__ = ["Strip", "Rotor", "observer_position", "full_spectrum", "simplified_spectrum",
           "stationary_spectrum", "rotor_spectrum", "sound_power"]


@dataclass
class Strip:
    """One radial blade element."""
    index: int
    r: float          # mid radius [m]
    dr: float         # span of the strip [m]
    chord: float      # [m]
    Omega: float      # |angular speed| [rad/s]
    Ux: float         # axial speed through the rotor [m/s]
    c0: float = 340.0
    rho: float = 1.225

    @property
    def Ut(self):
        return self.Omega * self.r

    @property
    def U(self):
        return float(np.hypot(self.Ut, self.Ux))

    @property
    def psi(self):
        """Inflow (stagger) angle from the rotor plane [rad]."""
        return float(np.arctan2(self.Ux, self.Ut))

    @property
    def M(self):
        return self.U / self.c0


def _interp_prop(value, r, r_hub, r_tip):
    """Evaluate a scalar / callable / {'r_over_R': [...], 'value': [...]} property at r."""
    if callable(value):
        return float(value(r))
    if isinstance(value, dict):
        xs = np.asarray(value.get("r_over_R", value.get("r")), float)
        ys = np.asarray(value.get("value", value.get("chord")), float)
        x = r / r_tip if "r_over_R" in value else r
        return float(np.interp(x, xs, ys))
    if isinstance(value, (list, tuple, np.ndarray)):
        ys = np.asarray(value, float)
        xs = np.linspace(r_hub / r_tip, 1.0, len(ys))
        return float(np.interp(r / r_tip, xs, ys))
    return float(value)


@dataclass
class Rotor:
    """Rotor geometry and operating point.

    chord: scalar [m], list over r/R from hub to tip, dict {'r_over_R': [], 'value': []}
    or callable c(r).  ``Ux`` may likewise vary with radius (axial velocity through
    the disc); ``flight_speed`` is the free-stream speed used for convection
    (defaults to the hub value of Ux).
    """
    B: int
    r_tip: float
    r_hub: float
    chord: object
    rpm: float
    Ux: object = 0.0
    flight_speed: float | None = None
    n_strips: int = 10
    c0: float = 340.0
    rho: float = 1.225
    name: str = "rotor"
    strip_edges: list | None = None

    @property
    def Omega(self):
        return abs(self.rpm) * 2.0 * np.pi / 60.0

    @property
    def shaft_frequency(self):
        return abs(self.rpm) / 60.0

    @property
    def Mx(self):
        U = self.flight_speed if self.flight_speed is not None else _interp_prop(
            self.Ux, self.r_hub, self.r_hub, self.r_tip)
        return U / self.c0

    def strips(self):
        if self.strip_edges is not None:
            edges = np.asarray(self.strip_edges, float)
        else:
            edges = np.linspace(self.r_hub, self.r_tip, self.n_strips + 1)
        out = []
        for i in range(len(edges) - 1):
            r = 0.5 * (edges[i] + edges[i + 1])
            out.append(Strip(i, r, edges[i + 1] - edges[i],
                             _interp_prop(self.chord, r, self.r_hub, self.r_tip), self.Omega,
                             _interp_prop(self.Ux, r, self.r_hub, self.r_tip), self.c0, self.rho))
        return out

    def summary(self):
        st = self.strips()
        tip = st[-1]
        return {"name": self.name, "B": self.B, "rpm": self.rpm, "r_tip": self.r_tip,
                "r_hub": self.r_hub, "tip_mach_rotational": self.Omega * self.r_tip / self.c0,
                "tip_mach_relative": tip.M, "Mx": self.Mx, "bpf_hz": self.B * self.shaft_frequency,
                "strips": [{"r": s.r, "dr": s.dr, "chord": s.chord, "U": s.U,
                            "psi_deg": np.degrees(s.psi), "M": s.M} for s in st]}


def observer_position(R, theta_deg, phi_deg=0.0):
    """Observer at distance R, polar angle theta from the upstream (flight) axis."""
    th = np.radians(theta_deg)
    ph = np.radians(phi_deg)
    return np.array([R * np.sin(th) * np.cos(ph), R * np.sin(th) * np.sin(ph), -R * np.cos(th)])


def _convected(dx, Mx):
    """sigma, K/k (radial vector, axial) and propagation time*c0 for separation dx."""
    beta2 = 1.0 - Mx * Mx
    rho_vec = dx[..., :2]
    z = dx[..., 2]
    rho = np.sqrt(np.sum(rho_vec ** 2, axis=-1))
    sigma = np.sqrt(z * z + beta2 * rho * rho)
    Kt = rho_vec / sigma[..., None]           # transverse part of K/k
    Kz = (z / sigma - Mx) / beta2
    c0T = (sigma - Mx * z) / beta2
    return sigma, Kt, Kz, c0T


# ---------------------------------------------------------------------------
# Full (rotating dipole) formulation
# ---------------------------------------------------------------------------

def _source_eval(source, strip, omega_s, qbar, ky):
    """Evaluate S_F for arbitrary-sign source frequency (S_F is even in omega)."""
    neg = omega_s < 0
    q = np.where(neg, -qbar, qbar)
    w = np.abs(omega_s)
    tiny = w < 1e-9 * max(np.max(w), 1.0)
    w = np.where(tiny, 1.0, w)
    out = source.force_spectrum(strip, w, q, ky)
    return np.where(tiny, 0.0, np.nan_to_num(out, nan=0.0, posinf=0.0))


def full_spectrum(rotor: Rotor, source, omega, x, per_strip=False, n_extra=None, spanwise=True):
    """Far-field PSD S_pp(omega) from the exact rotating-dipole formulation.

    Returns the spectrum in the source's native convention (see ``source.spectral_factor``).
    ``spanwise=True`` evaluates the gust spectrum at the local radial wavenumber of each
    azimuthal mode (consistent with Amiet's k x2/sigma); ``False`` uses ky = 0.
    """
    omega = np.atleast_1d(np.asarray(omega, float))
    x = np.asarray(x, float)
    sigma, Kt, Kz, _ = _convected(x, rotor.Mx)
    Kr_over_k = float(np.hypot(*Kt))
    Kz_over_k = float(Kz)
    total = np.zeros_like(omega)
    parts = []
    k_all = omega / rotor.c0
    for st in rotor.strips():
        b = 0.5 * st.chord
        cp, sp = np.cos(st.psi), np.sin(st.psi)
        # assemble all (frequency, mode) pairs of this strip, then evaluate the source once
        idx, n_all = [], []
        for i, w in enumerate(omega):
            arg = k_all[i] * Kr_over_k * st.r
            extra = n_extra if n_extra is not None else int(12 + 4 * arg ** (1 / 3))
            N = int(np.ceil(arg)) + extra
            n = np.arange(-N, N + 1)
            n_all.append(n)
            idx.append(np.full(n.size, i))
        n = np.concatenate(n_all).astype(float)
        i_f = np.concatenate(idx)
        k = k_all[i_f]
        arg = k * Kr_over_k * st.r
        J2 = jv(n, arg) ** 2
        Kz_ = k * Kz_over_k
        D = Kz_ * cp - n / st.r * sp
        qn = -b * (n * cp / st.r + Kz_ * sp)
        ws = omega[i_f] + n * st.Omega
        # Evanescent modes (|n| > K_r R) have chordwise wavenumbers outside the range reachable
        # by any real radiation direction, mubar (M - x1/sigma) with |x1/sigma| <= 1.  Clip them to
        # that range: this removes the spurious trailing-edge hydrodynamic coincidence
        # (alpha K + q = 0) and leaves the radiating modes untouched.
        ksb = np.abs(ws) * b / rotor.c0
        sgn = np.where(ws < 0, -1.0, 1.0)
        qn = sgn * np.clip(sgn * qn, -ksb / (1.0 + st.M), ksb / (1.0 - st.M))
        # local radial (spanwise) wavenumber of J_n at the strip: stationary-phase
        # value K_r sqrt(1 - (n / K_r R)^2); zero for evanescent (|n| > K_r R) modes
        if spanwise:
            ky = k * Kr_over_k * np.sqrt(np.clip(1.0 - (n / np.maximum(arg, 1e-12)) ** 2, 0.0, None))
        else:
            ky = np.zeros_like(n)
        keep = J2 > 1e-14 * np.maximum(J2.max(), 1e-300)
        terms = np.zeros_like(n)
        if np.any(keep):
            SF = _source_eval(source, st, ws[keep], qn[keep], ky[keep])
            terms[keep] = J2[keep] * D[keep] ** 2 * SF
        S = np.bincount(i_f, weights=terms, minlength=omega.size)
        S *= rotor.B / (4.0 * np.pi * sigma) ** 2
        total += S
        parts.append(S)
    return (total, parts) if per_strip else total


# ---------------------------------------------------------------------------
# Simplified (Amiet azimuthal average) formulation
# ---------------------------------------------------------------------------

def simplified_spectrum(rotor: Rotor, source, omega, x, n_psi=72, doppler_exponent=2.0,
                        per_strip=False):
    """Far-field PSD from Amiet's azimuthally averaged formulation."""
    omega = np.atleast_1d(np.asarray(omega, float))
    x = np.asarray(x, float)
    Psi = (np.arange(n_psi) + 0.5) * 2.0 * np.pi / n_psi
    er = np.stack([np.cos(Psi), np.sin(Psi), np.zeros_like(Psi)], axis=-1)
    ephi = np.stack([-np.sin(Psi), np.cos(Psi), np.zeros_like(Psi)], axis=-1)
    ez = np.array([0.0, 0.0, 1.0])
    total = np.zeros_like(omega)
    parts = []
    for st in rotor.strips():
        y = st.r * er
        dx = x[None, :] - y
        sigma_c, Kt, Kz, c0T = _convected(dx, rotor.Mx)
        Kvec = np.concatenate([Kt, Kz[:, None]], axis=-1)          # K/k
        Vb = st.Ut * ephi
        ratio = 1.0 - np.sum(Kvec * Vb, axis=-1) / rotor.c0          # w_s / w
        xb = dx - Vb * (c0T / rotor.c0)[:, None]                     # observer in blade frame
        e1 = (st.Ux * ez[None, :] - st.Ut * ephi) / st.U
        e2 = er
        e3 = np.cross(e1, e2)
        x1 = np.sum(xb * e1, axis=-1)
        x2 = np.sum(xb * e2, axis=-1)
        x3 = np.sum(xb * e3, axis=-1)
        M = st.M
        beta2 = 1.0 - M * M
        sig = np.sqrt(x1 ** 2 + beta2 * (x2 ** 2 + x3 ** 2))
        b = 0.5 * st.chord
        ws = omega[:, None] * ratio[None, :]
        ks = ws / rotor.c0
        qbar = ks * b / beta2 * (M - x1 / sig)[None, :]
        ky = ks * (x2 / sig)[None, :]
        Kn = ks * (x3 / sig)[None, :]
        SF = _source_eval(source, st, ws.ravel(), qbar.ravel(), ky.ravel()).reshape(ws.shape)
        Sst = (Kn / (4.0 * np.pi * sig[None, :])) ** 2 * SF
        S = rotor.B * np.mean(ratio[None, :] ** doppler_exponent * Sst, axis=1)
        total += S
        parts.append(S)
    return (total, parts) if per_strip else total


def stationary_spectrum(strip: Strip, source, omega, x_airfoil):
    """Stationary airfoil (Amiet) PSD with the observer in airfoil axes (x1 downstream,
    x2 spanwise, x3 normal) - uses the same effective force spectrum as the rotor models."""
    omega = np.atleast_1d(np.asarray(omega, float))
    x1, x2, x3 = x_airfoil
    M = strip.M
    beta2 = 1.0 - M * M
    sig = np.sqrt(x1 ** 2 + beta2 * (x2 ** 2 + x3 ** 2))
    b = 0.5 * strip.chord
    k = omega / strip.c0
    qbar = k * b / beta2 * (M - x1 / sig)
    ky = k * x2 / sig
    SF = _source_eval(source, strip, omega, qbar, ky)
    return (k * x3 / sig / (4.0 * np.pi * sig)) ** 2 * SF


def rotor_spectrum(rotor, source, omega, x, formulation="full", **kw):
    if formulation == "full":
        return full_spectrum(rotor, source, omega, x, **{k: v for k, v in kw.items()
                                                         if k in ("per_strip", "n_extra", "spanwise")})
    if formulation in ("simplified", "amiet"):
        return simplified_spectrum(rotor, source, omega, x, **{k: v for k, v in kw.items()
                                                               if k in ("per_strip", "n_psi",
                                                                        "doppler_exponent")})
    raise ValueError(f"unknown formulation {formulation!r} (use 'full' or 'simplified')")


def sound_power(rotor, source, omega, formulation="full", R=100.0, n_theta=19, **kw):
    """Radiated sound power PSD W(omega) = int S_pp / (rho0 c0) dS (static-medium intensity)."""
    th = np.linspace(0.0, 180.0, n_theta)
    th[0], th[-1] = 0.5, 179.5
    vals = np.array([rotor_spectrum(rotor, source, omega, observer_position(R, t), formulation, **kw)
                     for t in th])
    integrand = vals * np.sin(np.radians(th))[:, None]
    return 2.0 * np.pi * R * R * np.trapezoid(integrand, np.radians(th), axis=0) / (rotor.rho * rotor.c0)
