<div align="center">

# 📐 SFD & BMD Calculator

**Shear Force and Bending Moment Diagrams for beams — in the browser, from the command line, or as a JSON API.**

Enter a beam and its loads; get support reactions, peak shear and moment with their locations, points of contraflexure, and clean diagrams.

[![CI](https://github.com/ChetanGadhiya017/SFD-BMD-Calculator/actions/workflows/ci.yml/badge.svg)](https://github.com/ChetanGadhiya017/SFD-BMD-Calculator/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3-000000?logo=flask&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?logo=numpy&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-11557c)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

<img src="docs/screenshot.png" alt="SFD & BMD Calculator web interface" width="90%" />

</div>

---

## ✨ Features

| | |
|---|---|
| 🏗️ **Beam types** | Simply supported · overhanging (supports anywhere on the span) · cantilever |
| ⬇️ **Loads** | Any number of point loads, partial UDLs and applied (clockwise/anticlockwise) moments |
| 📊 **Results** | Reactions (and fixed-end moment), max \|V\|, max sagging & hogging moment with positions, points of contraflexure |
| 🖼️ **Diagrams** | Loaded-beam sketch + SFD + BMD in one figure, peaks annotated, jumps drawn exactly |
| 🌐 **Three interfaces** | Web app, CLI (`python -m beam_solver`), and `POST /api/solve` JSON endpoint |
| ✅ **Verified** | 21 automated tests against textbook results (PL/4, Pab/L, wL²/8, cantilever PL, overhang hogging…) |

---

## 🚀 Quick start

```bash
git clone https://github.com/ChetanGadhiya017/SFD-BMD-Calculator.git
cd SFD-BMD-Calculator
pip install -r requirements.txt

python app.py            # open http://127.0.0.1:5000
```

Click one of the **Try:** examples, or enter your own beam and press **Calculate**.

### Command line

```bash
# 6 m simply supported beam, 10 kN at 2 m
python -m beam_solver --length 6 --point 10@2

# Overhanging beam with UDL, two point loads and a couple; save the diagrams
python -m beam_solver -L 6 --supports 0 4.5 --udl 2@0-6 --point 10@2 --point 3@6 --moment 5@3.5 --plot beam.png

# Cantilever
python -m beam_solver -L 3 --cantilever --point 4@3 --udl 2@0-3
```

```
Reactions
  R_A  =      6.667 kN
  R_B  =      3.333 kN
Extremes
  |V|max   =      6.667 kN      at x = 0.000 m
  M sag    =     13.333 kN·m   at x = 2.000 m
```

### JSON API

```bash
curl -X POST http://127.0.0.1:5000/api/solve \
     -H "Content-Type: application/json" \
     -d '{"kind":"simply_supported","length":4,"udls":[[5,0,4]]}'
```

```json
{
  "reactions": {"R_A": 10.0, "R_B": 10.0},
  "max_sagging_moment": {"value": 10.0, "x": 2.0},
  "contraflexure_points": [],
  "...": "..."
}
```

`point_loads` are `[P, x]`, `udls` are `[w, from, to]`, `moments` are `[M, x]`; add `"support_a"`/`"support_b"` for overhangs or `"kind": "cantilever"`.

---

## 📏 Sign convention

| Quantity | Positive direction |
|---|---|
| Point loads, UDL intensity | ↓ downward |
| Applied moments | ↻ clockwise |
| Reactions | ↑ upward |
| Shear force V(x) | Net upward force **left** of the section |
| Bending moment M(x) | Sagging (concave up) |

---

## 🧠 How it works

1. **Reactions from equilibrium.** For two supports at *a* and *b*:
   ΣM about A = 0 → `R_B = [ΣP(x−a) + ΣW(x̄−a) + ΣM] / (b−a)`, then ΣF = 0 → `R_A = ΣP + ΣW − R_B`.
   For a cantilever, `R_A = ΣP + ΣW` and the fixed-end moment closes the moment balance.
2. **Section method on a dense grid.** V(x) and M(x) are summed from every force to the left of each section (singularity-function style). Each load position is sampled on both sides so jumps are exact and peaks are not missed.
3. **Post-processing.** Extremes, and zero-crossings of M that are not caused by an applied couple (true contraflexure).

```
beam_solver/
├── solver.py      # Beam, loads, equilibrium, V(x) and M(x)
├── plotting.py    # beam sketch + SFD + BMD (Matplotlib, headless)
└── __main__.py    # CLI
app.py             # Flask UI + /api/solve
templates/, static/
tests/             # solver, CLI and web tests
```

---

## 🧪 Tests

```bash
pip install pytest
pytest -q
```

---

## 🗺 Roadmap

- [ ] Shear and moment equations per segment (step-by-step working for students)
- [ ] Triangular / trapezoidal distributed loads
- [ ] Deflection curve (EI input)
- [ ] Export results to PDF / CSV

---

## 📄 License

[GPL-3.0](LICENSE.md) © Chetan Gadhiya
