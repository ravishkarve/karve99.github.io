"""Installation noise: boundary-layer ingestion with a hard wall (BPRI_BL).

Ports inputs_pylon.m (BPRI_BL branch), BPRI_amiet_hard_wall.m,
correlatd_velspec.m and acoustic_lift.m.  MATLAB's ``/`` between two row
vectors is a least-squares division returning a scalar; ``mdiv`` reproduces it
wherever an operand can depend on the observer angle.
"""
from __future__ import annotations

import math
from types import SimpleNamespace as NS

import numpy as np
from scipy.special import hankel2, jv

from .inputs import MCodeError, NU, interp_idx, mlinspace, mlogspace, read_bl_ingestion
from .mlab import csqrt, erfz, interp1

__all__ = ["run_installation", "inputs_pylon_bl", "BPRI_amiet_hard_wall"]

I1 = 1j
_KE_FAC = math.gamma(5 / 6) / math.gamma(1 / 3)


def mdiv(a, b):
    """MATLAB ``a / b``: elementwise for a scalar ``b``; least squares (scalar) for row vectors."""
    a = np.asarray(a)
    b = np.asarray(b)
    if b.size == 1:
        return a / b.ravel()[0]
    if a.size == 1:
        raise MCodeError("The MATLAB code stops here (scalar / vector in MATLAB: dimensions do not agree)")
    a = np.broadcast_to(a, b.shape)
    return np.sum(a * np.conj(b)) / np.sum(b * np.conj(b))


def _all(cond):
    return bool(np.all(np.asarray(cond)))


def inputs_pylon_bl(pre, base_dir=".", bl_ingestion=None):
    """inputs_pylon.m, BPRI_BL branch: rotor 1 seen as the 'rear' blade row of a pylon case."""
    opt = dict(pre.opt)
    ig, ic = pre.geom, pre.cond
    opt["uniform_inflow"] = True
    flow = NS()
    if opt.get("bondary_layer_input_from_file"):
        src = bl_ingestion if bl_ingestion is not None else str(_join(base_dir, opt["boundary_layer_input_filepath"]))
        t = read_bl_ingestion(src) if not isinstance(src, dict) else src
        flow.bl_wnd, flow.bl_ua, flow.bl_la, flow.bl_ut, flow.bl_lt = (np.asarray(t[k], float) for k in
                                                                      ("bl_wnd", "bl_ua", "bl_la", "bl_ut", "bl_lt"))
    lists = NS()
    geom = NS()
    st = int(opt["st_num"])
    lists.scale = float(np.ravel(ig.get("scale", 1))[0])
    geom.r0 = float(opt["r0"])
    geom.B = np.array([1.0, float(np.ravel(ig["B1"])[0])])
    geom.OM = np.array([0.0, float(np.ravel(ic["Omega1"])[0])])
    r1 = np.ravel(np.asarray(ig["r1"], float))
    d = (r1[-1] - r1[0]) / st
    geom.drj = np.array([d, d])
    flow.MX = float(np.ravel(ic["Mx"])[0])
    flow.c0 = float(np.ravel(ic["c0"])[0])
    flow.rho = float(np.ravel(ic["rho"])[0])
    flow.nu = NU
    flow.kr = 0.0
    c1 = np.ravel(np.asarray(ig["c1"], float))
    a1 = np.ravel(np.asarray(ig["alpha1"], float))
    geom.rj = np.zeros((st, 2))
    geom.C = np.zeros((st, 2))
    geom.alpha = np.zeros((st, 2))
    pos = lambda arr, j: interp_idx(arr, 1 + j * (arr.size - 1) / st + (arr.size - 1) / st / 2)  # noqa: E731
    for j in range(st):
        geom.rj[j] = pos(r1, j), pos(r1, j)
        geom.C[j] = float(np.ravel(ig["c_pylon"])[0]), pos(c1, j)
        geom.alpha[j] = 0.0, pos(a1, j)
    geom.alpha1 = geom.alpha[:, 0].copy()
    geom.alpha2 = geom.alpha[:, 1].copy()
    geom.b = geom.C / 2
    th = np.atleast_1d(np.asarray(opt["theta"], float))
    lists.theta = th
    if not opt.get("spectral_study", True):
        raise MCodeError("Boundary layer ingestion currently does not compute azimuthal directivity. "
                       "A list of thetas can be specified to determine axial directivity")
    lists.omega = mlogspace(np.log10(opt["f_l"] * 2 * np.pi), np.log10(opt["f_h"] * 2 * np.pi), opt["f_num"]) * lists.scale
    lists.offset_list = np.atleast_1d(np.asarray(opt.get("spectral_phi_obs", [0]), float))
    opt["phi_obs_num"] = lists.offset_list.size
    return NS(geom=geom, flow=flow, opt=opt, lists=lists)


