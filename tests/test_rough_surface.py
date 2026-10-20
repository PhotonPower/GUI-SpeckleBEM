"""G10/G21: rough-surface plugin (library mesher), Fresnel reference, library meshing in the worker."""

import math

import numpy as np
import pytest

from sbgui.checks import collect_issues
from sbgui.config import default_config, materialise
from sbgui.plugins.geometry_rough import RoughSurface
from sbgui.plugins.observables import fresnel_reflectance
from sbgui.registry import GEOMETRIES, load_plugins

SI_RULES = {"box_depth": 5.6e-6, "waist_fraction": 1 / 6, "plasmonic": False, "weak_absorber": True}
AG_RULES = {"box_depth": 2.0e-6, "waist_fraction": 1 / 4, "plasmonic": True, "weak_absorber": False}


def rough_cfg(**params):
    cfg = default_config()
    p = RoughSurface.schema().defaults()
    p.update(params)
    cfg["geometry"] = {"type": "rough_surface", "params": p}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {"beam_model": "rigorous", "polarization": "p",
                                                             "incidence_angle": 0.0, "waist_mode": "auto",
                                                             "waist": 0.6}}
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 24, "n_phi": 48}}]
    return cfg


def msgs(cfg, rules, level=None):
    return [i.msg for i in collect_issues(cfg, rules) if level is None or i.level == level]


def test_plugin_is_registered_as_library_mesher():
    load_plugins()
    cls = GEOMETRIES.get("rough_surface")
    assert cls.mesher == "library" and cls.kind == "substrate"
    d = cls.schema().defaults()
    assert d["L"] == 4.5 and d["sigma"] == 50.0 and d["grading"] == "uniform"


def test_size_estimate_matches_the_library_grid():
    # measured with the library: L = 4.5 um, h = 50 nm, Si box depth 5.65 um -> 113 760 triangles
    m = materialise(rough_cfg(), SI_RULES | {"box_depth": 5.645512306863873e-06})
    geom, pg = m["geometry"]
    assert geom.estimate_triangles(pg, 50e-9) == pytest.approx(113_760, rel=0.02)


def test_default_si_case_is_runnable_and_names_its_uncertainties():
    cfg = rough_cfg()
    assert not msgs(cfg, SI_RULES, "error")
    info = " ".join(msgs(cfg, SI_RULES, "info"))
    assert "Randunsicherheit" not in info  # sigma = 50 nm is inside the validated rule
    assert "konvergiert" in info  # h = lambda/10 > lambda/20: mesh-convergence note
    cfg = rough_cfg(sigma=100.0)
    assert any("Randunsicherheit" in m for m in msgs(cfg, SI_RULES, "info"))


def test_rough_silver_in_the_box_is_flagged_flat_silver_is_not():
    assert any("plasmonisch" in m for m in msgs(rough_cfg(), AG_RULES, "warning"))
    flat = rough_cfg(sigma=0.0)
    assert not any("plasmonisch" in m for m in msgs(flat, AG_RULES, "warning"))
    assert any("Fresnel" in m for m in msgs(flat, AG_RULES, "info"))


def test_box_depth_rules():
    no_depth = {k: v for k, v in SI_RULES.items() if k != "box_depth"} | {"box_depth_error": "lossless"}
    assert any("Boxtiefe" in m for m in msgs(rough_cfg(), no_depth, "error"))
    assert not any("Boxtiefe" in m for m in msgs(rough_cfg(depth_mode="manual", depth=3.0), no_depth, "error"))
    assert any("unter der Regel" in m for m in msgs(rough_cfg(depth_mode="manual", depth=1.0), SI_RULES, "warning"))


def test_waist_rule_uses_the_patch_length():
    cfg = rough_cfg(L=3.0)
    cfg["excitation"]["params"].update(waist_mode="manual", waist=0.6)  # limit 3 um / 6 = 0.5 um
    assert any("Randregel" in m for m in msgs(cfg, SI_RULES, "error"))


def test_fresnel_reference():
    assert fresnel_reflectance(1, 1.5, 0, "p") == pytest.approx(0.04)
    assert fresnel_reflectance(1, 1.5, 0, "s") == pytest.approx(0.04)
    assert fresnel_reflectance(1, 1.5, math.atan(1.5), "p") == pytest.approx(0, abs=1e-12)  # Brewster
    n = 4.299182157332219 - 0.0704785210096846j  # library silicon_500nm
    assert fresnel_reflectance(1, n, 0, "p") == pytest.approx(0.387718, rel=1e-5)
    assert fresnel_reflectance(1, n, 0.5, "s") == pytest.approx(fresnel_reflectance(1, n.conjugate(), 0.5, "s"))
    assert fresnel_reflectance(1.5, 1.0, 0.8, "s") == pytest.approx(1.0)  # total internal reflection


@pytest.mark.needs_library
def test_library_builds_a_closed_box_with_the_rule_parameters():
    sb = pytest.importorskip("specklebem")
    p = RoughSurface.schema().to_si(RoughSurface.schema().defaults() | {"L": 1.0, "sigma": 30.0})
    ctx = {"wavelength": 500e-9, "object": sb.silicon_500nm(), "background": sb.vacuum(), "rules": None}
    lm = RoughSurface().build_lib(sb, p, 100e-9, ctx)
    assert lm.route == "closed" and lm.handle.is_closed()
    assert lm.result.n_unknowns == 3 * lm.result.n_triangles
    assert lm.result.meta["beam_waist_fraction"] == pytest.approx(1 / 6)
    assert np.isfinite(lm.result.meta["sigma_measured"])
    p_man = p | {"depth_mode": "manual", "depth": 1e-6}  # band deeper than the box -> dropped
    assert RoughSurface().build_lib(sb, p_man, 100e-9, ctx).result.meta["box_fine_depth"] is None
