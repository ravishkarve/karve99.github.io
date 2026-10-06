"""Solver inputs: geometry and conditions, boundary-layer and wake tables, strip
discretisation, velocity triangles, observer and frequency lists.

Internally the solver works with ``geom``, ``flow``, ``bl``, ``lists`` and ``opt``
namespaces; arrays are indexed ``[strip, rotor, azimuth]`` (e.g. ``flow.Ux[j, rot, p]``).
Use :mod:`bbn.config` to build these from the three input sections.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

from .numerics import interp1, interp_idx, linspace_end, logspace_end

__all__ = ["read_bl", "read_bl_file", "preprocess", "inputs", "BL_COLUMNS", "read_bl_ingestion", "SolverError"]

# columns of a boundary-layer table (one row per strip)
BL_COLUMNS = ["R", "delta", "delta_star", "theta", "unused", "tau_max", "dpdx", "rho_wall", "U_inf", "Pi",
              "nu_wall", "tau_wall", "discard"]
_BL_FIELDS = {"d": 1, "d_star": 2, "mom_th": 3, "taumax": 5, "dpdx": 6, "rhow": 7, "uinf": 8, "pi": 9,
              "nuw": 10, "tauwall": 11, "discard": 12}

NU = 1.46e-5                                     # kinematic viscosity of air [m^2/s]
WAKE_P = np.array([0.3199563, 0.009744477, -1.401561e-4, 1.012495e-6, -4.331075e-9,
                   1.156742e-11, -1.949208e-14, 2.014538e-17, -1.166189e-20, 2.895878e-24])


class SolverError(RuntimeError):
    """An input or option combination the solver does not support."""


# ---------------------------------------------------------------------------
# file readers
# ---------------------------------------------------------------------------

def _read_table(text):
    """One header line, then whitespace- or comma-separated numbers."""
    rows = []
    for line in text.splitlines()[1:]:
        s = line.strip()
        if not s:
            continue
        rows.append([float(v) for v in s.replace(",", " ").split()])
    width = max(len(r) for r in rows)
    return np.array([r + [np.nan] * (width - len(r)) for r in rows], float)


def read_bl_file(source):
    """One boundary-layer table (path or text) -> dict of 1-D arrays by field name."""
    text = Path(source).read_text() if (isinstance(source, (str, Path)) and "\n" not in str(source)
                                        and os.path.exists(str(source))) else str(source)
    tab = _read_table(text)
    if tab.shape[1] < 13:
        raise ValueError(f"a boundary-layer file needs 13 columns ({', '.join(BL_COLUMNS)}); "
                         f"found {tab.shape[1]}")
    out = {k: tab[:, c].copy() for k, c in _BL_FIELDS.items()}
    out["R"] = tab[:, 0].copy()
    return out


def read_bl(files, stage_count):
    """Tables [front top, front bottom, (rear top, rear bottom)] -> dict of (stage, n) arrays."""
    need = 2 * stage_count
    if len(files) < need:
        raise ValueError(f"{need} boundary-layer files are needed (top and bottom of each rotor)")
    bl = {}
    for rot in range(stage_count):
        for side, src in (("t", files[2 * rot]), ("b", files[2 * rot + 1])):
            d = src if isinstance(src, dict) else read_bl_file(src)
            for k in _BL_FIELDS:
                bl.setdefault(f"{k}_{side}", []).append(d[k])
    return {k: np.array(v, float) for k, v in bl.items()}


def _as_dict(s):
    return dict(s) if isinstance(s, dict) else {f: getattr(s, f) for f in s._fieldnames}


def read_bl_ingestion(source):
    """BL-ingestion turbulence table: z, ua, la, ut, lt (one header line)."""
    text = Path(source).read_text() if os.path.exists(str(source)) else str(source)
    tab = _read_table(text)
    return {"bl_wnd": tab[:, 0], "bl_ua": tab[:, 1], "bl_la": tab[:, 2], "bl_ut": tab[:, 3], "bl_lt": tab[:, 4]}


# ---------------------------------------------------------------------------
# gather the inputs
# ---------------------------------------------------------------------------

def preprocess(opt, case_data, bl_data=None, wake_data=None):
    """Gather geometry/conditions (``case_data = {"geom": ..., "cond": ...}``), the
    boundary-layer tables (``bl_data``: list of four tables or a dict of arrays) and the
    wake table (``wake_data``: bw, wrms_bg, wrms_wake, L_bg, L_wake per strip)."""
    opt = dict(opt)
    if opt.get("uniform_inflow", True):
        opt.update(bpv=0, wpv=0, vpv=0, eoffset=0)
    if opt.get("amiet") and opt.get("noise_type") == "BRTE":
        opt["chapman"] = True
    geom = _as_dict(case_data["geom"])
    cond = _as_dict(case_data["cond"])
    bl = {}
    ntype = opt.get("noise_type", "BRTE")
    if ntype in ("BRTE", "BOTH") and opt.get("rotor_noise", True):
        if bl_data is None:
            raise SolverError("trailing-edge noise needs boundary-layer tables (top and bottom of each rotor)")
        if isinstance(bl_data, (list, tuple)):
            bl_data = read_bl(bl_data, int(opt["StageCount"]))
        bl.update(bl_data)
    bl.update(bw=0, wrms_wake=0, wrms_bg=0, L_wake=0, L_bg=0)
    if ntype in ("BRWI", "BOTH") and opt.get("rotor_noise", True):
        if wake_data is None:
            raise SolverError("interaction noise needs the wake table (bw, wrms_bg, wrms_wake, L_bg, L_wake)")
        bl.update({k: np.atleast_1d(np.asarray(v, float)) for k, v in wake_data.items()})
    if int(opt["StageCount"]) == 1:
        cond["Omega2"] = 0
        geom["r2"] = np.zeros(np.shape(geom["r1"]))
        geom["eta"] = np.zeros(np.shape(geom["r1"]))
        geom["c2"] = np.zeros(np.shape(geom["c1"]))
        geom["alpha2"] = np.zeros(np.shape(geom["alpha1"]))
        geom["s2"] = np.zeros(np.shape(geom["s1"]))
        cond["AoA2"] = np.zeros(np.shape(cond["AoA1"]))
        cond["Ux2"] = np.zeros(np.shape(cond.get("Ux1", np.zeros(1))))
    cond["theta"] = np.atleast_1d(np.asarray(opt["theta"], float))
    return NS(opt=opt, geom=geom, cond=cond, bl=bl, extra={})


# ---------------------------------------------------------------------------
# strips, velocities, observers and frequencies
# ---------------------------------------------------------------------------

def _f(x):
    return np.atleast_1d(np.asarray(x, float)).ravel()


def inputs(pre):
    """Strip discretisation, velocities, wake and BL data, observer and frequency lists."""
    opt = dict(pre.opt)
    ig, ic, ibl = pre.geom, pre.cond, pre.bl
    lists = NS()
    if opt.get("axial_velocity_tables"):
        opt["contraction_perc"] = 100
    elif not opt.get("uniform_inflow", True):
        raise SolverError("non-uniform inflow needs axial-velocity tables")
    if opt.get("uniform_inflow", True) or not opt.get("amiet"):
        opt["phi_obs_num"] = 1
    if not opt.get("amiet"):
        opt["phi_num"] = 1
    lists.phi_list = linspace_end(0, 2 * np.pi, opt["phi_num"])
    if not opt.get("rotor_noise", True):
        return None, None, opt, None, None
    st = int(opt["st_num"])
    if int(opt["StageCount"]) == 1:
        if opt["noise_type"] == "BRWI":
            raise SolverError("interaction noise needs two rotors")
        opt["noise_type"] = "BRTE"
        opt["contraction_perc"] = 100
    ntype = opt["noise_type"]
    nphi = lists.phi_list.size
    geom = NS()
    flow = NS()
    geom.r0 = float(opt["r0"])
    lists.scale = float(np.ravel(ig.get("scale", 1))[0])
    geom.B = np.array([float(np.ravel(ig["B1"])[0]), float(np.ravel(ig["B2"])[0])])
    geom.OM = np.array([float(np.ravel(ic["Omega1"])[0]), float(np.ravel(ic["Omega2"])[0])])
    r1, r2 = _f(ig["r1"]), _f(ig["r2"])
    geom.drj = np.array([(r1[-1] - r1[0]) / st, (r2[-1] - r2[0]) / st])
    geom.eta = ig.get("eta")
    flow.MX = float(np.ravel(ic["Mx"])[0])
    flow.c0 = float(np.ravel(ic["c0"])[0])
    flow.rho = float(np.ravel(ic["rho"])[0])
    flow.nu = NU
    flow.kr = 0.0
    pos = lambda arr, j: interp_idx(arr, 1 + (j + 0.5) * (arr.size - 1) / st)   # noqa: E731
    c1, c2 = _f(ig["c1"]), _f(ig["c2"])
    a1, a2 = _f(ig["alpha1"]), _f(ig["alpha2"])
    s1, s2 = _f(ig["s1"]), _f(ig["s2"])
    aoa1, aoa2 = _f(ic["AoA1"]), _f(ic["AoA2"])
    geom.rj = np.zeros((st, 2))
    geom.C = np.zeros((st, 2))
    geom.alpha = np.zeros((st, 2))
    geom.S = np.zeros((st, 2))
    geom.alfa = np.zeros((st, 2))
    flow.Ux = np.zeros((st, 2, nphi))
    for j in range(st):
        geom.rj[j] = pos(r1, j), pos(r2, j)
        geom.C[j] = pos(c1, j), pos(c2, j)
        geom.alpha[j] = pos(a1, j), pos(a2, j)
        geom.S[j] = pos(s1, j), pos(s2, j)
        geom.alfa[j] = pos(aoa1, j) / np.pi * 180, pos(aoa2, j) / np.pi * 180
        if not opt.get("axial_velocity_tables"):
            flow.Ux[j, 0, :] = np.sqrt((geom.OM[0] * geom.rj[j, 0]) ** 2 + (flow.MX * flow.c0) ** 2)
        else:
            u = pos(_f(ic["Ux1"]), j)
            for p in range(nphi):
                flow.Ux[j, 0, p] = u if opt.get("uniform_inflow", True) else \
                    u * (1 + opt["vpv"] * np.sin(lists.phi_list[p] + opt["eoffset"]))
    geom.C2 = geom.C[:, 1].copy()
    geom.alpha1 = geom.alpha[:, 0].copy()
    geom.alpha2 = geom.alpha[:, 1].copy()
    flow.U_X2 = np.zeros((st, nphi))
    if int(opt["StageCount"]) == 2:
        cd = np.asarray(ic["Cd"], float)
        cd_row = cd[0] if cd.ndim == 2 else cd.ravel()
        cp = float(opt.get("contraction_perc", 100))
        if cp == 100:
            flow.Cd = np.array([pos(cd_row, j) for j in range(st)])
            for j in range(st):
                if not opt.get("axial_velocity_tables"):
                    flow.Ux[j, 1, :] = ((geom.rj[j, 0] * geom.OM[0] + geom.rj[j, 1] * geom.OM[1])
                                        * np.cos(geom.alpha[j, 0]) / np.sin(geom.alpha[j, 0] + geom.alpha[j, 1]))
                else:
                    u = pos(_f(ic["Ux2"]), j)
                    for p in range(nphi):
                        flow.Ux[j, 1, p] = u if opt.get("uniform_inflow", True) else \
                            u * (1 + opt["vpv"] * np.sin(lists.phi_list[p] + opt["eoffset"]))
                flow.U_X2[j, :] = flow.Ux[j, 1, :]
        elif cp == 0:
            flow.Cd = interp1(r1, cd_row, geom.rj[:, 1])
            alpha_temp = interp1(r1, a1, geom.rj[:, 1])
            for j in range(st):
                # first azimuth only
                flow.Ux[j, 1, 0] = (geom.rj[j, 1] * (geom.OM[0] + geom.OM[1]) * np.cos(geom.alpha[j, 0])
                                    / np.sin(alpha_temp[j] + geom.alpha[j, 1]))
                flow.U_X2[j, :] = flow.Ux[j, 1, :]
        else:
            raise SolverError("stream-tube contraction must be 0 % or 100 %")
        if ntype in ("BRWI", "BOTH"):
            _wake(opt, geom, flow, ibl, lists, st, nphi)
    # case-specific parameters
    if ntype in ("BRWI", "BOTH"):
        flow.Mw = flow.U_X2 / flow.c0
        flow.betaw = np.sqrt(1 - flow.Mw ** 2)
    geom.b = np.zeros((st, 2))
    if ntype in ("BRTE", "BOTH"):
        flow.Uc = 0.8 * flow.Ux
        flow.Mc = flow.Uc / flow.c0
        flow.Mx = flow.Ux / flow.c0
        flow.beta_x = np.sqrt(1 - flow.Mx ** 2)
        geom.b[:, 0] = geom.C[:, 0] / 2
        if int(opt["StageCount"]) == 2:
            geom.b[:, 1] = geom.C[:, 1] / 2
    if ntype == "BRWI":
        geom.b[:, 1] = geom.C2 / 2
    if ntype == "BOTH":
        geom.b[:, 1] = geom.C[:, 1] / 2
    bl = None
    if ntype in ("BRTE", "BOTH"):
        bl = _bl_tables(opt, ibl, lists, st)
    # observer angles and frequencies
    lists.theta = np.pi - np.atleast_1d(np.asarray(pre.cond["theta"], float))
    if not opt.get("spectral_study", True):
        lists.omega = logspace_end(np.log10(opt["f_d"] * 2 * np.pi), np.log10(opt["f_d"] * 2 * np.pi), 1) * lists.scale
        lists.offset_list = linspace_end(0, 2 * np.pi, opt["phi_obs_num"])
    else:
        lists.omega = logspace_end(np.log10(opt["f_l"] * 2 * np.pi), np.log10(opt["f_h"] * 2 * np.pi),
                                opt["f_num"]) * lists.scale
        if not opt.get("uniform_inflow", True):
            lists.offset_list = np.atleast_1d(np.asarray(opt["spectral_phi_obs"], float))
            opt["phi_obs_num"] = lists.offset_list.size
        else:
            lists.offset_list = np.array([0.0])
            opt["phi_obs_num"] = 1
    beta_theta = np.sqrt(1 - flow.MX ** 2 * np.sin(lists.theta) ** 2)
    flow.Mx_eff = 1.0
    flow.betax_mf2 = 1 - flow.MX ** 2
    if opt.get("chapman"):
        geom.r0_hat = geom.r0 / flow.betax_mf2 * beta_theta
        lists.theta_hat = np.arccos(np.cos(lists.theta) / beta_theta)
    else:
        flow.Mx_eff = beta_theta if not opt.get("emission_angle") else 1 + flow.MX * np.cos(lists.theta)
    return geom, flow, opt, bl, lists


def _wake(opt, geom, flow, ibl, lists, st, nphi):
    flow.L_wake = np.zeros((st, nphi))
    flow.wrms2_wake = np.zeros((st, nphi))
    flow.L_bg = np.zeros((st, nphi))
    flow.wrms2_bg = np.zeros((st, nphi))
    bw = np.atleast_1d(np.asarray(ibl.get("bw", 0), float))
    if bw[0] == 0:
        return
    flow.bw_engine = np.zeros((st, nphi))
    Lw = np.atleast_1d(np.asarray(ibl["L_wake"], float))
    Lb = np.atleast_1d(np.asarray(ibl["L_bg"], float))
    ww = np.atleast_1d(np.asarray(ibl["wrms_wake"], float))
    wb = np.atleast_1d(np.asarray(ibl["wrms_bg"], float))
    Lopt = opt.get("L", 0.4)
    bg_set = True
    for j in range(st):
        for p in range(nphi):
            flow.bw_engine[j, p] = bw[j] / lists.scale
            if Lopt == "BW":
                flow.L_wake[j, p] = 0.42 * flow.bw_engine[j, p]
                bg_set = False
            elif Lopt == "Pope":
                re_l = np.sqrt(20 / 3 * Lw[j] * ww[j] ** 0.5 / flow.nu)
                coeff = 0.43 + 14.0 / re_l ** 1.05
                flow.L_wake[j, p] = coeff * Lw[j] / lists.scale
                flow.L_bg[j, p] = coeff * Lb[j] / lists.scale
            else:
                flow.L_wake[j, p] = float(Lopt) * Lw[j] / lists.scale
                flow.L_bg[j, p] = float(Lopt) * Lb[j] / lists.scale
            flow.wrms2_wake[j, p] = ww[j] ** 2
            flow.wrms2_bg[j, p] = wb[j] ** 2
    flow.L_bg_defined = bg_set
    if not opt.get("uniform_inflow", True):
        for p in range(nphi):
            fac = 1 + opt["wpv"] * np.sin(lists.phi_list[p] + opt["eoffset"])
            flow.L_wake[:, p] *= fac
            flow.bw_engine[:, p] *= fac
            flow.wrms2_wake[:, p] *= fac


_BL_KEYS = ("d_star", "d", "mom_th", "dpdx", "taumax", "tauwall", "rhow", "pi", "uinf", "nuw")


def _bl_tables(opt, ibl, lists, st):
    sc = int(opt["StageCount"])
    nphi = int(opt["phi_num"])
    bl = NS()
    for k in _BL_KEYS:
        for side in ("t", "b"):
            src = np.asarray(ibl[f"{k}_{side}"], float)
            src = src.reshape(src.shape[0], -1) if src.ndim > 1 else src.reshape(1, -1)
            if src.shape[1] < st:
                raise SolverError(f"the boundary-layer tables have {src.shape[1]} rows; one per strip is needed "
                               f"(st_num = {st})")
            arr = np.zeros((sc, st, nphi))
            for p in range(nphi):
                temp = 1 + opt.get("bpv", 0) * np.sin(lists.phi_list[p] + opt.get("eoffset", 0))
                arr[:, :, p] = src[:sc, :st] * temp
            setattr(bl, f"{k}_{side}", arr)
    disc_t = np.asarray(ibl["discard_t"], float).reshape(sc, -1)[:, :st]
    disc_b = np.asarray(ibl["discard_b"], float).reshape(sc, -1)[:, :st]
    bl.discard_t, bl.discard_b = disc_t.copy(), disc_b.copy()
    bad = opt.get("baddata", "IGNORE")
    if bad == "REPLACE":
        half = st // 2
        for s in range(sc):
            for j in list(range(half, st)) + list(range(half - 1, -1, -1)):
                if disc_b[s, j] + disc_t[s, j] > 0:
                    src = j - 1 if j >= half else j + 1
                    for k in _BL_KEYS:
                        for side in ("t", "b"):
                            a = getattr(bl, f"{k}_{side}")
                            a[s, j, :] = a[s, src, :]
    return bl
