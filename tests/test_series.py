"""G14a: series over sigma and seed - config generation, sequential runner, start/cancel contract."""

import json
import subprocess

import pytest

from sbgui import bridge, series, store
from sbgui.config import default_config
from sbgui.plugins.geometry_rough import RoughSurface
from sbgui.sweeps import MAX_RUNS, parse_numbers, rough_series, supports_series


@pytest.fixture(autouse=True)
def _runs_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SBGUI_RUNS_DIR", str(tmp_path))


def rough_cfg():
    cfg = default_config()
    cfg["name"] = "wps2"
    cfg["geometry"] = {"type": "rough_surface", "params": RoughSurface.schema().defaults()}
    cfg["resolved"] = {"rules": {"box_depth": 5.6e-6}}
    return cfg


def test_parse_numbers():
    assert parse_numbers("50, 100  150;200") == [50.0, 100.0, 150.0, 200.0]
    assert parse_numbers("1,2,2,1", integers=True, minimum=1) == [1, 2]
    assert parse_numbers("12,5") == [12.0, 5.0]  # a comma separates; there is no decimal comma
    for bad, kw in (("", {}), ("a", {}), ("1.5", {"integers": True}), ("0", {"integers": True, "minimum": 1})):
        with pytest.raises(ValueError):
            parse_numbers(bad, **kw)


def test_only_rough_surfaces_support_a_series():
    assert supports_series(rough_cfg()) and not supports_series(default_config())
    with pytest.raises(ValueError, match="raue Oberfläche"):
        rough_series(default_config(), [50.0], [1])


def test_series_configs_are_sigma_major_and_independent():
    cfgs = rough_series(rough_cfg(), [50.0, 100.0], [1, 2])
    got = [(c["geometry"]["params"]["sigma"], c["geometry"]["params"]["seed"]) for c in cfgs]
    assert got == [(50.0, 1), (50.0, 2), (100.0, 1), (100.0, 2)]
    assert cfgs[0]["name"] == "wps2_sigma50_seed1" and cfgs[3]["name"] == "wps2_sigma100_seed2"
    assert cfgs[0]["geometry"]["params"] is not cfgs[1]["geometry"]["params"]
    assert cfgs[0]["resolved"]["rules"]["box_depth"] == 5.6e-6  # rules do not depend on sigma


def test_series_limits():
    with pytest.raises(ValueError, match="Höchstens"):
        rough_series(rough_cfg(), [float(i + 1) for i in range(MAX_RUNS)], [1, 2])
    with pytest.raises(ValueError, match="Seed 0"):
        rough_series(rough_cfg(), [50.0], [0])


def queued(n):
    dirs = []
    for i in range(n):
        d = store.new_run_dir(f"r{i}")
        store.write_status(d, state="queued")
        dirs.append(d)
    return dirs


def test_runs_are_processed_in_order_and_each_ends_in_its_own_state():
    dirs = queued(3)
    order = []

    def start(d):
        order.append(d.name)
        if d == dirs[1]:
            store.write_status(d, state="error", message="boom")
            return 1
        store.write_status(d, state="done")
        return 0

    states = series.run_series(dirs, start)
    assert order == [d.name for d in dirs]
    assert list(states.values()) == ["done", "error", "done"]  # an error does not stop the series


def test_a_run_cancelled_while_queued_is_skipped():
    dirs = queued(3)
    store.write_status(dirs[1], state="cancelled")
    started = []
    series.run_series(dirs, lambda d: (started.append(d), store.write_status(d, state="done"), 0)[2])
    assert started == [dirs[0], dirs[2]]


def test_a_runner_that_dies_without_reporting_is_marked_as_error():
    (d,) = queued(1)
    states = series.run_series([d], lambda d: -9)  # killed (out of memory)
    assert states[d.name] == "error" and "Speicher" in store.read_status(d)["message"]


def test_start_series_creates_queued_runs_and_one_detached_runner(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, argv, **kw):
            calls.append((argv, kw))
            self.pid = 4242

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    cfgs = rough_series(rough_cfg(), [50.0, 100.0], [1])
    dirs = bridge.start_series(cfgs)
    assert len(dirs) == 2 and all(store.read_status(d)["state"] == "queued" for d in dirs)
    assert all((d / "config.json").exists() for d in dirs)
    assert len(calls) == 1  # one runner for the whole series, never one process per run
    argv, kw = calls[0]
    assert argv[1:3] == ["-m", "sbgui.series"]
    spec = json.loads(open(argv[3], encoding="utf-8").read())
    assert spec["runs"] == [str(d) for d in dirs]
    assert kw.get("start_new_session") is True or "creationflags" in kw
    # queued runs wait for the runner (series_pid) but carry no jobrunner_pid: cancelling one of them must not
    # kill the runner of the others
    assert store.read_status(dirs[0])["series_pid"] == 4242 and "jobrunner_pid" not in store.read_status(dirs[0])
    bridge.cancel(dirs[1])
    assert store.read_status(dirs[1])["state"] == "cancelled"
    assert series.run_series(dirs, lambda d: (store.write_status(d, state="done"), 0)[1])[dirs[1].name] == "cancelled"


def test_queued_runs_of_a_dead_series_runner_are_reported_as_crashed(monkeypatch):
    (d,) = queued(1)
    store.write_status(d, series_pid=999_999_999)  # no such process
    monkeypatch.setattr(store, "pid_alive", lambda pid: False)
    st = store.live_status(d)
    assert st["state"] == "error" and st["crashed"]
    monkeypatch.setattr(store, "pid_alive", lambda pid: True)
    assert store.live_status(d)["state"] == "queued"
    store.write_status(d, state="solving")  # a running run is judged by its own processes only
    monkeypatch.setattr(store, "pid_alive", lambda pid: False)
    assert store.live_status(d)["state"] == "solving"  # no jobrunner/worker pid recorded: no verdict
