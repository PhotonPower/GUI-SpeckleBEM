"""G24: block-diagonal preconditioner (library WP-PC1, ADR 0011) in the solver settings, checks and worker probes."""

import types

from sbgui.checks import capability_issues, collect_issues, resolve_solver
from sbgui.config import SOLVER, default_config
from sbgui.worker import library_features


def test_schema_offers_block_diagonal_and_its_level_only_then():
    f = {x.key: x for x in SOLVER.fields}
    assert "block_diagonal" in [c[0] for c in f["preconditioner"].choices]
    assert SOLVER.defaults()["block_level"] == 1
    assert not SOLVER.is_visible(f["block_level"], {"preconditioner": "auto"})
    assert SOLVER.is_visible(f["block_level"], {"preconditioner": "block_diagonal"})
    assert not SOLVER.errors({"preconditioner": "block_diagonal", "block_level": 0})


def test_block_diagonal_with_automatic_solver_is_gmres_even_for_small_dense_systems():
    s = SOLVER.defaults() | {"preconditioner": "block_diagonal", "block_level": 0}
    r = resolve_solver(s, 3_000)  # auto would be the direct LU for 2N = 3000
    assert (r["compression"], r["solver"], r["block_level"]) == ("dense", "gmres", 0)
    assert resolve_solver(SOLVER.defaults(), 3_000)["solver"] == "direct"  # unchanged without block-diagonal


def test_block_diagonal_with_the_direct_solver_is_an_error():
    cfg = default_config()
    cfg["solver"].update(preconditioner="block_diagonal", solver="direct", compression="dense")
    msgs = [i.msg for i in collect_issues(cfg, None, 3_000) if i.level == "error"]
    assert any("Block-Diagonal" in m and "GMRES" in m for m in msgs)
    cfg["solver"]["solver"] = "gmres"
    assert not any("Block-Diagonal" in i.msg for i in collect_issues(cfg, None, 3_000) if i.level == "error")


def test_old_library_without_block_preconditioner_is_reported_before_the_run():
    cfg = default_config()
    cfg["solver"]["preconditioner"] = "block_diagonal"
    old = {"features": {"block_preconditioner": False}}
    assert any("WP-PC1" in i.msg for i in capability_issues(cfg, old, {}, 1000) if i.level == "error")
    assert not capability_issues(cfg, {"features": {"block_preconditioner": True}}, {}, 1000)
    assert not capability_issues(cfg, {"features": {}}, {}, 1000)  # probe unknown (cached capabilities): no verdict
    cfg["solver"]["preconditioner"] = "auto"
    assert not capability_issues(cfg, old, {}, 1000)


def test_probe_finds_block_level_in_the_constructor_docstring():
    class Sim:
        def __init__(self, mesh, excitation, *, preconditioner="auto", block_level=1):
            """__init__(self, mesh, excitation, *, preconditioner: str = 'auto', block_level: int = 1)"""

    class Before:
        def __init__(self, mesh, excitation, *, preconditioner="auto"):
            """__init__(self, mesh, excitation, *, preconditioner: str = 'auto')"""

    assert library_features(types.SimpleNamespace(Simulation=Sim), have_h5py=False)["block_preconditioner"]
    assert not library_features(types.SimpleNamespace(Simulation=Before), have_h5py=False)["block_preconditioner"]
