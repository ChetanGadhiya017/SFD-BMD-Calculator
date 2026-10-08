"""Matplotlib rendering of the beam, SFD and BMD (headless-safe)."""

from __future__ import annotations

import base64
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .solver import Result  # noqa: E402

BLUE, RED, GREEN, INK = "#2563eb", "#dc2626", "#16a34a", "#1f2937"


def _fmt(v: float) -> str:
    return f"{v:.3g}" if abs(v) < 1e4 else f"{v:.3e}"


def _beam_sketch(ax, res: Result, fu: str, lu: str) -> None:
    b = res.beam
    L = b.length
    ax.plot([0, L], [0, 0], color=INK, lw=6, solid_capstyle="butt")
    ax.set_xlim(-0.05 * L, 1.05 * L)
    ax.set_ylim(-1.15, 1.45)
    ax.axis("off")

    if b.kind == "cantilever":
        ax.plot([0, 0], [-0.8, 0.8], color=INK, lw=3)
        for y in [-0.7, -0.35, 0, 0.35, 0.7]:
            ax.plot([-0.03 * L, 0], [y - 0.15, y], color=INK, lw=1)
    else:
        ax.plot(b.support_a, -0.35, marker="^", ms=16, color=GREEN)
        ax.plot(b.support_b, -0.35, marker="o", ms=12, color=GREEN)
        ax.text(b.support_a, -0.95, "A", ha="center", fontsize=10, weight="bold")
        ax.text(b.support_b, -0.95, "B", ha="center", fontsize=10, weight="bold")

    for p in b.point_loads:
        d = 1 if p.magnitude >= 0 else -1
        ax.annotate("", xy=(p.position, 0.08 * d), xytext=(p.position, 1.0 * d),
                    arrowprops=dict(arrowstyle="-|>", color=RED, lw=2))
        ax.text(p.position, 1.15 * d, f"{_fmt(abs(p.magnitude))} {fu}", ha="center", color=RED, fontsize=9)
    for u in b.udls:
        ax.fill_between([u.start, u.end], 0.08, 0.55, color=RED, alpha=0.15, lw=0)
        n = max(2, int((u.end - u.start) / L * 20))
        for i in range(n + 1):
            xx = u.start + (u.end - u.start) * i / n
            ax.annotate("", xy=(xx, 0.08), xytext=(xx, 0.55),
                        arrowprops=dict(arrowstyle="-|>", color=RED, lw=0.8))
        ax.text(u.centroid, 0.7, f"{_fmt(u.intensity)} {fu}/{lu}", ha="center", color=RED, fontsize=9)
    for m in b.moments:
        sym = "↻" if m.magnitude >= 0 else "↺"
        ax.text(m.position, 0.25, sym, ha="center", va="center", fontsize=22, color="#7c3aed")
        ax.text(m.position, 0.85, f"{_fmt(abs(m.magnitude))} {fu}·{lu}", ha="center", color="#7c3aed", fontsize=9)


def _diagram(ax, x, y, color, title, ylabel, lu, mark_max=True) -> None:
    ax.fill_between(x, y, 0, color=color, alpha=0.18, lw=0)
    ax.plot(x, y, color=color, lw=2)
    ax.axhline(0, color=INK, lw=1)
    ax.set_title(title, loc="left", fontsize=11, weight="bold", color=INK, pad=14)
    ax.margins(y=0.18)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(f"x ({lu})")
    ax.grid(True, alpha=0.3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    if mark_max and len(y):
        for idx in {int(y.argmax()), int(y.argmin())}:
            if abs(y[idx]) > 1e-9:
                ax.annotate(_fmt(y[idx]), (x[idx], y[idx]), textcoords="offset points",
                            xytext=(0, 8 if y[idx] >= 0 else -14), ha="center", fontsize=9, color=color,
                            weight="bold")


def render_png(res: Result, force_unit: str = "kN", length_unit: str = "m", dpi: int = 110) -> bytes:
    fig, (a0, a1, a2) = plt.subplots(
        3, 1, figsize=(9, 7.8), gridspec_kw={"height_ratios": [0.75, 1.4, 1.4]}, sharex=False
    )
    _beam_sketch(a0, res, force_unit, length_unit)
    _diagram(a1, res.x, res.shear, BLUE, "Shear Force Diagram (SFD)", f"V ({force_unit})", length_unit)
    _diagram(a2, res.x, res.moment, RED, "Bending Moment Diagram (BMD)",
             f"M ({force_unit}·{length_unit})", length_unit)
    for xc in res.contraflexure_points:
        a2.axvline(xc, color="#7c3aed", ls="--", lw=1)
        a2.annotate(f"x = {xc:.3g}", (xc, 0), textcoords="offset points", xytext=(4, 4),
                    color="#7c3aed", fontsize=8)
    for ax in (a1, a2):
        ax.set_xlim(a0.get_xlim())
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def render_base64(res: Result, force_unit: str = "kN", length_unit: str = "m") -> str:
    return base64.b64encode(render_png(res, force_unit, length_unit)).decode("ascii")
