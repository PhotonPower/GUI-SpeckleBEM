"""G12: PML route of the rough surface (open surface, ADR 0009) - zones, size estimate, rules, and
the shared height map of box and PML route (library cross-check 7e set-up)."""

import math

import numpy as np
import pytest

from sbgui.checks import collect_issues
from sbgui.config import default_config, materialise
from sbgui.plugins.geometry_rough import RoughSurface

SI = {"box_depth": 5.6e-6, "waist_fraction": 1 / 6, "plasmonic": False, "weak_absorber": True}
AG = {"box_depth": 2.0e-6, "waist_fraction": 1 / 4, "plasmonic": True, "weak_absorber": False}


def pml_cfg(waist=None, h=125.0, **params):
    cfg = default_config()
    p = RoughSurface.schema().defaults() | {"termination": "pml", "L": 1.5, "sigma": 0.0}
    p.update(params)
    cfg["mesh"]["h"] = h
    cfg["geometry"] = {"type": "rough_surface", "params": p}
    exc = {"beam_model": "rigorous", "polarization": "p", "incidence_angle": 0.0,
           "waist_mode": "manual" if waist else "auto", "waist": waist or 0.6}
    cfg["excitation"] = {"type": "gaussian_beam", "params": exc}
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 24, "n_phi": 48}}]
    return cfg


def issues(cfg, rules, level=None):
    return [i.msg for i in collect_issues(cfg, rules) if level is None or i.level == level]


def test_zones_and_region_radius_of_the_validated_7a_geometry():
    m = materialise(pml_cfg(), SI)
    geom, p = m["geometry"]
    z = geom.zones(p)
    assert z["taper_end"] == pytest.approx(1.25e-6) and z["pml_start"] == pytest.approx(1.75e-6)
    assert z["outer_half"] == pytest.approx(2.75e-6)
    assert geom.meta_hint(p)["beam_region_radius"] == pytest.approx(1.02 * math.sqrt(2) * 1.75e-6)
    assert geom.estimate_triangles(p, 125e-9) == 3872  # library: 44 x 44 cells, 2 triangles each


def test_validated_7a_configuration_has_no_errors_or_warnings():
    cfg = pml_cfg(waist=0.5)
    assert not issues(cfg, SI, "error")
    assert not [m for m in issues(cfg, SI, "warning") if "h =" not in m]  # only the generic mesh note


def test_pml_rules():
    assert any("Vielfaches" in m for m in issues(pml_cfg(L=1.6), SI, "error"))
    assert any("W_g > 0" in m for m in issues(pml_cfg(gap=0.0), SI, "error"))
    assert any("Korrelationslänge" in m for m in issues(pml_cfg(sigma=50.0, Lc=800.0), SI, "error"))
    assert any("PML-Start" in m for m in issues(pml_cfg(waist=0.6), SI, "warning"))  # 1.75 < 3.5 * 0.6
    rough_ag = issues(pml_cfg(sigma=50.0), AG, "warning")  # gap 0.5 um = 1 lambda < 6 lambda (ADR 0010 decision 3)
    assert any("6 λ" in m for m in rough_ag) and not any("Box-Prüfungen" in m for m in rough_ag)
    assert any("PML" in m for m in issues(pml_cfg(sigma=50.0, termination="box", L=4.5), AG, "warning"))


def test_box_waist_rule_does_not_apply_to_the_pml_route():
    cfg = pml_cfg(waist=0.5)  # 0.5 um > L/6 = 0.25 um: an error on the box route
    assert not any("Randregel" in m for m in issues(cfg, SI, "error"))
    cfg["geometry"]["params"]["termination"] = "box"
    assert any("Randregel" in m for m in issues(cfg, SI, "error"))


def test_mlfmm_with_direct_solver_is_rejected():
    cfg = pml_cfg(waist=0.5)
    cfg["solver"].update(compression="mlfmm", solver="direct")
    assert any("GMRES" in i.msg for i in collect_issues(cfg, SI, 30_000) if i.level == "error")


