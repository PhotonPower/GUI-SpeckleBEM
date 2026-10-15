"""Round trip GUI core -> job runner -> worker -> results with the real library.

Skipped without an importable specklebem. Marked slow: ~30 s on one core (dense assembly of a
3840-unknown sphere); not run in CI, run manually (docs/04_testing.md).
"""

import time

import numpy as np
import pytest

pytest.importorskip("specklebem")
pytestmark = [pytest.mark.needs_library, pytest.mark.slow]


def test_sphere_matches_mie(tmp_path, monkeypatch):
    monkeypatch.setenv("SBGUI_RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("SBGUI_WORKER_PYTHON", raising=False)
    from sbgui import bridge, store
    from sbgui.config import default_config

    cfg = default_config()
    cfg["geometry"]["params"]["radius"] = 300.0
    cfg["mesh"]["h"] = 80.0
    cfg["object"] = {"type": "constant", "params": {"n": 1.5, "k": 0.0}}
    cfg["resolved"] = {"rules": bridge.rules(cfg)}
    run = bridge.start_run(cfg)
    t0 = time.time()
    while time.time() - t0 < 600 and store.read_status(run).get("state") not in store.FINAL:
        time.sleep(2)
    st = store.read_status(run)
    assert st["state"] == "done", st.get("message")
    r = np.load(run / "results.npz")
    assert float(r["obs0__rel_l2_error"]) < 0.02  # measured 0.0054 at h = 80 nm
    assert float(r["obs0__C_sca"]) == pytest.approx(float(r["obs0__C_sca_mie"]), rel=0.02)
