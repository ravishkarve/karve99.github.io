"""Blade-section geometry for linear cascades.

Coordinate and angle conventions (identical to MISES):

* ``x`` is the axial (meridional) direction, ``y`` the pitchwise direction.
* Flow and metal angles are measured from the axial direction, positive
  towards ``+y``, in degrees at the user level.
* A blade contour is stored counter-clockwise, starting at the trailing edge,
  running over the *upper* (suction for positive camber) surface to the
  leading edge and back along the *lower* (pressure) surface.

Blades can be read from the MISES ``blade.xxx`` format, built from aerofoil
coordinates in Selig or Lednicer format (placed in the cascade at a given
stagger and pitch), or generated from a circular-arc camber line with a
NACA 65-series, NACA 4-digit or C4 thickness distribution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator
from scipy.optimize import minimize_scalar

# --------------------------------------------------------------------------
# Thickness distributions (half thickness / chord for the base section)
# --------------------------------------------------------------------------

# NACA 65-010 basic thickness form (Abbott & von Doenhoff), 10 % thick.
_NACA65_X = np.array([0.0, 0.5, 0.75, 1.25, 2.5, 5.0, 7.5, 10, 15, 20, 25, 30, 35, 40,
                      45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]) / 100.0
_NACA65_Y = np.array([0.0, 0.772, 0.932, 1.169, 1.574, 2.177, 2.647, 3.040, 3.666, 4.143,
                      4.503, 4.760, 4.924, 4.996, 4.963, 4.812, 4.530, 4.146, 3.682, 3.156,
                      2.584, 1.987, 1.385, 0.810, 0.306, 0.0]) / 100.0
_NACA65_RLE = 0.00687  # leading-edge radius / chord at 10 % thickness

# British C4 section (Dixon & Hall, Table 3.1), 10 % thick.
_C4_X = np.array([0.0, 1.25, 2.5, 5.0, 7.5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 95,
                  100]) / 100.0
_C4_Y = np.array([0.0, 1.65, 2.27, 3.08, 3.62, 4.02, 4.55, 4.83, 5.00, 4.89, 4.57, 4.05,
                  3.37, 2.54, 1.60, 1.06, 0.0]) / 100.0
_C4_RLE = 0.012  # 12 % of thickness at t/c = 0.1

THICKNESS_FORMS = ("naca65", "naca4", "c4")


def _tabulated_half_thickness(xi, xt, yt, rle, tmax, tref=0.10):
    """Interpolate a tabulated half-thickness form with correct sqrt(x) LE behaviour."""
    g = np.empty_like(xt)
    g[1:] = yt[1:] / np.sqrt(xt[1:])
    g[0] = math.sqrt(2.0 * rle)
    interp = PchipInterpolator(xt, g)
    xi = np.clip(xi, 0.0, 1.0)
    return interp(xi) * np.sqrt(xi) * (tmax / tref)


def half_thickness(xi, form="naca65", tmax=0.10):
    """Half thickness / chord at chord fractions ``xi`` for a named form."""
    xi = np.asarray(xi, dtype=float)
    form = form.lower()
    if form == "naca65":
        return _tabulated_half_thickness(xi, _NACA65_X, _NACA65_Y, _NACA65_RLE, tmax)
    if form == "c4":
        return _tabulated_half_thickness(xi, _C4_X, _C4_Y, _C4_RLE, tmax)
    if form == "naca4":
        x = np.clip(xi, 0.0, 1.0)
        return 5.0 * tmax * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2
                             + 0.2843 * x ** 3 - 0.1015 * x ** 4)
    raise ValueError(f"unknown thickness form '{form}', expected one of {THICKNESS_FORMS}")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _signed_area(x, y):
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


def _arclength(x, y):
    ds = np.hypot(np.diff(x), np.diff(y))
    return np.concatenate([[0.0], np.cumsum(ds)])


def _clustered(n, strength=0.85):
    """n+1 points on [0,1], clustered towards both ends (cosine blended with linear)."""
    t = np.linspace(0.0, 1.0, n + 1)
    return strength * 0.5 * (1.0 - np.cos(np.pi * t)) + (1.0 - strength) * t


# --------------------------------------------------------------------------
# Aerofoil coordinate files (Selig / Lednicer)
# --------------------------------------------------------------------------

def _numeric_pair(line):
    """The first two numbers on a line, or ``None`` if the line is not data."""
    vals = line.replace(",", " ").replace("\t", " ").split()
    if len(vals) < 2:
        return None
    try:
        return float(vals[0]), float(vals[1])
    except ValueError:
        return None


def parse_airfoil_coordinates(text):
    """Parse aerofoil coordinates in Selig or Lednicer format.

    *Selig* (UIUC database, XFOIL): an optional name line, then ``x y`` pairs
    running from the trailing edge over the upper surface to the leading edge
    and back along the lower surface to the trailing edge.

    *Lednicer*: a name line, a line holding the number of upper and lower
    points (e.g. ``61. 61.``), then the upper surface from the leading edge to
    the trailing edge, a blank line, and the lower surface likewise.

    Commas, tabs and comment lines starting with ``#`` are accepted.

    Returns
    -------
    name, x, y, fmt
        The name (or ``"aerofoil"``), one contour in Selig order, and the
        detected format (``"selig"`` or ``"lednicer"``).
    """
    name = None
    rows = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pair = _numeric_pair(line)
        if pair is None:
            if not rows and name is None:
                name = line
                continue
            if not rows:
                continue  # extra header text before the data
            raise ValueError(f"could not read coordinates from line: {raw.strip()[:60]!r}")
        rows.append(pair)
    if not rows:
        raise ValueError("no coordinate pairs found")
    fmt = "selig"
    n0, n1 = rows[0]
    if n0 > 1.5 and n1 > 1.5 and float(n0).is_integer() and float(n1).is_integer():
        nu, nl = int(n0), int(n1)
        pts = rows[1:]
        if len(pts) != nu + nl:
            raise ValueError(f"Lednicer header announces {nu} + {nl} points but "
                             f"{len(pts)} were found")
        up = np.array(pts[:nu])
        lo = np.array(pts[nu:])
        if np.hypot(*(up[0] - lo[0])) < 1e-9:
            lo = lo[1:]
        xy = np.vstack([up[::-1], lo])
        fmt = "lednicer"
    else:
        xy = np.array(rows)
    if not np.all(np.isfinite(xy)):
        raise ValueError("coordinates contain non-finite values")
    if len(xy) < 8:
        raise ValueError(f"need at least 8 coordinate points, got {len(xy)}")
    return (name or "aerofoil"), xy[:, 0].copy(), xy[:, 1].copy(), fmt


def normalise_airfoil(x, y, check=True):
    """Move the leading edge to the origin and the trailing edge to (1, 0).

    The trailing edge is the midpoint of the first and last points; the
    leading edge is the contour point farthest from it (as in XFOIL).
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    xt, yt = 0.5 * (x[0] + x[-1]), 0.5 * (y[0] + y[-1])
    span = max(float(np.ptp(x)), float(np.ptp(y)))
    if check and max(x.max() - x[0], x.max() - x[-1]) > 0.05 * span:
        raise ValueError("coordinates must start and end at the trailing edge (largest x): "
                         "use Selig order TE -> upper surface -> LE -> lower surface -> TE, "
                         "or Lednicer format")
    # leading edge on a spline through the contour, exactly as Blade defines it
    xl, yl = Blade(x, y, 1.0).le_point
    c = math.hypot(xt - xl, yt - yl)
    if c <= 1e-12 * max(span, 1e-300):
        raise ValueError("degenerate aerofoil (zero chord)")
    ang = math.atan2(yt - yl, xt - xl)
    ca, sa = math.cos(-ang), math.sin(-ang)
    dx, dy = x - xl, y - yl
    return (dx * ca - dy * sa) / c, (dx * sa + dy * ca) / c