@pytest.mark.needs_library
def test_box_and_pml_route_share_the_surface():
    sb = pytest.importorskip("specklebem")
    schema = RoughSurface.schema()
    p = schema.to_si(schema.defaults() | {"L": 1.5, "sigma": 40.0, "Lc": 250.0, "taper": 0.5})
    ctx = {"wavelength": 500e-9, "object": sb.silicon_500nm(), "background": sb.vacuum(), "rules": None}
    h = 125e-9
    box = RoughSurface().build_lib(sb, p | {"depth_mode": "manual", "depth": 1e-6}, h, ctx)
    pml = RoughSurface().build_lib(sb, p | {"termination": "pml"}, h, ctx)
    assert box.route == "closed" and pml.route == "pml"
    assert pml.options["pml"]["correlation_length"] == pytest.approx(250e-9)
    assert pml.result.meta["pml_start"] == pytest.approx(1.75e-6)
    assert pml.result.n_triangles == 3872 and pml.result.n_unknowns == 2 * pml.handle.mesh.num_edges  # interior edges
    assert box.result.meta["sigma_measured"] == pytest.approx(pml.result.meta["sigma_measured"])

    def top_heights(v, half):  # smallest z per patch grid node = top face (walls/bottom lie below the rim)
        out = {}
        for x, y, z in v[(np.abs(v[:, 0]) <= half + 1e-12) & (np.abs(v[:, 1]) <= half + 1e-12)]:
            k = (round(x / h), round(y / h))
            out[k] = min(out.get(k, np.inf), z)
        return out

    hb, hp = top_heights(box.result.vertices, 0.75e-6), top_heights(pml.result.vertices, 0.75e-6)
    assert set(hb) == set(hp) and len(hb) == 13 * 13
    assert max(abs(hb[k] - hp[k]) for k in hb) == 0.0  # bitwise, as the library's 7e height identity


@pytest.mark.needs_library
@pytest.mark.parametrize("case", ["flat", "rough", "ridge", "trench"])
def test_with_pml_accepts_every_height_map_surface(case):
    """Construct the Simulation (no solve): catches termination arguments the library rejects."""
    sb = pytest.importorskip("specklebem")
    from sbgui.plugins.geometry_line import IsolatedLine

    if case in ("flat", "rough"):
        g, extra = RoughSurface(), {"L": 1.5, "sigma": 0.0 if case == "flat" else 30.0, "Lc": 250.0}
    else:
        g, extra = IsolatedLine(), {"meshing": "library", "feature": case, "Lx": 1.5, "cd": 300.0}
    s = g.schema()
    p = g.resolve(s.to_si(s.defaults() | extra | {"termination": "pml"}), {"box_depth": 5.6e-6})
    ctx = {"wavelength": 500e-9, "object": sb.silicon_500nm(), "background": sb.vacuum(), "rules": None}
    assert not [i.msg for i in g.validate(p, ctx | {"h": 100e-9}) if i.level == "error"]
    lm = g.build_lib(sb, p, 100e-9, ctx)
    exc = sb.AngularSpectrumBeam(wavelength=500e-9, waist=0.5e-6, polarization="p", incidence_angle=0.0,
                                 background=sb.vacuum(), region_radius=lm.result.meta["beam_region_radius"])
    sim = sb.Simulation.with_pml(lm.handle, exc, pml=sb.PmlTermination(**lm.options["pml"]), object=ctx["object"],
                                 exterior=ctx["background"])
    assert sim.dark_band_ratio < 1e-4


def test_line_pml_needs_a_taper_of_at_least_the_cd():
    from sbgui.plugins.geometry_line import IsolatedLine

    s = IsolatedLine.schema()
    p = s.to_si(s.defaults() | {"meshing": "library", "termination": "pml", "Lx": 1.5, "cd": 600.0})
    errs = [i.msg for i in IsolatedLine().validate(p, {"h": 50e-9, "wavelength": 500e-9}) if i.level == "error"]
    assert any("CD (als Lc)" in e for e in errs)
    p["termination"] = "box"
    assert not any("CD (als Lc)" in i.msg for i in IsolatedLine().validate(p, {"h": 50e-9}))


def test_pml_route_rejects_a_plane_wave():
    cfg = pml_cfg(waist=0.5)
    cfg["excitation"] = {"type": "plane_wave", "params": {}}
    assert any("begrenzten Strahl" in m for m in issues(cfg, SI, "error"))
    cfg["geometry"]["params"]["termination"] = "box"
    assert not any("begrenzten Strahl" in m for m in issues(cfg, SI, "error"))
    cfg = pml_cfg(waist=0.5)
    cfg["excitation"]["params"]["beam_model"] = "paraxial"
    assert any("rigorose" in m for m in issues(cfg, SI, "warning"))
