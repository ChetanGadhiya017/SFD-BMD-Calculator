"""Beam analysis: reactions, shear force, bending moment, slope and deflection.

Sign conventions
----------------
* x is measured from the left end (0 … L).
* Point loads and distributed-load intensities are positive **downwards**.
* Applied moments are positive **clockwise**.
* Reactions are positive **upwards**.
* Shear force V(x): sum of vertical forces to the left of the section, upward positive.
* Bending moment M(x): sagging positive.
* Deflection y(x): upward positive (so a loaded simply supported beam has y < 0).

Supports
--------
* ``simply_supported``    pin at ``support_a`` + roller at ``support_b`` (move them inward for overhangs)
* ``cantilever``          fixed at x = 0, free at x = L
* ``propped_cantilever``  fixed at x = 0, roller at ``support_b`` (default L)   — statically indeterminate
* ``fixed_fixed``         fixed at both ends                                   — statically indeterminate

Indeterminate beams are solved with the method of consistent deformations
(primary structure: cantilever fixed at x = 0; redundants: reactions at the right
support), assuming constant EI. Their reactions do not depend on the value of EI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

EPS = 1e-9

SUPPORT_TYPES = ("simply_supported", "cantilever", "propped_cantilever", "fixed_fixed")
SUPPORT_LABELS = {
    "simply_supported": "Simply supported / overhanging",
    "cantilever": "Cantilever (fixed at left)",
    "propped_cantilever": "Propped cantilever",
    "fixed_fixed": "Fixed at both ends",
}


class BeamError(ValueError):
    """Invalid beam definition."""


# --------------------------------------------------------------------------- loads
@dataclass
class PointLoad:
    magnitude: float
    position: float


@dataclass
class DistributedLoad:
    """Linearly varying load: ``w_start`` at ``start`` to ``w_end`` at ``end``.

    Equal intensities give a UDL; one zero gives a triangular load."""

    w_start: float
    w_end: float
    start: float
    end: float

    @property
    def span(self) -> float:
        return self.end - self.start

    @property
    def intensity(self) -> float:  # backwards compatibility for UDLs
        return self.w_start

    @property
    def total(self) -> float:
        return 0.5 * (self.w_start + self.w_end) * self.span

    @property
    def first_moment_from_start(self) -> float:
        """∫ w(s)·s ds over the load, with s measured from ``start``."""
        n = self.span
        return self.w_start * n * n / 2 + (self.w_end - self.w_start) * n * n / 3

    @property
    def centroid(self) -> float:
        if abs(self.total) < 1e-15:
            return 0.5 * (self.start + self.end)
        return self.start + self.first_moment_from_start / self.total

    @property
    def is_uniform(self) -> bool:
        return abs(self.w_start - self.w_end) < 1e-12

    def shear_and_moment(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Resultant force of the part left of x, and its moment about x."""
        n = self.span
        c = np.clip(x - self.start, 0.0, n)  # loaded length left of the section
        k = (self.w_end - self.w_start) / n
        force = self.w_start * c + k * c * c / 2
        first = self.w_start * c * c / 2 + k * c**3 / 3  # ∫0^c w(s)·s ds
        moment = (x - self.start) * force - first
        return force, moment


def UDL(intensity: float, start: float, end: float) -> DistributedLoad:  # noqa: N802 - public API name
    """Uniformly distributed load."""
    return DistributedLoad(intensity, intensity, start, end)


@dataclass
class MomentLoad:
    magnitude: float  # clockwise positive
    position: float


