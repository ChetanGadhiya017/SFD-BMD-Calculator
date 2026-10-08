"""Statically determinate beam analysis.

Sign conventions
----------------
* x is measured from the left end (0 … L).
* Point loads and UDL intensities are positive **downwards**.
* Applied moments are positive **clockwise**.
* Reactions are positive **upwards**.
* Shear force V(x): sum of vertical forces to the left of the section, upward positive.
* Bending moment M(x): sagging positive (sum of clockwise moments of the forces to
  the left of the section, taken about the section).

Supported beams
---------------
* ``simply_supported`` – pin at ``support_a`` and roller at ``support_b``
  (defaults 0 and L; move them inward to model overhanging beams).
* ``cantilever`` – fixed at x = 0, free at x = L.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

EPS = 1e-9


class BeamError(ValueError):
    """Invalid beam definition."""


@dataclass
class PointLoad:
    magnitude: float
    position: float


@dataclass
class UDL:
    intensity: float  # load per unit length
    start: float
    end: float

    @property
    def total(self) -> float:
        return self.intensity * (self.end - self.start)

    @property
    def centroid(self) -> float:
        return 0.5 * (self.start + self.end)


@dataclass
class MomentLoad:
    magnitude: float  # clockwise positive
    position: float


@dataclass
class Beam:
    length: float
    kind: str = "simply_supported"
    support_a: float | None = None
    support_b: float | None = None
    point_loads: list[PointLoad] = field(default_factory=list)
    udls: list[UDL] = field(default_factory=list)
    moments: list[MomentLoad] = field(default_factory=list)

    def __post_init__(self) -> None:
        L = self.length
        if not L or L <= 0:
            raise BeamError("Beam length must be positive")
        if self.kind not in ("simply_supported", "cantilever"):
            raise BeamError(f"Unknown beam type '{self.kind}'")
        if self.kind == "simply_supported":
            self.support_a = 0.0 if self.support_a is None else float(self.support_a)
            self.support_b = L if self.support_b is None else float(self.support_b)
            for name, s in (("A", self.support_a), ("B", self.support_b)):
                if not 0 <= s <= L:
                    raise BeamError(f"Support {name} must lie on the beam (0 … {L})")
            if self.support_b - self.support_a <= EPS:
                raise BeamError("Support B must be to the right of support A")
        for p in self.point_loads:
            self._check_pos(p.position, "Point load")
        for m in self.moments:
            self._check_pos(m.position, "Moment")
        for u in self.udls:
            self._check_pos(u.start, "UDL start")
            self._check_pos(u.end, "UDL end")
            if u.end - u.start <= EPS:
                raise BeamError("UDL end must be after its start")

    def _check_pos(self, x: float, what: str) -> None:
        if not -EPS <= x <= self.length + EPS:
            raise BeamError(f"{what} at x = {x} is outside the beam (0 … {self.length})")

    @property
    def total_load(self) -> float:
        return sum(p.magnitude for p in self.point_loads) + sum(u.total for u in self.udls)

    def key_points(self) -> list[float]:
        pts = {0.0, self.length}
        pts.update(p.position for p in self.point_loads)
        pts.update(m.position for m in self.moments)
        for u in self.udls:
            pts.update((u.start, u.end))
        if self.kind == "simply_supported":
            pts.update((self.support_a, self.support_b))
        return sorted(pts)


@dataclass
class Result:
    beam: Beam
    reactions: dict[str, float]
    fixed_end_moment: float | None
    x: np.ndarray
    shear: np.ndarray
    moment: np.ndarray

    def _extreme(self, arr: np.ndarray, fn) -> tuple[float, float]:
        i = int(fn(arr))
        return float(arr[i]), float(self.x[i])

    @property
    def max_shear(self) -> tuple[float, float]:
        """(value, x) of the largest |V|."""
        return self._extreme(self.shear, lambda a: np.argmax(np.abs(a)))

    @property
    def max_moment(self) -> tuple[float, float]:
        """(value, x) of the most positive (sagging) moment."""
        return self._extreme(self.moment, np.argmax)

    @property
    def min_moment(self) -> tuple[float, float]:
        """(value, x) of the most negative (hogging) moment."""
        return self._extreme(self.moment, np.argmin)

    @property
    def contraflexure_points(self) -> list[float]:
        """x where the bending moment changes sign inside the beam."""
        tol = 1e-6 * max(1.0, float(np.max(np.abs(self.moment))))
        m, x = self.moment, self.x
        nz = np.abs(m) > tol
        xs, ms = x[nz], m[nz]  # ignore samples that are (numerically) zero
        points: list[float] = []
        for i in range(len(xs) - 1):
            a, b = ms[i], ms[i + 1]
            if a * b > 0:
                continue
            if xs[i + 1] - xs[i] > 0.01 * self.beam.length:
                # long run of zero moment (e.g. unloaded segment) is not contraflexure
                continue
            if xs[i + 1] - xs[i] < 1e-6 * self.beam.length:
                continue  # sign flip across a jump (applied couple), not a smooth zero
            xc = xs[i] - a * (xs[i + 1] - xs[i]) / (b - a)
            if EPS < xc < self.beam.length - EPS and (not points or xc - points[-1] > 1e-6):
                points.append(float(xc))
        return points

    def to_dict(self) -> dict:
        vmax, xv = self.max_shear
        mmax, xm = self.max_moment
        mmin, xn = self.min_moment
        return {
            "reactions": self.reactions,
            "fixed_end_moment": self.fixed_end_moment,
            "max_shear": {"value": vmax, "x": xv},
            "max_sagging_moment": {"value": mmax, "x": xm},
            "max_hogging_moment": {"value": mmin, "x": xn},
            "contraflexure_points": self.contraflexure_points,
        }


def _reactions(beam: Beam) -> tuple[dict[str, float], float | None]:
    P = beam.point_loads
    W = beam.udls
    Mc = beam.moments
    if beam.kind == "cantilever":
        R = beam.total_load
        # Moment equilibrium about the wall gives the fixed-end moment (sagging sign).
        MA = -(sum(p.magnitude * p.position for p in P) + sum(u.total * u.centroid for u in W)
               + sum(m.magnitude for m in Mc))
        return {"R_A": R}, MA

    a, b = beam.support_a, beam.support_b
    # ΣM about A = 0  ->  R_B (b - a) = Σ P (x - a) + Σ W (c - a) + Σ M_cw
    rb = (sum(p.magnitude * (p.position - a) for p in P)
          + sum(u.total * (u.centroid - a) for u in W)
          + sum(m.magnitude for m in Mc)) / (b - a)
    ra = beam.total_load - rb
    return {"R_A": ra, "R_B": rb}, None


def _sample_x(beam: Beam, n: int) -> np.ndarray:
    """Dense grid that also contains both sides of every discontinuity,
    so jumps in V and M are drawn as vertical lines and extremes are exact."""
    L = beam.length
    d = L * 1e-9
    xs = [np.linspace(0, L, n)]
    for k in beam.key_points():
        xs.append(np.array([max(0.0, k - d), k, min(L, k + d)]))
    return np.unique(np.concatenate(xs))


def solve(beam: Beam, samples: int = 2001) -> Result:
    reactions, MA = _reactions(beam)
    x = _sample_x(beam, samples)

    V = np.zeros_like(x)
    M = np.zeros_like(x)

    def step(pos: float) -> np.ndarray:
        # A load exactly at the section belongs to the left part only from x+ onward,
        # except at the right end where everything has been applied.
        return (x > pos + 1e-12) | ((x >= beam.length - 1e-12) & (pos >= beam.length - 1e-12))

    # Reactions
    if beam.kind == "cantilever":
        V += reactions["R_A"]
        M += reactions["R_A"] * x + MA
    else:
        for pos, r in ((beam.support_a, reactions["R_A"]), (beam.support_b, reactions["R_B"])):
            h = step(pos) if pos > 0 else np.ones_like(x, bool)
            V += r * h
            M += r * (x - pos) * h

    for p in beam.point_loads:
        h = step(p.position) if p.position > 0 else np.ones_like(x, bool)
        V -= p.magnitude * h
        M -= p.magnitude * (x - p.position) * h

    for u in beam.udls:
        covered = np.clip(x - u.start, 0, u.end - u.start)  # loaded length left of section
        V -= u.intensity * covered
        # resultant of covered part acts at its centroid
        M -= u.intensity * covered * (x - (u.start + covered / 2))

    for m in beam.moments:
        h = step(m.position) if m.position > 0 else np.ones_like(x, bool)
        M += m.magnitude * h

    # Clean floating-point noise (e.g. 1e-15 at free ends)
    scale = max(1.0, float(np.max(np.abs(M))), float(np.max(np.abs(V))))
    V[np.abs(V) < 1e-10 * scale] = 0.0
    M[np.abs(M) < 1e-10 * scale] = 0.0

    return Result(beam, reactions, MA, x, V, M)
