"""Rotor broadband noise models after V. P. Blandeau's thesis (Southampton, 2011).

``BRWI``           rotor-wake interaction noise of the rear rotor, full rotational
                   model (wake + background turbulence), thesis ch. 2
``BRTE``           rotor trailing-edge (self) noise, full rotational model, thesis ch. 3
``BRTE_amiet``     rotor trailing-edge noise, Amiet's simplified rotational model, thesis ch. 5

Spectra are returned as ``Spp[omega, theta, strip]`` (BRWI) or
``Spp[omega, theta, strip, observer]`` (BRTE), double-sided in omega, the last
strip index holding the sum over strips.

Wall-pressure models (``phi_sw``): WA Willmarth-Roos-Amiet, CH Chase-Howe, GY Goody,
KG Kim-George, RZ Rozenberg, VKI the VKI gene-expression-programming model of
Dominique et al. (2021).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import hankel2, jv

from .inputs import SolverError
from .numerics import first, cpow, csqrt, erfz, root_from_start, round_away

__all__ = ["BRWI", "BRTE", "BRTE_amiet", "BPRI_amiet", "GAUSS_X", "GAUSS_W"]

GAUSS_X = np.array([0.9324700, 0.6612094, 0.2386192, -0.2386192, -0.6612094, -0.9324700])
GAUSS_W = np.array([0.1713245, 0.3607616, 0.4679139, 0.4679139, 0.3607616, 0.1713245])
I1 = 1j
_KE_FAC = math.gamma(5 / 6) / math.gamma(1 / 3)


def _thetas(opt, geom, lists):
    if opt.get("chapman"):
        return np.asarray(lists.theta_hat, float), np.asarray(geom.r0_hat, float)
    return np.asarray(lists.theta, float), geom.r0


def _progress(cb, msg):
    if cb:
        cb(msg)


# ---------------------------------------------------------------------------
# rotor-wake interaction (BRWI)
# ---------------------------------------------------------------------------

def BRWI(geom, flow, opt, lists, progress=None):
    """Interaction noise of the rear rotor: background plus wake turbulence (whichever are present)."""
    wake = np.max(flow.wrms2_wake) > 1e-10
    bg = np.max(flow.wrms2_bg) > 1e-10
    if wake and bg:
        return _brwi(geom, flow, opt, lists, "uniform", progress) + _brwi(geom, flow, opt, lists, "wake", progress)
    if bg:
        return _brwi(geom, flow, opt, lists, "uniform", progress)
    return _brwi(geom, flow, opt, lists, "wake", progress)


def _lqmn_le(mua, Mwin, betawin, fmx, k_mn):
    """Leading-edge response Lqmn for one mua (scalar) and an array of k_mn."""
    muh = mua / Mwin
    muaMw = mua * Mwin
    muain = abs(mua)
    if muain <= np.pi / 4:
        sears = 2.0 / (np.pi * muh) / (hankel2(0, muh) - I1 * hankel2(1, muh))
        return np.exp(I1 * muh * fmx) * sears / betawin * (jv(0, muaMw - k_mn) - I1 * jv(1, muaMw - k_mn))
    tet1 = muain - muaMw + k_mn
    tet1b = abs(muain - muaMw) + np.abs(k_mn)
    tet3 = muain + muaMw - k_mn
    L1 = erfz(csqrt(2 * I1 * tet1)) / csqrt(I1 * muh * (1 + Mwin) * tet1b)
    L22 = 1 - erfz(2 * abs(betawin) * csqrt(I1 * muain))
    L23 = 1 - csqrt(2 * muain / tet3) * erfz(csqrt(2 * I1 * tet3))
    L2 = I1 / tet1b / csqrt(2 * np.pi * muh * (1 + Mwin)) * (L22 - np.exp(-2 * I1 * tet1) * L23)
    tet2 = betawin ** 2 * muh + k_mn - np.pi / 4
    return np.exp(I1 * tet2) / (np.pi * betawin) * (L1 + L2)


def _brwi(geom, flow, opt, lists, turb, progress):
    if turb == "wake":
        L, wrms2 = flow.L_wake, flow.wrms2_wake
    else:
        if not getattr(flow, "L_bg_defined", True):
            raise SolverError("length scale 'BW' defines the wake length scale only; with background "
                              "turbulence use a factor C (L = C x L_table) or 'Pope'")
        L, wrms2 = flow.L_bg, flow.wrms2_bg
    omega = np.asarray(lists.omega, float)
    st = int(opt["st_num"])
    thetas, r0 = _thetas(opt, geom, lists)
    nth = thetas.size
    Spp = np.zeros((omega.size, nth, st + 1), dtype=complex)
    sinXa, cosXa = np.sin(thetas), np.cos(thetas)
    a = math.log(2.0)
    B1, B2 = geom.B
    Mx_eff = flow.Mx_eff
    for j in range(st):
        _progress(progress, f"Computing BRWI strip {j + 1}")
        Mwin = flow.Mw.ravel(order="F")[j]
        betawin = flow.betaw.ravel(order="F")[j]
        rj = geom.rj[j, -1]
        aa = rj - geom.drj[-1] / 2
        bb = rj + geom.drj[-1] / 2
        rr = 0.5 * ((bb - aa) * GAUSS_X + bb + aa)
        sinalf2, cosalf2 = math.sin(geom.alpha2[j]), math.cos(geom.alpha2[j])
        Lj = L.ravel(order="F")[j]
        w2j = wrms2.ravel(order="F")[j]
        ke = (math.sqrt(math.pi) / Lj) * _KE_FAC
        coe_Fiww = 4 / 9 / math.pi * w2j / (ke * ke) if opt.get("Karman_spec", True) else Lj ** 2 * w2j * 3 / (4 * math.pi)
        bwj = flow.bw_engine.ravel(order="F")[j]
        sigma = math.sqrt(2 * a) / (B1 * bwj) * rr
        coe_Dml = 0.5 * (bb - aa) / geom.drj[-1]
        coe_fm = 1 / (B1 * math.sqrt(2 * math.pi))
        UX2 = flow.U_X2.ravel(order="F")[j]
        b = geom.b[j, -1]
        amp = math.pi * B2 / 2 * UX2 * geom.drj[-1]
        amp = amp * (flow.rho * b * B1 / r0 / Mx_eff) ** 2
        coe_mua = Mwin * b / betawin ** 2
        fmx = (1 - betawin) * math.log(Mwin) + betawin * math.log(1 + betawin) - math.log(2)
        mmax = 4 * rj * math.sqrt(2 * a) / B1 / bwj
        ma = 0 if turb == "uniform" else int(round_away(mmax))
        m = np.arange(-ma, ma + 1, dtype=float)
        if turb == "uniform":
            fm2 = np.full((m.size, 6), (1 / B1) ** 2)
        else:
            fm2 = (coe_fm / sigma[None, :] * np.exp(-0.5 * (m[:, None] / sigma[None, :]) ** 2)) ** 2
        for i, w in enumerate(omega):
            k0 = w / Mx_eff / flow.c0
            coe1 = k0 * sinalf2 * cosXa
            coe_k = -k0 * cosalf2 * cosXa
            coe2 = k0 * sinXa
            if not opt.get("chapman") and not opt.get("emission_angle"):
                coe1 = (coe1 / flow.betax_mf2) * (1 - Mx_eff * flow.MX / cosXa)
                coe_k = -k0 * cosalf2 * (cosXa - flow.MX * Mx_eff) / flow.betax_mf2
            coe1 = np.broadcast_to(coe1, (nth,))
            coe_k = np.broadcast_to(coe_k, (nth,))
            coe2 = np.broadcast_to(coe2, (nth,))
            lmax = 1.25 * k0 * rj + 3
            na = int(round_away(first(lmax)))
            l = np.arange(-na, na + 1, dtype=float)
            # Dml[m, l, theta] = sum_k w_k fm_k(m)^2 (l cos a2 / r_k + coe1)^2 J_l(r_k coe2)^2
            A = np.empty((6, l.size, nth))
            for k in range(6):
                A[k] = (l[:, None] * cosalf2 / rr[k] + coe1[None, :]) ** 2 * jv(l[:, None], rr[k] * coe2[None, :]) ** 2
            Dml = np.einsum("k,mk,klt->mlt", GAUSS_W, fm2, A)
            om_mn = m[:, None] * B1 * (geom.OM[0] + geom.OM[1]) - l[None, :] * geom.OM[1]
            Kx_mn = np.abs(w + om_mn) / UX2
            if opt.get("Karman_spec", True):
                k2 = (Kx_mn / ke) ** 2
                Fi = k2 / ((1 + k2) ** (7 / 3))
            else:
                k2 = (Lj * Kx_mn) ** 2
                Fi = k2 / (1 + k2) ** 2.5
            Kx_mnk = np.abs(w - l * geom.OM[1]) / UX2
            L2 = np.empty((l.size, nth))
            for q in range(l.size):
                k_mn = (coe_k + l[q] * sinalf2 / rj) * b
                L2[q] = np.abs(_lqmn_le(coe_mua * Kx_mnk[q], Mwin, betawin, fmx, k_mn)) ** 2
            sum1 = np.einsum("mlt,ml,lt->t", Dml, Fi, L2)
            Spp[i, :, j] = Spp[i, :, j] + coe_Dml * coe_Fiww * amp * sum1
        Spp[:, :, st] = Spp[:, :, st] + Spp[:, :, j]
    return Spp


# ---------------------------------------------------------------------------
# rotor trailing-edge noise, full model (BRTE)
# ---------------------------------------------------------------------------

def _uc_omega(opt, om, bl, flow, rot, j, g):
    """Convection velocity for an array of omega_l."""
    om = np.asarray(om, float)
    dstar = 0.5 * (bl.d_star_t[rot, j, g] + bl.d_star_b[rot, j, g])
    model = opt.get("Uc", "0.8")
    Ux = flow.Ux[j, rot, g]
    if model == "0.8":
        return np.full(om.shape, 0.8 * Ux)
    if model == "DEL":
        ut = 0.5 * (math.sqrt(bl.tauwall_t[rot, j, g] / bl.rhow_t[rot, j, g])
                    + math.sqrt(bl.tauwall_b[rot, j, g] / bl.rhow_b[rot, j, g]))
        Ub = 0.92 * Ux
        delta = 0.5 * (bl.d_t[rot, j, g] + bl.d_b[rot, j, g])
        return np.array([_uc_del(ut, Ub, delta, o) for o in om.ravel()]).reshape(om.shape)
    if model == "GLB":
        ombar = om * dstar / Ux
        return flow.Ux[j, rot, 0] * (0.75 + 0.6 * ombar) / (1 + 1.333 * ombar)
    if model == "DEL2":
        ombar = om * dstar / flow.Ux[j, rot, 0]
        return flow.Ux[j, rot, 0] * (0.8 + 20 * ombar ** 2) / (1 + 50 * ombar ** 2)
    raise SolverError(f"unknown convection velocity model {model!r}")


def _uc_del(ut, Ub, delta, om):
    niv1 = 11 * ut
    fin = 0.9 * Ub

    def uc(lh):
        return ((math.atan((lh - 4) * 0.8) + math.pi / 2) - 0.303) / math.pi * (fin - 0.85 * niv1) + niv1

    lh = root_from_start(lambda lam: uc(lam) * 2 * math.pi / om - lam * delta, 10.0)
    return uc(lh)


def _bl_side(bl, sw, rot, j, g):
    s = "t" if sw == 1 else "b"
    get = lambda k: getattr(bl, f"{k}_{s}")[rot, j, g]   # noqa: E731
    return dict(delta_star=get("d_star"), delta=get("d"), taumax=get("taumax"), tauwall=get("tauwall"),
                mom_th=get("mom_th"), dpdx=get("dpdx"), rho=get("rhow"), uinf=get("uinf"), nuw=get("nuw"),
                PI=get("pi"))


def _phi_lr(opt, flow, omega, bl, sw, rot, j, g, Uc):
    """Wall-pressure spectrum times spanwise correlation length, vectorised over omega_l."""
    q = _bl_side(bl, sw, rot, j, g)
    omega = np.asarray(omega, float)
    Ux = flow.Ux[j, rot, g]
    ds, delta, tauwall, rho, uinf = q["delta_star"], q["delta"], q["tauwall"], q["rho"], q["uinf"]
    Cf = tauwall / (0.5 * rho * Ux ** 2)
    mu_t = math.sqrt(tauwall / rho)
    ob = omega * ds / uinf
    model = opt.get("phi_sw", "RZ")
    if model == "WA":
        phi = (0.00002 / (1 + ob + 0.217 * ob ** 2 + 0.00562 * ob ** 4)) * (0.5 * rho * Ux ** 2) ** 2 * ds / Ux
    elif model == "CH":
        phi = (ob ** 2 / cpow(ob ** 2 + 0.0144, 1.5)) * tauwall ** 2 * ds / Ux
    elif model == "GY":
        d8 = 8 * ds
        ob1 = omega * d8 / Ux
        R_t = (mu_t * d8 / flow.nu) * math.sqrt(Cf / 2)
        phi = 3 * ob1 ** 2 / (cpow(cpow(ob1, 0.75) + 0.5, 3.7) + cpow(1.1 * R_t ** (-0.57) * ob1, 7)) \
            * tauwall ** 2 * d8 / Ux
        delta = d8                     # with Goody's model the l_r models below use delta = 8 delta*
    elif model == "KG":
        lo = (0.5 * 0.001732 * ob) / (1 - 5.489 * ob + 36.74 * ob ** 2 + 0.1505 * ob ** 5)
        hi = (0.5 * 0.0014216 * ob) / (0.3261 + 4.1837 * ob + 22.818 * ob ** 2 + 0.0013 * ob ** 3 + 0.0028 * ob ** 5)
        phi = np.where(ob < 0.06, lo, hi) * (0.5 * rho * Ux ** 2) ** 2 * ds / Ux
    elif model == "RZ":
        D = delta / ds
        Bc = q["mom_th"] / tauwall * q["dpdx"] if (q["dpdx"] > 0 and sw == 1) else 0.0
        Rt = delta / uinf / (q["nuw"] / mu_t ** 2)
        A1 = 3.7 + 1.5 * Bc
        A2 = min(3, 19 / math.sqrt(Rt)) + 7
        F1 = 4.76 * (1.4 / D) ** 0.75 * (0.375 * A1 - 1)
        C3 = 8.8 * Rt ** (-0.57)
        redim = q["taumax"] ** 2 * ds / uinf
        X1 = 2.82 * D ** 2 * cpow(6.13 * D ** (-0.75) + F1, A1)
        phi = X1 * (4.2 * q["PI"] / D + 1) * ob ** 2 / (cpow(4.76 * cpow(ob, 0.75) + F1, A1) + cpow(C3 * ob, A2)) * redim
    elif model == "VKI":
        phi = _phi_vki(omega, ds, q["mom_th"], tauwall, q["dpdx"], rho, uinf, q["nuw"], flow.c0)
    else:
        raise SolverError(f"unknown wall-pressure model {model!r}")
    lr_model = opt.get("lr", "COR")
    if lr_model == "COR":
        l2 = Uc / omega / 0.625
    elif lr_model in ("ROG", "LGL", "RGS"):
        A = 1.10 if lr_model == "RGS" else 0.95
        s, f0 = 0.32, 0.55
        lng = delta if lr_model == "LGL" else ds
        f = omega * lng / uinf
        l2 = lng * A ** 2 / s / math.sqrt(2 * math.pi) / f * np.exp(-(_clog10(f) - math.log10(f0)) ** 2 / 2 / s ** 2)
    elif lr_model == "CORL":
        f = omega * ds / uinf
        l2 = np.where(f < 0.2, delta, Uc / omega / 0.625)
    elif lr_model == "EFP":
        utau = math.sqrt(tauwall / rho)
        St = omega * delta / utau
        l2 = delta * cpow((0.85 * St / (Uc / utau)) ** 2 + 60.0 ** 2 / (St ** 2 + (60.0 / 4.0) ** 2), -0.5)
    elif lr_model == "SLZ":
        utau = math.sqrt(tauwall / rho)
        a4, a5, a6 = 0.85, 12.0, 1.0
        od1 = omega * ds / uinf
        l2 = ds * cpow((a4 * od1 / (Uc / uinf)) ** 2
                       + a5 * a5 / ((delta / ds) ** 2 * ((omega * delta / utau) ** 2 + (a5 / a6) ** 2)), -0.5)
    else:
        raise SolverError(f"unknown spanwise correlation model {lr_model!r}")
    lr = l2 * (1 / (1 + l2 ** 2 * flow.kr ** 2))
    out = phi * lr
    if opt.get("baddata") == "DISCARD" and bl.discard_t[rot, j] + bl.discard_b[rot, j] > 0:
        out = out * 0
    return out


def _phi_vki(omega, ds, theta, tau_w, dpdx, rho, ue, nu, c0):
    """VKI gene-expression-programming wall-pressure model (Dominique, Christophe, Schram &
    Sandberg 2021, J. Sound Vib. 506, 116162), double-sided like the other models:

        Phi Ue/(tau_w^2 delta*) = 1/2 (5.41 + Cf (beta_C+1)^5.41) w /
            (w^2 + w + (beta_C+1) M + (w + 3.6) w^4.76 / (Cf R_T^5.83))

    w = omega delta*/Ue, Cf = tau_w/(rho Ue^2/2), beta_C = (theta/tau_w) dp/dx,
    R_T = (delta*/Ue)/(nu/u_tau^2), M = Ue/c0.
    """
    w = np.asarray(omega) * ds / ue
    cf = tau_w / (0.5 * rho * ue ** 2)
    bc1 = theta / tau_w * dpdx + 1.0
    rt = (ds / ue) / (nu / (tau_w / rho))
    num = (5.41 + cf * cpow(bc1, 5.41)) * w
    den = w ** 2 + w + bc1 * (ue / c0) + (w + 3.6) * cpow(w, 4.76) / (cf * rt ** 5.83)
    return 0.5 * tau_w ** 2 * ds / ue * num / den


def _clog10(x):
    x = np.asarray(x)
    if np.iscomplexobj(x) or np.any(x < 0):
        return np.log10(x.astype(complex))
    return np.log10(x)


def _lte(b, K, kappa, theta_a, denom):
    """LTE of eq. 3.19 with the thesis' p. 79 correction (denominator supplied)."""
    theta_b = b * (K + kappa)
    E1 = erfz(csqrt(2 * I1 * (theta_a - theta_b)))
    E2 = erfz(csqrt(2 * I1 * theta_a))
    temp1 = np.exp(-2 * I1 * theta_b) * csqrt(theta_a / (theta_a - theta_b)) * E1
    return (np.exp(2 * I1 * theta_b) / (I1 * denom)) * (temp1 - E2 + 1)


