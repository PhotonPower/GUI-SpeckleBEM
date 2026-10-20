"""Worker: the only process that imports ``specklebem``.

    python -m sbgui.worker info                  -> JSON capabilities of the installed library
    python -m sbgui.worker rules   < request     -> JSON of library rule values (box depth, ...)
    python -m sbgui.worker run <run_dir>         -> solve + observables, writes results.npz
    python -m sbgui.worker mesh    < request     -> library-made mesh (preview), writes request["out"]
    python -m sbgui.worker h5info  < request     -> reload a run's HDF5 file with specklebem.io (check)

It runs in whatever Python environment has the library (e.g. the MSYS2 UCRT64 build), selected
by ``SBGUI_WORKER_PYTHON`` / ``SBGUI_WORKER_PYTHONPATH`` in the GUI. It needs numpy only besides
the library; plugin modules are written so that they import without gmsh/plotly.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from . import liblog, store
from .checks import collect_issues, resolve_solver
from .config import load_config, materialise
from .meshing.common import save_mesh
from .registry import load_plugins


def _json_out(obj) -> None:
    sys.stdout.write("\n" + json.dumps(obj) + "\n")  # last line is the payload (library may log above)
    sys.stdout.flush()


def cmd_info() -> dict:
    import importlib.util

    import specklebem as sb

    return {
        "version": sb.__version__,
        "has_openmp": bool(sb.has_openmp()), "has_blas": bool(sb.has_blas_lapack()),
        "has_cuda": bool(sb.has_cuda()),
        "compression": ["dense", "mlfmm"],
        "features": library_features(sb, importlib.util.find_spec("h5py") is not None),
    }


def library_features(sb, have_h5py: bool) -> dict:
    """Which optional library features this build offers (feature probes, no version numbers:
    the library reports 0.1.0 for every commit so far)."""
    sim = getattr(sb, "Simulation", None)
    with_pml = getattr(sim, "with_pml", None)
    return {
        "angular_spectrum_beam": hasattr(sb, "AngularSpectrumBeam"),
        "rough_surface": hasattr(sb, "RoughSurface") and hasattr(sb, "rough_surface_box_params"),
        "pml": with_pml is not None and hasattr(sb, "make_open_surface_mesh"),
        # PML route with MLFMM: before WP-PML5a (2026-10-19) dense only ('compression must be "dense"'),
        # WP-PML5a: "mlfmm" with default parameters and an exact ring, WP-PML5b (2026-10-20): mlfmm dict
        "pml_mlfmm": with_pml is not None and '"mlfmm"' in (with_pml.__doc__ or "")
        and 'must be "dense"' not in (with_pml.__doc__ or ""),
        "pml_mlfmm_params": with_pml is not None and "mlfmm:" in (with_pml.__doc__ or "").split("\n", 1)[0],
        "near_field": hasattr(sb, "plane_grid") and hasattr(sim, "field"),
        "absolute_drc": hasattr(sim, "incident_power") and hasattr(sim, "reflectance"),
        "hdf5": have_h5py and hasattr(sim, "save"),
    }


def cmd_rules(req: dict) -> dict:
    import specklebem as sb

    load_plugins()
    m = materialise(req["cfg"])
    lam, h = m["wavelength"], m["h"]
    obj = m["object"][0].build(sb, m["object"][1], lam)
    bg = m["background"][0].build(sb, m["background"][1], lam)
    out: dict = {}
    for key, fn in (
        ("box_depth", lambda: sb.default_box_depth(obj, lam)),
        ("waist_fraction", lambda: sb.beam_waist_fraction(obj, lam, h)),
        ("plasmonic", lambda: bool(sb.is_plasmonic(obj))),
        ("weak_absorber", lambda: bool(sb.is_weakly_absorbing(obj, lam, h))),
        ("exterior_wavelength", lambda: sb.exterior_wavelength(bg, lam)),
        ("field_decay_length", lambda: sb.field_decay_length(obj, lam)),
    ):
        try:
            val = fn()
            out[key] = val if isinstance(val, bool) else float(val)
        except Exception as e:  # noqa: BLE001 - one failing rule must not hide the others
            out[key + "_error"] = str(e)
    return out


# min_box_size_lambda after "cannot represent region" (ADR 0008 §6). Measured on a Si line on the PML route
# (h = lambda/3, H = 180 nm, r_max = 259 nm): the default leaves fail at R2 level 4, >= 2 lambda passes every
# level. 4 lambda also passes but makes the near field almost dense - offered in the solver settings only.
MLFMM_LEAF_RETRIES = (2.0,)
MLFMM_LOSSY_HELP = ("MLFMM: das verlustbehaftete Gebiet (z. B. Si) ist mit diesen Blättern nicht auf die verlangte "
                    "Genauigkeit darstellbar, meist wegen großer Basisfunktionen (lange Flankendreiecke der "
                    "Höhenkarte bei hohen Stegen). Auswege: MLFMM-Blattgröße „≥ 4 λ“ (viel Speicher), Matrix "
                    "„dicht“ (kleine Fälle), oder die GUI-Vernetzung (gmsh) mit kurzen Flankendreiecken.")


def next_mlfmm_leaf(err: Exception, kw: dict) -> float | None:
    """Larger MLFMM leaves after the library's lossy-region failure, or None (give up / other error)."""
    if "cannot represent region" not in str(err) or "mlfmm" not in kw:
        return None
    current = float(kw["mlfmm"].get("min_box_size_lambda") or 0.0)
    return next((x for x in MLFMM_LEAF_RETRIES if x > current), None)