# --------------------------------------------------------------------------- beam
@dataclass
class Beam:
    length: float
    kind: str = "simply_supported"
    support_a: float | None = None
    support_b: float | None = None
    point_loads: list[PointLoad] = field(default_factory=list)
    udls: list[DistributedLoad] = field(default_factory=list)
    moments: list[MomentLoad] = field(default_factory=list)
    EI: float | None = None  # flexural rigidity, in force·length² units

    def __post_init__(self) -> None:
        try:
            L = float(self.length)
        except (TypeError, ValueError):
            raise BeamError("Beam length must be a number") from None
        if not np.isfinite(L) or L <= 0:
            raise BeamError("Beam length must be positive")
        self.length = L
        if self.kind not in SUPPORT_TYPES:
            raise BeamError(f"Unknown beam type '{self.kind}'")

        if self.kind == "simply_supported":
            self.support_a = 0.0 if self.support_a is None else float(self.support_a)
            self.support_b = L if self.support_b is None else float(self.support_b)
        elif self.kind == "propped_cantilever":
            self.support_a = 0.0
            self.support_b = L if self.support_b is None else float(self.support_b)
        else:
            self.support_a = 0.0
            self.support_b = L if self.kind == "fixed_fixed" else None

        for name, s in (("A", self.support_a), ("B", self.support_b)):
            if s is not None and not -EPS <= s <= L + EPS:
                raise BeamError(f"Support {name} must lie on the beam (0 … {L:g})")
        if self.support_b is not None and self.support_b - self.support_a <= EPS:
            raise BeamError("Support B must be to the right of support A")

        for p in self.point_loads:
            self._check_pos(p.position, "Point load")
        for m in self.moments:
            self._check_pos(m.position, "Moment")
        for u in self.udls:
            self._check_pos(u.start, "Distributed load start")
            self._check_pos(u.end, "Distributed load end")
            if u.end - u.start <= EPS:
                raise BeamError("A distributed load must end after it starts")
        if self.EI is not None:
            self.EI = float(self.EI)
            if not np.isfinite(self.EI) or self.EI <= 0:
                raise BeamError("EI must be a positive number")

    def _check_pos(self, x: float, what: str) -> None:
        if not -EPS <= x <= self.length + EPS:
            raise BeamError(f"{what} at x = {x:g} is outside the beam (0 … {self.length:g})")

    @property
    def is_indeterminate(self) -> bool:
        return self.kind in ("propped_cantilever", "fixed_fixed")

    @property
    def total_load(self) -> float:
        return sum(p.magnitude for p in self.point_loads) + sum(u.total for u in self.udls)

    def key_points(self) -> list[float]:
        pts = {0.0, self.length}
        pts.update(p.position for p in self.point_loads)
        pts.update(m.position for m in self.moments)
        for u in self.udls:
            pts.update((u.start, u.end))
        pts.update(s for s in (self.support_a, self.support_b) if s is not None)
        return sorted(pts)


# --------------------------------------------------------------------------- core maths
@dataclass
class _Reactions:
    forces: list[tuple[str, float, float]]   # (name, x, upward force)
    couples: list[tuple[str, float, float]]  # (name, x, clockwise couple)


def _step(x: np.ndarray, pos: float, L: float) -> np.ndarray:
    """1 where a concentrated action at ``pos`` is left of the section."""
    if pos <= EPS:
        return np.ones_like(x, dtype=bool)
    return (x > pos + 1e-12) | ((x >= L - 1e-12) & (pos >= L - 1e-12))


def _internal(beam: Beam, x: np.ndarray, rx: _Reactions) -> tuple[np.ndarray, np.ndarray]:
    L = beam.length
    V = np.zeros_like(x, dtype=float)
    M = np.zeros_like(x, dtype=float)
    for _, pos, r in rx.forces:
        h = _step(x, pos, L)
        V += r * h
        M += r * (x - pos) * h
    for _, pos, c in rx.couples:
        if pos >= L - 1e-12:
            continue  # reaction couple at the right boundary only closes M(L+) = 0
        M += c * _step(x, pos, L)
    for p in beam.point_loads:
        h = _step(x, p.position, L)
        V -= p.magnitude * h
        M -= p.magnitude * (x - p.position) * h
    for u in beam.udls:
        f, m = u.shear_and_moment(x)
        V -= f
        M -= m
    for m in beam.moments:
        M += m.magnitude * _step(x, m.position, L)
    return V, M


def _load_moment_about(beam: Beam, a: float) -> float:
    """Clockwise moment of all applied loads about point a."""
    return (
        sum(p.magnitude * (p.position - a) for p in beam.point_loads)
        + sum(u.total * (u.start - a) + u.first_moment_from_start for u in beam.udls)
        + sum(m.magnitude for m in beam.moments)
    )


