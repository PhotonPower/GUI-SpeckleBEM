"""The only way the GUI talks to the compute side: subprocesses and files.

Environment variables (all optional):
  SBGUI_WORKER_PYTHON       interpreter that has ``specklebem`` (default: the GUI's interpreter),
                            e.g. C:/msys64/ucrt64/bin/python.exe
  SBGUI_WORKER_PYTHONPATH   extra PYTHONPATH for it, e.g. build/win-release/python;python
  SBGUI_RUNS_DIR            where runs are stored (default ~/sbgui_runs)

A remote server later = replace ``_worker_argv`` by an ssh/queue command; nothing else changes
because the contract is the run directory.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from . import store
from .config import save_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def worker_command(*args: str) -> tuple[list[str], dict]:
    """(argv, env) for a worker invocation; used by the job runner."""
    return _worker_argv(*args), _worker_env()


def _worker_python() -> str:
    return os.environ.get("SBGUI_WORKER_PYTHON", sys.executable)


def _worker_env() -> dict:
    env = os.environ.copy()
    extra = os.environ.get("SBGUI_WORKER_PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(PROJECT_ROOT), extra, env.get("PYTHONPATH", "")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _gui_env() -> dict:
    """Environment for the job runner: GUI interpreter, so it must NOT see the worker's PYTHONPATH."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(PROJECT_ROOT), env.get("PYTHONPATH", "")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _worker_argv(*args: str) -> list[str]:
    return [_worker_python(), "-m", "sbgui.worker", *args]


class WorkerError(RuntimeError):
    pass


def query(cmd: str, payload: dict | None = None, timeout: float = 120.0) -> dict:
    """Run a short worker command and return its JSON payload (last stdout line)."""
    try:
        r = subprocess.run(_worker_argv(cmd), input=json.dumps(payload or {}), capture_output=True,
                           text=True, timeout=timeout, env=_worker_env(), cwd=PROJECT_ROOT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorkerError(f"Worker nicht startbar: {e}") from e
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["?"]
        raise WorkerError(f"Worker-Fehler: {tail[0]}")
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1])


def capabilities() -> dict | None:
    """Library capabilities, or None if no usable specklebem is reachable (GUI still shows previews)."""
    try:
        return query("info", timeout=60)
    except (WorkerError, json.JSONDecodeError, IndexError):
        return None


def rules(cfg: dict) -> dict | None:
    try:
        return query("rules", {"cfg": cfg})
    except (WorkerError, json.JSONDecodeError, IndexError):
        return None


def preview_mesh(cfg: dict, rules: dict | None, h: float, timeout: float = 900.0):
    """Library-made mesh for the preview (``Geometry.mesher == "library"``): runs the worker's
    ``mesh`` command and returns a ``MeshResult`` (meta includes mesh_stats and max_radius)."""
    import tempfile  # noqa: PLC0415

    import numpy as np  # noqa: PLC0415

    from .base import MeshResult  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="sbgui_mesh_") as d:
        out = Path(d) / "mesh.npz"
        query("mesh", {"cfg": cfg, "rules": rules, "h": h, "out": str(out)}, timeout=timeout)
        with np.load(out, allow_pickle=False) as z:
            return MeshResult(z["vertices"].copy(), z["triangles"].copy(), json.loads(str(z["meta"])))


def start_run(cfg: dict) -> Path:
    """Create the run directory and start the detached job runner (meshing, then the worker)."""
    run_dir = store.new_run_dir(cfg.get("name", "lauf"))
    save_config(cfg, run_dir / "config.json")
    store.write_status(run_dir, state="queued", message="in der Warteschlange")
    log = open(run_dir / "run.log", "ab")
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen([sys.executable, "-m", "sbgui.jobrunner", str(run_dir)], stdout=log,
                         stderr=subprocess.STDOUT, cwd=PROJECT_ROOT, env=_gui_env(), **kw)
    store.write_status(run_dir, jobrunner_pid=p.pid)
    return run_dir


def start_series(cfgs: list[dict]) -> list[Path]:
    """Create one run directory per config (state ``queued``) and start a detached process that runs them one
    after another (``sbgui.series``). Returns the run directories in run order."""
    dirs = []
    for cfg in cfgs:
        d = store.new_run_dir(cfg.get("name", "lauf"))
        save_config(cfg, d / "config.json")
        store.write_status(d, state="queued", message="in der Serie wartend")
        dirs.append(d)
    spec = dirs[0].parent / f"series_{dirs[0].name}.json"
    spec.write_text(json.dumps({"runs": [str(d) for d in dirs]}), encoding="utf-8")
    log = open(dirs[0] / "series.log", "ab")
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "sbgui.series", str(spec)], stdout=log,
                            stderr=subprocess.STDOUT, cwd=PROJECT_ROOT, env=_gui_env(), **kw)
    for d in dirs:  # not a jobrunner_pid: cancelling one queued run must not kill the runner of the others
        store.write_status(d, series_pid=proc.pid)
    return dirs


def _kill_tree(pid: int) -> None:
    try:
        import psutil

        proc = psutil.Process(pid)
        for c in proc.children(recursive=True):
            c.kill()
        proc.kill()
    except ImportError:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001 - process already gone
        pass


def cancel(run_dir: Path) -> None:
    st = store.read_status(run_dir)
    if st.get("state") in store.FINAL:
        return
    for key in ("worker_pid", "jobrunner_pid"):
        if st.get(key):
            _kill_tree(int(st[key]))
    store.write_status(run_dir, state="cancelled", message="vom Benutzer abgebrochen")
