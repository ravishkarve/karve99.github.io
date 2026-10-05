"""Post-processing: SPL_calc.m, PWL_calc.m, PWL_plus_bands.m and the data files of pp.m.

Levels are computed exactly as the MATLAB code does it, including the log of complex spectra
(MATLAB's ``log10`` of a complex number; files print the real part).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from .inputs import MCodeError
from .mlab import interp_idx

__all__ = ["SPL_calc", "PWL_plus_bands", "third_octave_bands", "compute_results", "write_outputs",
           "compute_results_pylon", "write_outputs_pylon"]


def _clog10(x):
    return np.log10(np.asarray(x, dtype=complex))


def SPL_calc(Spp, scale):
    """SPL_calc.m: 10 log10(2*2*2*pi Spp / 4e-10) + 10 log10(scale^3)."""
    return 10 * _clog10(2 * 2 * 2 * np.pi * np.asarray(Spp) / (4e-10)) + 10 * math.log10(scale ** 3)


def _power(lists, opt, geom, flow, Spp):
    """Sound power P1[omega, strip] (PWL_calc.m / PWL_plus_bands.m)."""
    MX = flow.MX
    th = np.asarray(lists.theta, float)
    if opt.get("emission_angle"):
        X = np.pi + np.arctan2(-np.sin(th), MX + np.cos(th))
        dist = (np.sin(th) / np.sin(X)) ** 2
    else:
        X = th
        dist = 1.0
    F = (1 - MX ** 2) ** 2 * np.sqrt(1 - MX ** 2 * np.sin(X) ** 2) / \
        (np.sqrt(1 - MX ** 2 * np.sin(X) ** 2) - MX * np.cos(X)) ** 2
    Y = (F * np.sin(X))[None, :, None] * Spp * (dist[None, :, None] if np.ndim(dist) else dist)
    return np.trapezoid(Y, X, axis=1) * 2 * np.pi * geom.r0 ** 2 / flow.rho / flow.c0


def third_octave_bands(lists, opt, P1):
    """third_octave_bands (PWL_plus_bands.m): 21 bands 99 Hz - 10 kHz from a 5000-point resample."""
    nb = 21
    bands = 1000.0 * (2 ** (1 / 3)) ** np.arange(-10, nb - 10) * 2 * np.pi
    bands_l = (1000.0 * (2 ** (1 / 3)) ** np.arange(-10, nb - 10 + 1) * 2 * np.pi) / 2 ** (1 / 6)
    om = np.asarray(lists.omega, float) / lists.scale
    n = om.size
    dr = (n - 1) / 5000
    pos = 1 + np.arange(5000) * dr
    om_int = interp_idx(om, pos)
    P1 = np.asarray(P1)
    P_int = np.stack([interp_idx(P1[:, j].real, pos) + 1j * interp_idx(P1[:, j].imag, pos)
                      for j in range(P1.shape[1])], axis=1)
    out = np.zeros((nb, P1.shape[1]), dtype=complex)
    for ib in range(nb):
        lo = np.nonzero(om_int >= bands_l[ib])[0]
        hi = np.nonzero(om_int >= bands_l[ib + 1])[0]
        if lo.size == 0 or hi.size == 0:
            raise MCodeError("PWL band cannot be computed: The MATLAB code's 1/3-octave bands need computed frequencies "
                           "from about 89 Hz to 11.2 kHz (f_l <= 89 Hz, f_h >= 11.3 kHz)")
        l, h = lo[0], hi[0]
        out[ib] = np.trapezoid(P_int[l:h + 1], om_int[l:h + 1], axis=0)
    return bands, out


def PWL_plus_bands(lists, opt, geom, flow, Spp):
    """PWL_plus_bands.m: PWL[omega, strip], band centres [rad/s] and PWL_thirds[band, strip]."""
    P1 = _power(lists, opt, geom, flow, Spp)
    sc = 10 * math.log10(lists.scale ** 3)
    PWL = 10 * np.log10(np.abs(2 * 2 * np.pi * P1 / 1e-12)) + sc
    try:
        bands, P3 = third_octave_bands(lists, opt, P1)
        PWL3 = 10 * np.log10(np.abs(2 * P3 / 1e-12)) + sc
    except MCodeError:
        bands, PWL3 = None, None
    return PWL, bands, PWL3


def _as4(S):
    S = np.asarray(S)
    return S[..., None] if S.ndim == 3 else S


def _sources(opt):
    nt = opt["noise_type"]
    if nt == "BRWI":
        return ["BRWI"]
    if nt == "BRTE":
        return ["BRTE1"] if int(opt["StageCount"]) == 1 else ["BRTE1", "BRTE2"]
    return ["BRTE1", "BRTE2", "BRWI", "tot"]


def compute_results(res):
    """results structure of pp.m (rotor noise): SPL for directivity studies, PWL (+ thirds) for spectra."""
    opt, lists, geom, flow = res.opt, res.lists, res.geom, res.flow
    out = {"omega": np.asarray(lists.omega), "warnings": []}
    for s in _sources(opt):
        S = _as4(res.Spps[s])
        if not opt.get("spectral_study", True):
            out[f"SPL_{s}"] = SPL_calc(S[..., 0], lists.scale)            # [1, theta, strip]
        else:
            pw, p3 = [], []
            for g in range(S.shape[3]):
                PWL, bands, PWL3 = PWL_plus_bands(lists, opt, geom, flow, S[..., g])
                pw.append(PWL)
                p3.append(PWL3)
            out[f"PWL_{s}"] = np.array(pw)                                  # [obs, omega, strip]
            if all(x is not None for x in p3):
                out[f"PWL_thirds_{s}"] = np.array(p3)
                out["bands"] = bands
            else:
                out["warnings"].append("Warning PWL band cannot be computed. Either the frequency range is too "
                                       "small or only one observer is specified")
    return out


# ---------------------------------------------------------------------------
# data files (pp.m)
# ---------------------------------------------------------------------------

def _matlab_text(text):
    """MATLAB's fprintf prints non-finite values as Inf / -Inf / NaN."""
    return re.sub(r"\b(inf|nan)\b", lambda m: "Inf" if m.group(1) == "inf" else "NaN", text)