def _cantilever_reactions(beam: Beam, extra_force: tuple[float, float] | None = None,
                          extra_couple: tuple[float, float] | None = None) -> _Reactions:
    """Fixed at x=0. Optional extra upward force / clockwise couple (redundants)."""
    F = beam.total_load
    Mo = _load_moment_about(beam, 0.0)
    forces, couples = [], []
    if extra_force:
        xb, rb = extra_force
        F -= rb
        Mo -= rb * xb  # upward force gives an anticlockwise moment about A
        forces.append(("R_B", xb, rb))
    if extra_couple:
        xc, cb = extra_couple
        Mo += cb
        couples.append(("C_B", xc, cb))
    # ΣFy = 0 → R_A = F ;  ΣM_A = 0 → C_A = -Mo   (C_A clockwise couple at the wall)
    return _Reactions(forces=[("R_A", 0.0, F)] + forces, couples=[("C_A", 0.0, -Mo)] + couples)


def _double_integrate(x: np.ndarray, M: np.ndarray, EI: float) -> tuple[np.ndarray, np.ndarray]:
    """θ(x) = ∫ M/EI dx and y(x) = ∫ θ dx from x=0 with zero constants."""
    k = M / EI
    dx = np.diff(x)
    theta = np.concatenate([[0.0], np.cumsum(0.5 * (k[1:] + k[:-1]) * dx)])
    y = np.concatenate([[0.0], np.cumsum(0.5 * (theta[1:] + theta[:-1]) * dx)])
    return theta, y


def _interp(x: np.ndarray, f: np.ndarray, at: float) -> float:
    return float(np.interp(at, x, f))


def _sample_x(beam: Beam, n: int) -> np.ndarray:
    """Dense grid that also contains both sides of every discontinuity."""
    L = beam.length
    d = L * 1e-9
    xs = [np.linspace(0, L, n)]
    for k in beam.key_points():
        xs.append(np.array([max(0.0, k - d), k, min(L, k + d)]))
    return np.unique(np.concatenate(xs))


# --------------------------------------------------------------------------- result
@dataclass
class Segment:
    start: float
    end: float
    shear: list[float]   # polynomial coefficients, highest power first, in global x
    moment: list[float]


@dataclass
class Result:
    beam: Beam
    reactions: dict[str, float]
    support_moments: dict[str, float]
    x: np.ndarray
    shear: np.ndarray
    moment: np.ndarray
    slope: np.ndarray | None
    deflection: np.ndarray | None
    working: list[str]
    segments: list[Segment]

    # Backwards-compatible alias (cantilever fixed-end moment)
    @property
    def fixed_end_moment(self) -> float | None:
        return self.support_moments.get("M_A")

    def _extreme(self, arr: np.ndarray, fn) -> tuple[float, float]:
        i = int(fn(arr))
        return float(arr[i]), float(self.x[i])

    @property
    def max_shear(self) -> tuple[float, float]:
        return self._extreme(self.shear, lambda a: np.argmax(np.abs(a)))

    @property
    def max_moment(self) -> tuple[float, float]:
        return self._extreme(self.moment, np.argmax)

    @property
    def min_moment(self) -> tuple[float, float]:
        return self._extreme(self.moment, np.argmin)

    @property
    def max_deflection(self) -> tuple[float, float] | None:
        if self.deflection is None:
            return None
        return self._extreme(self.deflection, lambda a: np.argmax(np.abs(a)))

    @property
    def contraflexure_points(self) -> list[float]:
        """x where the bending moment changes sign smoothly inside the beam."""
        tol = 1e-6 * max(1.0, float(np.max(np.abs(self.moment))))
        m, x = self.moment, self.x
        nz = np.abs(m) > tol
        xs, ms = x[nz], m[nz]
        points: list[float] = []
        for i in range(len(xs) - 1):
            a, b = ms[i], ms[i + 1]
            if a * b > 0:
                continue
            gap = xs[i + 1] - xs[i]
            if gap > 0.01 * self.beam.length or gap < 1e-6 * self.beam.length:
                continue  # zero-moment stretch, or a jump caused by an applied couple
            xc = xs[i] - a * gap / (b - a)
            if EPS < xc < self.beam.length - EPS and (not points or xc - points[-1] > 1e-6):
                points.append(float(xc))
        return points

    def to_dict(self, series: bool = False, max_points: int = 1500) -> dict:
        vmax, xv = self.max_shear
        mmax, xm = self.max_moment
        mmin, xn = self.min_moment
        out = {
            "beam": {
                "kind": self.beam.kind,
                "length": self.beam.length,
                "support_a": self.beam.support_a,
                "support_b": self.beam.support_b,
                "EI": self.beam.EI,
                "determinate": not self.beam.is_indeterminate,
            },
            "reactions": self.reactions,
            "support_moments": self.support_moments,
            "fixed_end_moment": self.fixed_end_moment,
            "max_shear": {"value": vmax, "x": xv},
            "max_sagging_moment": {"value": mmax, "x": xm},
            "max_hogging_moment": {"value": mmin, "x": xn},
            "contraflexure_points": self.contraflexure_points,
            "max_deflection": None,
            "working": self.working,
            "segments": [s.__dict__ for s in self.segments],
        }
        if self.max_deflection is not None:
            d, xd = self.max_deflection
            out["max_deflection"] = {"value": d, "x": xd}
        if series:
            idx = _thin(self.x, self.beam.key_points(), max_points)
            out["series"] = {
                "x": self.x[idx].tolist(),
                "shear": self.shear[idx].tolist(),
                "moment": self.moment[idx].tolist(),
                "slope": self.slope[idx].tolist() if self.slope is not None else None,
                "deflection": self.deflection[idx].tolist() if self.deflection is not None else None,
            }
        return out


