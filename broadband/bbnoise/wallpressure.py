"""Wall-pressure spectrum (WPS) models beneath turbulent boundary layers and
boundary-layer parameter handling for trailing-edge (self) noise.

All models return the *one-sided* point spectrum Phi_pp(omega) in
Pa^2 / (rad/s), i.e. p_rms^2 = int_0^inf Phi_pp d omega.  Blandeau's thesis
(ch. 3.2) writes them double-sided (p^2 = int_-inf^inf Phi d omega), i.e. half
of the values returned here.  Normalisations (w = omega delta*/Ue unless noted):

amiet        Willmarth-Roos-Amiet (Amiet 1976; thesis eq. 3.21), a double-sided fit:
             Phi2 Ue/(q^2 delta*) = 2e-5 / (1 + w + 0.217 w^2 + 0.00562 w^4)
kim_george   Kim & George (1982), NACA 0012 fit (thesis eqs. 3.25-3.26), double-sided:
             Phi2 Ue/(q^2 delta*) = 1/2 * 1.732e-3 w / (1 - 5.489 w + 36.74 w^2 + 0.1505 w^5), w < 0.06
                                  = 1/2 * 1.4216e-3 w / (0.3261 + 4.1837 w + 22.818 w^2 + 0.0013 w^3 + 0.0028 w^5)
rozenberg_2010  Rozenberg's model as used in the thesis (eqs. 3.27-3.29), double-sided:
             Phi2 Ue/(tau_w^2 delta*) = 1/2 C w^2 / ([w^0.75 + 0.105]^3.7 + [3.76 R_T^-0.57 w]^7),
             C = 0.78 (1.8 Pi beta_C + 6), R_T with delta = 8 delta*, Pi from Coles' law,
             beta_C = 0 for favourable gradients
chase_howe   Howe (1998), Chase model:
             Phi Ue/(tau_w^2 delta*) = 2 w^2 / (w^2 + 0.0144)^1.5
goody        Goody (2004), omega delta/Ue:
             Phi Ue/(tau_w^2 delta) = 3 w^2 / ((w^0.75 + 0.5)^3.7 + (1.1 Rt^-0.57 w)^7)
rozenberg    Rozenberg, Robert & Moreau (2012), adverse pressure gradient extension
kamruzzaman  Kamruzzaman et al. (2015), APG and FPG
lee          Lee (2018), correction of Rozenberg for strong APG
dominique_gep  VKI Gene Expression Programming model, Dominique, Christophe,
             Schram & Sandberg (2021, J. Sound Vib. 506, 116162):
             Phi Ue/(tau_w^2 delta*) = (5.41 + Cf (beta_C+1)^5.41) w /
                 ( w^2 + w + (beta_C+1) M + (w + 3.6) w^4.76 / (Cf R_T^5.83) )
             with R_T = (delta*/Ue)/(nu/u_tau^2) and M the edge Mach number.

Parameters: Delta = delta/delta*, H = delta*/theta, beta_C = (theta/tau_w) dp/dx
(Clauser parameter based on the momentum thickness), Pi = Coles wake strength,
Rt = (delta/Ue)/(nu/u_tau^2) (Goody's ratio of outer to inner time scales).

Spanwise coherence: Corcos, l_y = b_c Uc / omega (b_c = 1.47 by default).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

__all__ = ["BoundaryLayer", "wps", "WPS_MODELS", "WPS_INFO", "corcos_ly", "wps_normalised", "coles_pi"]


@dataclass
class BoundaryLayer:
    """Boundary-layer state at (or just upstream of) the trailing edge.

    Give at least Ue and delta*; missing quantities are estimated by
    :meth:`complete` (shape factor H = 1.4, Ludwieg-Tillmann skin friction,
    Drela's delta(theta, H), Durbin & Reif wake strength).
    """
    Ue: float
    delta_star: float
    delta: float | None = None
    theta: float | None = None
    H: float | None = None
    cf: float | None = None
    tau_w: float | None = None
    dpdx: float | None = None
    beta_c: float | None = None
    Pi: float | None = None
    tau_max: float | None = None
    rho: float = 1.225
    nu: float = 1.5e-5
    c0: float = 340.0
    notes: list = field(default_factory=list)

    def complete(self):
        """Fill in the missing parameters with standard correlations; returns self."""
        if self.H is None:
            if self.theta is not None and self.theta > 0:
                self.H = self.delta_star / self.theta
            else:
                self.H = 1.4
                self.notes.append("H assumed 1.4")
        if self.theta is None:
            self.theta = self.delta_star / self.H
        re_theta = max(self.Ue * self.theta / self.nu, 10.0)
        if self.cf is None and self.tau_w is None:
            # Ludwieg & Tillmann (1949)
            self.cf = 0.246 * 10.0 ** (-0.678 * self.H) * re_theta ** -0.268
            self.notes.append("cf from Ludwieg-Tillmann")
        q = 0.5 * self.rho * self.Ue ** 2
        if self.tau_w is None:
            self.tau_w = self.cf * q
        if self.cf is None:
            self.cf = self.tau_w / q
        if self.delta is None:
            # Drela (1989) correlation used by XFOIL-based TE noise codes
            self.delta = self.theta * (3.15 + 1.72 / max(self.H - 1.0, 0.05)) + self.delta_star
            self.notes.append("delta from Drela's correlation")
        if self.beta_c is None:
            self.beta_c = 0.0 if self.dpdx is None else self.theta / self.tau_w * self.dpdx
        if self.dpdx is None:
            self.dpdx = self.beta_c * self.tau_w / self.theta
        if self.Pi is None:
            # Durbin & Reif (2001), used by Rozenberg, Kamruzzaman and Lee
            self.Pi = 0.8 * (max(self.beta_c, -0.49) + 0.5) ** 0.75
        if self.tau_max is None:
            self.tau_max = self.tau_w
        return self

    # derived quantities ------------------------------------------------------
    @property
    def u_tau(self):
        return np.sqrt(self.tau_w / self.rho)

    @property
    def Rt(self):
        """Goody's time-scale ratio (delta/Ue)/(nu/u_tau^2)."""
        return (self.delta / self.Ue) * self.u_tau ** 2 / self.nu

    @property
    def RT_star(self):
        """Time-scale ratio based on delta*: (delta*/Ue)/(nu/u_tau^2)."""
        return (self.delta_star / self.Ue) * self.u_tau ** 2 / self.nu

    @property
    def Delta(self):
        return self.delta / self.delta_star

    @property
    def mach(self):
        return self.Ue / self.c0

    def as_dict(self):
        d = asdict(self)
        d.update(u_tau=self.u_tau, Rt=self.Rt, RT_star=self.RT_star, Delta=self.Delta, mach=self.mach)
        return d


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _amiet(w, bl):
    # the Willmarth-Roos fit is double-sided (thesis eq. 3.21): one-sided = 2 x
    q = 0.5 * bl.rho * bl.Ue ** 2
    ws = w * bl.delta_star / bl.Ue
    return 2.0 * q ** 2 * bl.delta_star / bl.Ue * 2e-5 / (1 + ws + 0.217 * ws ** 2 + 0.00562 * ws ** 4)


def _kim_george(w, bl):
    """Kim & George (1982) as given in the thesis (eqs. 3.25-3.26), converted to one-sided."""
    q = 0.5 * bl.rho * bl.Ue ** 2
    ws = np.asarray(w * bl.delta_star / bl.Ue, float)
    lo = 1.732e-3 * ws / (1 - 5.489 * ws + 36.74 * ws ** 2 + 0.1505 * ws ** 5)
    hi = 1.4216e-3 * ws / (0.3261 + 4.1837 * ws + 22.818 * ws ** 2 + 0.0013 * ws ** 3 + 0.0028 * ws ** 5)
    return q ** 2 * bl.delta_star / bl.Ue * np.where(ws < 0.06, lo, hi)


KAPPA_VK = 0.41


def coles_pi(bl):
    """Coles' wake strength from the log law at the edge (thesis eq. 3.28):
    2 Pi - ln(1 + Pi) = kappa Ue/u_tau - ln(delta* Ue/nu) - 5.1 kappa - ln kappa."""
    rhs = KAPPA_VK * bl.Ue / bl.u_tau - np.log(bl.delta_star * bl.Ue / bl.nu) - 5.1 * KAPPA_VK - np.log(KAPPA_VK)
    if rhs <= 0:
        return 0.0
    P = max(rhs / 2.0, 0.1)
    for _ in range(60):                 # Newton on f(P) = 2P - ln(1+P) - rhs
        f = 2 * P - np.log1p(P) - rhs
        P -= f / (2 - 1 / (1 + P))
        P = max(P, 0.0)
    return float(P)


def _rozenberg_2010(w, bl):
    """Rozenberg's model in the form used by the thesis (eq. 3.27), converted to one-sided."""
    ws = w * bl.delta_star / bl.Ue
    bc = max(bl.beta_c, 0.0)            # favourable gradients neglected (thesis, section 3.2.3)
    Pi = coles_pi(bl)
    C = 0.78 * (1.8 * Pi * bc + 6.0)
    RT = (8.0 * bl.delta_star / bl.Ue) * bl.u_tau ** 2 / bl.nu      # delta = 8 delta*
    return bl.tau_w ** 2 * bl.delta_star / bl.Ue * C * ws ** 2 / ((ws ** 0.75 + 0.105) ** 3.7 + (3.76 * RT ** -0.57 * ws) ** 7)


def _chase_howe(w, bl):
    ws = w * bl.delta_star / bl.Ue
    return bl.tau_w ** 2 * bl.delta_star / bl.Ue * 2 * ws ** 2 / (ws ** 2 + 0.0144) ** 1.5


def _goody(w, bl):
    wd = w * bl.delta / bl.Ue
    C3 = 1.1 * bl.Rt ** -0.57
    return bl.tau_w ** 2 * bl.delta / bl.Ue * 3.0 * wd ** 2 / ((wd ** 0.75 + 0.5) ** 3.7 + (C3 * wd) ** 7)


def _rozenberg(w, bl):
    ws = w * bl.delta_star / bl.Ue
    D = bl.Delta
    bc = bl.beta_c
    A1 = 3.7 + 1.5 * bc
    A2 = min(3.0, 19.0 / np.sqrt(bl.Rt)) + 7.0
    F1 = 4.76 * (1.4 / D) ** 0.75 * (0.375 * A1 - 1.0)
    num = 2.82 * D ** 2 * (6.13 * D ** -0.75 + F1) ** A1 * (4.2 * bl.Pi / D + 1.0) * ws ** 2
    den = (4.76 * ws ** 0.75 + F1) ** A1 + (8.8 * bl.Rt ** -0.57 * ws) ** A2
    return bl.tau_max ** 2 * bl.delta_star / bl.Ue * num / den


def _kamruzzaman(w, bl):
    ws = w * bl.delta_star / bl.Ue
    m = 0.5 * (bl.H / 1.31) ** 0.3
    a = 0.45 * (1.75 * (bl.Pi ** 2 * bl.beta_c ** 2) ** m + 15.0)
    num = a * ws ** 2
    den = (ws ** 1.637 + 0.27) ** 2.47 + (1.15 * bl.RT_star ** (-2.0 / 7.0) * ws) ** 7
    return bl.tau_w ** 2 * bl.delta_star / bl.Ue * num / den


def _lee(w, bl):
    ws = w * bl.delta_star / bl.Ue
    D = bl.Delta
    bc = bl.beta_c
    e = 3.7 + 1.5 * bc
    d = 4.76 * (1.4 / D) ** 0.75 * (0.375 * e - 1.0)
    if bc < 0.5:
        d = max(1.0, 1.5 * d)
    a = 2.82 * D ** 2 * (6.13 * D ** -0.75 + d) ** e * (4.2 * bl.Pi / D + 1.0)
    a_star = max(1.0, 0.25 * bc - 0.52) * a
    h = min(3.0, 0.139 + 3.1043 * bc) + 7.0
    den = (4.76 * ws ** 0.75 + d) ** e + (8.8 * bl.Rt ** -0.57 * ws) ** h
    return bl.tau_w ** 2 * bl.delta_star / bl.Ue * a_star * ws ** 2 / den


def _dominique_gep(w, bl):
    ws = w * bl.delta_star / bl.Ue
    bc1 = bl.beta_c + 1.0
    cf = bl.cf
    num = (5.41 + cf * bc1 ** 5.41) * ws
    den = ws ** 2 + ws + bc1 * bl.mach + (ws + 3.6) * ws ** 4.76 / (cf * bl.RT_star ** 5.83)
    return bl.tau_w ** 2 * bl.delta_star / bl.Ue * num / den


WPS_MODELS = {
    "amiet": _amiet,
    "chase_howe": _chase_howe,
    "goody": _goody,
    "rozenberg": _rozenberg,
    "kamruzzaman": _kamruzzaman,
    "lee": _lee,
    "dominique_gep": _dominique_gep,
    "kim_george": _kim_george,
    "rozenberg_2010": _rozenberg_2010,
}

WPS_INFO = {
    "amiet": "Willmarth-Roos-Amiet (Amiet 1976; thesis eq. 3.21); zero pressure gradient, outer scaling",
    "chase_howe": "Chase-Howe (Howe 1998); ZPG, mixed scaling, omega^2 low / omega^-1 high",
    "goody": "Goody (2004); ZPG, Reynolds-number dependent high-frequency roll-off",
    "rozenberg": "Rozenberg, Robert & Moreau (2012); adverse pressure gradient (beta_C, Pi, Delta)",
    "kamruzzaman": "Kamruzzaman et al. (2015); adverse and favourable pressure gradients (H, Pi, beta_C)",
    "lee": "Lee (2018); Rozenberg corrected for strong APG and low-frequency level",
    "dominique_gep": "VKI Gene Expression Programming model, Dominique et al. (2021, JSV 506)",
    "kim_george": "Kim & George (1982), NACA 0012 fit, outer scaling (thesis eqs. 3.25-3.26)",
    "rozenberg_2010": "Rozenberg as used in Blandeau's thesis (eq. 3.27): Coles Pi, delta = 8 delta*",
}

ALIASES = {"chase": "chase_howe", "howe": "chase_howe", "chasehowe": "chase_howe",
           "gep": "dominique_gep", "vki": "dominique_gep", "vki_gep": "dominique_gep",
           "dominique": "dominique_gep", "kam": "kamruzzaman", "kimgeorge": "kim_george",
           "rozenberg_thesis": "rozenberg_2010", "willmarth_roos": "amiet"}


def _resolve(model):
    m = str(model).lower().replace("-", "_").replace(" ", "_")
    m = ALIASES.get(m, m)
    if m not in WPS_MODELS:
        raise ValueError(f"unknown wall-pressure model {model!r}; choose from {sorted(WPS_MODELS)}")
    return m


def wps(model, omega, bl: BoundaryLayer):
    """One-sided wall-pressure PSD Phi_pp(omega) [Pa^2 s/rad] for ``model``."""
    omega = np.abs(np.asarray(omega, float))
    return WPS_MODELS[_resolve(model)](omega, bl)


def wps_normalised(model, omega_tilde, bl: BoundaryLayer):
    """Phi_pp Ue / (tau_w^2 delta*) as a function of omega delta*/Ue (for plots)."""
    omega = np.asarray(omega_tilde) * bl.Ue / bl.delta_star
    return wps(model, omega, bl) * bl.Ue / (bl.tau_w ** 2 * bl.delta_star)


def corcos_ly(omega, Uc, b_c=1.47):
    """Corcos spanwise correlation length l_y = b_c Uc / omega."""
    omega = np.maximum(np.abs(np.asarray(omega, float)), 1e-12)
    return b_c * Uc / omega
