"""MLFMM leaf size: solver field, and the retry after the library's lossy-region failure (ADR 0008 §6)."""

from sbgui.checks import resolve_solver
from sbgui.config import SOLVER
from sbgui.worker import next_mlfmm_leaf

ERR = RuntimeError('Simulation: compression "mlfmm" cannot represent region R2 to 10^-3: the region is too lossy')


def test_retry_once_with_two_wavelength_leaves():
    kw = {"mlfmm": {"accuracy_digits": 3}}
    assert next_mlfmm_leaf(ERR, kw) == 2.0
    kw["mlfmm"]["min_box_size_lambda"] = 2.0
    assert next_mlfmm_leaf(ERR, kw) is None  # 4 lambda only by hand (near field almost dense)
    assert next_mlfmm_leaf(RuntimeError("other"), {"mlfmm": {}}) is None
    assert next_mlfmm_leaf(ERR, {}) is None  # dense, or WP-PML5a without the mlfmm dict


def test_leaf_field_reaches_the_resolved_solver():
    s = SOLVER.defaults() | {"compression": "mlfmm", "solver": "gmres", "mlfmm_leaf": 2.0}
    assert resolve_solver(s, 100_000)["mlfmm_leaf"] == 2.0
    assert resolve_solver(SOLVER.defaults(), 100_000)["mlfmm_leaf"] == 0.0
    f = {x.key: x for x in SOLVER.fields}["mlfmm_leaf"]
    assert not f.visible_if({"compression": "dense"}) and f.visible_if({"compression": "auto"})