def BRTE(geom, flow, opt, bl, lists, rot, model="BRTE", progress=None):
    """Full rotational trailing-edge noise model (thesis eq. 3.18); ``rot`` is 0 (front) or 1 (rear)."""
    thetas, r0 = _thetas(opt, geom, lists)
    sinXa, cosXa = np.sin(thetas), np.cos(thetas)
    omega = np.asarray(lists.omega, float)
    st = int(opt["st_num"])
    nobs = int(opt["phi_obs_num"])
    nth = thetas.size
    Spp = np.zeros((omega.size, nth, st + 1, nobs), dtype=complex)
    Amp_spp = geom.B[rot] / (2 * math.pi) * geom.drj[rot]
    Mx_eff = flow.Mx_eff
    for g in range(nobs):
        for j in range(st):
            _progress(progress, f"Computing {model}{'2' if rot == 1 else ''} observer {g + 1}, strip {j + 1}")
            rj = geom.rj[j, rot]
            aa = rj - geom.drj[rot] / 2
            bb = rj + geom.drj[rot] / 2
            rr = 0.5 * ((bb - aa) * GAUSS_X + bb + aa)
            coe_Dml = 0.5 * (bb - aa) / geom.drj[rot]
            cosalf, sinalf = math.cos(geom.alpha[j, rot]), math.sin(geom.alpha[j, rot])
            b = geom.b[j, rot]
            bx2 = flow.beta_x[j, rot, 0] ** 2
            Mxj = flow.Mx[j, rot, 0]
            for i, w in enumerate(omega):
                k0 = w / flow.c0 / Mx_eff
                up = 1.25 * w / flow.c0 * rj * np.sin(thetas) + 3
                limit = int(round_away(np.max(up)))
                coe_k = -k0 * cosalf * cosXa
                coe1 = k0 * sinalf * cosXa
                coe2 = k0 * sinXa
                if not opt.get("chapman") and not opt.get("emission_angle"):
                    coe1 = coe1 / flow.betax_mf2 * (1 - Mx_eff * flow.MX / cosXa)
                    coe_k = -k0 * cosalf * (cosXa - flow.MX * Mx_eff) / flow.betax_mf2
                coe1 = np.broadcast_to(coe1, (nth,))
                coe_k = np.broadcast_to(coe_k, (nth,))
                coe2 = np.broadcast_to(coe2, (nth,))
                l = np.arange(-limit, limit + 1, dtype=float)
                kappa = coe_k[None, :] + l[:, None] * sinalf / rj
                omega_l = w + l * geom.OM[rot]
                Uc = _uc_omega(opt, omega_l, bl, flow, rot, j, g)
                Mc = Uc / flow.c0
                K = omega_l / Uc
                mu_a = K * Mc * b / bx2
                mu_a_inf = np.sqrt(mu_a ** 2 - (flow.kr * b / flow.beta_x[j, rot, 0]) ** 2)
                theta_a = (b * K + mu_a_inf + mu_a * Mxj)[:, None]
                LTE = _lte(b, K[:, None], kappa, theta_a, b * (np.abs(K)[:, None] + np.abs(kappa)))
                D = np.zeros((l.size, nth))
                f1 = l * cosalf
                for k in range(6):
                    ff = (f1[:, None] / rr[k] + coe1[None, :]) * jv(l[:, None], rr[k] * coe2[None, :])
                    D = D + GAUSS_W[k] * ff ** 2
                D = D * coe_Dml
                Sqq = 1 / math.pi * (_phi_lr(opt, flow, omega_l, bl, 1, rot, j, g, Uc)
                                     + _phi_lr(opt, flow, omega_l, bl, 2, rot, j, g, Uc))
                summ = np.sum(D * np.abs(LTE) ** 2 * np.asarray(Sqq)[:, None], axis=0)
                Spp[i, :, j, g] = Spp[i, :, j, g] + Amp_spp * (b / r0 / Mx_eff) ** 2 * summ
            Spp[:, :, st, g] = Spp[:, :, st, g] + Spp[:, :, j, g]
    return Spp