def _join(base, p):
    from pathlib import Path
    q = Path(p)
    return q if q.is_absolute() else Path(base) / q


def acoustic_lift(muain, Mwin, betawin, muh, muaMw, k_mn, cosXa):
    A = np.sqrt(1 - Mwin ** 2 * np.asarray(cosXa) ** 2)
    p1 = np.pi / (4 * (1 - mdiv(cosXa, A)))
    if _all(np.asarray(muain) < np.pi / 4):
        fmx = (1 - betawin) * math.log(Mwin) + betawin * math.log(1 + betawin) - math.log(2)
        f11 = np.exp(I1 * muh * fmx)
        S1 = 2.0 / np.pi / muh / (hankel2(0, muh) - I1 * hankel2(1, muh))
        return 1.0 / betawin * S1 * f11 * (jv(0, muaMw - k_mn) - I1 * jv(1, muaMw - k_mn))
    tet1 = muain - muaMw + k_mn
    tet1b = np.abs(muain - muaMw) + np.abs(k_mn)
    tet2 = betawin ** 2 * muh + k_mn - np.pi / 4
    tet3 = muain + muaMw - k_mn
    tempi1 = np.exp(I1 * tet2) / np.pi
    tempi2 = 2 * I1 * tet1
    tempi3 = muh * (1 + Mwin)
    L1 = erfz(csqrt(tempi2)) * tempi1 / betawin / csqrt(I1 * tempi3 * tet1b)
    if _all((np.asarray(muain) >= np.pi / 4) & (np.asarray(muain) <= np.real(p1))):
        return L1
    L2 = I1 * tempi1 / tet1b / betawin / csqrt(2 * np.pi * tempi3) * \
        (1 - erfz(2 * abs(betawin) * csqrt(I1 * muain)) - np.exp(-tempi2) * (1 - csqrt(2 * muain / tet3) * erfz(csqrt(2 * I1 * tet3))))
    return L1 + L2


_N = np.arange(-100, 101, dtype=float)


