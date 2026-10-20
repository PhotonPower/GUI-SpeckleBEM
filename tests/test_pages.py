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
