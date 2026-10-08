"""Flask web interface for the SFD & BMD calculator.

Run:  python app.py   →  http://127.0.0.1:5000
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from beam_solver import UDL, Beam, BeamError, MomentLoad, PointLoad, solve
from beam_solver.plotting import render_base64

app = Flask(__name__)

FORCE_UNITS = ["kN", "N", "kgf", "lbf", "kip"]
LENGTH_UNITS = ["m", "mm", "cm", "ft", "in"]

EXAMPLES = {
    "simple": {
        "label": "Simply supported · point load + UDL",
        "kind": "simply_supported", "length": 8, "support_a": 0, "support_b": 8,
        "point_loads": [[20, 3]], "udls": [[5, 4, 8]], "moments": [],
    },
    "overhang": {
        "label": "Overhanging beam · contraflexure",
        "kind": "simply_supported", "length": 6, "support_a": 0, "support_b": 4.5,
        "point_loads": [[10, 2], [3, 6]], "udls": [[2, 0, 6]], "moments": [[5, 3.5]],
    },
    "cantilever": {
        "label": "Cantilever · tip load + UDL",
        "kind": "cantilever", "length": 3, "support_a": None, "support_b": None,
        "point_loads": [[4, 3]], "udls": [[2, 0, 3]], "moments": [],
    },
}


def _num(value, name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise BeamError(f"'{name}' must be a number") from None


def beam_from_mapping(data: dict) -> Beam:
    """Build a Beam from JSON or flattened form data (lists of lists)."""
    kind = data.get("kind", "simply_supported")
    length = _num(data.get("length"), "Beam length")
    sa = data.get("support_a")
    sb = data.get("support_b")
    return Beam(
        length=length,
        kind=kind,
        support_a=_num(sa, "Support A") if sa not in (None, "") and kind != "cantilever" else None,
        support_b=_num(sb, "Support B") if sb not in (None, "") and kind != "cantilever" else None,
        point_loads=[PointLoad(_num(p, "Load"), _num(x, "Load position")) for p, x in data.get("point_loads", [])],
        udls=[UDL(_num(w, "UDL intensity"), _num(a, "UDL start"), _num(b, "UDL end"))
              for w, a, b in data.get("udls", [])],
        moments=[MomentLoad(_num(m, "Moment"), _num(x, "Moment position")) for m, x in data.get("moments", [])],
    )


def _form_rows(prefix: str, fields: list[str]) -> list[list[str]]:
    cols = [request.form.getlist(f"{prefix}_{f}") for f in fields]
    rows = []
    for values in zip(*cols, strict=False):
        if all(v.strip() == "" for v in values):
            continue  # ignore completely empty rows
        rows.append(list(values))
    return rows


def _form_to_mapping() -> dict:
    return {
        "kind": request.form.get("kind", "simply_supported"),
        "length": request.form.get("length"),
        "support_a": request.form.get("support_a"),
        "support_b": request.form.get("support_b"),
        "point_loads": _form_rows("pl", ["p", "x"]),
        "udls": _form_rows("udl", ["w", "a", "b"]),
        "moments": _form_rows("m", ["m", "x"]),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    fu = request.values.get("force_unit", "kN")
    lu = request.values.get("length_unit", "m")
    ctx = {"force_units": FORCE_UNITS, "length_units": LENGTH_UNITS, "examples": EXAMPLES, "fu": fu, "lu": lu}

    if request.method == "GET":
        ex = EXAMPLES.get(request.args.get("example", "simple"), EXAMPLES["simple"])
        return render_template("index.html", form=ex, **ctx)

    form = _form_to_mapping()
    try:
        result = solve(beam_from_mapping(form))
    except BeamError as exc:
        return render_template("index.html", form=form, error=str(exc), **ctx), 400

    return render_template(
        "index.html", form=form, result=result.to_dict(), plot=render_base64(result, fu, lu), **ctx
    )


@app.post("/api/solve")
def api_solve():
    """JSON API. Example body:
    {"kind": "simply_supported", "length": 6, "point_loads": [[10, 2]], "udls": [[2, 0, 6]]}
    """
    try:
        result = solve(beam_from_mapping(request.get_json(force=True) or {}))
    except BeamError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(result.to_dict())


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
