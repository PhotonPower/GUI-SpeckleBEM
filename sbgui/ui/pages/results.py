"""Page 3 - browse runs, show observables, export, reuse a run as template."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from sbgui import bridge, store
from sbgui.config import load_config
from sbgui.export import observable_csv
from sbgui.registry import OBSERVABLES
from sbgui.sweeps import ensemble_request, has_speckle
from sbgui.ui.state import bootstrap, load_into_session, show_library_messages, show_progress

bootstrap()
st.title("Ergebnisse")

runs = store.list_runs()
if not runs:
    st.info("Noch keine Läufe. Auf der Seite „Berechnung“ einen Lauf starten.")
    st.stop()

ICON = {"done": "✅", "error": "⛔", "cancelled": "⏹️"}
labels = {str(r["dir"]): f"{ICON.get(r['state'], '⏳')} {r['name']}" for r in runs}
default = st.session_state.get("active_run")
keys = list(labels)
idx = keys.index(default) if default in keys else 0
sel = st.sidebar.selectbox("Lauf", keys, index=idx, format_func=labels.get)
if st.sidebar.button("Aktualisieren"):
    st.rerun()
run_dir = Path(sel)
status = store.live_status(run_dir)
cfg = load_config(run_dir / "config.json")

c = st.columns(5)
c[0].metric("Zustand", status.get("state", "?"))
c[1].metric("Unbekannte", f"{status['n_unknowns']:,}".replace(",", ".") if status.get("n_unknowns") else "–")
c[2].metric("Iterationen", status.get("iterations", "–"))
c[3].metric("wahres Residuum", f"{status['true_residual']:.1e}" if status.get("true_residual") is not None else "–")
c[4].metric("Lösezeit", f"{status['solve_seconds']:.0f} s" if status.get("solve_seconds") else "–")

if status.get("dark_band_ratio") is not None:
    st.caption(f"PML-Route: Dark-Band-Verhältnis {status['dark_band_ratio']:.2e} (einfallendes Feld am PML-Start "
               "relativ zum Patch; Toleranz siehe Konfiguration).")
used = []
if status.get("far_field_source"):
    gp = cfg["geometry"]["params"]
    used.append(f"Fernfeld-Quelle: {status['far_field_source']}"
                + (f" (z_H = {gp.get('huygens_z_h', 0.0):g} µm, Raster {gp.get('huygens_spacing', 0.0):g} nm; "
                   "0 = automatisch)"
                   if status["far_field_source"] == "huygens" else "")
                + f"; L = {gp.get('L', gp.get('Lx', '?'))} µm, Lücke W_g = {gp.get('gap', '?')} µm")
if status.get("preconditioner"):
    used.append(f"Vorkonditionierer: {status['preconditioner']}")
if used:
    st.caption(" · ".join(used))
show_progress(run_dir, status.get("state", "?"))
show_library_messages(status)
if status.get("state") == "error":
    st.error(status.get("message", ""))
    with st.expander("Details"):
        st.code(status.get("traceback", ""))
if status.get("state") not in ("done",) or not (run_dir / "results.npz").exists():
    st.info("Für diesen Lauf liegen (noch) keine Ergebnisse vor.")
else:
    z = np.load(run_dir / "results.npz", allow_pickle=False)
    meta = json.loads(str(np.load(run_dir / "mesh.npz", allow_pickle=False)["meta"]))
    ctx = {"cfg": cfg, "meta": meta}
    for i, spec in enumerate(cfg["observables"]):
        cls = OBSERVABLES.get(spec["type"])
        data = {k.split("__", 1)[1]: z[k] for k in z.files if k.startswith(f"obs{i}__")}
        st.subheader(cls.label)
        summ = getattr(cls, "summary", None)
        if summ and data:
            cols = st.columns(max(1, len(s := summ(data))))
            for col, (k, v) in zip(cols, s.items()):
                col.metric(k, f"{v:.4g}")
        for note in getattr(cls, "notes", lambda d: [])(data) if data else []:
            st.info(note, icon="ℹ️")
        for fig in cls().figures(data, ctx):
            st.plotly_chart(fig, width="stretch")
        csv = observable_csv(data) if data else None
        if csv:
            st.download_button(f"{cls.label}: CSV", csv.encode("utf-8"), f"{run_dir.name}_obs{i}_{cls.id}.csv",
                               "text/csv", key=f"csv{i}")
    if "residual_history" in z.files and len(z["residual_history"]) > 1:
        fig = go.Figure(go.Scatter(y=z["residual_history"], mode="lines"))
        fig.update_layout(title="GMRES-Residuum", yaxis_type="log", xaxis_title="Iteration", height=300)
        st.plotly_chart(fig, width="stretch")

    d = st.columns(4)
    d[0].download_button("results.npz", (run_dir / "results.npz").read_bytes(), "results.npz")
    d[1].download_button("config.json", (run_dir / "config.json").read_bytes(), "config.json")
    if (run_dir / "mesh.npz").exists():
        d[2].download_button("mesh.npz", (run_dir / "mesh.npz").read_bytes(), "mesh.npz")
    h5 = run_dir / "currents.h5"
    if h5.exists():
        d[3].download_button(f"HDF5 ({h5.stat().st_size / 1e6:.1f} MB)", h5.read_bytes(), f"{run_dir.name}.h5")
        if st.button("HDF5 mit specklebem.io.load_hdf5 prüfen"):
            try:
                st.json(bridge.query("h5info", {"path": str(h5)}, timeout=300))
            except Exception as e:  # noqa: BLE001
                st.error(f"HDF5 nicht lesbar: {e}")
    if status.get("hdf5_error"):
        st.warning(status["hdf5_error"])

if has_speckle(cfg) and status.get("state") == "done":
    st.subheader("Speckle-Ensemble über mehrere Läufe")
    st.caption("Fasst die gespeicherten Intensitäten mehrerer Läufe mit der Statistik der Bibliothek zusammen "
               "(gepoolter KS-Test, Kontrast je Muster, Speckle-Größe, Korrelation). Alle Läufe müssen dieselbe "
               "Beobachtungsebene haben (Abstand, Pixel, Strahltaille). Serien starten auf der Seite „Berechnung“.")
    cands = {}
    for r in runs:
        if r["state"] != "done" or not (Path(r["dir"]) / "results.npz").exists():
            continue
        rc = load_config(Path(r["dir"]) / "config.json")
        if has_speckle(rc):
            gp = rc["geometry"]["params"]
            tag = f"σ = {gp['sigma']:g} nm, Seed {gp['seed']}" if "sigma" in gp else ""
            cands[str(r["dir"])] = f"{r['name']}  ({tag})" if tag else r["name"]
    picked = st.multiselect("Läufe im Ensemble", list(cands), default=[sel] if sel in cands else [],
                            format_func=cands.get, key="ens.pick")
    if st.button("Ensemble-Statistik berechnen", disabled=len(picked) < 1):
        try:
            res = bridge.query("speckle_ensemble",
                               ensemble_request(picked, [load_config(Path(d) / "config.json") for d in picked]),
                               timeout=600)
            st.session_state["ens.result"] = (picked, res)
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("ens.result", None)
            st.error(f"Ensemble nicht berechenbar: {e}")
    if "ens.result" in st.session_state:
        used_runs, res = st.session_state["ens.result"]
        ks = res["ks"]
        m = st.columns(4)
        m[0].metric("Muster", res["n_patterns"])
        m[1].metric("Kontrast (Mittel ± Streuung)", f"{res['mean_contrast']:.3f} ± {res['std_contrast']:.3f}")
        m[2].metric("Stephens-D* (Grenze 1,094)", f"{ks['modified_statistic']:.3f}",
                    "verworfen" if ks["rejects_5pct"] else "nicht verworfen", delta_color="off")
        m[3].metric("Speckle-Größe / (c·λ·z/D) − 1", f"{res['speckle_size_rel_error']:+.3f}")
        st.caption(f"KS: D = {ks['statistic']:.3f}, p = {ks['p_value']:.3g} (Kolmogorov, konservativ), "
                   f"n = {ks['n']} unabhängige Stichproben (Schritt {res['ks_stride']} Pixel); erwartete Speckle-Größe "
                   f"{res['speckle_size_expected'] * 1e3:.3f} mm, gemessen {res['speckle_size_mean'] * 1e3:.3f} mm. "
                   "Das Verwerfen der Exponentialverteilung ist nur für voll entwickelte Fälle (kohärenter Anteil "
                   "< 1e-2) ein Befund.")
        if "by_sigma" in res:
            b = res["by_sigma"]
            fig = go.Figure(go.Scatter(x=np.asarray(b["sigma"]) * 1e9, y=b["mean_contrast"], mode="lines+markers"))
            fig.update_layout(title="Mittlerer Kontrast über σ", xaxis_title="σ [nm]", yaxis_title="Kontrast",
                              height=320)
            st.plotly_chart(fig, width="stretch")
            st.write("Kontrast monoton fallend in σ (docs/05): "
                     + ("**ja**" if b["monotone_decreasing"] else "**nein**"))
        st.dataframe([{"Lauf": Path(d).name, "Kontrast": c} for d, c in zip(used_runs, res["contrast"])])
        if res["n_patterns"] > 1:
            cm = go.Figure(go.Heatmap(z=res["correlation"], colorscale="Viridis", zmin=-1, zmax=1))
            cm.update_layout(title="Korrelationskoeffizient der Intensitätsmuster", height=380,
                             yaxis_autorange="reversed")
            st.plotly_chart(cm, width="stretch")

with st.expander("Konfiguration und Bericht"):
    st.json({k: v for k, v in cfg.items() if k != "resolved"})
    st.caption("Verwendete Regeln der Bibliothek und Version:")
    st.json(cfg.get("resolved", {}))
    if (run_dir / "report.txt").exists():
        st.code((run_dir / "report.txt").read_text(encoding="utf-8"))
if st.button("Als Vorlage ins Modell übernehmen"):
    load_into_session(cfg)
    st.switch_page("sbgui/ui/pages/model.py")
