"""Command-line interface.

Examples
--------
python -m beam_solver --length 6 --point 10@2
python -m beam_solver --length 6 --supports 0 4.5 --udl 2@0-6 --point 10@2 --point 3@6 --moment 5@3.5 --plot beam.png
python -m beam_solver --length 3 --cantilever --point 4@3 --udl 2@0-3
python -m beam_solver -L 8 --support fixed_fixed --vload 2,6@0-5 --point 10@6 --EI 20000 --equations
"""

from __future__ import annotations

import argparse
import sys

from . import SUPPORT_TYPES, UDL, Beam, BeamError, DistributedLoad, MomentLoad, PointLoad, solve
from .plotting import poly_to_text


def _pair(text: str) -> tuple[float, float]:
    value, at = text.split("@")
    return float(value), float(at)


def _udl(text: str) -> UDL:
    w, rng = text.split("@")
    a, b = rng.split("-")
    return UDL(float(w), float(a), float(b))


def _vload(text: str) -> DistributedLoad:
    ws, rng = text.split("@")
    w1, w2 = ws.split(",")
    a, b = rng.split("-")
    return DistributedLoad(float(w1), float(w2), float(a), float(b))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m beam_solver", description="Shear force & bending moment calculator")
    p.add_argument("--length", "-L", type=float, required=True, help="beam length")
    p.add_argument("--cantilever", action="store_true", help="shortcut for --support cantilever")
    p.add_argument("--support", choices=SUPPORT_TYPES, default="simply_supported")
    p.add_argument("--supports", nargs=2, type=float, metavar=("A", "B"), help="support positions (default 0 and L)")
    p.add_argument("--point", action="append", default=[], metavar="P@x", help="point load, e.g. 10@2 (repeatable)")
    p.add_argument("--udl", action="append", default=[], metavar="w@a-b", help="UDL, e.g. 2@0-6 (repeatable)")
    p.add_argument("--vload", action="append", default=[], metavar="w1,w2@a-b",
                   help="linearly varying load, e.g. 0,6@0-4 (repeatable)")
    p.add_argument("--EI", type=float, help="flexural rigidity, enables deflection")
    p.add_argument("--equations", action="store_true", help="print working and segment equations")
    p.add_argument("--moment", action="append", default=[], metavar="M@x", help="clockwise moment, e.g. 5@3.5")
    p.add_argument("--force-unit", default="kN")
    p.add_argument("--length-unit", default="m")
    p.add_argument("--plot", metavar="FILE.png", help="save beam + SFD + BMD figure")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fu, lu = args.force_unit, args.length_unit
    try:
        beam = Beam(
            length=args.length,
            kind="cantilever" if args.cantilever else args.support,
            support_a=args.supports[0] if args.supports else None,
            support_b=args.supports[1] if args.supports else None,
            point_loads=[PointLoad(*_pair(s)) for s in args.point],
            udls=[_udl(s) for s in args.udl] + [_vload(s) for s in args.vload],
            EI=args.EI,
            moments=[MomentLoad(*_pair(s)) for s in args.moment],
        )
    except (BeamError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = solve(beam)
    res = result.to_dict()
    print("Reactions")
    for k, v in res["reactions"].items():
        print(f"  {k:<4} = {v:10.3f} {fu}")
    for k, v in res["support_moments"].items():
        print(f"  {k:<4} = {v:10.3f} {fu}·{lu}")
    print("Extremes")
    print(f"  |V|max   = {abs(res['max_shear']['value']):10.3f} {fu}      at x = {res['max_shear']['x']:.3f} {lu}")
    print(f"  M sag    = {res['max_sagging_moment']['value']:10.3f} {fu}·{lu}   at x = {res['max_sagging_moment']['x']:.3f} {lu}")
    print(f"  M hog    = {res['max_hogging_moment']['value']:10.3f} {fu}·{lu}   at x = {res['max_hogging_moment']['x']:.3f} {lu}")
    cf = res["contraflexure_points"]
    print(f"  Contraflexure at x = {', '.join(f'{x:.3f}' for x in cf) if cf else 'none'}")

    if res["max_deflection"]:
        md = res["max_deflection"]
        print(f"  y max    = {md['value']:10.4g} {lu}       at x = {md['x']:.3f} {lu}")
    if args.equations:
        print("Working")
        for w in result.working:
            print("  " + w)
        print("Equations")
        for s in result.segments:
            print(f"  {s.start:g} < x < {s.end:g}:  V = {poly_to_text(s.shear)}   M = {poly_to_text(s.moment)}")

    if args.plot:
        from .plotting import render_png

        with open(args.plot, "wb") as fh:
            fh.write(render_png(result, fu, lu))
        print(f"Saved diagrams to {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
