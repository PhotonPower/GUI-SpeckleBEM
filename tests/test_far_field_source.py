"""G25: far-field source of the PML route (library WP-PML6, ADR 0010) and the rough-metal gap rule (WP-PML6b)."""

import pytest

from sbgui import heightmap_route as hr
from sbgui.checks import capability_issues, collect_issues
from sbgui.config import default_config
from sbgui.plugins.geometry_rough import RoughSurface

SI = {"box_depth": 5.6e-6, "waist_fraction": 1 / 6, "plasmonic": False, "weak_absorber": True,
      "exterior_wavelength": 500e-9}
AG = {"box_depth": 2.0e-6, "waist_fraction": 1 / 4, "plasmonic": True, "weak_absorber": False,
      "exterior_wavelength": 500e-9}


def cfg_with(**params):
    cfg = default_config()
    p = RoughSurface.schema().defaults() | {"termination": "pml", "L": 1.5, "sigma": 50.0, "Lc": 250.0}
    p.update(params)
    cfg["mesh"]["h"] = 125.0
    cfg["geometry"] = {"type": "rough_surface", "params": p}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {
        "beam_model": "rigorous", "polarization": "p", "incidence_angle": 0.0, "waist_mode": "manual", "waist": 0.5}}
    cfg["observables"] = [{"type": "drc_hemisphere", "params": {"n_theta": 24, "n_phi": 48}}]
    return cfg


def msgs(cfg, rules, level):
    return [i.msg for i in collect_issues(cfg, rules) if i.level == level]


def test_defaults_keep_the_validated_currents_window_and_send_no_extra_keywords():
    p = RoughSurface.schema().to_si(RoughSurface.schema().defaults())
    assert p["far_field_source"] == "currents"
    assert hr.far_field_kwargs(p) == {}  # a library before WP-PML6 has no such PmlTermination keywords


def test_huygens_keywords_are_in_si_and_zero_means_automatic():
    schema = RoughSurface.schema()
    p = schema.to_si(schema.defaults() | {"far_field_source": "huygens"})
    assert hr.far_field_kwargs(p) == {"far_field_source": "huygens"}
    p = schema.to_si(schema.defaults() | {"far_field_source": "huygens", "huygens_z_h": 0.75, "huygens_spacing": 125.0})
    assert hr.far_field_kwargs(p) == {"far_field_source": "huygens", "huygens_z_h": pytest.approx(0.75e-6),
                                      "huygens_spacing": pytest.approx(125e-9)}


def test_huygens_fields_are_only_visible_with_huygens_on_the_pml_route():
    f = {x.key: x for x in RoughSurface.schema().fields}
    s = RoughSurface.schema()
    assert not s.is_visible(f["far_field_source"], {"termination": "box"})
    assert s.is_visible(f["far_field_source"], {"termination": "pml"})
    assert not s.is_visible(f["huygens_z_h"], {"termination": "pml", "far_field_source": "currents"})
    assert s.is_visible(f["huygens_z_h"], {"termination": "pml", "far_field_source": "huygens"})
    assert not s.is_visible(f["huygens_spacing"], {"termination": "box", "far_field_source": "huygens"})


def test_huygens_is_flagged_as_a_diagnostic():
    m = msgs(cfg_with(far_field_source="huygens"), SI, "info")
    assert any("Huygens" in x and "Diagnose" in x for x in m)
    assert not any("Huygens-Ebene: Diagnose" in x for x in msgs(cfg_with(), SI, "info"))


def test_rough_metal_needs_a_gap_of_six_wavelengths():
    narrow = msgs(cfg_with(), AG, "warning")  # gap 0.5 um = 1 lambda
    assert any("6 λ = 3 µm" in x and "ADR 0010" in x for x in narrow)
    wide = cfg_with(gap=3.0)
    assert not any("6 λ" in x for x in msgs(wide, AG, "warning"))
    assert any("θ ≤ 30°" in x for x in msgs(wide, AG, "info"))
    # a rough dielectric is not subject to the rule, a flat metal neither
    assert not any("6 λ" in x for x in msgs(cfg_with(), SI, "warning"))
    assert not any("6 λ" in x for x in msgs(cfg_with(sigma=0.0), AG, "warning"))


def test_gap_rule_uses_the_exterior_wavelength_of_the_library_rules():
    rules = AG | {"exterior_wavelength": 250e-9}  # water-like exterior: 6 lambda = 1.5 um
    assert any("1.5 µm" in x for x in msgs(cfg_with(gap=1.0), rules, "warning"))
    assert not any("6 λ" in x for x in msgs(cfg_with(gap=1.5), rules, "warning"))


def test_line_geometry_offers_the_same_termination_fields():
    from sbgui.plugins.geometry_line import IsolatedLine  # noqa: PLC0415

    keys = {f.key for f in IsolatedLine.schema().fields}
    assert {"far_field_source", "huygens_z_h", "huygens_spacing"} <= keys


def test_old_library_without_huygens_is_reported_only_when_it_is_chosen():
    meta = {"termination": "pml"}
    old = {"features": {"huygens": False}}
    assert not capability_issues(cfg_with(), old, meta, 1000)
    errs = [i for i in capability_issues(cfg_with(far_field_source="huygens"), old, meta, 1000) if i.level == "error"]
    assert errs and "WP-PML6" in errs[0].msg
    assert not capability_issues(cfg_with(far_field_source="huygens"), {"features": {"huygens": True}}, meta, 1000)


def test_box_route_no_longer_claims_the_pml_route_is_missing():
    box = cfg_with(termination="box", L=4.5)
    m = msgs(box, AG, "warning")
    assert any("PML" in x and "nicht angebunden" not in x for x in m)
    assert not any("nicht angebunden" in x for x in msgs(cfg_with(), AG, "warning"))
