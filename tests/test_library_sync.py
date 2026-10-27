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
        """with_pml(open_mesh, excitation, *, compression: str = 'dense', mlfmm: Optional[dict] = None) -> Simulation

        Simulation of an open surface terminated by a PML (ADR 0009; dense, or "mlfmm" since WP-PML5a)."""

    sim = types.SimpleNamespace(with_pml=with_pml, field=1, incident_power=1, reflectance=1, save=1,
                                block_preconditioner=1)
    full = types.SimpleNamespace(Simulation=sim, AngularSpectrumBeam=1, RoughSurface=1,
                                 rough_surface_box_params=1, make_open_surface_mesh=1, plane_grid=1,
                                 PmlTermination=types.SimpleNamespace(far_field_source=1),
                                 ks_test_exponential=1, speckle_contrast=1, speckle=1)
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


# -- progress from run.log (lines copied from a real PML + MLFMM run, 2N = 172 720) -----------------------

REAL_LOG = """\
[2026-10-26 10:50:19.128] [info] [angular_spectrum_beam.cpp:218] AngularSpectrumBeam: w0 = 7.493e-07 m, 3268 plane waves
[2026-10-26 10:50:19.354] [info] [simulation.cpp:901] Simulation (PML): sigma_max 4, order 2, gap 5e-07 m
[2026-10-26 10:50:27.533] [info] [far_operator.cpp:674] MlfmmFarOperator: region R1 level 5 (a = 0.531 lambda_i): expansion
[2026-10-26 10:52:12.323] [info] [far_operator.cpp:1266] MlfmmFarOperator: 2N = 172720, 6 octree levels, d0 = 3
[2026-10-26 10:52:13.166] [info] [assembler.cpp:854] sparse assembly: N = 86360, 2N = 172720, nnz = 143695616
[2026-10-26 10:53:00.414] [info] [timer.cpp:13] [timer] sparse assembly (2N = 172720, nnz = 143695616): 47.247 s
[2026-10-26 10:53:00.428] [info] [pml_ring.cpp:763] PmlRingOperator: N = 86360, 35920 stretched (41.6 %)
[2026-10-26 10:53:10.298] [info] [assembler.cpp:911] sparse assembly (PML): 6797824 unordered stretched pairs
[2026-10-26 11:11:54.930] [info] [timer.cpp:13] [timer] sparse assembly (2N = 172720, nnz = 108836736): 1133.847 s
"""


def test_progress_lines_keep_all_levels_and_drop_file_and_line():
    lines = liblog.parse_lines("python print\n" + REAL_LOG, limit=3)
    assert [x["time"] for x in lines] == ["2026-10-26 10:53:00.428", "2026-10-26 10:53:10.298",
                                          "2026-10-26 11:11:54.930"]
    assert lines[0]["level"] == "info" and lines[0]["msg"].startswith("PmlRingOperator")
    assert lines[2]["msg"].startswith("[timer] sparse assembly") and "timer.cpp" not in lines[2]["msg"]


def test_phase_follows_the_last_message_of_the_pml_run():
    steps = REAL_LOG.splitlines()
    expect = ["Strahl ist berechnet", "MLFMM-Fernoperatoren werden aufgebaut", "Gebiete und Oktree-Ebenen",
              "Nahfeld-Matrizen werden assembliert", "Nahfeld-Matrix wird assembliert",
              "Nahfeld-Assemblierungsschritt", "Fernring (ACA)", "PML-Nahring", "Nahfeld-Assemblierungsschritt"]
    for n, word in enumerate(expect, start=1):
        assert word in liblog.phase_of(liblog.parse_lines("\n".join(steps[:n]))), (n, word)
    assert liblog.phase_of([]) is None
    assert liblog.phase_of([{"time": "t", "level": "info", "msg": "something new"}]) == "something new"


def test_read_progress_reports_the_silence_and_survives_a_missing_log(tmp_path):
    import os
    import time

    assert liblog.read_progress(tmp_path) == {"phase": None, "lines": [], "silent_seconds": None}
    log = tmp_path / "run.log"
    log.write_text(REAL_LOG, encoding="utf-8")
    os.utime(log, (time.time() - 600, time.time() - 600))
    p = liblog.read_progress(tmp_path, limit=4)
    assert len(p["lines"]) == 4 and 590 < p["silent_seconds"] < 700 and p["phase"]
    log.write_text("no spdlog output yet\n", encoding="utf-8")
    assert liblog.read_progress(tmp_path)["silent_seconds"] is None


def test_duration_format():
    from sbgui.ui.state import format_duration

    assert (format_duration(45), format_duration(600), format_duration(9000)) == ("45 s", "10 min", "2 h 30 min")