def library_mesh(sb, m: dict, rules: dict | None, h: float):
    """Let a ``mesher == "library"`` geometry build its mesh; returns a ``LibraryMesh``."""
    geom, pg = m["geometry"]
    lam = m["wavelength"]
    ctx = {"wavelength": lam, "h": h, "rules": rules,
           "object": m["object"][0].build(sb, m["object"][1], lam),
           "background": m["background"][0].build(sb, m["background"][1], lam)}
    return geom.build_lib(sb, pg, h, ctx)


def cmd_mesh(req: dict) -> dict:
    """Preview of a library-made mesh: writes vertices/triangles/meta to ``req["out"]``."""
    import specklebem as sb

    load_plugins()
    m = materialise(req["cfg"], req.get("rules"))
    h = float(req.get("h") or m["h"])
    t0 = time.time()
    lm = library_mesh(sb, m, req.get("rules"), h)
    meta = save_mesh(Path(req["out"]), lm.result, time.time() - t0)
    return {"n_triangles": lm.result.n_triangles, "n_unknowns": lm.result.n_unknowns, "route": lm.route,
            "meta": meta}


def cmd_h5info(req: dict) -> dict:
    """Reload a run's HDF5 file with ``specklebem.io.load_hdf5`` and summarise it (export check)."""
    from specklebem.io import load_hdf5

    r = load_hdf5(req["path"])
    cur = None if r.currents is None else np.asarray(r.currents)
    mesh = r.mesh or {}
    return {"format_version": str((r.attrs or {}).get("format_version", "?")),
            "n_currents": None if cur is None else int(cur.size),
            "n_triangles": int(np.asarray(mesh["triangles"]).shape[0]) if "triangles" in mesh else None,
            "solver": {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                       for k, v in (r.solver or {}).items() if not hasattr(v, "__len__") or isinstance(v, str)},
            "has_gui_config": "gui_config" in (r.metadata or {})}


