"""Headless render tests of the Streamlit pages. They must pass WITHOUT specklebem (CI): the
pages then show an error banner and keep working for geometry, preview and checks."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGES = {name: str(ROOT / "sbgui" / "ui" / "pages" / f"{name}.py") for name in ("model", "run", "results")}


@pytest.fixture(autouse=True)
def _no_library_and_tmp_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("SBGUI_WORKER_PYTHON", "nonexistent-python")
    monkeypatch.setenv("SBGUI_RUNS_DIR", str(tmp_path))


def _app(name):
    return AppTest.from_file(PAGES[name], default_timeout=60).run()


@pytest.mark.parametrize("name", list(PAGES))
def test_page_renders_without_exception(name):
    at = _app(name)
    assert not at.exception, [e.value for e in at.exception]


def test_model_page_reports_missing_library_but_stays_usable():
    at = _app("model")
    assert any("specklebem" in e.value for e in at.error)
    assert any(m.label == "Unbekannte 2N" for m in at.metric)  # cost estimate works without the library


@pytest.mark.parametrize("geometry", ["ellipsoid", "isolated_line", "rough_surface"])
def test_switching_geometry_keeps_page_alive(geometry):
    at = _app("model")
    at.selectbox(key="w:geometry.type").set_value(geometry).run()
    assert not at.exception, [e.value for e in at.exception]


def test_impossible_profile_is_reported_as_error_not_exception():
    at = _app("model")
    at.selectbox(key="w:geometry.type").set_value("isolated_line").run()
    at.number_input(key="w:geometry.p.swa").set_value(45.0).run()
    at.number_input(key="w:geometry.p.cd").set_value(100.0).run()  # 45 deg, H = 100 nm, CD = 100 nm closes
    assert not at.exception
    assert any("spitz" in e.value for e in at.error)


# -- G24/G25/G15: solver choice, series, speckle results ------------------------------------------------


def _with_cfg(name, mutate):
    from sbgui.config import default_config

    cfg = default_config()
    mutate(cfg)
    at = AppTest.from_file(PAGES[name], default_timeout=60)
    at.session_state["cfg"] = cfg
    return at.run()


def _rough(cfg):
    from sbgui.plugins.geometry_rough import RoughSurface

    cfg["geometry"] = {"type": "rough_surface", "params": RoughSurface.schema().defaults()}


def test_run_page_offers_the_block_preconditioner_and_its_level():
    at = _app("run")
    sel = at.selectbox(key="w:solver.preconditioner")
    assert any("Block-Diagonal" in o for o in sel.options)  # options are the display labels
    assert not [s for s in at.selectbox if s.key == "w:solver.block_level"]
    sel.set_value("block_diagonal").run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s for s in at.selectbox if s.key == "w:solver.block_level"]


def test_series_expander_only_for_rough_surfaces():
    assert not [e for e in _app("run").expander if "Serie" in e.label]
    at = _with_cfg("run", _rough)
    assert not at.exception, [e.value for e in at.exception]
    assert [e for e in at.expander if "Serie" in e.label]
    assert [b for b in at.button if b.key == "series.start"][0].disabled  # no library in CI


def test_series_input_errors_are_shown_not_raised():
    at = _with_cfg("run", _rough)
    at.text_input(key="series.sigma").set_value("50, abc").run()
    assert not at.exception and any("keine Zahl" in e.value for e in at.error)
    at.text_input(key="series.sigma").set_value("50, 100").run()
    at.text_input(key="series.seeds").set_value("0").run()
    assert not at.exception and any("Seed" in e.value for e in at.error)


def test_pml_options_render_on_the_model_page():
    def pml(cfg):
        _rough(cfg)
        cfg["geometry"]["params"]["termination"] = "pml"

    at = _with_cfg("model", pml)
    assert not at.exception, [e.value for e in at.exception]
    src = at.selectbox(key="w:geometry.p.far_field_source")
    assert [o.split(" (")[0] for o in src.options] == ["Ströme im Fenster", "Huygens-Ebene"]
    src.set_value("huygens").run()
    assert not at.exception and at.number_input(key="w:geometry.p.huygens_z_h") is not None


def _speckle_run(root, sigma=150.0, seed=1):
    import json

    import numpy as np

    from sbgui.config import default_config, save_config
    from sbgui.plugins.geometry_rough import RoughSurface

    cfg = default_config()
    cfg["geometry"] = {"type": "rough_surface", "params": RoughSurface.schema().defaults() | {
        "sigma": sigma, "seed": seed, "termination": "pml"}}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {
        "beam_model": "rigorous", "polarization": "p", "incidence_angle": 0.0, "waist_mode": "auto", "waist": 0.6}}
    cfg["observables"] = [{"type": "speckle_statistics", "params": {"distance": 1.0, "n_speckles": 20,
                                                                    "n_pixels": 21}}]
    d = root / f"20261026-120000_s{sigma:g}_{seed}"
    d.mkdir()
    save_config(cfg, d / "config.json")
    np.savez(d / "mesh.npz", meta=json.dumps({"kind": "substrate", "termination": "pml"}),
             vertices=np.zeros((3, 3)), triangles=np.array([[0, 1, 2]]))
    I = np.random.default_rng(seed).exponential(size=(21, 21))
    np.savez(d / "results.npz", **{f"obs0__{k}": v for k, v in dict(
        intensity=I, pixel_size=1e-4, wavelength_medium=5e-7, distance=1e-3, aperture=1e-5, side=2e-3, x0=0.0,
        contrast=float(I.std() / I.mean()), coherent_fraction=1.4e-4, speckle_size_expected=2.5e-4,
        ks_statistic=0.05, ks_p_value=0.6, ks_n=100, ks_modified=0.8, ks_rejects=False,
        speckle_size=np.array([2.6e-4, 2.6e-4]), speckle_size_rel_error=0.04).items()})
    status = {"state": "done", "n_unknowns": 1000, "far_field_source": "huygens",
              "preconditioner": "block_diagonal"}
    (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def test_results_page_shows_speckle_statistics_ensemble_and_run_settings(tmp_path):
    _speckle_run(tmp_path, 150.0, 1)
    _speckle_run(tmp_path, 200.0, 1)
    at = _app("results")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Speckle-Statistik" in s.value for s in at.subheader)
    assert any("Speckle-Ensemble" in s.value for s in at.subheader)
    assert any("wird nicht verworfen" in i.value for i in at.info)
    caps = " ".join(c.value for c in at.caption)
    assert "Fernfeld-Quelle: huygens" in caps and "Vorkonditionierer: block_diagonal" in caps
    assert len([m for m in at.multiselect if m.key == "ens.pick"][0].options) == 2


def test_ensemble_without_library_is_an_error_message_not_an_exception(tmp_path):
    _speckle_run(tmp_path)
    at = _app("results")
    [b for b in at.button if b.label.startswith("Ensemble-Statistik")][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Ensemble nicht berechenbar" in e.value for e in at.error)


def test_results_page_shows_progress_of_a_running_run(tmp_path):
    import json
    import os

    from sbgui.config import default_config, save_config

    d = tmp_path / "20261026-105015_lauf"
    d.mkdir()
    save_config(default_config(), d / "config.json")
    (d / "status.json").write_text(json.dumps({"state": "solving", "worker_pid": os.getpid()}), encoding="utf-8")
    (d / "run.log").write_text(
        "[2026-10-26 10:53:00.428] [info] [pml_ring.cpp:763] PmlRingOperator: N = 86360\n", encoding="utf-8")
    at = _app("results")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Fernring (ACA)" in c.value and "vor " in c.value for c in at.caption)
    assert any("Letzte Zeilen der Bibliothek" in e.label for e in at.expander)
