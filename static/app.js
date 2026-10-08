/* SFD & BMD Calculator: client.
 * State lives in one object, mirrored to the URL hash (shareable) and localStorage.
 * Every edit re-solves on the server (debounced) and re-renders the beam, stats,
 * charts, equations and working.
 */
(() => {
  "use strict";

  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
  const { presets } = window.SFD;
  const STORAGE_KEY = "sfd-state-v3";

  const GROUPS = {
    point_loads: { cls: "point", fields: [["P", "Load P"], ["x", "at x"]], make: (L) => ({ P: 10, x: round(L / 2) }) },
    distributed: {
      cls: "dist",
      fields: [["w1", "w₁ (start)"], ["w2", "w₂ (end)"], ["a", "from x"], ["b", "to x"]],
      make: (L) => ({ w1: 5, w2: 5, a: 0, b: L }),
    },
    moments: { cls: "moment", fields: [["M", "Moment M"], ["x", "at x"]], make: (L) => ({ M: 10, x: round(L / 2) }) },
  };

  // ------------------------------------------------------------------ helpers
  function round(v) { return Math.round(v * 1000) / 1000; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function num(v) { const n = parseFloat(v); return Number.isFinite(n) ? n : NaN; }
  function fmt(v, digits = 4) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    if (Math.abs(v) < 1e-12) return "0";
    const a = Math.abs(v);
    if (a >= 1e5 || a < 1e-3) return v.toExponential(2).replace("e-", "e−");
    return String(Number(v.toPrecision(digits)));
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 2200);
  }
  const encode = (o) => btoa(unescape(encodeURIComponent(JSON.stringify(o)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const decode = (s) => JSON.parse(decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/")))));

  function normalize(s) {
    const d = {
      kind: "simply_supported", length: 6, support_a: 0, support_b: "", EI: "",
      units: { force: "kN", length: "m" }, point_loads: [], distributed: [], moments: [],
    };
    const o = Object.assign(d, clone(s || {}));
    o.units = Object.assign({ force: "kN", length: "m" }, o.units || {});
    if (o.support_b === undefined || o.support_b === null) o.support_b = "";
    if (o.EI === undefined || o.EI === null) o.EI = "";
    for (const g of Object.keys(GROUPS)) if (!Array.isArray(o[g])) o[g] = [];
    delete o.name;
    return o;
  }

  function initialState() {
    const m = location.hash.match(/s=([^&]+)/);
    if (m) { try { return normalize(decode(m[1])); } catch (e) { /* ignore broken links */ } }
    try { const saved = localStorage.getItem(STORAGE_KEY); if (saved) return normalize(JSON.parse(saved)); } catch (e) { /* storage blocked */ }
    return normalize(presets.overhang);
  }

  let state = initialState();
  let result = null;
  let timer = null;
  let inflight = null;

  // ------------------------------------------------------------------ payload
  function payload(extra = {}) {
    const p = clone(state);
    if (p.kind !== "simply_supported") delete p.support_a;
    if (!["simply_supported", "propped_cantilever"].includes(p.kind)) delete p.support_b;
    if (p.support_b === "") delete p.support_b;
    if (p.EI === "" || p.EI === 0) p.EI = null;
    return Object.assign(p, extra);
  }

  function persist() {
    const h = "#s=" + encode(state);
    history.replaceState(null, "", h);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------------ form
  function renderRows() {
    for (const [group, spec] of Object.entries(GROUPS)) {
      const box = $("#" + group);
      if (!state[group].length) {
        box.innerHTML = `<div class="empty-row">None yet</div>`;
        continue;
      }
      box.innerHTML = state[group].map((item, i) => `
        <div class="load-row ${spec.cls}">
          ${spec.fields.map(([k, label]) => `
            <label>${label}<input type="number" step="any" inputmode="decimal"
              data-group="${group}" data-i="${i}" data-k="${k}" value="${esc(item[k] ?? "")}"></label>`).join("")}
          <button class="del" data-group="${group}" data-i="${i}" aria-label="Remove">✕</button>
        </div>`).join("");
    }
  }

  function syncForm() {
    $$('input[name="kind"]').forEach((r) => (r.checked = r.value === state.kind));
    $("#length").value = state.length;
    $("#support_a").value = state.support_a ?? 0;
    $("#support_b").value = state.support_b === "" ? state.length : state.support_b;
    $("#EI").value = state.EI;
    $("#force_unit").value = state.units.force;
    $("#length_unit").value = state.units.length;
    renderRows();
    updateVisibility();
    updateUnits();
  }

  function updateVisibility() {
    $("#sa-field").hidden = state.kind !== "simply_supported";
    $("#sb-field").hidden = !["simply_supported", "propped_cantilever"].includes(state.kind);
  }

  function updateUnits() {
    $$('[data-unit="length"]').forEach((s) => (s.textContent = state.units.length));
    $("#ei-unit").textContent = `${state.units.force}·${state.units.length}²`;
  }

  function bindForm() {
    $$('input[name="kind"]').forEach((r) => r.addEventListener("change", () => {
      state.kind = r.value;
      updateVisibility();
      schedule(0);
    }));
    for (const id of ["length", "support_a", "support_b", "EI"]) {
      $("#" + id).addEventListener("input", (e) => {
        state[id] = e.target.value === "" ? "" : num(e.target.value);
        if (id === "length" && state.support_b === "") $("#support_b").value = e.target.value;
        schedule();
      });
    }
    $("#force_unit").addEventListener("change", (e) => { state.units.force = e.target.value; updateUnits(); schedule(0); });
    $("#length_unit").addEventListener("change", (e) => { state.units.length = e.target.value; updateUnits(); schedule(0); });

    document.addEventListener("input", (e) => {
      const t = e.target;
      if (!t.dataset || !t.dataset.group) return;
      state[t.dataset.group][+t.dataset.i][t.dataset.k] = t.value === "" ? "" : num(t.value);
      schedule();
    });
    document.addEventListener("click", (e) => {
      const del = e.target.closest(".del");
      if (del) {
        state[del.dataset.group].splice(+del.dataset.i, 1);
        renderRows();
        schedule(0);
      }
      const add = e.target.closest("[data-add]");
      if (add) {
        const g = add.dataset.add;
        const L = num(state.length) > 0 ? num(state.length) : 6;
        state[g].push(GROUPS[g].make(L));
        renderRows();
        schedule(0);
        const inputs = $$(`#${g} input`);
        inputs[inputs.length - GROUPS[g].fields.length]?.focus();
      }
    });
    $("#clear").addEventListener("click", () => {
      state.point_loads = []; state.distributed = []; state.moments = [];
      renderRows(); schedule(0);
    });
    $("#preset").addEventListener("change", (e) => {
      const p = presets[e.target.value];
      if (!p) return;
      const units = state.units;
      state = normalize(p);
      state.units = units;
      syncForm();
      schedule(0);
      e.target.value = "";
      toast(`Loaded: ${p.name}`);
    });

    // EI helper (E in GPa × I in 10⁶ mm⁴ = EI in kN·m²)
    const eiCalc = () => {
      const v = num($("#E-gpa").value) * num($("#I-mm4").value);
      $("#ei-preview").textContent = Number.isFinite(v) ? fmt(v) : "–";
      return v;
    };
    $("#E-gpa").addEventListener("input", eiCalc);
    $("#I-mm4").addEventListener("input", eiCalc);
    $("#apply-ei").addEventListener("click", () => {
      const v = eiCalc();
      if (!Number.isFinite(v) || v <= 0) return;
      state.EI = v;
      $("#EI").value = v;
      schedule(0);
    });
    eiCalc();
  }

  // ------------------------------------------------------------------ solve
  function schedule(delay = 250) {
    clearTimeout(timer);
    persist();
    drawBeam();
    timer = setTimeout(solve, delay);
  }

  async function solve() {
    if (inflight) inflight.abort();
    inflight = new AbortController();
    document.body.classList.add("loading");
    try {
      const r = await fetch("/api/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
        signal: inflight.signal,
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || "Could not solve this beam");
      result = body;
      setStatus(null);
      drawBeam();
      renderStats();
      renderCharts();
      renderEquations();
      renderWorking();
    } catch (err) {
      if (err.name === "AbortError") return;
      setStatus(err.message);
    } finally {
      document.body.classList.remove("loading");
    }
  }

  function setStatus(msg) {
    const s = $("#status");
    s.hidden = !msg;
    s.textContent = msg ? "⚠ " + msg : "";
  }

  // ------------------------------------------------------------------ beam SVG
  function drawBeam() {
    const svg = $("#beam-svg");
    const L = num(state.length);
    if (!(L > 0)) {
      svg.innerHTML = `<text x="500" y="120" text-anchor="middle">Enter a beam length to begin</text>`;
      return;
    }
    const X0 = 70, X1 = 930, Y = 120;
    const X = (x) => X0 + (Math.min(Math.max(x, 0), L) / L) * (X1 - X0);
    const fu = state.units.force, lu = state.units.length;
    const c = { load: css("--load"), couple: css("--couple"), sup: css("--support"), ink: css("--ink-2"), muted: css("--muted"), beam: css("--ink") };
    const parts = [`<defs>
      <marker id="ah-load" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${c.load}" stroke="none"/></marker>
      <marker id="ah-small" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${c.load}" stroke="none"/></marker>
      <marker id="ah-couple" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${c.couple}" stroke="none"/></marker>
      <marker id="ah-react" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${c.sup}" stroke="none"/></marker>
      <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="${c.muted}" stroke-width="1.5"/></pattern>
    </defs>`];

    // distributed loads (behind everything)
    const wmax = Math.max(1e-12, ...state.distributed.flatMap((u) => [Math.abs(num(u.w1)) || 0, Math.abs(num(u.w2)) || 0]));
    for (const u of state.distributed) {
      const a = num(u.a), b = num(u.b), w1 = num(u.w1), w2 = Number.isFinite(num(u.w2)) ? num(u.w2) : w1;
      if (!(b > a) || !Number.isFinite(w1)) continue;
      const h1 = 8 + 52 * Math.abs(w1) / wmax, h2 = 8 + 52 * Math.abs(w2) / wmax;
      const xa = X(a), xb = X(b), top = Y - 8;
      parts.push(`<polygon points="${xa},${top} ${xa},${top - h1} ${xb},${top - h2} ${xb},${top}" fill="${c.load}" fill-opacity=".12" stroke="none"/>`);
      parts.push(`<line x1="${xa}" y1="${top - h1}" x2="${xb}" y2="${top - h2}" stroke="${c.load}" stroke-width="1.5"/>`);
      const n = Math.max(2, Math.round((xb - xa) / 26));
      for (let i = 0; i <= n; i++) {
        const xx = xa + ((xb - xa) * i) / n, hh = h1 + ((h2 - h1) * i) / n;
        if (hh > 12) parts.push(`<line x1="${xx}" y1="${top - hh}" x2="${xx}" y2="${top - 1}" stroke="${c.load}" stroke-width="1.2" marker-end="url(#ah-small)"/>`);
      }
      const lbl = Math.abs(w1 - w2) < 1e-12 ? `${fmt(w1)} ${fu}/${lu}` : `${fmt(w1)} → ${fmt(w2)} ${fu}/${lu}`;
      parts.push(`<text x="${(xa + xb) / 2}" y="${top - Math.max(h1, h2) - 8}" text-anchor="middle" font-size="12" style="fill:${c.load}">${esc(lbl)}</text>`);
    }

    // beam
    parts.push(`<rect x="${X0}" y="${Y - 6}" width="${X1 - X0}" height="12" rx="2" fill="${c.beam}" stroke="none"/>`);

    // supports
    const wall = (x, side) => {
      const w = 16, xs = side < 0 ? x - w : x;
      parts.push(`<rect x="${xs}" y="${Y - 42}" width="${w}" height="84" fill="url(#hatch)" stroke="none"/>`);
      parts.push(`<line x1="${x}" y1="${Y - 42}" x2="${x}" y2="${Y + 42}" stroke="${c.beam}" stroke-width="3"/>`);
    };
    const pin = (x, label) => {
      parts.push(`<polygon points="${x},${Y + 6} ${x - 15},${Y + 32} ${x + 15},${Y + 32}" fill="${c.sup}" stroke="none"/>`);
      parts.push(`<rect x="${x - 22}" y="${Y + 33}" width="44" height="8" fill="url(#hatch)" stroke="none"/><line x1="${x - 22}" y1="${Y + 33}" x2="${x + 22}" y2="${Y + 33}" stroke="${c.ink}" stroke-width="1.5"/>`);
      parts.push(`<text x="${x}" y="${Y + 58}" text-anchor="middle" font-weight="700" font-size="13">${label}</text>`);
    };
    const roller = (x, label) => {
      parts.push(`<polygon points="${x},${Y + 6} ${x - 13},${Y + 25} ${x + 13},${Y + 25}" fill="${c.sup}" stroke="none"/>`);
      parts.push(`<circle cx="${x - 7}" cy="${Y + 29}" r="4" fill="${c.sup}" stroke="none"/><circle cx="${x + 7}" cy="${Y + 29}" r="4" fill="${c.sup}" stroke="none"/>`);
      parts.push(`<rect x="${x - 22}" y="${Y + 34}" width="44" height="8" fill="url(#hatch)" stroke="none"/><line x1="${x - 22}" y1="${Y + 34}" x2="${x + 22}" y2="${Y + 34}" stroke="${c.ink}" stroke-width="1.5"/>`);
      parts.push(`<text x="${x}" y="${Y + 58}" text-anchor="middle" font-weight="700" font-size="13">${label}</text>`);
    };
    const sa = Number.isFinite(num(state.support_a)) ? num(state.support_a) : 0;
    const sb = state.support_b === "" || !Number.isFinite(num(state.support_b)) ? L : num(state.support_b);
    if (state.kind === "simply_supported") { pin(X(sa), "A"); roller(X(sb), "B"); }
    else {
      wall(X(0), -1);
      if (state.kind === "fixed_fixed") wall(X(L), 1);
      if (state.kind === "propped_cantilever") roller(X(sb), "B");
    }

    // point loads
    for (const p of state.point_loads) {
      const P = num(p.P), x = num(p.x);
      if (!Number.isFinite(P) || !Number.isFinite(x)) continue;
      const xx = X(x);
      if (P >= 0) {
        parts.push(`<line x1="${xx}" y1="${Y - 78}" x2="${xx}" y2="${Y - 9}" stroke="${c.load}" stroke-width="3" marker-end="url(#ah-load)"/>`);
        parts.push(`<text x="${xx}" y="${Y - 86}" text-anchor="middle" font-weight="700" font-size="13" style="fill:${c.load}">${fmt(P)} ${esc(fu)}</text>`);
      } else {
        parts.push(`<line x1="${xx}" y1="${Y + 70}" x2="${xx}" y2="${Y + 9}" stroke="${c.load}" stroke-width="3" marker-end="url(#ah-load)"/>`);
        parts.push(`<text x="${xx}" y="${Y + 86}" text-anchor="middle" font-weight="700" font-size="13" style="fill:${c.load}">${fmt(-P)} ${esc(fu)} ↑</text>`);
      }
    }

    // moments
    for (const m of state.moments) {
      const M = num(m.M), x = num(m.x);
      if (!Number.isFinite(M) || !Number.isFinite(x)) continue;
      const xx = X(x), r = 22;
      const cw = M >= 0;
      const start = cw ? [xx - r, Y] : [xx + r, Y];
      const end = cw ? [xx + r * 0.7, Y + r * 0.7] : [xx - r * 0.7, Y + r * 0.7];
      parts.push(`<path d="M${start[0]} ${start[1]} A${r} ${r} 0 1 ${cw ? 1 : 0} ${end[0]} ${end[1]}" stroke="${c.couple}" stroke-width="2.5" marker-end="url(#ah-couple)"/>`);
      parts.push(`<text x="${xx}" y="${Y - 32}" text-anchor="middle" font-weight="600" font-size="12" style="fill:${c.couple}">${fmt(Math.abs(M))} ${esc(fu)}·${esc(lu)}</text>`);
    }

    // reactions from the last good result
    if (result && result.beam && Math.abs(result.beam.length - L) < 1e-9) {
      const rx = result.reactions;
      const place = { R_A: result.beam.support_a ?? 0, R_B: result.beam.support_b ?? L };
      for (const [k, v] of Object.entries(rx)) {
        const xx = X(place[k] ?? 0);
        parts.push(`<text x="${xx}" y="${Y + 78}" text-anchor="middle" font-size="12" style="fill:${c.sup}" font-weight="600">${k.replace("_", "")} = ${fmt(v)} ${esc(fu)}</text>`);
      }
    }

    // dimension line
    const keys = [...new Set([0, L, sa, sb, ...state.point_loads.map((p) => num(p.x)), ...state.moments.map((m) => num(m.x)),
      ...state.distributed.flatMap((u) => [num(u.a), num(u.b)])].filter((v) => Number.isFinite(v) && v >= 0 && v <= L))].sort((a, b) => a - b);
    const dy = 218;
    parts.push(`<line x1="${X0}" y1="${dy}" x2="${X1}" y2="${dy}" stroke="${c.muted}" stroke-width="1"/>`);
    let lastX = -1e9;
    for (const k of keys) {
      const xx = X(k);
      parts.push(`<line x1="${xx}" y1="${dy - 5}" x2="${xx}" y2="${dy + 5}" stroke="${c.muted}" stroke-width="1"/>`);
      if (xx - lastX > 34) {
        parts.push(`<text x="${xx}" y="${dy + 17}" text-anchor="middle" font-size="11" style="fill:${c.muted}">${fmt(k)}</text>`);
        lastX = xx;
      }
    }
    svg.innerHTML = parts.join("");
  }

  // ------------------------------------------------------------------ stats
  function stat(k, v, u, cls = "") {
    return `<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="u">${u}</div></div>`;
  }

  function renderStats() {
    const r = result, fu = esc(state.units.force), lu = esc(state.units.length);
    const out = [];
    for (const [k, v] of Object.entries(r.reactions)) out.push(stat(k.replace("_", " "), fmt(v), `${fu} ${v >= 0 ? "↑" : "↓"}`));
    for (const [k, v] of Object.entries(r.support_moments)) out.push(stat(k.replace("_", " "), fmt(v), `${fu}·${lu} (${v < 0 ? "hogging" : "sagging"})`, "moment"));
    out.push(stat("Max |V|", fmt(Math.abs(r.max_shear.value)), `${fu} @ x = ${fmt(r.max_shear.x)}`, "shear"));
    out.push(stat("Max sagging M", fmt(r.max_sagging_moment.value), `${fu}·${lu} @ x = ${fmt(r.max_sagging_moment.x)}`, "moment"));
    out.push(stat("Max hogging M", fmt(r.max_hogging_moment.value), `${fu}·${lu} @ x = ${fmt(r.max_hogging_moment.x)}`, "moment"));
    if (r.max_deflection) {
      const d = r.max_deflection;
      const mm = state.units.length === "m" ? ` (${fmt(d.value * 1000)} mm)` : "";
      out.push(stat("Max deflection", fmt(d.value), `${lu}${mm} @ x = ${fmt(d.x)}`, "defl"));
      if (state.units.length === "m" && Math.abs(d.value) > 0) {
        out.push(stat("Span / deflection", `L/${Math.round(r.beam.length / Math.abs(d.value))}`, "limit often L/250–L/360", "defl"));
      }
    }
    const cf = r.contraflexure_points;
    out.push(stat("Contraflexure", cf.length ? cf.map((v) => fmt(v, 3)).join(", ") : "none", `x (${lu})`));
    $("#stats").innerHTML = out.join("");
  }

  // ------------------------------------------------------------------ charts
  const CHARTS = [
    { id: "chart-shear", key: "shear", color: "--shear", title: "Shear force V(x)", unit: () => state.units.force },
    { id: "chart-moment", key: "moment", color: "--moment", title: "Bending moment M(x)", unit: () => `${state.units.force}·${state.units.length}` },
    { id: "chart-deflection", key: "deflection", color: "--defl", title: "Deflection y(x)", unit: () => state.units.length },
  ];

  function hexToRgba(hex, a) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  function renderCharts() {
    if (!window.Plotly || !result) return;
    const s = result.series;
    const ink = css("--ink-2"), grid = css("--line"), lu = state.units.length;
    for (const ch of CHARTS) {
      const el = $("#" + ch.id);
      const y = s[ch.key];
      if (!y) { el.hidden = true; Plotly.purge(el); continue; }
      el.hidden = false;
      const color = css(ch.color);
      let iMax = 0, iMin = 0;
      y.forEach((v, i) => { if (v > y[iMax]) iMax = i; if (v < y[iMin]) iMin = i; });
      const ann = [...new Set([iMax, iMin])].filter((i) => Math.abs(y[i]) > 1e-12).map((i) => ({
        x: s.x[i], y: y[i], text: `<b>${fmt(y[i])}</b>`, showarrow: false, yshift: y[i] >= 0 ? 12 : -12,
        xanchor: s.x[i] > 0.92 * result.beam.length ? "right" : s.x[i] < 0.08 * result.beam.length ? "left" : "center",
        font: { color, size: 12 },
      }));
      const shapes = ch.key === "moment" ? result.contraflexure_points.map((x) => ({
        type: "line", x0: x, x1: x, yref: "paper", y0: 0, y1: 1, line: { color: css("--couple"), dash: "dot", width: 1 },
      })) : [];
      Plotly.react(el, [{
        x: s.x, y, type: "scatter", mode: "lines", line: { color, width: 2.5 }, fill: "tozeroy",
        fillcolor: hexToRgba(color, 0.15),
        hovertemplate: `x = %{x:.4g} ${lu}<br>${ch.title.split(" ")[0]} = %{y:.4g} ${ch.unit()}<extra></extra>`,
      }], {
        title: { text: `${ch.title} <span style="font-size:11px">(${ch.unit()})</span>`, x: 0.01, font: { size: 14, color: ink } },
        margin: { l: 58, r: 16, t: 40, b: 36 },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Inter, sans-serif", color: ink, size: 11 },
        xaxis: { gridcolor: grid, zeroline: false, range: [0, result.beam.length], title: { text: `x (${lu})`, standoff: 4 } },
        yaxis: { gridcolor: grid, zerolinecolor: ink, zerolinewidth: 1.5, automargin: true },
        hovermode: "x", showlegend: false, annotations: ann, shapes,
      }, { displayModeBar: false, responsive: true });
      if (!el._synced) {
        el.on("plotly_hover", (ev) => syncHover(el, ev.points[0].x));
        el.on("plotly_unhover", () => CHARTS.forEach((c) => { const o = $("#" + c.id); if (o !== el && !o.hidden) Plotly.Fx.unhover(o); }));
        el._synced = true;
      }
    }
    $("#ei-tip").hidden = !!s.deflection;
  }

  let hovering = false;
  function syncHover(src, x) {
    if (hovering) return;
    hovering = true;
    for (const c of CHARTS) {
      const o = $("#" + c.id);
      if (o !== src && !o.hidden && o.data) Plotly.Fx.hover(o, { xval: x });
    }
    hovering = false;
  }

  // ------------------------------------------------------------------ equations & working
  function poly(coeffs) {
    const deg = coeffs.length - 1, sup = ["", "", "²", "³"];
    const terms = [];
    coeffs.forEach((c, i) => {
      const p = deg - i;
      if (Math.abs(c) < 1e-12) return;
      const mag = fmt(Math.abs(c));
      let body = p === 0 ? mag : `${mag === "1" ? "" : mag}x${sup[p]}`;
      terms.push((c < 0 ? "− " : "+ ") + body);
    });
    if (!terms.length) return "0";
    const s = terms.join(" ");
    return s.startsWith("+ ") ? s.slice(2) : "−" + s.slice(2);
  }

  function renderEquations() {
    $("#eq-body").innerHTML = result.segments.map((s) =>
      `<tr><td>${fmt(s.start)} &lt; x &lt; ${fmt(s.end)}</td><td>${poly(s.shear)}</td><td>${poly(s.moment)}</td></tr>`).join("");
  }

  function renderWorking() {
    $("#working").innerHTML = result.working.map((w) => `<li>${esc(w)}</li>`).join("");
  }

  // ------------------------------------------------------------------ tabs, theme, share, export
  function bindChrome() {
    $$(".tab").forEach((t) => t.addEventListener("click", () => {
      $$(".tab").forEach((o) => { o.classList.toggle("active", o === t); o.setAttribute("aria-selected", o === t); });
      $$(".tab-panel").forEach((p) => (p.hidden = p.id !== "tab-" + t.dataset.tab));
      if (t.dataset.tab === "diagrams") CHARTS.forEach((c) => { const el = $("#" + c.id); if (!el.hidden && el.data) Plotly.Plots.resize(el); });
    }));

    $("#theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("sfd-theme", next); } catch (e) { /* ignore */ }
      drawBeam();
      renderCharts();
    });

    $("#share").addEventListener("click", async () => {
      persist();
      try { await navigator.clipboard.writeText(location.href); toast("Link copied: anyone can open this exact beam"); }
      catch (e) { prompt("Copy this link:", location.href); }
    });

    const btn = $("#export-btn"), menu = $("#export-menu");
    btn.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; btn.setAttribute("aria-expanded", !menu.hidden); });
    document.addEventListener("click", () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); });
    menu.addEventListener("click", (e) => {
      const kind = e.target.closest("[data-export]")?.dataset.export;
      if (kind) exportAs(kind);
    });
  }

  async function download(url, filename) {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload({ units: state.units, title: "Beam analysis report" })),
    });
    if (!r.ok) { const b = await r.json().catch(() => ({})); throw new Error(b.error || "Export failed"); }
    saveBlob(await r.blob(), filename);
  }

  function saveBlob(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function exportAs(kind) {
    try {
      if (kind === "pdf") { toast("Preparing PDF…"); await download("/api/report.pdf", "beam-report.pdf"); }
      if (kind === "csv") await download("/api/export.csv", "beam-results.csv");
      if (kind === "json") saveBlob(new Blob([JSON.stringify(payload({ units: state.units }), null, 2)], { type: "application/json" }), "beam.json");
      if (kind === "png") for (const c of CHARTS) { const el = $("#" + c.id); if (!el.hidden && el.data) await Plotly.downloadImage(el, { format: "png", width: 1200, height: 400, filename: c.key }); }
    } catch (err) { toast(err.message); }
  }

  // ------------------------------------------------------------------ boot
  function boot() {
    syncForm();
    bindForm();
    bindChrome();
    schedule(0);
    window.addEventListener("hashchange", () => {
      const m = location.hash.match(/s=([^&]+)/);
      if (!m) return;
      try { state = normalize(decode(m[1])); syncForm(); schedule(0); } catch (e) { /* ignore */ }
    });
  }

  // Draw support icons in the picker.
  function drawSupportIcons() {
    const icons = {
      simply_supported: '<line x1="8" y1="12" x2="72" y2="12" stroke-width="4"/><path d="M14 14l-6 10h12z" fill="currentColor" stroke="none"/><path d="M66 14l-6 9h12z" fill="currentColor" stroke="none"/><circle cx="63" cy="27" r="2.2" fill="currentColor" stroke="none"/><circle cx="69" cy="27" r="2.2" fill="currentColor" stroke="none"/>',
      cantilever: '<line x1="10" y1="14" x2="72" y2="14" stroke-width="4"/><line x1="10" y1="2" x2="10" y2="28" stroke-width="3"/><path d="M4 6l6-4M4 14l6-4M4 22l6-4M4 30l6-4" stroke-width="1.2"/>',
      propped_cantilever: '<line x1="10" y1="12" x2="72" y2="12" stroke-width="4"/><line x1="10" y1="0" x2="10" y2="26" stroke-width="3"/><path d="M4 4l6-4M4 12l6-4M4 20l6-4M4 28l6-4" stroke-width="1.2"/><path d="M66 14l-6 9h12z" fill="currentColor" stroke="none"/><circle cx="63" cy="27" r="2.2" fill="currentColor" stroke="none"/><circle cx="69" cy="27" r="2.2" fill="currentColor" stroke="none"/>',
      fixed_fixed: '<line x1="10" y1="14" x2="70" y2="14" stroke-width="4"/><line x1="10" y1="2" x2="10" y2="28" stroke-width="3"/><line x1="70" y1="2" x2="70" y2="28" stroke-width="3"/><path d="M4 6l6-4M4 14l6-4M4 22l6-4M4 30l6-4M76 2l-6 4M76 10l-6 4M76 18l-6 4M76 26l-6 4" stroke-width="1.2"/>',
    };
    for (const [k, v] of Object.entries(icons)) $$(".sicon-" + k).forEach((s) => (s.innerHTML = v));
  }

  drawSupportIcons();
  boot();
  // Plotly is deferred from a CDN; draw charts as soon as it arrives.
  window.addEventListener("load", () => renderCharts());
})();
