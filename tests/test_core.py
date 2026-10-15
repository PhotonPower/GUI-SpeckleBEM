import json

import pytest

from sbgui import store
from sbgui.checks import collect_issues, estimate_memory_gb, resolve_solver
from sbgui.config import SCHEMA_VERSION, default_config, load_config, materialise, migrate, save_config
from sbgui.params import Field, Schema
from sbgui.registry import EXCITATIONS, GEOMETRIES, MATERIALS, OBSERVABLES, Registry, load_plugins


def test_plugins_are_discovered():
    load_plugins()
    assert {"sphere", "ellipsoid", "isolated_line"} <= set(GEOMETRIES.ids())
    assert {"library", "constant", "table"} <= set(MATERIALS.ids())
    assert {"plane_wave", "gaussian_beam"} <= set(EXCITATIONS.ids())
    assert {"bistatic_rcs", "drc_hemisphere"} <= set(OBSERVABLES.ids())


def test_duplicate_plugin_id_is_rejected():
    reg = Registry("x")

    class A:
        id = "a"

    class B:
        id = "a"

    reg.register(A)
    with pytest.raises(ValueError):
        reg.register(B)


def test_schema_si_conversion_and_errors():
    s = Schema((Field("w", "Breite", "float", 100.0, "nm", min=10, max=1000),
                Field("a", "Winkel", "float", 90.0, "deg"),
                Field("x", "x", "float", 1.0, "µm", visible_if=lambda v: v.get("m") == "on"),
                Field("m", "m", "choice", "off", choices=(("on", "an"), ("off", "aus")))))
    si = s.to_si({"w": 200, "a": 180})
    assert si["w"] == pytest.approx(200e-9) and si["a"] == pytest.approx(3.14159265, rel=1e-6)
    assert s.errors({"w": 5}) and not s.errors({"w": 50})
    assert not s.errors({"x": 1e9})  # hidden fields are not validated
    assert s.fill({"nope": 1}).keys() == {"w", "a", "x", "m"}


def test_config_roundtrip_and_migration(tmp_path):
    cfg = default_config()
    save_config(cfg, tmp_path / "c.json")
    assert load_config(tmp_path / "c.json") == cfg
    old = {**cfg, "schema_version": 0}
    assert migrate(old)["schema_version"] == SCHEMA_VERSION
    with pytest.raises(ValueError):
        migrate({**cfg, "schema_version": SCHEMA_VERSION + 1})


def test_materialise_converts_units():
    m = materialise(default_config())
    assert m["wavelength"] == pytest.approx(500e-9) and m["h"] == pytest.approx(50e-9)
    geom, p = m["geometry"]
    assert p["radius"] == pytest.approx(500e-9)


def test_issues_for_bad_inputs():
    cfg = default_config()
    cfg["mesh"]["h"] = 400.0  # > lambda/3
    assert any(i.level == "error" and "λ/3" in i.msg for i in collect_issues(cfg, None))
    cfg = default_config()
    cfg["optics"]["wavelength"] = 633.0  # Si table exists only at 500 nm
    assert any("500 nm" in i.msg for i in collect_issues(cfg, None))
    cfg = default_config()
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 30, "n_phi": 60}}]
    assert any("passt nicht" in i.msg for i in collect_issues(cfg, None))  # DRC needs a substrate


def test_beam_waist_rule_blocks_too_wide_beam():
    cfg = default_config()
    cfg["geometry"] = {"type": "isolated_line", "params": GEOMETRIES.get("isolated_line").schema().defaults()}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {**EXCITATIONS.get("gaussian_beam").schema().defaults(),
                                                             "waist_mode": "manual", "waist": 1.5}}
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 30, "n_phi": 60}}]
    msgs = [i.msg for i in collect_issues(cfg, {"waist_fraction": 1 / 6}) if i.level == "error"]
    assert any("Randregel" in m for m in msgs)  # L = 4 um -> w0 <= 0.67 um


def test_solver_auto_resolution_and_memory():
    assert resolve_solver({}, 3840) == {**resolve_solver({}, 3840), "compression": "dense", "solver": "direct"}
    assert resolve_solver({}, 15_000)["solver"] == "gmres"
    assert resolve_solver({}, 200_000)["compression"] == "mlfmm"
    assert estimate_memory_gb(20_000, "dense", "gmres")[0] == pytest.approx(6.4)  # docs/backlog figure
    lo, hi = estimate_memory_gb(1_000_000, "mlfmm", "gmres")
    assert lo < 75 < hi  # recorded Si run: 75 GB at 2N = 1.0e6


def test_store_status_is_merged_atomically(tmp_path, monkeypatch):
    monkeypatch.setenv("SBGUI_RUNS_DIR", str(tmp_path))
    d = store.new_run_dir("mein lauf!")
    store.write_status(d, state="solving", n=1)
    store.write_status(d, iteration=5)
    st = store.read_status(d)
    assert st["state"] == "solving" and st["iteration"] == 5 and "updated" in st
    assert "mein_lauf" in d.name
    assert json.loads((d / "status.json").read_text())["n"] == 1