# ---------------------------------------------------------------------------
# rotor trailing-edge noise, Amiet's simplified model
# ---------------------------------------------------------------------------

def _mrdivide_row(a, b):
    """``a / b`` for row vectors as a least-squares scalar, elementwise for a scalar ``b``."""
    a = np.atleast_1d(np.asarray(a))
    b = np.atleast_1d(np.asarray(b))
    if b.size == 1:
        return a / b[0]
    a = np.broadcast_to(a, b.shape)
    return np.sum(a * np.conj(b)) / np.sum(b * np.conj(b))


def _phi_lr_amiet(opt, flow, omega, sw, toff, j, p, g, rot, bl):
    """Wall-pressure spectrum times spanwise correlation length for the simplified model."""
    s = "t" if sw == 1 else "b"
    get = lambda k: toff[f"{k}_{s}"][j, p, g]   # noqa: E731
    ds, delta, taumax, tauwall = get("d_star"), get("d"), get("taumax"), get("tauwall")
    mom_th, dpdx, rho, uinf, nuw, PI = get("mom_th"), get("dpdx"), get("rhow"), get("uinf"), get("nuw"), get("pi")
    Ux = toff["Ux"][j, p, g]
    Cf = tauwall / (0.5 * rho * Ux ** 2)
    mu_t = math.sqrt(tauwall / rho)
    omega = np.asarray(omega)
    ob = omega * ds / uinf
    model = opt.get("phi_sw", "RZ")
    if model == "WA":
        phi = (0.00002 / (1 + ob + 0.217 * ob ** 2 + 0.00562 * ob ** 4)) * (0.5 * flow.rho * Ux ** 2) ** 2 * ds / Ux
    elif model == "CH":
        phi = _mrdivide_row(ob ** 2, cpow(ob ** 2 + 0.0144, 1.5)) * tauwall ** 2 * ds / Ux
    elif model == "GY":
        d8 = 8 * ds
        R_t = (mu_t * d8 / flow.nu) * math.sqrt(Cf / 2)
        x = omega * d8 / Ux
        phi = 0.5 * 3 * x ** 2 / (cpow(cpow(x, 0.75) + 0.5, 3.7) + cpow(1.1 * R_t ** (-0.57) * x, 7)) * tauwall ** 2 * d8 / Ux
        delta = d8                     # with Goody's model the l_r models below use delta = 8 delta*
    elif model == "KG":
        if np.all(np.real(ob) < 0.06):
            phi_t = _mrdivide_row(0.5 * 0.001732 * ob, 1 - 5.489 * ob + 36.74 * ob ** 2 + 0.1505 * ob ** 5)
        else:
            phi_t = _mrdivide_row(0.5 * 0.0014216 * ob,
                                  0.3261 + 4.1837 * ob + 22.818 * ob ** 2 + 0.0013 * ob ** 3 + 0.0028 * ob ** 5)
        phi = phi_t * (0.5 * rho * Ux ** 2) ** 2 * ds / Ux
    elif model == "RZ":
        D = delta / ds
        Bc = mom_th / tauwall * dpdx if (dpdx > 0 and sw == 1) else 0.0
        Rt = delta / uinf / (nuw / mu_t ** 2)
        A1 = 3.7 + 1.5 * Bc
        A2 = min(3, 19 / math.sqrt(Rt)) + 7
        F1 = 4.76 * (1.4 / D) ** 0.75 * (0.375 * A1 - 1)
        C3 = 8.8 * Rt ** (-0.57)
        redim = taumax ** 2 * ds / uinf
        X1 = 2.82 * D ** 2 * (6.13 * D ** (-0.75) + F1) ** A1
        phi = X1 * (4.2 * PI / D + 1) * _mrdivide_row(ob ** 2, cpow(4.76 * cpow(ob, 0.75) + F1, A1)
                                                      + cpow(C3 * ob, A2)) * redim
    elif model == "VKI":
        phi = _phi_vki(omega, ds, mom_th, tauwall, dpdx, rho, uinf, nuw, flow.c0)
    else:
        raise SolverError(f"unknown wall-pressure model {model!r}")
    lr_model = opt.get("lr", "COR")
    if lr_model == "COR":
        l2 = toff["Uc"][j, p, g] / omega / 0.625
    elif lr_model in ("ROG", "LGL"):
        lng = delta if lr_model == "LGL" else ds
        f = omega * lng / uinf
        l2 = lng * 0.95 ** 2 / 0.32 / math.sqrt(2 * math.pi) / f * np.exp(-(_clog10(f) - math.log10(0.55)) ** 2 / 2 / 0.32 ** 2)
    else:
        raise SolverError(f"spanwise correlation model {lr_model!r} is available with the full formulation only "
                          "(simplified formulation: COR, ROG, LGL)")
    out = phi * (l2 * (1 / (1 + l2 ** 2 * flow.kr ** 2)))
    if opt.get("baddata") == "DISCARD" and bl.discard_t[rot, j] + bl.discard_b[rot, j] > 0:
        out = out * 0
    return out


