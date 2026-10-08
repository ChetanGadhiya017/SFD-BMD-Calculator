"""Matplotlib rendering: beam sketch, SFD, BMD, deflection, and a multi-page PDF report."""

from __future__ import annotations

import base64
import datetime as _dt
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Polygon, Rectangle  # noqa: E402

from .solver import SUPPORT_LABELS, Result  # noqa: E402

BLUE, RED, GREEN, INK, PURPLE, TEAL = "#2563eb", "#dc2626", "#16a34a", "#1f2937", "#7c3aed", "#0d9488"


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    return f"{v:.4g}" if 1e-3 <= abs(v) < 1e5 else f"{v:.3e}"


# ------------------------------------------------------------------ beam sketch
def _wall(ax, x: float, L: float, side: int) -> None:
    w = 0.025 * L
    ax.add_patch(Rectangle((x - (w if side < 0 else 0), -0.8), w, 1.6, color="#9ca3af", lw=0))
    ax.plot([x, x], [-0.8, 0.8], color=INK, lw=2.5)


def _pin(ax, x: float, L: float, label: str) -> None:
    s = 0.022 * L
    ax.add_patch(Polygon([[x, -0.06], [x - s, -0.5], [x + s, -0.5]], closed=True, color=GREEN))
    ax.plot([x - 1.6 * s, x + 1.6 * s], [-0.52, -0.52], color=INK, lw=1.5)
    ax.text(x, -0.95, label, ha="center", fontsize=10, weight="bold")


def _roller(ax, x: float, L: float, label: str) -> None:
    s = 0.022 * L
    ax.add_patch(Polygon([[x, -0.06], [x - s, -0.38], [x + s, -0.38]], closed=True, color=GREEN))
    for dx in (-0.6 * s, 0.6 * s):
        ax.plot(x + dx, -0.46, "o", ms=4, color=GREEN)
    ax.plot([x - 1.6 * s, x + 1.6 * s], [-0.54, -0.54], color=INK, lw=1.5)
    ax.text(x, -0.95, label, ha="center", fontsize=10, weight="bold")


def draw_beam(ax, res: Result, fu: str, lu: str) -> None:
    b = res.beam
    L = b.length
    ax.plot([0, L], [0, 0], color=INK, lw=6, solid_capstyle="butt")
    ax.set_xlim(-0.06 * L, 1.06 * L)
    ax.set_ylim(-1.15, 1.6)
    ax.axis("off")

    if b.kind == "simply_supported":
        _pin(ax, b.support_a, L, "A")
        _roller(ax, b.support_b, L, "B")
    else:
        _wall(ax, 0, L, -1)
        if b.kind == "fixed_fixed":
            _wall(ax, L, L, 1)
        elif b.kind == "propped_cantilever":
            _roller(ax, b.support_b, L, "B")

    wmax = max([abs(u.w_start) for u in b.udls] + [abs(u.w_end) for u in b.udls] + [1e-12])
    for u in b.udls:
        h1 = 0.1 + 0.55 * abs(u.w_start) / wmax
        h2 = 0.1 + 0.55 * abs(u.w_end) / wmax
        ax.add_patch(Polygon([[u.start, 0.08], [u.start, h1], [u.end, h2], [u.end, 0.08]],
                             closed=True, color=RED, alpha=0.14, lw=0))
        ax.plot([u.start, u.end], [h1, h2], color=RED, lw=1)
        n = max(2, int(u.span / L * 22))
        for i in range(n + 1):
            xx = u.start + u.span * i / n
            hh = h1 + (h2 - h1) * i / n
            if hh > 0.14:
                ax.annotate("", xy=(xx, 0.08), xytext=(xx, hh),
                            arrowprops=dict(arrowstyle="-|>", color=RED, lw=0.8, mutation_scale=8))
        lbl = f"{_fmt(u.w_start)} {fu}/{lu}" if u.is_uniform else f"{_fmt(u.w_start)}→{_fmt(u.w_end)} {fu}/{lu}"
        ax.text((u.start + u.end) / 2, max(h1, h2) + 0.12, lbl, ha="center", color=RED, fontsize=8.5)

    for p in b.point_loads:
        d = 1 if p.magnitude >= 0 else -1
        ax.annotate("", xy=(p.position, 0.08 * d), xytext=(p.position, 1.05 * d),
                    arrowprops=dict(arrowstyle="-|>", color=RED, lw=2))
        ax.text(p.position, 1.18 * d, f"{_fmt(abs(p.magnitude))} {fu}", ha="center", color=RED, fontsize=9,
                weight="bold")
    for m in b.moments:
        sym = "↻" if m.magnitude >= 0 else "↺"
        ax.text(m.position, 0.3, sym, ha="center", va="center", fontsize=22, color=PURPLE)
        ax.text(m.position, 0.82, f"{_fmt(abs(m.magnitude))} {fu}·{lu}", ha="center", color=PURPLE, fontsize=8.5)