# --------------------------------------------------------------------------
# Blade
# --------------------------------------------------------------------------

@dataclass
class Blade:
    """A cascade blade section.

    Parameters
    ----------
    x, y
        Contour coordinates (counter-clockwise from the trailing edge).  Any
        input ordering is normalised on construction.
    pitch
        Blade spacing ``s`` in the same units as the coordinates.
    name
        Descriptive name.
    metal_angles
        Optional ``(inlet, exit)`` metal angles in degrees (set by the
        parametric generator; estimated from the contour otherwise).
    """

    x: np.ndarray
    y: np.ndarray
    pitch: float
    name: str = "blade"
    metal_angles: tuple | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        x = np.asarray(self.x, dtype=float).copy()
        y = np.asarray(self.y, dtype=float).copy()
        if x.shape != y.shape or x.ndim != 1 or x.size < 8:
            raise ValueError("blade contour needs matching 1-D x and y arrays (>= 8 points)")
        # The contour must start and end at the trailing edge (MISES / Selig
        # convention).  A closed (sharp) TE keeps both coincident end points.
        keep = np.concatenate([[True], np.hypot(np.diff(x), np.diff(y)) > 1e-13])
        x, y = x[keep], y[keep]
        if _signed_area(x, y) < 0.0:
            x, y = x[::-1].copy(), y[::-1].copy()
        self.x, self.y = x, y
        if self.pitch <= 0:
            raise ValueError("pitch must be positive")
        self._spline = None

    # ------------------------------------------------------------------ basic
    @property
    def n_points(self) -> int:
        return self.x.size

    @property
    def te_gap(self) -> float:
        return float(math.hypot(self.x[0] - self.x[-1], self.y[0] - self.y[-1]))

    @property
    def te_point(self):
        return 0.5 * (self.x[0] + self.x[-1]), 0.5 * (self.y[0] + self.y[-1])

    def spline(self):
        """Cubic splines x(s), y(s) in contour arclength."""
        if self._spline is None:
            s = _arclength(self.x, self.y)
            self._spline = (s, CubicSpline(s, self.x), CubicSpline(s, self.y))
        return self._spline

    def leading_edge_arclength(self) -> float:
        """Arclength of the LE, the contour point farthest from the TE midpoint."""
        s, sx, sy = self.spline()
        xt, yt = self.te_point
        d2 = (self.x - xt) ** 2 + (self.y - yt) ** 2
        i = int(np.argmax(d2))
        lo = s[max(i - 2, 0)]
        hi = s[min(i + 2, s.size - 1)]
        res = minimize_scalar(lambda t: -((sx(t) - xt) ** 2 + (sy(t) - yt) ** 2),
                              bounds=(lo, hi), method="bounded",
                              options={"xatol": 1e-12 * s[-1]})
        return float(res.x)

    @property
    def le_point(self):
        s_le = self.leading_edge_arclength()
        _, sx, sy = self.spline()
        return float(sx(s_le)), float(sy(s_le))

    @property
    def chord(self) -> float:
        xl, yl = self.le_point
        xt, yt = self.te_point
        return math.hypot(xt - xl, yt - yl)

    @property
    def stagger(self) -> float:
        """Stagger angle of the chord line from axial [deg]."""
        xl, yl = self.le_point
        xt, yt = self.te_point
        return math.degrees(math.atan2(yt - yl, xt - xl))

    @property
    def axial_chord(self) -> float:
        return float(np.ptp(self.x))

    @property
    def solidity(self) -> float:
        return self.chord / self.pitch

    def surfaces(self, n_dense=400):
        """Dense upper and lower surfaces, both ordered LE -> TE."""
        s, sx, sy = self.spline()
        s_le = self.leading_edge_arclength()
        su = np.linspace(s_le, 0.0, n_dense)
        sl = np.linspace(s_le, s[-1], n_dense)
        return (sx(su), sy(su)), (sx(sl), sy(sl))

    def camber_and_thickness(self, n=201):
        """Approximate camber line and thickness in chord coordinates.

        Returns (xi, camber, thickness) with camber/thickness normalised by
        chord and measured normal to the chord line.
        """
        (xu, yu), (xl, yl) = self.surfaces(600)
        x0, y0 = self.le_point
        c = self.chord
        g = math.radians(self.stagger)
        cg, sg = math.cos(g), math.sin(g)

        def to_chord(xx, yy):
            dx, dy = xx - x0, yy - y0
            return (dx * cg + dy * sg) / c, (-dx * sg + dy * cg) / c

        xiu, etau = to_chord(xu, yu)
        xil, etal = to_chord(xl, yl)
        xi = _clustered(n - 1, 0.9)
        fu = np.interp(xi, *_monotone(xiu, etau))
        fl = np.interp(xi, *_monotone(xil, etal))
        return xi, 0.5 * (fu + fl), fu - fl

    @property
    def max_thickness(self) -> float:
        _, _, t = self.camber_and_thickness()
        return float(np.max(t))

    def estimated_metal_angles(self):
        """Metal angles (deg) from the camber-line slope near LE and TE."""
        if self.metal_angles is not None:
            return self.metal_angles
        xi, cam, _ = self.camber_and_thickness(401)
        g = self.stagger
        i1 = np.searchsorted(xi, 0.03)
        i2 = np.searchsorted(xi, 0.97)
        a1 = math.degrees(math.atan2(cam[i1] - cam[0], xi[i1] - xi[0]))
        a2 = math.degrees(math.atan2(cam[-1] - cam[i2], xi[-1] - xi[i2]))
        return g + a1, g + a2

    # ------------------------------------------------------------ panelling
    def repanel(self, n_panels=180, cosine_fraction=0.3):
        """Return a new blade with ``n_panels`` panels, fine at the LE, moderate at the TE.

        Each surface uses  f(t) = a (1 - cos(pi t))/2 + (1 - a) sin(pi t / 2)
        (t = 0 at the TE, 1 at the LE): quadratic clustering at the leading
        edge and panels of about (1 - a) pi S / (2 n) at the trailing edge,
        which keeps TE panels longer than a typical TE gap (a smooth TE
        velocity).  ``cosine_fraction`` = 1 gives full cosine spacing at both
        ends.  The LE node is placed exactly at the leading edge.
        """
        s, sx, sy = self.spline()
        s_le = self.leading_edge_arclength()
        n_up = n_panels // 2
        n_lo = n_panels - n_up
        a = float(cosine_fraction)

        def dist(n):
            t = np.linspace(0.0, 1.0, n + 1)
            return a * 0.5 * (1.0 - np.cos(np.pi * t)) + (1.0 - a) * np.sin(0.5 * np.pi * t)

        tu = dist(n_up)                       # 0 at TE -> 1 at LE
        tl = 1.0 - dist(n_lo)[::-1]           # 0 at LE -> 1 at TE
        s_new = np.concatenate([tu * s_le, s_le + tl[1:] * (s[-1] - s_le)])
        blade = Blade(sx(s_new), sy(s_new), self.pitch, self.name, self.metal_angles,
                      dict(self.meta))
        blade.meta["i_le"] = n_up
        return blade

    def closed_te(self, blend=0.08):
        """Return a copy whose surfaces are blended to meet at the TE midpoint.

        Points within the last ``blend`` fraction of the chord are moved
        towards the trailing-edge midpoint with a smooth weight, giving a
        sharp (closed) trailing edge.  The panel and Euler solvers use this
        form; the original TE thickness is kept in ``meta['te_gap_original']``
        and accounted for as base blockage in the mixed-out loss.
        """
        gap = self.te_gap
        if gap < 1e-12 * max(self.axial_chord, 1e-12):
            return self
        x, y = self.x.copy(), self.y.copy()
        (xl, yl), (xt, yt) = self.le_point, self.te_point
        c = math.hypot(xt - xl, yt - yl)
        cdx, cdy = (xt - xl) / c, (yt - yl) / c
        xi = ((x - xl) * cdx + (y - yl) * cdy) / c
        t = np.clip((xi - (1.0 - blend)) / blend, 0.0, 1.0)
        w = t * t * (3.0 - 2.0 * t)
        i_le = int(np.argmin((x - xl) ** 2 + (y - yl) ** 2))
        up = np.arange(x.size) <= i_le
        dxu, dyu = xt - self.x[0], yt - self.y[0]
        dxl, dyl = xt - self.x[-1], yt - self.y[-1]
        x = x + w * np.where(up, dxu, dxl)
        y = y + w * np.where(up, dyu, dyl)
        x[0] = x[-1] = xt
        y[0] = y[-1] = yt
        meta = dict(self.meta)
        meta["te_gap_original"] = gap
        meta.pop("i_le", None)
        return Blade(x, y, self.pitch, self.name, self.metal_angles, meta)

    @property
    def i_le(self) -> int:
        """Index of the node closest to the leading edge."""
        if "i_le" in self.meta:
            return int(self.meta["i_le"])
        xl, yl = self.le_point
        return int(np.argmin((self.x - xl) ** 2 + (self.y - yl) ** 2))

    def translated(self, dx=0.0, dy=0.0):
        return Blade(self.x + dx, self.y + dy, self.pitch, self.name, self.metal_angles,
                     dict(self.meta))

    # ------------------------------------------------------------ builders
    @classmethod
    def from_parameters(cls, inlet_metal_angle=45.0, exit_metal_angle=15.0,
                        max_thickness=0.10, pitch=None, solidity=None,
                        thickness_form="naca65", te_thickness=0.004, chord=1.0,
                        n_points=241, name=None, camber="circular", le_camber_fraction=0.5):
        """Circular-arc camber line with a standard thickness distribution.

        Parameters
        ----------
        inlet_metal_angle, exit_metal_angle
            Camber-line angles at LE and TE, degrees from axial.
        max_thickness
            Maximum thickness / chord.
        pitch or solidity
            Blade spacing / chord, or chord / spacing (one of them).
        thickness_form
            ``'naca65'``, ``'naca4'`` or ``'c4'``.
        te_thickness
            Trailing-edge thickness / chord added as a linear ramp.
        camber
            ``'circular'`` (circular arc, symmetric loading) or ``'bezier'``
            (quadratic Bezier mean line whose LE angle takes the fraction
            ``le_camber_fraction`` of the total camber: > 0.5 gives the
            front-loaded, straight-backed shape typical of turbine blades).
        """
        if pitch is None and solidity is None:
            raise ValueError("give either pitch (s/c) or solidity (c/s)")
        if pitch is None:
            pitch = 1.0 / float(solidity)
        chi1, chi2 = math.radians(inlet_metal_angle), math.radians(exit_metal_angle)
        theta = chi1 - chi2
        gam = 0.5 * (chi1 + chi2)
        xi = _clustered(n_points - 1, 0.95)
        if camber not in ("circular", "bezier"):
            raise ValueError("camber must be 'circular' or 'bezier'")
        if abs(theta) < 1e-6:
            yc = np.zeros_like(xi)
            phi = np.zeros_like(xi)
        elif camber == "bezier":
            f = float(le_camber_fraction)
            if not 0.05 <= f <= 0.95:
                raise ValueError("le_camber_fraction must be within [0.05, 0.95]")
            phi1 = f * theta                     # LE angle relative to the chord
            phi2 = phi1 - theta                  # TE angle relative to the chord
            gam = chi1 - phi1                    # stagger
            t1, t2 = math.tan(phi1), math.tan(-phi2)
            a = t2 / (t1 + t2)                   # control point (a, h) of the Bezier curve
            h = a * t1
            tt = np.linspace(0.0, 1.0, 4001)
            xb = 2 * tt * (1 - tt) * a + tt ** 2
            yb = 2 * tt * (1 - tt) * h
            tq = np.interp(xi, xb, tt)
            yc = 2 * tq * (1 - tq) * h
            dx = 2 * (1 - 2 * tq) * a + 2 * tq
            dy = 2 * (1 - 2 * tq) * h
            phi = np.arctan2(dy, dx)
        else:
            r = 0.5 / math.sin(abs(theta) / 2.0)
            sgn = math.copysign(1.0, theta)
            root = np.sqrt(r * r - (xi - 0.5) ** 2)
            yc = sgn * (root - math.sqrt(r * r - 0.25))
            phi = np.arctan(sgn * -(xi - 0.5) / root)
        yt = half_thickness(xi, thickness_form, max_thickness) + 0.5 * te_thickness * xi
        nx, ny = -np.sin(phi), np.cos(phi)
        xu, yu = xi + yt * nx, yc + yt * ny
        xl, yl = xi - yt * nx, yc - yt * ny
        # contour: TE upper -> LE -> TE lower
        xc = np.concatenate([xu[::-1], xl[1:]])
        yc2 = np.concatenate([yu[::-1], yl[1:]])
        cg, sg = math.cos(gam), math.sin(gam)
        X = chord * (xc * cg - yc2 * sg)
        Y = chord * (xc * sg + yc2 * cg)
        kind = "circular-arc" if camber == "circular" else "Bezier-camber"
        nm = name or (f"{thickness_form.upper()} {kind} blade "
                      f"({inlet_metal_angle:g}/{exit_metal_angle:g} deg, t/c={max_thickness:g})")
        return cls(X, Y, pitch * chord, nm, (float(inlet_metal_angle), float(exit_metal_angle)),
                   {"thickness_form": thickness_form, "max_thickness": max_thickness,
                    "te_thickness": te_thickness})

    @classmethod
    def naca4(cls, code="0012", pitch=1000.0, alpha=0.0, n_points=241, te_closed=False):
        """A NACA 4-digit aerofoil (chord 1) rotated to angle ``alpha`` (deg).

        With a very large pitch this is an isolated aerofoil, useful for
        verification.  Positive ``alpha`` is a nose-up rotation relative to
        a flow along +x.
        """
        m = int(code[0]) / 100.0
        p = int(code[1]) / 10.0
        t = int(code[2:]) / 100.0
        xi = _clustered(n_points - 1, 0.95)
        a4 = -0.1036 if te_closed else -0.1015
        yt = 5 * t * (0.2969 * np.sqrt(xi) - 0.1260 * xi - 0.3516 * xi ** 2
                      + 0.2843 * xi ** 3 + a4 * xi ** 4)
        if m > 0:
            yc = np.where(xi < p, m / p ** 2 * (2 * p * xi - xi ** 2),
                          m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * xi - xi ** 2))
            dy = np.where(xi < p, 2 * m / p ** 2 * (p - xi), 2 * m / (1 - p) ** 2 * (p - xi))
        else:
            yc = np.zeros_like(xi)
            dy = np.zeros_like(xi)
        th = np.arctan(dy)
        xu, yu = xi - yt * np.sin(th), yc + yt * np.cos(th)
        xl, yl = xi + yt * np.sin(th), yc - yt * np.cos(th)
        xc = np.concatenate([xu[::-1], xl[1:]])
        yc2 = np.concatenate([yu[::-1], yl[1:]])
        a = math.radians(-alpha)
        X = xc * math.cos(a) - yc2 * math.sin(a)
        Y = xc * math.sin(a) + yc2 * math.cos(a)
        return cls(X, Y, pitch, f"NACA {code}", None, {"naca": code, "alpha": alpha})

    # --------------------------------------------------- aerofoil coordinates
    @classmethod
    def from_airfoil(cls, x, y, stagger=0.0, pitch=None, solidity=None, chord=1.0,
                     flip=False, name="aerofoil"):
        """Place an aerofoil section in a cascade.

        The section is normalised to its chord line (LE at the origin, TE at
        ``(chord, 0)``), optionally mirrored (``flip``, which swaps the
        suction and pressure sides), then rotated counter-clockwise by the
        ``stagger`` angle, measured from the axial direction [deg].  Give
        either ``pitch`` (same units as ``chord``) or ``solidity`` = c/s.

        With positive camber (upper surface convex) and positive stagger the
        blade turns a flow of positive inlet angle towards axial, like a
        compressor blade; use a negative stagger with ``flip`` for a blade
        turning flow the other way.
        """
        if (pitch is None) == (solidity is None):
            raise ValueError("give exactly one of pitch or solidity")
        chord = float(chord)
        if chord <= 0:
            raise ValueError("chord must be positive")
        pitch = float(pitch) if pitch is not None else chord / float(solidity)
        xn, yn = normalise_airfoil(x, y)
        if flip:
            yn = -yn
        a = math.radians(float(stagger))
        X = chord * (xn * math.cos(a) - yn * math.sin(a))
        Y = chord * (xn * math.sin(a) + yn * math.cos(a))
        return cls(X, Y, pitch, name, None, {"source": "airfoil", "stagger_input": float(stagger),
                                            "flip": bool(flip)})

    @classmethod
    def from_selig(cls, text, stagger=0.0, pitch=None, solidity=None, chord=1.0, flip=False,
                   name=None):
        """Build a cascade blade from Selig- or Lednicer-format coordinate text."""
        nm, x, y, fmt = parse_airfoil_coordinates(text)
        blade = cls.from_airfoil(x, y, stagger, pitch, solidity, chord, flip, name or nm)
        blade.meta["format"] = fmt
        return blade

    @classmethod
    def read_airfoil(cls, path, **kw):
        """Read a Selig- or Lednicer-format ``.dat`` file (see :meth:`from_selig`)."""
        return cls.from_selig(Path(path).read_text(errors="replace"), **kw)

    def to_selig(self, normalise=True):
        """The contour as Selig-format text (chord-normalised by default)."""
        x, y = (normalise_airfoil(self.x, self.y, check=False) if normalise else (self.x, self.y))
        out = [self.name] + [f"{xv:10.6f} {yv:10.6f}" for xv, yv in zip(x, y)]
        return "\n".join(out) + "\n"

    def write_selig(self, path, normalise=True):
        """Write the contour as a Selig-format ``.dat`` file."""
        Path(path).write_text(self.to_selig(normalise))

    # ------------------------------------------------------------ MISES I/O
    @classmethod
    def read_mises(cls, path):
        """Read a MISES ``blade.xxx`` file.

        Format::

            NAME
            SINL SOUT CHINL CHOUT PITCH
            x y
            ...

        Only single-element blades are supported (a line ``999. 999.``
        separating elements terminates reading).
        """
        text = Path(path).read_text().splitlines()
        lines = [ln for ln in text if ln.strip()]
        name = lines[0].strip()
        hdr = [float(v) for v in lines[1].replace(",", " ").split()]
        if len(hdr) < 5:
            raise ValueError("MISES blade file: second line must hold SINL SOUT CHINL CHOUT PITCH")
        sinl, sout, chinl, chout, pitch = hdr[:5]
        pts = []
        for ln in lines[2:]:
            vals = ln.replace(",", " ").split()
            if len(vals) < 2:
                continue
            xv, yv = float(vals[0]), float(vals[1])
            if xv >= 999.0 and yv >= 999.0:
                break
            pts.append((xv, yv))
        arr = np.array(pts)
        blade = cls(arr[:, 0], arr[:, 1], pitch, name)
        blade.meta.update({"sinl": sinl, "sout": sout, "chinl": chinl, "chout": chout})
        return blade

    def write_mises(self, path, inlet_angle=None, exit_angle=None, chinl=None, chout=None):
        """Write the blade in MISES ``blade.xxx`` format."""
        a1, a2 = self.estimated_metal_angles()
        b1 = inlet_angle if inlet_angle is not None else a1
        b2 = exit_angle if exit_angle is not None else a2
        xmin, xmax = float(self.x.min()), float(self.x.max())
        chinl = chinl if chinl is not None else xmin - 1.0 * self.axial_chord
        chout = chout if chout is not None else xmax + 1.5 * self.axial_chord
        out = [self.name,
               f"{math.tan(math.radians(b1)):12.6f} {math.tan(math.radians(b2)):12.6f} "
               f"{chinl:12.6f} {chout:12.6f} {self.pitch:12.6f}"]
        out += [f"{xv:14.8f} {yv:14.8f}" for xv, yv in zip(self.x, self.y)]
        Path(path).write_text("\n".join(out) + "\n")

    # -------------------------------------------------------- H-grid support
    def axial_surfaces(self, sharpen_te=0.04):
        """Upper and lower surfaces as single-valued functions of x.

        Returns ``(x_le, x_te, f_upper, f_lower)``.  The contour is split at
        its minimum- and maximum-x points.  With ``sharpen_te > 0`` both
        surfaces are blended over that fraction of axial chord so that they
        meet at the TE midpoint (the Euler H-grid needs a closed TE).
        """
        s, sx, sy = self.spline()
        sd = np.linspace(0.0, s[-1], 4000)
        xd, yd = sx(sd), sy(sd)
        i_min = int(np.argmin(xd))
        # max-x on each side of the LE: the TE region spans both ends
        x_le = float(xd[i_min])
        up_x, up_y = xd[:i_min + 1][::-1], yd[:i_min + 1][::-1]
        lo_x, lo_y = xd[i_min:], yd[i_min:]
        iu = int(np.argmax(up_x))
        il = int(np.argmax(lo_x))
        up_x, up_y = up_x[:iu + 1], up_y[:iu + 1]
        lo_x, lo_y = lo_x[:il + 1], lo_y[:il + 1]
        for xx, nm in ((up_x, "upper"), (lo_x, "lower")):
            if np.any(np.diff(xx) < -1e-9 * self.axial_chord):
                raise ValueError(f"{nm} surface is not single-valued in x; the Euler "
                                 "H-grid cannot represent this blade")
        x_te = float(min(up_x[-1], lo_x[-1]))
        y_te = 0.5 * (np.interp(x_te, *_monotone(up_x, up_y))
                      + np.interp(x_te, *_monotone(lo_x, lo_y)))
        y_le = float(yd[i_min])
        fu = PchipInterpolator(*_monotone(up_x, up_y), extrapolate=True)
        fl = PchipInterpolator(*_monotone(lo_x, lo_y), extrapolate=True)
        cax = x_te - x_le

        def blend(f, xq):
            xq = np.asarray(xq, dtype=float)
            val = f(np.clip(xq, x_le, x_te))
            val = np.where(xq <= x_le, y_le, val)
            if sharpen_te > 0:
                t = np.clip((xq - (x_te - sharpen_te * cax)) / (sharpen_te * cax), 0.0, 1.0)
                w = t * t * (3 - 2 * t)
                val = val + w * (y_te - f(x_te))
            return val

        return x_le, x_te, (lambda xq: blend(fu, xq)), (lambda xq: blend(fl, xq))

    # -------------------------------------------------------------- export
    def to_dict(self):
        a1, a2 = self.estimated_metal_angles()
        return {
            "name": self.name,
            "x": self.x.tolist(),
            "y": self.y.tolist(),
            "pitch": self.pitch,
            "chord": self.chord,
            "axial_chord": self.axial_chord,
            "stagger_deg": self.stagger,
            "solidity": self.solidity,
            "max_thickness": self.max_thickness,
            "te_gap": self.te_gap,
            "inlet_metal_angle": a1,
            "exit_metal_angle": a2,
        }


def _monotone(x, y):
    """Sort (x, y) by x and drop duplicate abscissae for interpolation."""
    order = np.argsort(x, kind="mergesort")
    xs, ys = np.asarray(x)[order], np.asarray(y)[order]
    keep = np.concatenate([[True], np.diff(xs) > 1e-14])
    return xs[keep], ys[keep]