def correlated_velspec(U_X2, K_phi, om_phi, L, la, lt, ua, ut, M_phi2, flow, opt, geom, cosXa, sinXa, r0,
                       XX, XXd, YY, YYd, sigma, sigmad, ke, sinalf2, cosalf2, phi, pm, MX, cterm):
    c0 = flow.c0
    if not opt.get("BPRI_correlation"):
        if opt.get("Karman_spec", True):
            k2 = (K_phi / ke) ** 2
            return k2 / ((1 + k2) ** (7 / 3))
        k2 = K_phi
        kxx = k2 * cosalf2
        kzz = k2 * sinalf2 * math.cos(phi)
        zz = np.sqrt(1 + la ** 2 * kxx ** 2 + lt ** 2 * kzz ** 2)
        t1 = 2 * (ut / ua) ** 2 - (lt / la) ** 2
        p11 = mdiv(3 * la * lt * ua ** 5, 4 * np.pi * zz ** 5) * (zz ** 2 + lt ** 2 * kzz ** 2)
        p22 = mdiv(3 * la * lt ** 3 * ua ** 5, 4 * np.pi * zz ** 5) * (kxx ** 2 + kzz ** 2 * t1)
        return -p11 * sinalf2 + p22 * cosalf2 * math.cos(phi)
    k1 = K_phi
    aniso = opt.get("aniso_spec", "Liep")
    if opt.get("Karman_spec", True) or aniso == "Liep":
        vt = -M_phi2 * c0
        vz = flow.MX * c0 if opt.get("Karman_spec", True) else MX * c0
        t0 = 2 * np.pi / (pm * geom.OM[1] * geom.B[1])
        t1 = t0 * vt ** 2 / (vt ** 2 + vz ** 2)
        Mb = U_X2 / c0
        zbig = t0 * vt * vz / math.sqrt(vt ** 2 + vz ** 2)
        if cterm == "nowall":
            dtau = mdiv(-zbig * YY, c0 * sigma)
        elif cterm == "wall":
            dtau = mdiv(-zbig * YYd, c0 * sigmad)
        elif cterm == "c1":
            dtau = (Mb * (XX - XXd) + (sigmad - sigma)) / ((1 - Mb ** 2) * c0) - mdiv(zbig * YY, c0 * sigma)
        elif cterm == "c2":
            dtau = (Mb * (XXd - XX) + (sigma - sigmad)) / ((1 - Mb ** 2) * c0) - mdiv(zbig * YYd, c0 * sigmad)
        else:
            raise MCodeError("warning from correlated velspec")
        t2 = t1 + dtau
        # sum over n = -100..100 (vectorised; n is the leading axis)
        k2 = (np.asarray(om_phi * t2)[None, ...] + 2 * np.pi * _N.reshape((-1,) + (1,) * np.ndim(om_phi * t2))) / zbig
        kxx = k1 * cosalf2 - k2 * sinalf2
        kyy = k1 * sinalf2 * math.cos(phi) + k2 * cosalf2 * math.cos(phi)
        kzz = k1 * sinalf2 * math.sin(phi) + k2 * cosalf2 * math.sin(phi)
        if opt.get("Karman_spec", True):
            den = (1 + (kxx / ke) ** 2 + (kyy / ke) ** 2 + (kzz / ke) ** 2) ** (-17 / 6)
            p11 = (kyy ** 2 + kzz ** 2) * den
            p22 = (kxx ** 2 + kzz ** 2) * den
            p33 = (kxx ** 2 + kyy ** 2) * den
        else:
            kt = np.sqrt(kyy ** 2 + kzz ** 2)
            ziso = 1 + la ** 2 * kxx ** 2 + lt ** 2 * kt ** 2
            F = (2 * la * lt ** 4 * ua ** 2) / (np.pi ** 2 * ziso ** 3)
            G = (2 * (ut ** 2 / ua ** 2) - (lt ** 2 / la ** 2) - 1) * F
            p11 = (kyy ** 2 + kzz ** 2) * F
            p22 = F * (kxx ** 2 + kzz ** 2) + G * kzz ** 2
            p33 = F * (kxx ** 2 + kyy ** 2) + G * kyy ** 2
        Fi = np.sum(-p11 * sinalf2 + p22 * cosalf2 * math.cos(phi) + p33 * cosalf2 * math.sin(phi), axis=0)
        return Fi * 2 * np.pi / zbig
    # modified isotropic von Karman spectrum ("slowed-down eddy")
    alpha = float(opt["aniso_alpha"])
    k1 = alpha * K_phi
    vt = M_phi2 * c0
    vz = flow.MX * c0
    t0 = 2 * np.pi / (pm * geom.OM[1] * geom.B[1])
    t1 = t0 * vt ** 2 / (vt ** 2 + vz ** 2)
    Mb = U_X2 / c0
    dtau = (t0 - t1) * vt * (Mb - mdiv(r0 * cosXa, sigma)) / ((1 - Mb ** 2) * c0)
    t2 = t1 + dtau
    zbig = t0 * vt * vz / math.sqrt(vt ** 2 + vz ** 2)
    k2 = (np.asarray(om_phi * t2)[None, ...] + 2 * np.pi * _N.reshape((-1,) + (1,) * np.ndim(om_phi * t2))) / zbig
    Fi = np.sum(k1 ** 2 * (1 + (k1 / ke) ** 2 + (k2 / ke) ** 2) ** (-17 / 6), axis=0)
    return alpha * Fi * 2 * np.pi / zbig


