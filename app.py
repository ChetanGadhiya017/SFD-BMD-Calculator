"""SFD & BMD Calculator — Flask application.

Development:  python app.py            → http://127.0.0.1:5000
Production:   gunicorn "app:create_app()" --bind 0.0.0.0:8000
"""

from __future__ import annotations

import csv
import io
import os
import re

from flask import Flask, Response, jsonify, render_template, request

from beam_solver import (
    SUPPORT_LABELS,
    Beam,
    BeamError,
    DistributedLoad,
    MomentLoad,
    PointLoad,
    __version__,
    solve,
)

MAX_LOADS = 50
FORCE_UNITS = ["kN", "N", "kgf", "lbf", "kip"]
LENGTH_UNITS = ["m", "mm", "cm", "ft", "in"]

PRESETS = {
    "simple": {
        "name": "Simply supported · point load + UDL",
        "kind": "simply_supported", "length": 8, "support_a": 0, "support_b": 8, "EI": 20000,
        "point_loads": [{"P": 20, "x": 3}], "distributed": [{"w1": 5, "w2": 5, "a": 4, "b": 8}], "moments": [],
    },
    "overhang": {
        "name": "Overhanging beam · contraflexure",
        "kind": "simply_supported", "length": 6, "support_a": 0, "support_b": 4.5, "EI": 15000,
        "point_loads": [{"P": 10, "x": 2}, {"P": 3, "x": 6}], "distributed": [{"w1": 2, "w2": 2, "a": 0, "b": 6}],
        "moments": [{"M": 5, "x": 3.5}],
    },
    "cantilever": {
        "name": "Cantilever · tip load + triangular load",
        "kind": "cantilever", "length": 3, "EI": 8000,
        "point_loads": [{"P": 4, "x": 3}], "distributed": [{"w1": 6, "w2": 0, "a": 0, "b": 3}], "moments": [],
    },
    "propped": {
        "name": "Propped cantilever · UDL",
        "kind": "propped_cantilever", "length": 8, "support_b": 8, "EI": 25000,
        "point_loads": [], "distributed": [{"w1": 4, "w2": 4, "a": 0, "b": 8}], "moments": [],
    },
    "fixed": {
        "name": "Fixed-fixed · trapezoidal + point load",
        "kind": "fixed_fixed", "length": 8, "EI": 20000,
        "point_loads": [{"P": 10, "x": 6}], "distributed": [{"w1": 2, "w2": 6, "a": 0, "b": 5}], "moments": [],
    },
}


# ------------------------------------------------------------------ parsing
def _num(value, name: str) -> float:
    if isinstance(value, bool):
        raise BeamError(f"'{name}' must be a number")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BeamError(f"'{name}' must be a number") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise BeamError(f"'{name}' must be finite")
    return v


def _opt(value, name: str) -> float | None:
    return None if value in (None, "") else _num(value, name)


def _items(data: dict, key: str, legacy: str | None = None) -> list:
    items = data.get(key)
    if items is None and legacy:
        items = data.get(legacy)
    items = items or []
    if not isinstance(items, list):
        raise BeamError(f"'{key}' must be a list")
    if len(items) > MAX_LOADS:
        raise BeamError(f"At most {MAX_LOADS} items are allowed in '{key}'")
    return items


def beam_from_json(data: dict) -> Beam:
    """Accepts objects ({"P":10,"x":2}) or the v2 list form ([10, 2])."""
    if not isinstance(data, dict):
        raise BeamError("Request body must be a JSON object")
    kind = data.get("kind", "simply_supported")

    points = []
    for i, p in enumerate(_items(data, "point_loads"), 1):
        P, x = (p.get("P"), p.get("x")) if isinstance(p, dict) else (p + [None, None])[:2]
        points.append(PointLoad(_num(P, f"Point load {i}"), _num(x, f"Point load {i} position")))

    dists = []
    for i, u in enumerate(_items(data, "distributed", legacy="udls"), 1):
        if isinstance(u, dict):
            w1 = _num(u.get("w1"), f"Distributed load {i} start intensity")
            w2 = _num(u.get("w2", u.get("w1")), f"Distributed load {i} end intensity")
            a, b = _num(u.get("a"), f"Distributed load {i} start"), _num(u.get("b"), f"Distributed load {i} end")
        else:  # [w, a, b]
            w, a, b = (list(u) + [None] * 3)[:3]
            w1 = w2 = _num(w, f"UDL {i} intensity")
            a, b = _num(a, f"UDL {i} start"), _num(b, f"UDL {i} end")
        dists.append(DistributedLoad(w1, w2, a, b))

    moments = []
    for i, m in enumerate(_items(data, "moments"), 1):
        M, x = (m.get("M"), m.get("x")) if isinstance(m, dict) else (m + [None, None])[:2]
        moments.append(MomentLoad(_num(M, f"Moment {i}"), _num(x, f"Moment {i} position")))

    return Beam(
        length=_num(data.get("length"), "Beam length"),
        kind=kind,
        support_a=_opt(data.get("support_a"), "Support A"),
        support_b=_opt(data.get("support_b"), "Support B"),
        point_loads=points,
        udls=dists,
        moments=moments,
        EI=_opt(data.get("EI"), "EI"),
    )


def _units(data: dict) -> tuple[str, str]:
    units = data.get("units") or {}
    fu = units.get("force", "kN")
    lu = units.get("length", "m")
    return (fu if fu in FORCE_UNITS else "kN", lu if lu in LENGTH_UNITS else "m")


def _safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "beam"


# ------------------------------------------------------------------ app
def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # inputs are tiny; reject abuse early
    app.json.sort_keys = False

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    @app.errorhandler(BeamError)
    def _beam_error(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(413)
    def _too_large(_):
        return jsonify(error="Request too large"), 413

    def _payload() -> dict:
        data = request.get_json(silent=True)
        if data is None:
            raise BeamError("Send the beam as a JSON body")
        return data

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            version=__version__,
            presets=PRESETS,
            supports=SUPPORT_LABELS,
            force_units=FORCE_UNITS,
            length_units=LENGTH_UNITS,
        )

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version=__version__)

    @app.get("/api/presets")
    def presets():
        return jsonify(PRESETS)

    @app.post("/api/solve")
    def api_solve():
        data = _payload()
        result = solve(beam_from_json(data))
        return jsonify(result.to_dict(series=bool(data.get("series", True))))

    @app.post("/api/report.pdf")
    def api_report():
        from beam_solver.plotting import render_pdf

        data = _payload()
        fu, lu = _units(data)
        title = str(data.get("title") or "Beam analysis report")[:80]
        pdf = render_pdf(solve(beam_from_json(data)), fu, lu, title)
        return Response(pdf, mimetype="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{_safe_filename(title)}.pdf"'})

    @app.post("/api/export.csv")
    def api_csv():
        data = _payload()
        fu, lu = _units(data)
        res = solve(beam_from_json(data), samples=1001)
        buf = io.StringIO()
        w = csv.writer(buf)
        header = [f"x ({lu})", f"V ({fu})", f"M ({fu}*{lu})"]
        if res.deflection is not None:
            header += ["slope (rad)", f"deflection ({lu})"]
        w.writerow(header)
        for i, x in enumerate(res.x):
            row = [f"{x:.6g}", f"{res.shear[i]:.6g}", f"{res.moment[i]:.6g}"]
            if res.deflection is not None:
                row += [f"{res.slope[i]:.6g}", f"{res.deflection[i]:.6g}"]
            w.writerow(row)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="beam-results.csv"'})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
