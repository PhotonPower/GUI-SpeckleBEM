"""G20: library log messages, feature probes, tolerance rule (no library needed)."""

import types

from sbgui import liblog
from sbgui.checks import collect_issues
from sbgui.config import default_config
from sbgui.worker import library_features


def test_spdlog_lines_are_parsed_with_and_without_colour():
    text = "\n".join([
        "some python print",
        "[2026-10-20 10:00:00.123] [info] assembling",
        "[2026-10-20 10:00:01.000] [\x1b[33mwarning\x1b[m] rough Ag: no quantitative results",
        "[2026-10-20 10:00:01.500] [specklebem] [error] budget exceeded",
        "[2026-10-20 10:00:02.000] [warning] rough Ag: no quantitative results",  # duplicate
    ])
    msgs = liblog.parse_messages(text)
    assert msgs == [{"level": "warning", "msg": "rough Ag: no quantitative results"},
                    {"level": "error", "msg": "budget exceeded"}]


def test_messages_since_reads_only_the_new_part(tmp_path):
    log = tmp_path / "run.log"
    log.write_text("[t] [warning] old\n", encoding="utf-8")
    off = liblog.log_size(tmp_path)
    with open(log, "a", encoding="utf-8") as f:
        f.write("[t] [warning] new\n")
    assert [m["msg"] for m in liblog.messages_since(tmp_path, off)] == ["new"]
    assert liblog.messages_since(tmp_path / "missing", 0) == []


def test_feature_probes_on_a_fake_library():
    def with_pml(*a, mlfmm=None):
        """with_pml(open_mesh, excitation, *, compression='dense', mlfmm=None)"""

    sim = types.SimpleNamespace(with_pml=with_pml, field=1, incident_power=1, reflectance=1, save=1)
    full = types.SimpleNamespace(Simulation=sim, AngularSpectrumBeam=1, RoughSurface=1,
                                 rough_surface_box_params=1, make_open_surface_mesh=1, plane_grid=1)
    f = library_features(full, have_h5py=True)
    assert all(f.values()), f
    old = types.SimpleNamespace(Simulation=types.SimpleNamespace())
    f = library_features(old, have_h5py=False)
    assert not any(f.values()), f


def test_plasmonic_material_with_loose_tolerance_gets_a_hint():
    cfg = default_config()
    rules = {"plasmonic": True, "waist_fraction": 0.25, "box_depth": 2e-6}
    msgs = [i.msg for i in collect_issues(cfg, rules) if i.level == "info"]
    assert any("1e-5" in m for m in msgs)
    cfg["solver"]["tol"] = 1e-5
    assert not any("1e-5" in i.msg for i in collect_issues(cfg, rules))