def cmd_run(run_dir: Path) -> None:
    import specklebem as sb

    load_plugins()
    cfg = load_config(run_dir / "config.json")
    rules = cfg.get("resolved", {}).get("rules")
    store.write_status(run_dir, state="solving", message="Lauf wird aufgebaut", worker_pid=_pid())
    log0 = liblog.log_size(run_dir)

    def report_library_messages() -> None:
        msgs = liblog.messages_since(run_dir, log0)
        if msgs:
            store.write_status(run_dir, library_messages=msgs)

    try:
        m = materialise(cfg, rules)
        lam = m["wavelength"]
        geom = m["geometry"][0]
        route, lib_mesh, route_opts = "closed", None, {}
        lm = None
        if geom.mesher_for(m["geometry"][1]) == "library":
            store.write_status(run_dir, state="meshing", message="Netz wird in der Bibliothek erzeugt")
            t0 = time.time()
            lm = library_mesh(sb, m, rules, m["h"])
            meta = save_mesh(run_dir / "mesh.npz", lm.result, time.time() - t0)
            report_library_messages()
            errors = [i.msg for i in collect_issues(cfg, rules, lm.result.n_unknowns, meta["mesh_stats"])
                      if i.level == "error"]
            if errors:
                raise RuntimeError("Vorab-Prüfung fehlgeschlagen: " + " | ".join(errors))
            store.write_status(run_dir, state="solving", n_triangles=lm.result.n_triangles,
                               n_unknowns=lm.result.n_unknowns, mesh_seconds=meta["mesh_seconds"])
            route, lib_mesh, route_opts = lm.route, lm.handle, lm.options
            z = None
        else:
            z = np.load(run_dir / "mesh.npz", allow_pickle=False)
            meta = json.loads(str(z["meta"]))
        obj = m["object"][0].build(sb, m["object"][1], lam)
        bg = m["background"][0].build(sb, m["background"][1], lam)
        n_bg = m["background"][0].refractive_index(m["background"][1], lam)
        ctx = {"wavelength": lam, "h": m["h"], "meta": meta, "rules": rules, "object": obj,
               "background": bg, "n_background": float(np.real(n_bg)) if n_bg is not None else 1.0}
        exc_plugin, pe = m["excitation"]
        ctx["excitation_params"] = pe
        exc = exc_plugin.build(sb, pe, ctx, bg)
        ctx["excitation"] = exc
        ctx["co_pol"] = None
        ctx["vertices"] = lm.result.vertices if lm is not None else z["vertices"]
        if lib_mesh is None:
            lib_mesh = sb.TriangleMesh(z["vertices"], z["triangles"])
        if route == "closed" and not lib_mesh.is_closed():
            raise RuntimeError("TriangleMesh.is_closed() is False - mesh rejected by the library")
        if route not in ("closed", "pml"):
            raise NotImplementedError(f"Rechenweg {route!r} ist in dieser GUI-Version nicht angebunden")

        r = resolve_solver(cfg["solver"], int(meta.get("n_unknowns") or 3 * len(z["triangles"])))
        if r["threads"] > 0:
            import os

            os.environ["OMP_NUM_THREADS"] = str(r["threads"])
        kw = {"object": obj, "exterior": bg, "solver": r["solver"], "compression": r["compression"],
              "formulation": r["formulation"], "preconditioner": r["preconditioner"]}
        if r["compression"] == "mlfmm":
            kw["mlfmm"] = {"accuracy_digits": r["mlfmm_digits"]}
            if r.get("mlfmm_leaf"):
                kw["mlfmm"]["min_box_size_lambda"] = float(r["mlfmm_leaf"])
        if route == "pml":
            feats = library_features(sb, have_h5py=False)
            if r["compression"] == "mlfmm" and not feats["pml_mlfmm"]:
                raise RuntimeError("Diese SpeckleBem-Version rechnet die PML-Route nur dicht (vor WP-PML5a, "
                                   "2026-10-19): Matrix „dicht“ wählen oder die Bibliothek aktualisieren.")
            if "mlfmm" in kw and not feats["pml_mlfmm_params"]:
                kw.pop("mlfmm")  # WP-PML5a: no mlfmm dict on the PML route, library defaults
                store.write_status(run_dir, notes=[
                    "SpeckleBem vor WP-PML5b: MLFMM-Einstellungen der PML-Route ignoriert (Standardwerte) und "
                    "exakter PML-Ring ohne ACA (deutlich mehr Speicher). Bibliothek aktualisieren empfohlen."])


        def make_sim():
            if route == "pml":
                return sb.Simulation.with_pml(lib_mesh, exc, pml=sb.PmlTermination(**route_opts["pml"]), **kw)
            return sb.Simulation(lib_mesh, exc, **kw)

        sim = make_sim()
        report_library_messages()
        if route == "pml":
            store.write_status(run_dir, dark_band_ratio=float(sim.dark_band_ratio))
        store.write_status(run_dir, state="solving", n_unknowns=int(sim.num_unknowns),
                           formulation=str(sim.formulation).split(".")[-1], resolved_solver=r,
                           message="Assemblierung und Lösung")

        last = [0.0]

        def progress(it, res):
            now = time.time()
            if now - last[0] > 1.0:
                last[0] = now
                store.write_status(run_dir, iteration=int(it), residual=float(res))

        t0 = time.time()
        notes = list(store.read_status(run_dir).get("notes") or [])
        while True:
            try:
                res = sim.solve(tol=r["tol"], callback=progress)
                break
            except RuntimeError as e:
                leaf = next_mlfmm_leaf(e, kw)
                if leaf is None:
                    if "cannot represent region" in str(e):
                        raise RuntimeError(f"{MLFMM_LOSSY_HELP}\n\nBibliothek: {e}") from e
                    raise
                kw["mlfmm"]["min_box_size_lambda"] = leaf
                notes.append(f"MLFMM: ein verlustbehaftetes Gebiet ist bei der gewählten Blattgröße nicht "
                             f"darstellbar; neuer Versuch mit Blättern ≥ {leaf:g} λ (mehr exaktes Nahfeld).")
                store.write_status(run_dir, notes=notes, message=f"Neuer Versuch, MLFMM-Blätter ≥ {leaf:g} λ")
                sim = make_sim()
        store.write_status(run_dir, state="postprocessing", message="Auswertung",
                           iterations=int(res.iterations), converged=bool(res.converged),
                           true_residual=float(res.true_relative_residual),
                           solve_seconds=time.time() - t0)
        (run_dir / "report.txt").write_text(sim.report(), encoding="utf-8")

        arrays = {"residual_history": np.asarray(res.residual_history, dtype=float)}
        if meta.get("kind") == "substrate":  # fixed lab-frame co-pol vector of the incident beam
            from .plugins.excitations import pol_vector

            th = pe.get("incidence_angle", 0.0)
            ctx["co_pol"] = pol_vector(pe["polarization"], th).tolist()
        for i, (obs, po) in enumerate(m["observables"]):
            for k, v in obs.compute(sb, sim, po, ctx).items():
                arrays[f"obs{i}__{k}"] = np.asarray(v)
        np.savez_compressed(run_dir / "results.npz", **arrays)
        if r["save_hdf5"]:
            try:  # library format (specklebem.io), GUI config and versions as /metadata
                sim.save(str(run_dir / "currents.h5"), overwrite=True, metadata={
                    "gui_config": json.dumps({k: v for k, v in cfg.items() if k != "resolved"}),
                    "gui_rules": json.dumps(rules or {}), "library_version": str(sb.__version__)})
                store.write_status(run_dir, hdf5="currents.h5")
            except ImportError as e:  # h5py missing in the worker environment: keep the results
                store.write_status(run_dir, hdf5_error=f"HDF5 nicht geschrieben: {e}")
        report_library_messages()
        store.write_status(run_dir, state="done", message="Fertig", finished=time.time())
    except BaseException as e:  # noqa: BLE001 - report everything to the GUI, then fail loudly
        report_library_messages()
        store.write_status(run_dir, state="error", message=f"{type(e).__name__}: {e}",
                           traceback=traceback.format_exc(), finished=time.time())
        raise


def _pid() -> int:
    import os

    return os.getpid()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "info":
        _json_out(cmd_info())
    elif cmd == "rules":
        _json_out(cmd_rules(json.load(sys.stdin)))
    elif cmd == "h5info":
        _json_out(cmd_h5info(json.load(sys.stdin)))
    elif cmd == "mesh":
        _json_out(cmd_mesh(json.load(sys.stdin)))
    elif cmd == "run":
        cmd_run(Path(argv[2]))
    else:
        print(f"unknown command {cmd!r}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