def _r(x):
    return float(np.real(x))


def write_outputs(res, folder, results=None):
    """Write the MATLAB code's .dat result files into ``folder``; returns the list of paths."""
    opt, lists, flow = res.opt, res.lists, res.flow
    results = results or compute_results(res)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    st = int(opt["st_num"])
    num1 = st                                # 0-based index of the strip total
    freq = np.asarray(lists.omega) / (2 * np.pi)
    theta1 = np.asarray(lists.theta) / np.pi * 180
    nt = opt["noise_type"]
    written = []

    def w(name, text):
        p = folder / name
        p.write_text(_matlab_text(text))
        written.append(str(p))

    if not opt.get("spectral_study", True):
        if not opt.get("uniform_inflow", True):
            raise MCodeError("azimuthal-directivity output (non-uniform inflow) is not written by this port")
        S = {s: results[f"SPL_{s}"] for s in _sources(opt)}
        if nt == "BRWI":
            w("BRWI_SPL_ax_Directivity.dat", "Theta, BRWI\n" + "".join(
                "%6.2f %12.8f\n" % (theta1[i], _r(S["BRWI"][0, i, num1])) for i in range(theta1.size)))
        elif nt == "BRTE" and int(opt["StageCount"]) == 1:
            w("BRTE_SPL_ax_Directivity.dat", "theta, BRTE1\n" + "".join(
                "%6.2f %12.8f\n" % (theta1[i], _r(S["BRTE1"][0, i, num1])) for i in range(theta1.size)))
        elif nt == "BRTE":
            w("BRTE_SPL_ax_Directivity.dat", "Theta, BRTE1, BRTE2\n" + "".join(
                "%6.2f %12.8f %12.8f\n" % (theta1[i], _r(S["BRTE1"][0, i, num1]), _r(S["BRTE2"][0, i, num1]))
                for i in range(theta1.size)))
        else:
            w("Total_SPL_Directivity.dat", "Theta, BRTE1, BRTE2, BRWI, Total \n" + "".join(
                "%6.2f %12.8f %12.8f %12.8f %12.8f\n" % (theta1[i], *(_r(S[s][0, i, num1]) for s in
                                                                     ("BRTE1", "BRTE2", "BRWI", "tot")))
                for i in range(theta1.size)))
        return written

    nobs = int(opt["phi_obs_num"])
    bands = results.get("bands")
    band = None if bands is None else bands / 2 / np.pi
    srcs = _sources(opt)
    have3 = all(f"PWL_thirds_{s}" in results for s in srcs)

    def suffix(g, strip=None):
        s = f"_Observer_{g + 1}" if nobs > 1 else ""
        return s + (f"_Strip_{strip + 1}" if strip is not None else "")

    for g in range(nobs):
        for strip in [None] + list(range(st)):
            jj = num1 if strip is None else strip
            if nt == "BRWI":
                P = results["PWL_BRWI"][g, :, jj]
                w(f"BRWI_PWL_Spectra{suffix(g, strip)}.dat", "#Frequency BRWI \n" + "".join(
                    " %6.2f  %12.8f \n" % (freq[i], _r(P[i])) for i in range(freq.size)))
                if have3:
                    P3 = results["PWL_thirds_BRWI"][g, :, jj]
                    w(f"BRWI_PWL_Thirds_Spectra{suffix(g, strip)}.dat", "#Frequency BRWI \n" + "".join(
                        " %6.2f  %12.8f \n" % (band[i], _r(P3[i])) for i in range(band.size)))
            elif nt == "BRTE" and int(opt["StageCount"]) == 1:
                if strip is not None:
                    continue                                 # pp.m writes no strip files here
                P = results["PWL_BRTE1"][g, :, jj]
                w(f"BRTE1_PWL_Spectra{suffix(g)}.dat", "#Frequency BRTE1 \n" + "".join(
                    " %6.2f  %12.8f \n" % (freq[i], _r(P[i])) for i in range(freq.size)))
                if have3:
                    P3 = results["PWL_thirds_BRTE1"][g, :, jj]
                    w(f"BRTE1_PWL_Thirds_Spectra{suffix(g)}.dat", "#Frequency BRTE1 \n" + "".join(
                        " %6.2f  %12.8f \n" % (band[i], _r(P3[i])) for i in range(band.size)))
            elif nt == "BRTE":
                P1, P2 = results["PWL_BRTE1"][g, :, jj], results["PWL_BRTE2"][g, :, jj]
                w(f"BRTE_PWL_Spectra{suffix(g, strip)}.dat", "#Frequency BRTE1 BRTE2 \n" + "".join(
                    "%6.2f %12.8f %12.8f \n " % (freq[i], _r(P1[i]), _r(P2[i])) for i in range(freq.size)))
                if have3:
                    Q1, Q2 = results["PWL_thirds_BRTE1"][g, :, jj], results["PWL_thirds_BRTE2"][g, :, jj]
                    w(f"BRTE_PWL_Thirds_Spectra{suffix(g, strip)}.dat", "#Frequency BRTE1 BRTE2 \n" + "".join(
                        "%6.2f %12.8f %12.8f \n " % (band[i], _r(Q1[i]), _r(Q2[i])) for i in range(band.size)))
            else:
                cols = [results[f"PWL_{s}"][g, :, jj] for s in ("BRTE1", "BRTE2", "BRWI", "tot")]
                w(f"Total_PWL_Spectra{suffix(g, strip)}.dat", "#Frequency BRTE1 BRTE2 BRWI Total \n" + "".join(
                    "%6.2f %12.8f %12.8f %12.8f %12.8f\n " % (freq[i], *(_r(c[i]) for c in cols))
                    for i in range(freq.size)))
                if have3:
                    cols = [results[f"PWL_thirds_{s}"][g, :, jj] for s in ("BRTE1", "BRTE2", "BRWI", "tot")]
                    w(f"Total_PWL_Thirds_Spectra{suffix(g, strip)}.dat",
                      "#Frequency BRTE1 BRTE2 BRWI Total \n" + "".join(
                          "%6.2f %12.8f %12.8f %12.8f %12.8f\n " % (band[i], *(_r(c[i]) for c in cols))
                          for i in range(band.size)))
    # full directivity of each source (pp.m, modTNL 20151112)
    dsrcs = ["BRTE1", "BRTE2"] if opt["noise_type"] == "BRTE" else srcs      # pp.m lists BRTE2 even for 1 rotor
    for g in range(nobs):
        for s in dsrcs:
            name = ("Total" if s == "tot" else s) + (f"_directivity_{g + 1}" if nobs > 1 else "_directivity") + ".dat"
            if opt.get("emission_angle"):
                th_em = np.pi - np.asarray(lists.theta)
                th_ph = np.pi + np.arctan2(-np.sin(th_em), flow.MX - np.cos(th_em))
                head = f"#Directivity spectra from bbnoise computation for microphones located at {_num2str(opt['r0'])} meter in emission distance\n"
            else:
                th_ph = np.pi - np.asarray(lists.theta)
                th_em = th_ph - np.arctan(flow.MX * np.sin(th_ph))
                head = f"#Directivity spectra from bbnoise computation for microphones located at {_num2str(opt['r0'])} meter in physical distance\n"
            text = head + "%-16s" % "#thetaEmDeg" + "".join("%10.2f" % v for v in th_em * 180 / np.pi) + "\n"
            text += "%-16s" % "#thetaPhysDeg" + "".join("%10.2f" % v for v in th_ph * 180 / np.pi) + "\n"
            if s not in res.Spps:
                w(name, text)
                raise MCodeError(f"The MATLAB code stops here: pp.m writes {name} for a single rotor too, but Spps.{s} "
                               "does not exist (the other output files are written)")
            S = _as4(res.Spps[s])
            for i in range(freq.size):
                spl = 10 * _clog10(2 * 2 * np.pi * S[i, :, num1, g] / 4e-10)
                text += "%16.2f" % freq[i] + "".join("%10.2f" % _r(v) for v in spl) + "\n"
            w(name, text)
    return written


