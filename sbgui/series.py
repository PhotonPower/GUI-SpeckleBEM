"""Series of runs (G14a): several run directories processed one after another by one detached process.

    python -m sbgui.series <series.json>

``series.json`` lists the run directories (all created up front in state ``queued``). Each run is started
exactly like a single run (``python -m sbgui.jobrunner <run_dir>``), so memory is never shared between runs and
a crash or a cancel of one run does not stop the others. A run that was cancelled while it was still queued is
skipped. stdlib only (plus the job runner, which is started as a subprocess).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import store


def run_series(run_dirs: list[Path], start: Callable[[Path], int] | None = None) -> dict[str, str]:
    """Process ``run_dirs`` in order; returns {run directory name: final state}. ``start(run_dir)`` runs one
    run to its end and returns the exit code (default: a ``sbgui.jobrunner`` subprocess; tests pass a stub)."""
    start = start or _start_jobrunner
    out: dict[str, str] = {}
    for d in map(Path, run_dirs):
        if store.read_status(d).get("state") != "queued":  # cancelled while queued, or started by hand
            out[d.name] = store.read_status(d).get("state", "?")
            continue
        code = start(d)
        st = store.read_status(d)
        if code != 0 and st.get("state") not in store.FINAL:  # runner died without reporting
            store.write_status(d, state="error", finished=time.time(),
                               message=f"Lauf beendet mit Code {code} (häufig: Speicher erschöpft)")
        out[d.name] = store.read_status(d).get("state", "?")
    return out


def _start_jobrunner(run_dir: Path) -> int:
    from .bridge import PROJECT_ROOT, _gui_env  # noqa: PLC0415

    with open(run_dir / "run.log", "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "sbgui.jobrunner", str(run_dir)], stdout=log,
                                stderr=subprocess.STDOUT, cwd=PROJECT_ROOT, env=_gui_env())
        store.write_status(run_dir, jobrunner_pid=proc.pid)  # cancel() kills exactly this run
        return proc.wait()


def main(path: Path) -> int:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    states = run_series([Path(d) for d in spec["runs"]])
    Path(path).with_suffix(".done.json").write_text(json.dumps(states), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