def _toff_brte(opt, flow, bl, lists, rot):
    """Azimuthal arrays shifted by one index for each observer offset."""
    nphi = int(opt["phi_num"])
    nobs = int(opt["phi_obs_num"])
    st = int(opt["st_num"])
    rep = lambda a: np.concatenate([a, a], axis=1)      # (st, 2 nphi)   # noqa: E731
    src = {"Ux": rep(flow.Ux[:, rot, :]), "Uc": rep(flow.Uc[:, rot, :]), "beta_x": rep(flow.beta_x[:, rot, :])}
    for k in ("d_star", "mom_th", "dpdx", "d", "taumax", "tauwall", "rhow", "uinf", "pi", "nuw"):
        for s in ("t", "b"):
            src[f"{k}_{s}"] = rep(getattr(bl, f"{k}_{s}")[rot, :, :])
    toff = {k: np.zeros((st, nphi, nobs)) for k in src}
    toff["Mx"] = np.zeros((st, nphi, nobs))
    toff["Mc"] = np.zeros((st, nphi, nobs))
    for g in range(nobs):
        idx = np.nonzero(lists.phi_list >= lists.offset_list[g])[0]
        if idx.size == 0:
            raise SolverError("observer offset beyond the azimuthal list")
        for p in range(nphi):
            t = idx[0] + p + 1                      # one index past the offset position
            for k in src:
                toff[k][:, p, g] = src[k][:, t]
            toff["Mx"][:, p, g] = src["Ux"][:, t] / flow.c0
            toff["Mc"][:, p, g] = src["Uc"][:, t] / flow.c0
    return toff