# ------------------------------------------------------------------ diagrams
def _diagram(ax, x, y, color, title, ylabel, lu) -> None:
    ax.fill_between(x, y, 0, color=color, alpha=0.16, lw=0)
    ax.plot(x, y, color=color, lw=2)
    ax.axhline(0, color=INK, lw=1)
    ax.set_title(title, loc="left", fontsize=11, weight="bold", color=INK, pad=12)
    ax.margins(y=0.2)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(f"x ({lu})")
    ax.grid(True, alpha=0.3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for idx in {int(np.argmax(y)), int(np.argmin(y))}:
        if abs(y[idx]) > 1e-12:
            ax.annotate(_fmt(y[idx]), (x[idx], y[idx]), textcoords="offset points",
                        xytext=(0, 8 if y[idx] >= 0 else -14), ha="center", fontsize=9, color=color,
                        weight="bold")


def figure(res: Result, fu: str = "kN", lu: str = "m"):
    panels = 4 if res.deflection is not None else 3
    ratios = [0.8, 1.3, 1.3] + ([1.1] if panels == 4 else [])
    fig, axes = plt.subplots(panels, 1, figsize=(9, 2.4 * panels + 0.6), gridspec_kw={"height_ratios": ratios})
    draw_beam(axes[0], res, fu, lu)
    _diagram(axes[1], res.x, res.shear, BLUE, "Shear Force Diagram (SFD)", f"V ({fu})", lu)
    _diagram(axes[2], res.x, res.moment, RED, "Bending Moment Diagram (BMD)", f"M ({fu}·{lu})", lu)
    for xc in res.contraflexure_points:
        axes[2].axvline(xc, color=PURPLE, ls="--", lw=1)
        axes[2].annotate(f"x = {xc:.3g}", (xc, 0), textcoords="offset points", xytext=(4, 4),
                         color=PURPLE, fontsize=8)
    if panels == 4:
        _diagram(axes[3], res.x, res.deflection, TEAL, "Deflected shape", f"y ({lu})", lu)
    for ax in axes[1:]:
        ax.set_xlim(axes[0].get_xlim())
    fig.tight_layout()
    return fig


def render_png(res: Result, force_unit: str = "kN", length_unit: str = "m", dpi: int = 110) -> bytes:
    fig = figure(res, force_unit, length_unit)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def render_base64(res: Result, force_unit: str = "kN", length_unit: str = "m") -> str:
    return base64.b64encode(render_png(res, force_unit, length_unit)).decode("ascii")


# ------------------------------------------------------------------ PDF report
def _poly(coeffs: list[float]) -> str:
    deg = len(coeffs) - 1
    terms = []
    for i, c in enumerate(coeffs):
        p = deg - i
        if abs(c) < 1e-12:
            continue
        mag = _fmt(abs(c))
        body = mag if p == 0 else (f"{mag}x" if p == 1 else f"{mag}x^{p}")
        if p > 0 and mag == "1":
            body = "x" if p == 1 else f"x^{p}"
        terms.append(("− " if c < 0 else "+ ") + body)
    if not terms:
        return "0"
    s = " ".join(terms)
    return s[2:] if s.startswith("+ ") else "−" + s[2:]


def render_pdf(res: Result, fu: str = "kN", lu: str = "m", title: str = "Beam analysis report") -> bytes:
    b = res.beam
    d = res.to_dict()
    buf = BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        y = 0.95

        def line(text, size=10, weight="normal", color=INK, dy=0.022, x=0.08):
            nonlocal y
            fig.text(x, y, text, fontsize=size, weight=weight, color=color, va="top")
            y -= dy

        line(title, 18, "bold", dy=0.035)
        line(f"Generated {_dt.datetime.now():%d %b %Y, %H:%M} · SFD & BMD Calculator", 9, color="#6b7280", dy=0.04)

        line("Beam", 13, "bold", dy=0.028)
        line(f"Type: {SUPPORT_LABELS[b.kind]}    Length L = {_fmt(b.length)} {lu}")
        if b.kind in ("simply_supported", "propped_cantilever") and b.support_b is not None:
            line(f"Supports: A at x = {_fmt(b.support_a)} {lu}, B at x = {_fmt(b.support_b)} {lu}")
        if b.EI:
            line(f"Flexural rigidity EI = {_fmt(b.EI)} {fu}·{lu}²")
        y -= 0.01

        line("Loads", 13, "bold", dy=0.028)
        for p in b.point_loads:
            line(f"• Point load {_fmt(p.magnitude)} {fu} at x = {_fmt(p.position)} {lu}")
        for u in b.udls:
            kind = "UDL" if u.is_uniform else "Varying load"
            line(f"• {kind} {_fmt(u.w_start)}→{_fmt(u.w_end)} {fu}/{lu} from x = {_fmt(u.start)} to {_fmt(u.end)} {lu}")
        for m in b.moments:
            line(f"• Moment {_fmt(m.magnitude)} {fu}·{lu} ({'clockwise' if m.magnitude >= 0 else 'anticlockwise'}) "
                 f"at x = {_fmt(m.position)} {lu}")
        if not (b.point_loads or b.udls or b.moments):
            line("• (no loads)")
        y -= 0.01

        line("Results", 13, "bold", dy=0.028)
        for k, v in d["reactions"].items():
            line(f"{k.replace('_', ' ')} = {_fmt(v)} {fu} {'↑' if v >= 0 else '↓'}")
        for k, v in d["support_moments"].items():
            line(f"{k.replace('_', ' ')} = {_fmt(v)} {fu}·{lu}")
        line(f"Max |V| = {_fmt(abs(d['max_shear']['value']))} {fu} at x = {_fmt(d['max_shear']['x'])} {lu}")
        line(f"Max sagging M = {_fmt(d['max_sagging_moment']['value'])} {fu}·{lu} "
             f"at x = {_fmt(d['max_sagging_moment']['x'])} {lu}")
        line(f"Max hogging M = {_fmt(d['max_hogging_moment']['value'])} {fu}·{lu} "
             f"at x = {_fmt(d['max_hogging_moment']['x'])} {lu}")
        cf = d["contraflexure_points"]
        line(f"Points of contraflexure: {', '.join(_fmt(c) for c in cf) if cf else 'none'}")
        if d["max_deflection"]:
            md = d["max_deflection"]
            line(f"Max deflection = {_fmt(md['value'])} {lu} at x = {_fmt(md['x'])} {lu}")
        y -= 0.01

        line("Working", 13, "bold", dy=0.028)
        for w in res.working:
            line(w, 9, dy=0.02)
        y -= 0.01

        line("Equations by segment", 13, "bold", dy=0.028)
        for s in res.segments:
            if y < 0.06:
                break
            line(f"{_fmt(s.start)} < x < {_fmt(s.end)}:   V(x) = {_poly(s.shear)}    M(x) = {_poly(s.moment)}", 8.5,
                 dy=0.019)
        pdf.savefig(fig)
        plt.close(fig)

        fig = figure(res, fu, lu)
        pdf.savefig(fig)
        plt.close(fig)
    return buf.getvalue()


def poly_to_text(coeffs: list[float]) -> str:
    return _poly(coeffs)
