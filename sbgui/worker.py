"""Worker: the only process that imports ``specklebem``.

    python -m sbgui.worker info                  -> JSON capabilities of the installed library
    python -m sbgui.worker rules   < request     -> JSON of library rule values (box depth, ...)
    python -m sbgui.worker run <run_dir>         -> solve + observables, writes results.npz

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

from . import store
from .checks import resolve_solver
from .config import load_config, materialise
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
        "features": {
            "angular_spectrum_beam": hasattr(sb, "AngularSpectrumBeam"),
            "pml": hasattr(sb.Simulation, "with_pml"),
            "hdf5": importlib.util.find_spec("h5py") is not None,
        },
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


def cmd_run(run_dir: Path) -> None:
    import specklebem as sb

    load_plugins()
    cfg = load_config(run_dir / "config.json")
    rules = cfg.get("resolved", {}).get("rules")
    store.write_status(run_dir, state="solving", message="Lauf wird aufgebaut", worker_pid=_pid())
    try:
        m = materialise(cfg, rules)
        lam = m["wavelength"]
        z = np.load(run_dir / "mesh.npz", allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        obj = m["object"][0].build(sb, m["object"][1], lam)
        bg = m["background"][0].build(sb, m["background"][1], lam)
        n_bg = m["background"][0].refractive_index(m["background"][1], lam)
        ctx = {"wavelength": lam, "h": m["h"], "meta": meta, "rules": rules, "object": obj,
               "background": bg, "n_background": float(np.real(n_bg)) if n_bg is not None else 1.0}
        exc_plugin, pe = m["excitation"]
        exc = exc_plugin.build(sb, pe, ctx, bg)
        ctx["co_pol"] = None
        mesh = sb.TriangleMesh(z["vertices"], z["triangles"])
        if not mesh.is_closed():
            raise RuntimeError("TriangleMesh.is_closed() is False - mesh rejected by the library")

        r = resolve_solver(cfg["solver"], 3 * len(z["triangles"]))
        if r["threads"] > 0:
            import os

            os.environ["OMP_NUM_THREADS"] = str(r["threads"])
        kw = {"object": obj, "exterior": bg, "solver": r["solver"], "compression": r["compression"],
              "formulation": r["formulation"], "preconditioner": r["preconditioner"]}
        if r["compression"] == "mlfmm":
            kw["mlfmm"] = {"accuracy_digits": r["mlfmm_digits"]}
        sim = sb.Simulation(mesh, exc, **kw)
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
        res = sim.solve(tol=r["tol"], callback=progress)
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
            sim.save(str(run_dir / "currents.h5"))
        store.write_status(run_dir, state="done", message="Fertig", finished=time.time())
    except BaseException as e:  # noqa: BLE001 - report everything to the GUI, then fail loudly
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
    elif cmd == "run":
        cmd_run(Path(argv[2]))
    else:
        print(f"unknown command {cmd!r}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