def _thin(x: np.ndarray, keys: list[float], max_points: int) -> np.ndarray:
    """Down-sample for transport while keeping both sides of every discontinuity."""
    if len(x) <= max_points:
        return np.arange(len(x))
    keep = set(np.linspace(0, len(x) - 1, max_points).astype(int).tolist())
    for k in keys:
        i = int(np.searchsorted(x, k))
        keep.update(j for j in (i - 2, i - 1, i, i + 1, i + 2) if 0 <= j < len(x))
    return np.array(sorted(keep))


# --------------------------------------------------------------------------- solve
def _fmt(v: float) -> str:
    return f"{v:.4g}"


def _segments(beam: Beam, rx: _Reactions) -> list[Segment]:
    pts = beam.key_points()
    segs = []
    for a, b in zip(pts[:-1], pts[1:], strict=False):
        if b - a < 1e-9 * beam.length:
            continue
        xs = np.linspace(a, b, 9)[1:-1]
        V, M = _internal(beam, xs, rx)
        cv = np.polyfit(xs, V, 2)
        cm = np.polyfit(xs, M, 3)
        scale = max(1.0, float(np.max(np.abs(M))), float(np.max(np.abs(V))))

        tol = 1e-9 * scale
        segs.append(Segment(float(a), float(b),
                            [0.0 if abs(v) < tol else float(v) for v in cv],
                            [0.0 if abs(v) < tol else float(v) for v in cm]))
    return segs