def _num2str(x):
    """MATLAB num2str for a scalar (4 significant digits after the decimal point, %.4g-like)."""
    x = float(x)
    if x == int(x):
        return str(int(x))
    return ("%.4f" % x).rstrip("0").rstrip(".") if abs(x) >= 1e-4 else "%g" % x


# ---------------------------------------------------------------------------
# installation noise (pp_pylon.m, BPRI_BL branch)
# ---------------------------------------------------------------------------

PWL_WARNING = ("Warning PWL band cannot be computed. Either the frequency range is too small or only one "
               "observer is specified")


def compute_results_pylon(res):
    """results structure of pp_pylon.m for BPRI_BL: PWL_B1[obs, omega, strip], bands, PWL_thirds_B1.

    As in the MATLAB code, a failed band computation sets PWL_B1 = bands = PWL_thirds_B1 = -999.
    """
    p = res.p
    opt, lists = p.opt, p.lists
    if opt.get("p_noise_type") != "BPRI_BL":
        raise MCodeError("only the BPRI_BL post-processing of pp_pylon.m is ported")
    if not opt.get("spectral_study", True):
        raise MCodeError("The MATLAB code stops here: pp_pylon.m uses Spps.B1 for BPRI_BL directivity studies "
                       "(spectral_study = false), which it never sets for BPRI_BL")
    S = _as4(res.Spps["BPRI"])
    out = {"omega": np.asarray(lists.omega), "warnings": []}
    pw, p3, bands = [], [], None
    for g in range(S.shape[3]):
        PWL, b, PWL3 = PWL_plus_bands(lists, opt, p.geom, p.flow, S[..., g])
        pw.append(PWL)
        p3.append(PWL3)
        bands = b if b is not None else bands
    if any(x is None for x in p3):
        out["warnings"].append(PWL_WARNING)
        out.update(PWL_B1=-999.0, bands=-999.0, PWL_thirds_B1=-999.0)
    else:
        out.update(PWL_B1=np.array(pw), bands=bands, PWL_thirds_B1=np.array(p3))
    return out