def BPRI_amiet_hard_wall(geom, flow, opt, lists, progress=None):
    """BPRI_amiet_hard_wall.m -> (Spp, SppNW, SppC1, SppC2, SppA) in the MATLAB code's layout."""
    if opt.get("emission_angle"):
        raise MCodeError("Sorry, this BPRI formulation is not written for emission co-ordinate output")
    thetas = np.atleast_1d(np.asarray(opt["theta"], float))
    r0 = float(opt["r0"])
    c0 = 350.0                                          # hard-coded in the MATLAB code
    MX = flow.MX
    U_mean = MX * c0
    sinXa, cosXa = np.sin(thetas), np.cos(thetas)
    nth = thetas.size
    omega = np.asarray(lists.omega, float)
    st = int(opt["st_num"])
    nobs = lists.offset_list.size
    shape = (omega.size, np.asarray(lists.theta).size, st + 1, nobs)
    out = {k: np.zeros(shape, dtype=complex) for k in ("Spp", "NW", "C1", "C2", "A")}
    phi_list = mlinspace(0, 2 * np.pi, opt["phi_num"])
    fl = NS(**vars(flow))
    fl.c0 = c0
    dwall = float(opt["dwall"])
    del_ = float(opt["bl_height"])
    B2, OM2 = geom.B[1], geom.OM[1]
    for j in range(st):
        if progress:
            progress(f"Computing BPRI observer 1, strip {j + 1}")
        sinalf2, cosalf2 = math.sin(geom.alpha2[j]), math.cos(geom.alpha2[j])
        r = geom.rj[j, -1]
        b = geom.b[j, -1]
        for i, om in enumerate(omega):
            Y = {k: np.zeros((phi_list.size, nth), dtype=complex) for k in ("Y", "C1", "C2", "A")}
            for p, phi in enumerate(phi_list):
                zzc = dwall + r * math.cos(phi)
                beta = math.sqrt(1 - MX ** 2)
                M_phi2 = r * OM2 / c0
                k0 = om / c0
                U_X2 = math.sqrt((M_phi2 * c0) ** 2 + (MX * c0) ** 2)
                M_X2 = U_X2 / c0
                if opt.get("bondary_layer_input_from_file"):
                    ua = interp1(fl.bl_wnd, fl.bl_ua, zzc)
                    la = interp1(fl.bl_wnd, fl.bl_la, zzc)
                    ut = interp1(fl.bl_wnd, fl.bl_ut, zzc)
                    lt = interp1(fl.bl_wnd, fl.bl_lt, zzc)
                    L, wrms2 = la, ua
                    if any(math.isnan(v) for v in (ua, la, ut, lt)):
                        ua = la = ut = lt = L = -999.0
                        wrms2 = 1.0
                else:
                    la, lt, ua, ut = (float(opt[k]) for k in ("la", "lt", "ua", "ut"))
                    L, wrms2 = la, float(opt["ua"])
                # acos may be complex (|arg| > 1); MATLAB's relational operators then use the real part
                ang = float(np.real(np.arccos(complex((dwall - del_) / r))))
                span_c = abs((dwall - del_) / (math.cos(np.pi - phi) if phi > np.pi else math.cos(np.pi + phi)))
                if opt.get("partial_loading"):
                    fm = 0.0
                    if (np.pi - ang) < phi < (np.pi + ang) and abs(r * math.cos(phi)) > span_c:
                        fm = 1.0
                else:
                    fm = 1.0
                ke = (math.sqrt(math.pi) / L) * _KE_FAC
                if opt.get("Karman_spec", True):
                    coe = 4 / 9 / math.pi * wrms2 / (ke * ke) if not opt.get("BPRI_correlation") else \
                        55 / (36 * math.pi ** 1.5) * _KE_FAC * wrms2 / ke ** 5
                else:
                    coe = 1.0 if opt.get("aniso_spec", "Liep") == "Liep" else \
                        55 / (36 * math.pi ** 1.5) * _KE_FAC * wrms2 / ke ** 5
                re = r0 * (np.sqrt(1 - MX ** 2 * sinXa ** 2) - MX * cosXa) / beta ** 2
                xtemp = r0 * cosXa
                ytemp = re * M_phi2 * math.cos(phi)
                ztemp = r0 * sinXa + re * M_phi2 * math.sin(phi)
                XX = xtemp * cosalf2 + sinalf2 * (ytemp * math.cos(phi) + ztemp * math.sin(phi))
                YY = -xtemp * sinalf2 + cosalf2 * (ytemp * math.cos(phi) + ztemp * math.sin(phi))
                ZZ = -ytemp * math.sin(phi) + ztemp * math.cos(phi)
                sigma = np.sqrt(XX ** 2 + beta ** 2 * (YY ** 2 + ZZ ** 2))
                r0_d = np.sqrt((r0 * sinXa + 2 * dwall) ** 2 + (r0 * cosXa) ** 2)
                theta_d = np.arctan2(r0 * sinXa + 2 * dwall, r0 * cosXa)
                sinXa_d, cosXa_d = np.sin(theta_d), np.cos(theta_d)
                re_d = r0_d * (np.sqrt(1 - MX ** 2 * sinXa ** 2) - MX * cosXa) / beta ** 2
                phi_d = phi
                xtempd = r0 * cosXa
                ytempd = -re_d * M_phi2 * math.cos(phi_d)
                ztempd = -(r0 * sinXa + 2 * dwall) - re_d * M_phi2 * math.sin(phi_d)
                XXd = xtempd * cosalf2 + sinalf2 * (ytempd * math.cos(phi_d) + ztempd * math.sin(phi_d))
                YYd = -xtempd * sinalf2 + cosalf2 * (ytempd * math.cos(phi_d) + ztempd * math.sin(phi_d))
                ZZd = -ytempd * math.sin(phi_d) + ztempd * math.cos(phi_d)
                sigmad = np.sqrt(XXd ** 2 + beta ** 2 * (YYd ** 2 + ZZd ** 2))
                if opt.get("chapman"):
                    raise MCodeError("The MATLAB code stops here: om_phi_d is undefined with chapman = true in "
                                   "BPRI_amiet_hard_wall.m")
                ratio_om = (1 + M_phi2 * (sinXa * math.sin(phi))) / np.sqrt(1 - MX ** 2 * sinXa ** 2)
                om_phi = om * ratio_om
                ratio_om_d = 1 + M_phi2 * ((r0 * sinXa + 2 * dwall) * math.sin(phi)) / (r0 * np.sqrt(1 - MX ** 2 * sinXa ** 2))
                om_phi_d = om * ratio_om_d
                Kx_no = om / U_X2
                Kx_mn = om_phi / U_X2
                Kx_mn_d = om_phi_d / U_X2
                Spp_const = (k0 * b * fl.rho) ** 2 * B2 * U_X2 * geom.drj[1] / 4
                K_phi = om_phi / U_X2
                K_phi_d = om_phi_d / U_X2
                Dml = YY ** 2 / sigma ** 4
                Dml_MI = YY * YYd / (sigma ** 2 * sigmad ** 2)
                Dml_d = YYd ** 2 / sigmad ** 4
                k_mn = (k0 / beta ** 2) * (M_X2 - XX / sigma) * b
                k_mn_d = (k0 / beta ** 2) * (M_X2 - XXd / sigmad) * b
                mua_no = M_X2 * Kx_no / beta ** 2
                muh_no = mua_no / M_X2
                muaMw_no = mua_no * M_X2
                mua = M_X2 * Kx_mn / beta ** 2
                muh = mua / M_X2
                muaMw = mua * M_X2
                mua_d = M_X2 * Kx_mn_d / beta ** 2
                muh_d = mua_d / M_X2
                muaMw_d = mua_d * M_X2
                bw = math.sqrt(1 - M_X2 ** 2)
                Lno = acoustic_lift(abs(mua_no * b), M_X2, bw, muh_no * b, muaMw_no * b, k_mn_d, cosXa)
                Lq = acoustic_lift(np.abs(mua) * b, M_X2, bw, muh * b, muaMw * b, k_mn, cosXa)
                Lqd = acoustic_lift(np.abs(mua_d) * b, M_X2, bw, muh_d * b, muaMw_d * b, k_mn_d, cosXa)
                args = (L, la, lt, ua, ut, M_phi2, fl, opt, geom)
                ph = np.exp(I1 * mua_no * (M_X2 * (XX - XXd) + (sigmad - sigma)))
                if opt.get("BPRI_correlation"):
                    F_c1 = correlated_velspec(U_X2, K_phi, om, *args, cosXa, sinXa, r0, XX, XXd, YY, YYd, sigma, sigmad,
                                              ke, sinalf2, cosalf2, phi, 1, MX, "c1")
                    F_c2 = correlated_velspec(U_X2, K_phi, om, *args, cosXa, sinXa, r0, XX, XXd, YY, YYd, sigma, sigmad,
                                              ke, sinalf2, cosalf2, phi_d, 1, MX, "c2")
                    F = correlated_velspec(U_X2, K_phi, om_phi, *args, cosXa, sinXa, r0, XX, XXd, YY, YYd, sigma, sigmad,
                                           ke, sinalf2, cosalf2, phi, 1, MX, "nowall")
                    F_d = correlated_velspec(U_X2, K_phi_d, om_phi_d, *args, cosXa_d, sinXa_d, r0_d, XX, XXd, YY, YYd,
                                             sigma, sigmad, ke, sinalf2, cosalf2, phi_d, 1, MX, "wall")
                    Y["Y"][p] = Spp_const * fm * coe * F * Dml * np.abs(Lq) ** 2
                    if opt.get("wall"):
                        Y["C1"][p] = Spp_const * fm * coe * F_c1 * Dml_MI * ph * np.abs(Lq * np.conj(Lno))
                        Y["C2"][p] = Spp_const * fm * coe * F_c2 * Dml_MI * np.conj(ph) * np.abs(np.conj(Lq) * Lno)
                        Y["A"][p] = Spp_const * fm * coe * F_d * Dml_d * np.abs(Lqd) ** 2
                else:
                    F = correlated_velspec(U_X2, K_phi, om_phi, *args, cosXa, sinXa, r0, XX, XXd, YY, YYd, sigma, sigmad,
                                           ke, sinalf2, cosalf2, phi, 1, MX, "nowall")
                    F_d = correlated_velspec(U_X2, K_phi, om_phi_d, *args, cosXa, sinXa, r0, XX, XXd, YY, YYd, sigma,
                                             sigmad, ke, sinalf2, cosalf2, phi, 1, MX, "nowall")
                    if opt.get("wall"):
                        Y["Y"][p] = Spp_const * Dml * fm * coe * F * Dml * np.abs(Lq) ** 2
                        Y["C1"][p] = Spp_const * Dml_MI * fm * coe * F * Dml_MI * ph * np.abs(Lq * np.conj(Lqd))
                        Y["C2"][p] = Spp_const * Dml_MI * fm * coe * F * Dml_MI * np.conj(ph) * np.abs(np.conj(Lq) * Lqd)
                        Y["A"][p] = Spp_const * fm * coe * F_d * Dml_d * np.abs(Lqd) ** 2
                    else:
                        Y["Y"][p] = Spp_const * fm * coe * F * Dml * np.abs(Lq) ** 2
            tr = lambda a: np.trapezoid(a, phi_list, axis=0)   # noqa: E731
            out["Spp"][i, :, j, 0] = tr(Y["Y"] + Y["C1"] + Y["C2"] + Y["A"])
            out["NW"][i, :, j, 0] = tr(Y["Y"])
            out["C1"][i, :, j, 0] = tr(Y["C1"])
            out["C2"][i, :, j, 0] = tr(Y["C2"])
            out["A"][i, :, j, 0] = tr(Y["A"])
    for k in out:
        out[k][:, :, st, :] = np.sum(out[k][:, :, :st, :], axis=2)
    return out["Spp"], out["NW"], out["C1"], out["C2"], out["A"]


def run_installation(res, pre, base_dir=".", bl_ingestion=None, progress=None):
    o = pre.opt
    ptype = o.get("p_noise_type")
    if ptype != "BPRI_BL":
        raise MCodeError(f"installation noise {ptype!r} is not ported (only the boundary-layer ingestion "
                       "model BPRI_BL of the MATLAB code)")
    if not o.get("amiet"):
        raise MCodeError("Boundary layer ingestion noise source only works with the simplified Amiet model "
                       "(amiet = true)")
    if int(o["StageCount"]) > 1:
        raise MCodeError("Boundary layer ingestion currently coded only for 1 rotor")
    p = inputs_pylon_bl(pre, base_dir, bl_ingestion)
    S, NW, C1, C2, A = BPRI_amiet_hard_wall(p.geom, p.flow, p.opt, p.lists, progress)
    res.Spps.update(BPRI=S, BPRINW=NW, BPRIC1=C1, BPRIC2=C2, BPRIA=A)
    res.p = p
    return res