def solve(beam: Beam, samples: int = 2001) -> Result:
    L = beam.length
    x = _sample_x(beam, samples)
    working: list[str] = []
    W = beam.total_load

    if beam.kind == "simply_supported":
        a, b = beam.support_a, beam.support_b
        Mo = _load_moment_about(beam, a)
        rb = Mo / (b - a)
        ra = W - rb
        rx = _Reactions([("R_A", a, ra), ("R_B", b, rb)], [])
        working += [
            f"Total downward load: ΣW = {_fmt(W)}",
            f"ΣM about A (x = {_fmt(a)}) = 0 → R_B × {_fmt(b - a)} = {_fmt(Mo)}  ⇒  R_B = {_fmt(rb)}",
            f"ΣFy = 0 → R_A = ΣW − R_B = {_fmt(W)} − {_fmt(rb)}  ⇒  R_A = {_fmt(ra)}",
        ]
    elif beam.kind == "cantilever":
        rx = _cantilever_reactions(beam)
        working += [
            f"ΣFy = 0 → R_A = ΣW = {_fmt(W)}",
            f"ΣM about A = 0 → fixed-end moment M_A = −{_fmt(_load_moment_about(beam, 0))}"
            f" = {_fmt(rx.couples[0][2])} (hogging)",
        ]
    else:
        # Method of consistent deformations on the cantilever primary structure (EI = 1).
        xb = beam.support_b
        rx0 = _cantilever_reactions(beam)
        _, M0 = _internal(beam, x, rx0)
        t0, y0 = _double_integrate(x, M0, 1.0)

        empty = Beam(L, kind="cantilever")
        rxf = _cantilever_reactions(empty, extra_force=(xb, 1.0))
        _, Mf = _internal(empty, x, rxf)
        tf, yf = _double_integrate(x, Mf, 1.0)

        if beam.kind == "propped_cantilever":
            rb = -_interp(x, y0, xb) / _interp(x, yf, xb)
            rx = _cantilever_reactions(beam, extra_force=(xb, rb))
            working += [
                "Statically indeterminate (degree 1): remove the prop at B and use consistent deformations.",
                f"Deflection at B from loads on the cantilever: δ_B0 = {_fmt(_interp(x, y0, xb))}/EI",
                f"Deflection at B from a unit upward force at B: f_BB = {_fmt(_interp(x, yf, xb))}/EI",
                f"Compatibility δ_B = 0 → R_B = −δ_B0 / f_BB = {_fmt(rb)}",
            ]
        else:
            rxc = _cantilever_reactions(empty, extra_couple=(L, 1.0))
            _, Mc = _internal(empty, x, rxc)
            tc, yc = _double_integrate(x, Mc, 1.0)
            A = np.array([[yf[-1], yc[-1]], [tf[-1], tc[-1]]])
            rhs = -np.array([y0[-1], t0[-1]])
            rb, cb = np.linalg.solve(A, rhs)
            rx = _cantilever_reactions(beam, extra_force=(L, rb), extra_couple=(L, cb))
            working += [
                "Statically indeterminate (degree 2): release the right end, redundants R_B and C_B.",
                "Compatibility at B: deflection = 0 and slope = 0  →  2 × 2 linear system",
                f"Solved: R_B = {_fmt(rb)}, end couple C_B = {_fmt(cb)}",
            ]
        working.append(
            f"Equilibrium of the whole beam → R_A = {_fmt(rx.forces[0][2])}, "
            f"wall couple C_A = {_fmt(rx.couples[0][2])}"
        )

    V, M = _internal(beam, x, rx)
    scale = max(1.0, float(np.max(np.abs(M))), float(np.max(np.abs(V))))
    V[np.abs(V) < 1e-10 * scale] = 0.0
    M[np.abs(M) < 1e-10 * scale] = 0.0

    reactions = {name: float(r) for name, _, r in rx.forces}
    support_moments: dict[str, float] = {}
    if beam.kind != "simply_supported":
        support_moments["M_A"] = float(M[0])
    if beam.kind == "fixed_fixed":
        support_moments["M_B"] = float(M[-1])

    slope = deflection = None
    if beam.EI:
        theta, y = _double_integrate(x, M, beam.EI)
        if beam.kind == "simply_supported":
            a, b = beam.support_a, beam.support_b
            ya, yb = _interp(x, y, a), _interp(x, y, b)
            c1 = -(yb - ya) / (b - a)
            c0 = -ya - c1 * a
            theta = theta + c1
            y = y + c1 * x + c0
        # cantilever-based supports already satisfy θ(0) = y(0) = 0
        slope, deflection = theta, y
        working.append("Slope θ = ∫M/EI dx and deflection y = ∫θ dx, constants from the support conditions.")

    return Result(
        beam=beam,
        reactions=reactions,
        support_moments=support_moments,
        x=x,
        shear=V,
        moment=M,
        slope=slope,
        deflection=deflection,
        working=working,
        segments=_segments(beam, rx),
    )