def write_outputs_pylon(res, folder, results=None):
    """BPRI_BL .dat files of pp_pylon.m (PWL spectra and 1/3-octave PWL, total and per strip)."""
    opt, lists = res.p.opt, res.p.lists
    results = results or compute_results_pylon(res)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if np.isscalar(results["PWL_B1"]) and results["PWL_B1"] == -999:
        results["warnings"].append("Warning PWL not computed and no data written to file")
        return []
    P, P3 = results["PWL_B1"], results["PWL_thirds_B1"]
    if P.shape[0] < 3:
        raise MCodeError("The MATLAB code stops here: pp_pylon.m writes PWL_B1(1:3,:,:), so BPRI_BL spectra need at least "
                       f"three azimuthal observers (opt.spectral_phi_obs has {P.shape[0]})")
    freq = np.asarray(lists.omega, float) / (2 * np.pi)
    band = np.asarray(results["bands"], float) / 2 / np.pi
    st = int(opt["st_num"])
    pname = opt["p_noise_type"]
    written = []

    def table(x, Y):
        return "".join("%6.2f %12.8f %12.8f %12.8f\n " % (x[i], *(float(v) for v in Y[:3, i])) for i in range(x.size))

    def w(name, text):
        path = folder / name
        path.write_text(_matlab_text(text))
        written.append(str(path))

    w(f"{pname}_PWL_Spectra_FR.dat", table(freq, P[:, :, st]))
    w(f"{pname}_PWL_Thirds_Spectra_FR.dat", table(band, P3[:, :, st]))
    for j in range(st):
        w(f"{pname}_PWL_Spectra_FR{j + 1}.dat", table(freq, P[:, :, j]))
        w(f"{pname}_PWL_Thirds_Spectra_FR{j + 1}.dat", table(band, P3[:, :, j]))
    return written
