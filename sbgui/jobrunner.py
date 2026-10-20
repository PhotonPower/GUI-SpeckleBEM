"""Detached job runner (GUI environment): meshing, then the worker in the library environment.

    python -m sbgui.jobrunner <run_dir>

Keeps Streamlit responsive and isolates crashes (out-of-memory kills only this run).
"""

from __future__ import annotations

import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import store
from .bridge import worker_command
from .checks import collect_issues
from .config import load_config, materialise
from .meshing.common import save_mesh
from .registry import load_plugins


def main(run_dir: Path) -> int:
    load_plugins()
    store.write_status(run_dir, state="meshing", message="Netz wird erzeugt", started=time.time())
    try:
        cfg = load_config(run_dir / "config.json")
        rules = cfg.get("resolved", {}).get("rules")
        m = materialise(cfg, rules)
        geom, pg = m["geometry"]
        if geom.mesher == "library":  # the worker meshes with the library (rough / open surfaces)
            store.write_status(run_dir, state="solving", message="Worker startet (Netz aus der Bibliothek)")
        else:
            t0 = time.time()
            mesh = geom.build(pg, m["h"])
            meta = save_mesh(run_dir / "mesh.npz", mesh, time.time() - t0)
            errors = [i.msg for i in collect_issues(cfg, rules, mesh.n_unknowns, meta["mesh_stats"])
                      if i.level == "error"]
            if errors:
                raise RuntimeError("Vorab-Prüfung fehlgeschlagen: " + " | ".join(errors))
            store.write_status(run_dir, state="solving", message="Worker startet", n_triangles=mesh.n_triangles,
                               n_unknowns=mesh.n_unknowns, mesh_seconds=meta["mesh_seconds"])
        argv, env = worker_command("run", str(run_dir))
        with open(run_dir / "run.log", "ab") as log:
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
            store.write_status(run_dir, worker_pid=proc.pid)
            code = proc.wait()
        final = store.read_status(run_dir)
        if code != 0 and final.get("state") not in store.FINAL:  # killed without a chance to report
            store.write_status(run_dir, state="error", finished=time.time(),
                               message=f"Worker beendet mit Code {code} (häufig: Speicher erschöpft)")
        return code
    except BaseException as e:  # noqa: BLE001
        if store.read_status(run_dir).get("state") not in store.FINAL:
            store.write_status(run_dir, state="error", message=f"{type(e).__name__}: {e}",
                               traceback=traceback.format_exc(), finished=time.time())
        return 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
