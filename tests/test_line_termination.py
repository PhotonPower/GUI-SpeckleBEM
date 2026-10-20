"""G23: isolated line/trench on the library height map - box (graded/fine band) or PML termination."""

import math

import numpy as np
import pytest

from sbgui.checks import collect_issues
from sbgui.config import default_config, materialise
from sbgui.plugins.geometry_line import IsolatedLine

SI = {"box_depth": 5.6e-6, "waist_fraction": 1 / 6, "plasmonic": False, "weak_absorber": True}
AG = {"box_depth": 2.0e-6, "waist_fraction": 1 / 4, "plasmonic": True, "weak_absorber": False}


def line_cfg(waist=None, h=50.0, **params):
    cfg = default_config()
    p = IsolatedLine.schema().defaults() | {"meshing": "library", "Lx": 1.5, "r_top": 0.0, "r_bottom": 0.0}
    p.update(params)
    cfg["mesh"]["h"] = h
    cfg["geometry"] = {"type": "isolated_line", "params": p}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {
        "beam_model": "rigorous", "polarization": "p", "incidence_angle": 0.0,
        "waist_mode": "manual" if waist else "auto", "waist": waist or 0.6}}
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 24, "n_phi": 48}}]
    return cfg


def msgs(cfg, rules, level):
    return [i.msg for i in collect_issues(cfg, rules) if i.level == level]


def test_mesher_follows_the_parameter_and_old_configs_stay_on_gmsh():
    g = IsolatedLine()
    assert g.mesher_for(IsolatedLine.schema().defaults()) == "gui"
    assert g.mesher_for({"meshing": "library"}) == "library"
    assert g.mesher_for({}) == "gui"  # configs saved before G23 have no "meshing" field


def test_termination_fields_only_with_library_meshing():
    s = IsolatedLine.schema()
    gui = s.defaults()
    lib = gui | {"meshing": "library"}
    f = {x.key: x for x in s.fields}

    def shown(key, v):
        return f[key].visible_if is None or f[key].visible_if(v)

    assert not shown("termination", gui) and shown("termination", lib)
    assert shown("Ly", gui) and not shown("Ly", lib)
    assert shown("grading", lib) and not shown("grading", lib | {"termination": "pml"})
    assert not shown("depth_mode", lib | {"termination": "pml"})


def test_pml_zones_estimate_and_waist_rule_use_the_square_patch():
    cfg = line_cfg(waist=0.5, termination="pml")
    m = materialise(cfg, SI)
    geom, p = m["geometry"]
    hint = geom.meta_hint(p)
    assert hint["pml_start"] == pytest.approx(1.75e-6) and hint["lateral_size"] == pytest.approx(1.5e-6)
    assert geom.estimate_triangles(p, 50e-9) == 24_200  # library: 110 x 110 cells
    assert not msgs(cfg, SI, "error")
    assert not any("Randregel" in x for x in msgs(cfg, SI, "error"))


def test_sampling_rules():
    steep = msgs(line_cfg(swa=88.0), SI, "warning")  # 100 nm / tan 88 deg = 3.5 nm < h
    assert any("innerhalb einer Gitterzelle" in x and f"{math.degrees(math.atan(2)):.0f}°" in x for x in steep)
    assert not any("Gitterzelle" in x for x in msgs(line_cfg(swa=60.0), SI, "warning"))
    assert any("Vielfaches" in x for x in msgs(line_cfg(Lx=1.52), SI, "error"))
    assert any("PML" in x for x in msgs(line_cfg(), AG, "warning"))  # Ag with structure in the box


@pytest.mark.needs_library
@pytest.mark.parametrize("feature,sign", [("ridge", -1), ("trench", 1)])
@pytest.mark.parametrize("termination", ["box", "pml"])
def test_library_mesh_orientation(feature, sign, termination):
    sb = pytest.importorskip("specklebem")
    g = IsolatedLine()
    s = g.schema()
    p = s.to_si(s.defaults() | {"meshing": "library", "feature": feature, "termination": termination, "Lx": 1.5,
                                "cd": 300.0, "height": 100.0, "swa": 80.0, "r_top": 0.0, "r_bottom": 0.0,
                                "depth_mode": "manual", "depth": 1.0, "grading": "graded"})
    ctx = {"wavelength": 500e-9, "object": sb.silicon_500nm(), "background": sb.vacuum(), "rules": None}
    lm = g.build_lib(sb, p, 50e-9, ctx)
    v = lm.result.vertices
    assert lm.route == ("pml" if termination == "pml" else "closed")
    if lm.route == "closed":
        assert lm.handle.is_closed()
    centre = v[(np.abs(v[:, 0]) < 100e-9) & (np.abs(v[:, 1]) < 0.7e-6)]
    extreme = centre[:, 2].min() if sign < 0 else centre[:, 2].max() if termination == "pml" else None
    if extreme is not None:
        assert extreme == pytest.approx(sign * 100e-9, abs=1e-12)  # ridge towards the light (-z), trench into +z
    assert lm.result.meta["z_min" if sign < 0 else "z_max"] == pytest.approx(sign * 100e-9, abs=1e-12)
