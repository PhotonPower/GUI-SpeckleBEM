"""Run directories: one folder per run, everything a run needs or produces lives inside.

    <runs_dir>/<timestamp>_<name>/
        config.json    full reproducibility record (incl. the library rules used)
        mesh.npz       vertices, triangles, meta (JSON string)
        status.json    state machine, written atomically by job runner and worker
        results.npz    observable arrays, keys ``obs<i>__<name>``
        report.txt     Simulation.report()
        run.log        stdout/stderr of job runner and worker
        currents.h5    optional, library HDF5 format (specklebem.io) with the GUI config as /metadata

stdlib only: imported by GUI, job runner and worker.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

STATES = ("queued", "meshing", "solving", "postprocessing", "done", "error", "cancelled")
FINAL = ("done", "error", "cancelled")


def runs_dir() -> Path:
    p = Path(os.environ.get("SBGUI_RUNS_DIR", Path.home() / "sbgui_runs"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_run_dir(name: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "lauf"
    base = runs_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}"
    d, i = base, 1
    while d.exists():
        i += 1
        d = Path(f"{base}_{i}")
    d.mkdir(parents=True)
    return d


def write_status(run_dir: Path, **fields) -> dict:
    """Merge ``fields`` into status.json (atomic replace; safe against concurrent readers)."""
    path = Path(run_dir) / "status.json"
    cur = read_status(run_dir)
    cur.update(fields)
    cur["updated"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur), encoding="utf-8")
    os.replace(tmp, path)
    return cur


def read_status(run_dir: Path) -> dict:
    try:
        return json.loads((Path(run_dir) / "status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def pid_alive(pid: int) -> bool | None:
    """True/False if it can be determined, None if not (Windows without psutil)."""
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except ImportError:
        pass
    if os.name == "nt":
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def live_status(run_dir: Path) -> dict:
    """Status with crash detection: a run that is not in a final state but whose job-runner and
    worker processes are both gone (killed, out of memory, machine reboot) is reported as error
    instead of 'solving' forever. Does not modify the file."""
    st = read_status(run_dir)
    if not st or st.get("state") in FINAL:
        return st
    keys = ("jobrunner_pid", "worker_pid") + (("series_pid",) if st.get("state") == "queued" else ())
    pids = [st.get(k) for k in keys if st.get(k)]  # series_pid: the runner a queued run of a series waits for
    if pids and all(pid_alive(int(p)) is False for p in pids):
        st = {**st, "state": "error", "crashed": True,
              "message": "Prozess existiert nicht mehr (abgestürzt, beendet oder Speicher erschöpft?). "
                         "Letzter Zustand: " + str(st.get("state"))}
    return st


def list_runs() -> list[dict]:
    out = []
    for d in sorted(runs_dir().iterdir(), reverse=True):
        if d.is_dir() and (d / "config.json").exists():
            st = live_status(d)
            out.append({"dir": d, "name": d.name, "state": st.get("state", "?"), "status": st})
    return out
