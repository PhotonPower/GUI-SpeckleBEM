"""Page 3 - browse runs, show observables, export, reuse a run as template."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from sbgui import store
from sbgui.config import load_config
from sbgui.registry import OBSERVABLES
from sbgui.ui.state import bootstrap, load_into_session

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
        for fig in cls().figures(data, ctx):
            st.plotly_chart(fig, width="stretch")
    if "residual_history" in z.files and len(z["residual_history"]) > 1:
        fig = go.Figure(go.Scatter(y=z["residual_history"], mode="lines"))
        fig.update_layout(title="GMRES-Residuum", yaxis_type="log", xaxis_title="Iteration", height=300)
        st.plotly_chart(fig, width="stretch")

    d1, d2 = st.columns(2)
    d1.download_button("results.npz", (run_dir / "results.npz").read_bytes(), "results.npz")
    d2.download_button("config.json", (run_dir / "config.json").read_bytes(), "config.json")

with st.expander("Konfiguration und Bericht"):
    st.json({k: v for k, v in cfg.items() if k != "resolved"})
    st.caption("Verwendete Regeln der Bibliothek und Version:")
    st.json(cfg.get("resolved", {}))
    if (run_dir / "report.txt").exists():
        st.code((run_dir / "report.txt").read_text(encoding="utf-8"))
if st.button("Als Vorlage ins Modell übernehmen"):
    load_into_session(cfg)
    st.switch_page("sbgui/ui/pages/model.py")