def _uc_amiet(opt, om, toff, j, p, g):
    ds = 0.5 * (toff["d_star_t"][j, p, g] + toff["d_star_b"][j, p, g])
    model = opt.get("Uc", "0.8")
    Ux = toff["Ux"][j, p, g]
    if model == "0.8":
        return 0.8 * Ux
    if model == "DEL":
        ut = 0.5 * (math.sqrt(toff["tauwall_t"][j, p, g] / toff["rhow_t"][j, p, g])
                    + math.sqrt(toff["tauwall_b"][j, p, g] / toff["rhow_b"][j, p, g]))
        delta = 0.5 * (toff["d_t"][j, p, g] + toff["d_b"][j, p, g])
        return _uc_del(ut, 0.92 * Ux, delta, om)
    if model == "GLB":
        ombar = om * ds / Ux
        return Ux * (0.75 + 0.6 * ombar) / (1 + 1.333 * ombar)
    raise SolverError(f"convection model {model!r} is available with the full formulation only "
                      "(simplified formulation: 0.8, DEL, GLB)")


def BRTE_amiet(geom, flow, opt, bl, lists, rot, model="BRTE", progress=None):
    """Amiet's simplified rotational trailing-edge noise model (thesis eq. 5.7)."""
    if not opt.get("chapman"):
        raise SolverError("the simplified trailing-edge model uses the Chapman mean-flow correction")
    thetas = np.asarray(lists.theta_hat, float)
    r0 = np.asarray(geom.r0_hat, float)
    cosXa, sinXa = np.cos(thetas), np.sin(thetas)
    omega = np.asarray(lists.omega, float)
    st = int(opt["st_num"])
    nobs = int(opt["phi_obs_num"])
    nth = thetas.size
    phi_list = np.asarray(lists.phi_list, float)
    Spp = np.zeros((omega.size, nth, st + 1, nobs), dtype=complex)
    toff = _toff_brte(opt, flow, bl, lists, rot)
    for g in range(nobs):
        for j in range(st):
            _progress(progress, f"Computing {model}{'2' if rot == 1 else ''} observer {g + 1}, strip {j + 1}")
            cosalf, sinalf = math.cos(geom.alpha[j, rot]), math.sin(geom.alpha[j, rot])
            b = geom.b[j, rot]
            for i, om in enumerate(omega):
                k0 = om / flow.c0
                Y = np.zeros((phi_list.size, nth), dtype=complex)
                for p, ph in enumerate(phi_list):
                    M_phi = geom.rj[j, rot] * geom.OM[rot] / flow.c0
                    om_phi = om * (1 + M_phi * math.cos(ph) * sinXa)
                    Uc = _uc_amiet(opt, om, toff, j, p, g)
                    Mc = Uc / flow.c0
                    K = om_phi / Uc
                    kappa = k0 * (sinXa * sinalf * math.cos(ph) - cosXa * cosalf)
                    Amp = (om_phi / om) ** -2 * geom.B[rot] * (om_phi / flow.c0 * b / (2 * math.pi * r0)) ** 2 * geom.drj[rot]
                    Dml = (-cosXa * sinalf - cosalf * sinXa * math.cos(ph)) ** 2
                    Sqq = 1 / math.pi * (_phi_lr_amiet(opt, flow, om_phi, 1, toff, j, p, g, rot, bl)
                                         + _phi_lr_amiet(opt, flow, om_phi, 2, toff, j, p, g, rot, bl))
                    bx = toff["beta_x"][j, p, g]
                    mu_a = K * Mc * b / bx ** 2
                    mu_a_inf = np.sqrt(mu_a ** 2 - (flow.kr * b / bx) ** 2)
                    theta_a = b * K + mu_a_inf + mu_a * toff["Mx"][j, p, g]
                    LTE = _lte(b, K, kappa, theta_a, b * (K + np.abs(kappa)))
                    Y[p, :] = np.abs(LTE) ** 2 * Dml * Sqq * Amp
                Spp[i, :, j, g] = Spp[i, :, j, g] + np.trapezoid(Y, phi_list, axis=0)
            Spp[:, :, st, g] = Spp[:, :, st, g] + Spp[:, :, j, g]
    return Spp[:, ::-1, :, :].copy()


def BPRI_amiet(geom, flow, opt, lists, model="BRWI"):
    """BRWI with the simplified formulation is not available."""
    raise SolverError("rotor-wake interaction noise is computed with the full formulation only "
                      "(set the formulation to 'full')")
