"""Propeller geometry: blade sections, sweep, spinner and nacelle.

Conventions
-----------
* x is the axial coordinate, positive downstream; the propeller rotates about +x with
  angular velocity Omega, blade 0 along +y at the reference time.  Local frame at a point:
  (axial, tangential = direction of rotation, radial).
* Blade sections are cylindrical cuts r = const.  ``chord`` is the section chord (b),
  ``beta`` the angle of the chord line from the plane of rotation, the leading edge leading
  in the direction of rotation.
* Sweep follows the Hamilton Standard mid-chord alignment: the mid-chord point of each
  section is displaced from the pitch-change axis (the radial line through the hub) by a
  distance ``mca`` measured along the local chord, positive towards the trailing edge.  Its
  radial derivative is the tangent of the sweep angle of the mid-chord line in the blade
  surface, which is close to the aerodynamic sweep seen by the relative flow.  A pitch
  change rotates every section, and its mid-chord offset, about the pitch-change axis.
* Face alignment (``fa``, optional) displaces the mid-chord point normal to the chord in the
  section plane (positive towards the pressure side, i.e. downstream for a tractor blade).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import PchipInterpolator


def _interp(x, xp, fp):
    return PchipInterpolator(np.asarray(xp, float), np.asarray(fp, float), extrapolate=True)(x)


@dataclass
class Blade:
    """Blade defined at stations r/R from hub to tip (all lengths divided by the diameter D,
    except r/R; angles in degrees)."""

    r_R: np.ndarray
    chord_D: np.ndarray              # b/D
    beta_deg: np.ndarray             # blade angle at the reference pitch setting
    t_c: np.ndarray                  # h/b
    cl_design: np.ndarray            # design lift coefficient (camber)
    mca_D: np.ndarray | None = None  # mid-chord alignment / D (sweep), along the chord
    fa_D: np.ndarray | None = None   # face alignment / D
    thickness_form: str = "naca16"
    mean_line: str = "a1"
    name: str = "blade"

    def __post_init__(self):
        for k in ("r_R", "chord_D", "beta_deg", "t_c", "cl_design"):
            setattr(self, k, np.asarray(getattr(self, k), dtype=float))
        n = self.r_R.size
        self.mca_D = np.zeros(n) if self.mca_D is None else np.asarray(self.mca_D, dtype=float)
        self.fa_D = np.zeros(n) if self.fa_D is None else np.asarray(self.fa_D, dtype=float)
        if np.any(np.diff(self.r_R) <= 0):
            raise ValueError("r_R must increase from hub to tip")

    @property
    def hub_ratio(self):
        return float(self.r_R[0])

    def at(self, r_R):
        """Interpolated section data at radii r/R."""
        out = {}
        for k in ("chord_D", "beta_deg", "t_c", "cl_design", "mca_D", "fa_D"):
            out[k] = _interp(r_R, self.r_R, getattr(self, k))
        out["chord_D"] = np.maximum(out["chord_D"], 1e-4)
        out["t_c"] = np.maximum(out["t_c"], 1e-3)
        return out

    # ------------------------------------------------------------------ figures of merit
    def activity_factor(self):
        """Blade activity factor 100000/16 int_{0.15}^{1} (b/D) x^3 dx (from the hub if larger)."""
        x = np.linspace(max(0.15, self.r_R[0]), 1.0, 2001)
        return float(100000.0 / 16.0 * np.trapezoid(self.at(x)["chord_D"] * x ** 3, x))

    def integrated_design_cl(self):
        """Integrated design lift coefficient 3 int cl_d x^2 dx from the hub."""
        x = np.linspace(self.r_R[0], 1.0, 2001)
        return float(3.0 * np.trapezoid(self.at(x)["cl_design"] * x ** 2, x))

    def to_dict(self):
        d = {k: getattr(self, k).tolist() for k in ("r_R", "chord_D", "beta_deg", "t_c", "cl_design", "mca_D", "fa_D")}
        d.update(thickness_form=self.thickness_form, mean_line=self.mean_line, name=self.name)
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Nacelle:
    """Axisymmetric spinner + nacelle, radius / D against x / D (propeller plane at x = 0).

    The body is closed (nose at the first point, closing tail at the last); a long nacelle
    stands for a semi-infinite one.
    """

    x_D: np.ndarray
    r_D: np.ndarray
    name: str = "nacelle"

    def __post_init__(self):
        self.x_D = np.asarray(self.x_D, dtype=float)
        self.r_D = np.asarray(self.r_D, dtype=float)

    def radius(self, x_D):
        return np.interp(x_D, self.x_D, self.r_D, left=0.0, right=0.0)

    @classmethod
    def spinner(cls, hub_radius_D, nose_length_D=0.35, waist=0.0, waist_x_D=0.0, waist_width_D=0.12,
                length_D=6.0, tail_D=2.0, n=241):
        """Spinner and nacelle of radius ``hub_radius_D``: an elliptic nose of length
        ``nose_length_D`` whose tip is that far ahead of the propeller plane, reaching full
        radius 15 % of its length ahead of the plane; a cylindrical nacelle ``length_D`` long
        closing over ``tail_D``; an optional area-ruling waist (fractional radius reduction
        ``waist``, Gaussian of half-width ``waist_width_D`` centred at ``waist_x_D``)."""
        x0 = -nose_length_D
        a = 0.85 * nose_length_D
        t = np.linspace(0.0, 1.0, n)
        x = np.unique(np.concatenate([
            x0 + a * (1.0 - np.cos(0.5 * np.pi * t[: n // 3])),
            np.linspace(x0 + a, length_D, n // 2),
            length_D + tail_D * np.sin(0.5 * np.pi * t[: n // 4]),
            [length_D + tail_D]]))
        R = hub_radius_D
        xi = np.clip((x - x0) / a, 0.0, 1.0)
        r = R * np.sqrt(np.maximum(1.0 - (1.0 - xi) ** 2, 0.0))
        tail = x > length_D
        r = np.where(tail, R * np.sqrt(np.maximum(1.0 - ((x - length_D) / tail_D) ** 2, 0.0)), r)
        if waist:
            r = r * (1.0 - waist * np.exp(-((x - waist_x_D) / waist_width_D) ** 2))
        return cls(x_D=x, r_D=r, name="spinner")


@dataclass
class Propeller:
    blade: Blade
    blades: int
    diameter: float                     # m
    nacelle: Nacelle | None = None
    name: str = "propeller"
    beta_ref_r_R: float = 0.75          # pitch setting reported at this radius

    @property
    def radius(self):
        return 0.5 * self.diameter

    @property
    def hub_radius(self):
        return self.blade.hub_ratio * self.radius

    def total_activity_factor(self):
        return self.blades * self.blade.activity_factor()

    def solidity(self, r_R):
        """Cylindrical solidity B b / (2 pi r) = B (b/D) / (pi r/R)."""
        return self.blades * self.blade.at(r_R)["chord_D"] / (np.pi * np.asarray(r_R))

    def beta_ref(self, dbeta=0.0):
        return float(self.blade.at(np.array([self.beta_ref_r_R]))["beta_deg"][0] + dbeta)

    # ------------------------------------------------------------------ 3-D lines
    def section_frame(self, r_R, dbeta_deg=0.0):
        """Section data and the mid-chord line in metres at radii r/R (blade 0).

        Returns a dict with chord, beta (rad), mid-chord point (x, theta) on the cylinder and
        the unit span tangent in local (axial, tangential, radial) components.
        """
        R = self.radius
        D = self.diameter
        s = self.blade.at(r_R)
        r = np.asarray(r_R) * R
        beta = np.radians(s["beta_deg"] + dbeta_deg)
        c = s["chord_D"] * D
        mca = s["mca_D"] * D
        fa = s["fa_D"] * D
        # mid-chord point: along the chord (sin b, -cos b) and normal (cos b, sin b) in the
        # (axial, tangential arc length) plane of the cylinder
        xm = mca * np.sin(beta) + fa * np.cos(beta)
        ym = -mca * np.cos(beta) + fa * np.sin(beta)          # arc length, + in rotation sense
        th = ym / r
        # span tangent from finite differences of the 3-D mid-chord line
        h = 1e-4
        def mid(rr):
            ss = self.blade.at(rr)
            bb = np.radians(ss["beta_deg"] + dbeta_deg)
            mm, ff = ss["mca_D"] * D, ss["fa_D"] * D
            xx = mm * np.sin(bb) + ff * np.cos(bb)
            tt = (-mm * np.cos(bb) + ff * np.sin(bb)) / (rr * R)
            return xx, tt
        rp, rm = np.asarray(r_R) + h, np.asarray(r_R) - h
        xp, tp = mid(rp)
        xq, tq = mid(rm)
        dx = (xp - xq) / (2 * h * R)
        dth = (tp - tq) / (2 * h * R)
        t = np.stack([dx, r * dth, np.ones_like(r)], axis=1)
        t /= np.linalg.norm(t, axis=1)[:, None]
        return dict(r=r, chord=c, beta=beta, t_c=s["t_c"], cl_design=s["cl_design"],
                    x_mid=xm, theta_mid=th, t_hat=t)

    def to_dict(self):
        d = dict(name=self.name, blades=self.blades, diameter=self.diameter,
                 beta_ref_r_R=self.beta_ref_r_R, blade=self.blade.to_dict())
        if self.nacelle is not None:
            d["nacelle"] = dict(x_D=self.nacelle.x_D.tolist(), r_D=self.nacelle.r_D.tolist(),
                                name=self.nacelle.name)
        return d

    @classmethod
    def from_dict(cls, d):
        nac = d.get("nacelle")
        return cls(blade=Blade.from_dict(d["blade"]), blades=int(d["blades"]),
                   diameter=float(d["diameter"]),
                   nacelle=Nacelle(np.asarray(nac["x_D"]), np.asarray(nac["r_D"]), nac.get("name", "nacelle")) if nac else None,
                   name=d.get("name", "propeller"), beta_ref_r_R=float(d.get("beta_ref_r_R", 0.75)))

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_dict(json.load(f))
