"""Mixed-out (constant-area mixing) analysis for cascade exit flows.

A non-uniform exit flow (inviscid core plus blade boundary layers and a
trailing-edge base) is replaced by the uniform state that has the same mass,
axial-momentum, tangential-momentum and energy fluxes across one pitch.  This
is how MISES reports its loss coefficient and mixed-out exit angle.

Units follow the solver convention rho0 = a0 = 1, so p0 = 1/gamma,
h0 = 1/(gamma-1), R = 1/gamma, cp = 1/(gamma-1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import gas


@dataclass
class MixedOutState:
    p: float
    p0: float
    T: float
    mach: float
    angle: float       # flow angle from axial [deg]
    u: float
    v: float
    rho: float
    choked: bool = False

    def to_dict(self):
        return dict(self.__dict__)


def mixed_out(mdot, fx, fy, h0, pitch, gamma=gas.GAMMA_AIR):
    """Uniform state with given pitchwise fluxes per unit span.

    mdot = rho u s,  fx = (p + rho u^2) s,  fy = rho u v s,  h0 = total enthalpy.
    """
    cp = 1.0 / (gamma - 1.0)
    v = fy / mdot
    h0p = h0 - 0.5 * v * v
    a = mdot * (gamma + 1.0) / (2.0 * gamma)
    c = mdot * (gamma - 1.0) / gamma * h0p
    disc = fx * fx - 4.0 * a * c
    choked = disc < 0.0
    u = (fx - math.sqrt(max(disc, 0.0))) / (2.0 * a)
    T = (h0 - 0.5 * (u * u + v * v)) / cp
    p = (fx - mdot * u) / pitch
    rho = mdot / (u * pitch)
    a_s = math.sqrt(max(T, 1e-12))            # a = sqrt(gamma R T) = sqrt(T)
    V = math.hypot(u, v)
    M = V / a_s
    T0 = h0 / cp
    p0 = p * (T0 / T) ** (gamma / (gamma - 1.0))
    return MixedOutState(p, p0, T, M, math.degrees(math.atan2(v, u)), u, v, rho, bool(choked))


def uniform_state(mach, angle_deg, gamma=gas.GAMMA_AIR, p0=None):
    """Primitive state (rho, V, p, T) of a uniform isentropic flow in solver units."""
    p0 = 1.0 / gamma if p0 is None else p0
    tr = float(gas.t_ratio(mach, gamma))
    rho = float(gas.rho_ratio(mach, gamma)) * (p0 * gamma)
    V = mach * math.sqrt(tr)
    p = p0 * tr ** (gamma / (gamma - 1.0))
    return rho, V, p, tr


def fluxes_of_uniform(mach, angle_deg, pitch, gamma=gas.GAMMA_AIR):
    rho, V, p, _ = uniform_state(mach, angle_deg, gamma)
    b = math.radians(angle_deg)
    u, v = V * math.cos(b), V * math.sin(b)
    return rho * u * pitch, (p + rho * u * u) * pitch, rho * u * v * pitch


def edge_state_for_mass(mdot, angle_deg, blockage, pitch, gamma=gas.GAMMA_AIR):
    """Isentropic edge Mach number such that rho V (s cos(beta) - blockage) = mdot."""
    cb = math.cos(math.radians(angle_deg))
    width = pitch * cb - blockage
    target = mdot / width                       # rho*V in units rho0*a0
    # rho V / (rho0 a0) = M * t^((g+1)/(2(g-1)))
    lo, hi = 0.0, 1.0
    fmax = float(gas.mass_flow_function(1.0, gamma)) / gamma
    if target > fmax:
        return 1.0, True
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        f = float(gas.mass_flow_function(mid, gamma)) / gamma
        if f < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), False


@dataclass
class LossBreakdown:
    omega: float                 # total mixed-out loss (p01 - p02)/(p01 - p1)
    omega_inviscid: float        # loss in the inviscid core (shocks, numerical)
    omega_viscous: float         # omega - omega_inviscid
    exit: MixedOutState          # mixed-out exit state
    inlet_p: float
    inlet_p0: float

    def to_dict(self):
        d = dict(omega=self.omega, omega_inviscid=self.omega_inviscid,
                 omega_viscous=self.omega_viscous, inlet_p=self.inlet_p, inlet_p0=self.inlet_p0)
        d["exit"] = self.exit.to_dict()
        return d


def cascade_mixed_out_loss(mach1, beta1, beta_e, pitch, dstar, theta, t_te=0.0,
                           gamma=gas.GAMMA_AIR, core_fluxes=None, edge=None, p0_core=None):
    """Mixed-out loss of a cascade from trailing-edge boundary-layer integrals.

    Parameters
    ----------
    mach1, beta1   : inlet Mach number and flow angle [deg].
    beta_e         : flow angle of the inviscid core at the trailing edge [deg].
    pitch          : blade pitch (chord units, same as dstar/theta).
    dstar, theta   : sums of displacement / momentum thickness of both sides at the TE.
    t_te           : trailing-edge thickness (base blockage, base pressure = p_e).
    core_fluxes    : optional (mdot, fx, fy) of an inviscid core flow that
                     already contains the displacement mass (Euler with
                     transpiration).  If omitted, an isentropic uniform core
                     carrying the inlet mass flow is constructed.
    edge           : (rho_e, V_e) edge density/speed used for the deficits when
                     core_fluxes is given.
    p0_core        : stagnation pressure of the inviscid core (for omega_inviscid).
    """
    p01 = 1.0 / gamma
    h0 = 1.0 / (gamma - 1.0)
    rho1, V1, p1, _ = uniform_state(mach1, beta1, gamma)
    b1 = math.radians(beta1)
    mdot1 = rho1 * V1 * math.cos(b1) * pitch
    be = math.radians(beta_e)
    if core_fluxes is None:
        Me, _ = edge_state_for_mass(mdot1, beta_e, dstar + t_te, pitch, gamma)
        rho_e, V_e, p_e, _ = uniform_state(Me, beta_e, gamma)
        wm = pitch * math.cos(be) - dstar - theta - t_te
        mdot = mdot1
        fx = p_e * pitch + rho_e * V_e ** 2 * wm * math.cos(be)
        fy = rho_e * V_e ** 2 * wm * math.sin(be)
        p0c = p01
    else:
        mdot_c, fx_c, fy_c = core_fluxes
        rho_e, V_e = edge
        mdot = mdot_c - rho_e * V_e * (dstar + t_te)
        fx = fx_c - rho_e * V_e ** 2 * (dstar + theta + t_te) * math.cos(be)
        fy = fy_c - rho_e * V_e ** 2 * (dstar + theta + t_te) * math.sin(be)
        p0c = p0_core if p0_core is not None else p01
    st = mixed_out(mdot, fx, fy, h0, pitch, gamma)
    q = p01 - p1
    omega = (p01 - st.p0) / q
    omega_inv = (p01 - p0c) / q
    return LossBreakdown(omega, omega_inv, omega - omega_inv, st, p1, p01)


def lieblein_loss(theta_c, H_te, solidity, beta1, beta2):
    """Lieblein & Roudebush (1956) incompressible wake-mixing loss coefficient.

    omega = 2 (theta/c) (sigma/cos b2) (cos b1/cos b2)^2 * [2H/(3H-1)]
            / [1 - (theta/c) sigma H / cos b2]^3
    """
    c1, c2 = math.cos(math.radians(beta1)), math.cos(math.radians(beta2))
    tc = theta_c * solidity / c2
    return 2.0 * tc * (c1 / c2) ** 2 * (2.0 * H_te / (3.0 * H_te - 1.0)) / (1.0 - tc * H_te) ** 3


def cascade_force_coefficients(rho1, u1, v1, p1, exit_state, pitch, chord, p01=None):
    """Blade force, lift and drag coefficients from a control-volume momentum balance.

    The control volume spans one pitch from the uniform inlet state to the
    mixed-out exit state (periodic sides cancel).  The force exerted by the
    fluid on one blade, per unit span, is

        F_x = s (p1 - p2) + mdot (u1 - u2),      F_y = mdot (v1 - v2),

    with mdot = rho1 u1 s.  Lift and drag are its components normal and
    parallel to the vector-mean direction tan(beta_m) = (tan beta1 + tan beta2)/2,

        L = F_y cos(beta_m) - F_x sin(beta_m),   D = F_x cos(beta_m) + F_y sin(beta_m),

    normalised by the inlet dynamic pressure rho1 V1^2 / 2 and the chord.  In
    incompressible flow this reproduces the classical cascade relations
    D = s dp0 cos(beta_m) and L = rho s c_x^2 (tan b1 - tan b2) / cos(beta_m) - s dp0 sin(beta_m)
    (Dixon & Hall).

    In compressible flow the density change through the passage gives the
    momentum "drag" D a component that is not zero even without loss (it is
    negative for a decelerating cascade), so the drag coefficient is taken from
    the total-pressure loss, C_D = (s/c) (p01 - p02) / (rho1 V1^2 / 2) cos(beta_m),
    which equals the momentum drag in incompressible flow.  The momentum value
    is returned as ``cd_momentum``.  Give ``p01`` (the inlet stagnation pressure);
    without it the momentum drag is used.  With an AVDR different from one the
    end-wall pressure force is not included, so the coefficients are approximate.
    """
    mdot = rho1 * u1 * pitch
    u2, v2, p2 = exit_state.u, exit_state.v, exit_state.p
    fx = pitch * (p1 - p2) + mdot * (u1 - u2)
    fy = mdot * (v1 - v2)
    bm = math.atan(0.5 * (v1 / u1 + v2 / u2))
    lift = fy * math.cos(bm) - fx * math.sin(bm)
    drag = fx * math.cos(bm) + fy * math.sin(bm)
    q1c = 0.5 * rho1 * (u1 * u1 + v1 * v1) * chord
    cd_mom = drag / q1c
    cd = cd_mom if p01 is None else pitch * (p01 - exit_state.p0) * math.cos(bm) / q1c
    return {"cl": lift / q1c, "cd": cd, "cd_momentum": cd_mom, "beta_m": math.degrees(bm),
            "fx": fx, "fy": fy}
