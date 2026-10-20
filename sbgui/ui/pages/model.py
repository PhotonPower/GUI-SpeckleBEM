"""Page 1 - define the model and see immediately what it costs and what is wrong with it."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from sbgui import bridge
from sbgui.checks import collect_issues, estimate_memory_gb, resolve_solver, system_memory_gb
from sbgui.config import MESH, OPTICS, materialise
from sbgui.meshing.common import mesh_stats
from sbgui.registry import EXCITATIONS, GEOMETRIES, MATERIALS, OBSERVABLES
from sbgui.ui.state import WKEY, bootstrap, lib_capabilities, lib_rules, plugin_picker, render_schema, show_issues

cfg = bootstrap()
st.title("Modell")

caps = lib_capabilities()
if caps is None:
    st.error("Keine nutzbare `specklebem`-Installation gefunden. Geometrie, Vorschau und Prüfungen "
             "funktionieren weiter, Rechnen ist deaktiviert. Interpreter festlegen mit "
             "`SBGUI_WORKER_PYTHON` (und ggf. `SBGUI_WORKER_PYTHONPATH`).", icon="🔌")

left, right = st.columns([5, 6], gap="large")

with left:
    cfg["name"] = st.text_input("Name des Laufs", cfg.get("name", "lauf"), key=f"{WKEY}name")
    t_geo, t_mat, t_exc, t_obs = st.tabs(["Geometrie", "Material & Optik", "Anregung", "Auswertung"])
    with t_geo:
        geom_cls = plugin_picker(GEOMETRIES, cfg["geometry"], "geometry", "Form")
        st.divider()
        render_schema(MESH, cfg["mesh"], "mesh", columns=1)
    with t_mat:
        render_schema(OPTICS, cfg["optics"], "optics", columns=1)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Objekt / Substrat**")
            plugin_picker(MATERIALS, cfg["object"], "object", "Material")
        with c2:
            st.markdown("**Umgebung**")
            plugin_picker(MATERIALS, cfg["background"], "background", "Material")
    with t_exc:
        exc_cls = plugin_picker(EXCITATIONS, cfg["excitation"], "excitation", "Anregung")
    with t_obs:
        ok = [o.id for o in OBSERVABLES.all() if geom_cls.kind in o.applies_to]
        have = [o["type"] for o in cfg["observables"] if o["type"] in ok]
        chosen = st.multiselect("Auswertungen", ok, default=have or ok[:1],
                                format_func=lambda i: OBSERVABLES.get(i).label, key=f"{WKEY}obs.sel")
        old = {o["type"]: o for o in cfg["observables"]}
        cfg["observables"] = [old.get(i) or {"type": i, "params": OBSERVABLES.get(i).schema().defaults()}
                              for i in chosen]
        for spec in cfg["observables"]:
            cls = OBSERVABLES.get(spec["type"])
            with st.expander(cls.label, expanded=False):
                st.caption(cls.description)
                render_schema(cls.schema(), spec["params"], f"obs.{spec['type']}")

# ---- derived quantities and checks --------------------------------------------------------------
rules = lib_rules(cfg) if caps else None
try:
    m = materialise(cfg, rules)
    geom, pg = m["geometry"]
    est_tri = geom.estimate_triangles(pg, m["h"])
except Exception:  # noqa: BLE001 - incomplete input; the issue list explains
    m, est_tri = None, None
issues = collect_issues(cfg, rules, 3 * est_tri if est_tri else None)

with right:
    if est_tri:
        r = resolve_solver(cfg["solver"], 3 * est_tri)
        lo, hi = estimate_memory_gb(3 * est_tri, r["compression"], r["solver"])
        have_gb = system_memory_gb()
        c = st.columns(4)
        c[0].metric("Dreiecke (Schätzung)", f"{est_tri:,}".replace(",", "."))
        c[1].metric("Unbekannte 2N", f"{3 * est_tri:,}".replace(",", "."))
        c[2].metric("Matrix", {"dense": "dicht", "mlfmm": "MLFMM"}[r["compression"]])
        c[3].metric("Speicher", f"{lo:.0f}–{hi:.0f} GB" if hi - lo > 1 else f"{lo:.1f} GB",
                    help=f"verfügbar: {have_gb:.0f} GB" if have_gb else None)
        if rules and "box_depth" in rules and geom.kind == "substrate":
            st.caption(f"Regeln der Bibliothek: Boxtiefe {rules['box_depth'] * 1e6:.2f} µm, "
                       f"max. Taille w₀ ≤ {rules['waist_fraction']:.3g}·L·cosθ")
    blocking = show_issues(issues)
    st.session_state["blocking"] = blocking

    if m:
        out = geom.outline(pg)
        if out:
            fig = go.Figure(go.Scatter(x=[x * 1e9 for x in out["x"]], y=[z * 1e9 for z in out["z"]],
                                       mode="lines", fill="tozeroy" if geom.kind == "substrate" else "toself"))
            fig.update_layout(title=out["title"], xaxis_title="x [nm]", yaxis_title="z [nm]", height=300,
                              yaxis_scaleanchor="x", margin={"t": 40, "b": 30})
            if geom.kind == "substrate" and "cd" in pg:  # show only a window around the feature
                w = max(pg["cd"] * 3, 600e-9) * 1e9
                fig.update_xaxes(range=[-w / 2 * 1.6, w / 2 * 1.6])
            st.plotly_chart(fig, width="stretch")

        by_lib = geom.mesher == "library"
        if by_lib and caps is None:
            st.caption("Dieses Netz erzeugt die Bibliothek: Vorschau erst mit erreichbarer `specklebem`.")
        no_mesher = (blocking and est_tri is None) or (by_lib and caps is None)
        if st.button("3D-Netz erzeugen (Vorschau)", disabled=no_mesher):
            h_prev = m["h"] * max(1.0, (est_tri / 40_000) ** 0.5) if est_tri else m["h"]
            try:
                with st.spinner("Netz wird erzeugt …" + (" (Bibliothek)" if by_lib else "")):
                    mesh = bridge.preview_mesh(cfg, rules, h_prev) if by_lib else geom.build(pg, h_prev)
                st.session_state["preview"] = (mesh, h_prev)
            except Exception as e:  # noqa: BLE001
                st.error(f"Netz konnte nicht erzeugt werden: {e}")
        prev = st.session_state.get("preview")
        if prev:
            mesh, h_prev = prev
            s = mesh_stats(mesh.vertices, mesh.triangles)
            note = f" (Vorschau grober: h = {h_prev * 1e9:.0f} nm)" if h_prev > m["h"] * 1.001 else ""
            st.caption(f"{s['n_triangles']:,} Dreiecke, kleinster Winkel {s['angle_min_deg']:.1f}°, "
                       f"Kantenlänge {s['edge_min'] * 1e9:.0f}–{s['edge_max'] * 1e9:.0f} nm{note}")
            if "sigma_measured" in mesh.meta:
                mm = mesh.meta
                band = f", Feinband {mm['box_fine_depth'] * 1e6:.2f} µm" if mm.get("box_fine_depth") else ""
                st.caption(f"Rauheit dieser Realisierung: σ = {mm['sigma_measured'] * 1e9:.1f} nm (Seed "
                           f"{mm['seed']}); Box {mm['depth'] * 1e6:.2f} µm tief{band}, {mm['grading']}"
                           + (" (auf einheitlich umgestellt)" if mm.get("uniform_fallback") else ""))
            v, f = mesh.vertices * 1e9, mesh.triangles
            fig3 = go.Figure(go.Mesh3d(x=v[:, 0], y=v[:, 1], z=v[:, 2], i=f[:, 0], j=f[:, 1], k=f[:, 2],
                                       color="#7aa6c2", flatshading=True, lighting={"ambient": 0.6}))
            fig3.update_layout(height=480, margin={"t": 10, "b": 0}, scene={
                "aspectmode": "data", "xaxis_title": "x [nm]", "yaxis_title": "y [nm]",
                "zaxis": {"title": "z [nm]  (Luft oben)" if geom.kind == "substrate" else "z [nm]",
                          "autorange": "reversed" if geom.kind == "substrate" else True}})
            st.plotly_chart(fig3, width="stretch")
