"""Page 2 - solver settings, cost estimate, start and live status."""

from __future__ import annotations

import copy
import time

import streamlit as st

from sbgui import __version__, bridge, store
from sbgui.checks import capability_issues, collect_issues, estimate_memory_gb, resolve_solver, system_memory_gb
from sbgui.config import SOLVER, materialise
from sbgui.sweeps import MAX_RUNS, parse_numbers, rough_series, supports_series
from sbgui.ui.state import (
    bootstrap,
    lib_capabilities,
    lib_rules,
    render_schema,
    show_issues,
    show_library_messages,
)

cfg = bootstrap()
st.title("Berechnung")
caps = lib_capabilities()
if caps is None:
    st.error("Keine nutzbare `specklebem`-Installation: Rechnen ist deaktiviert (siehe Seite Modell).", icon="🔌")

with st.expander("Löser-Einstellungen", expanded=True):
    render_schema(SOLVER, cfg["solver"], "solver", columns=3)

rules = lib_rules(cfg) if caps else None
issues, n_unk = [], None
try:
    m = materialise(cfg, rules)
    geom, pg = m["geometry"]
    n_unk = 3 * geom.estimate_triangles(pg, m["h"])
    issues = collect_issues(cfg, rules, n_unk) + capability_issues(cfg, caps, geom.meta_hint(pg), n_unk)
except Exception:  # noqa: BLE001
    issues = collect_issues(cfg, rules, None)

if n_unk:
    r = resolve_solver(cfg["solver"], n_unk)
    lo, hi = estimate_memory_gb(n_unk, r["compression"], r["solver"])
    have = system_memory_gb()
    c = st.columns(4)
    c[0].metric("Unbekannte 2N (Schätzung)", f"{n_unk:,}".replace(",", "."))
    c[1].metric("Matrix / Löser", f"{r['compression']} / {r['solver']}")
    c[2].metric("Speicher", f"{lo:.1f}–{hi:.1f} GB" if hi - lo > 0.5 else f"{lo:.1f} GB")
    c[3].metric("RAM verfügbar", f"{have:.0f} GB" if have else "?")
    st.caption("Referenz aus den Projektmessungen (Si, MLFMM, Desktop 24 Kerne): 2N = 1,0·10⁶ in ≈ 16 min "
               "und 75 GB; 5,95·10⁶ auf dem 1-TB-Server in 5,6 h und 697 GB.")

if caps and cfg["solver"].get("save_hdf5") and not caps.get("features", {}).get("hdf5"):
    st.warning("HDF5 gewählt, aber im Worker fehlt h5py (`pip install specklebem[io]`): der Lauf rechnet, "
               "schreibt aber keine HDF5-Datei.", icon="💾")
blocking = show_issues(issues)

c1, c2 = st.columns([1, 3])
if c1.button("Lauf starten", type="primary", disabled=blocking or caps is None):
    run_cfg = copy.deepcopy(cfg)
    run_cfg["resolved"] = {"rules": rules, "library": caps, "gui_version": __version__,
                           "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    st.session_state["active_run"] = str(bridge.start_run(run_cfg))
    st.rerun()
c2.caption("Der Lauf startet als eigener Prozess; diese Seite darf geschlossen werden.")

if supports_series(cfg):
    with st.expander("Serie über σ und Seed (Ensemble für die Speckle-Statistik)"):
        st.caption("Mehrere Läufe nacheinander in einem Hintergrundprozess (nie gleichzeitig, der Speicher wird "
                   f"nicht geteilt), höchstens {MAX_RUNS}. Alle übrigen Einstellungen stammen aus der aktuellen "
                   "Konfiguration. Die Ergebnisse fasst die Seite „Ergebnisse“ zusammen. Bibliothek (WP-S2): "
                   "5 σ-Werte (50–250 nm) × 2 Seeds.")
        sc = st.columns(2)
        sig_txt = sc[0].text_input("σ-Werte [nm]", value="50, 100, 150, 200, 250", key="series.sigma")
        seed_txt = sc[1].text_input("Seeds", value="1, 2", key="series.seeds")
        try:
            sigmas = parse_numbers(sig_txt, minimum=0.0)
            seeds = parse_numbers(seed_txt, integers=True, minimum=0)
            series_cfgs = rough_series(cfg, sigmas, seeds)
            series_err = None
        except ValueError as e:
            series_cfgs, series_err = [], str(e)
        if series_err:
            st.error(series_err, icon="⛔")
        else:
            bad = [(c["name"], i.msg) for c in series_cfgs
                   for i in collect_issues(c, rules, n_unk) if i.level == "error"]
            if bad:
                st.error(f"{len(bad)} Fehler in der Serie, z. B. {bad[0][0]}: {bad[0][1]}", icon="⛔")
            tags = [c["name"].rsplit("_sigma", 1)[1] for c in series_cfgs[:6]]
            st.write(f"{len(series_cfgs)} Läufe: " + ", ".join(tags) + (" …" if len(series_cfgs) > 6 else ""))
            if st.button("Serie starten", disabled=blocking or bool(bad) or caps is None, key="series.start"):
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                for c in series_cfgs:
                    c["resolved"] = {"rules": rules, "library": caps, "gui_version": __version__, "started_at": stamp}
                dirs = bridge.start_series(series_cfgs)
                st.session_state["active_run"] = str(dirs[0])
                st.success(f"Serie mit {len(dirs)} Läufen gestartet; Fortschritt auf der Seite „Ergebnisse“ "
                           "(Auswahl links).")


@st.fragment(run_every=2)
def live_status():
    path = st.session_state.get("active_run")
    if not path:
        return
    st_ = store.live_status(path)
    state = st_.get("state", "?")
    st.subheader(f"Aktiver Lauf: {path.split('/')[-1].split(chr(92))[-1]}")
    c = st.columns(4)
    c[0].metric("Zustand", state)
    c[1].metric("Unbekannte", f"{st_['n_unknowns']:,}".replace(",", ".") if st_.get("n_unknowns") else "–")
    c[2].metric("GMRES-Iteration", st_.get("iteration", "–"))
    c[3].metric("Residuum", f"{st_['residual']:.2e}" if st_.get("residual") else "–")
    st.write(st_.get("message", ""))
    show_library_messages(st_)
    if state not in store.FINAL:
        if st.button("Abbrechen"):
            bridge.cancel(path)
    elif state == "done":
        st.success("Fertig – Ergebnisse auf der Seite „Ergebnisse“.")
    elif state == "error":
        st.error(st_.get("message", "Fehler"))
        with st.expander("Details"):
            st.code(st_.get("traceback", ""))


live_status()
