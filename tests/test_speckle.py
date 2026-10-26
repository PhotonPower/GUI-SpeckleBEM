"""G15: speckle statistics observable (library WP-S1/WP-S2) - plane geometry, both routes, rules, ensemble command.

The library is replaced by small numerical stand-ins (no specklebem needed); the real harness is exercised by the
slow test at the end when specklebem is importable.
"""

import json
import math
import sys
import types

import numpy as np
import pytest

from sbgui import worker
from sbgui.checks import collect_issues
from sbgui.config import default_config
from sbgui.plugins.geometry_rough import RoughSurface
from sbgui.plugins.observables import (
    SpeckleStatistics,
    coherent_fraction,
    speckle_plane,
)

C_GAUSS = 1.060041
LAM = 500e-9
RULES = {"box_depth": 5.6e-6, "waist_fraction": 1 / 6, "plasmonic": False, "weak_absorber": True,
         "exterior_wavelength": LAM, "speckle_constant_gaussian": C_GAUSS}


class Ks:
    def __init__(self, n):
        self.statistic, self.p_value, self.n, self.modified_statistic = 0.05, 0.6, n, 0.8


def fake_speckle_module():
    def observation_plane_size(wl, z, aperture, shape="gaussian", n_speckles=20):
        return n_speckles * C_GAUSS * wl * z / aperture

    def ensemble_statistics(patterns, pixel, wl, z, aperture, shape="gaussian", **kw):
        n = len(patterns)
        c = [float(np.std(p) / np.mean(p)) for p in patterns]
        exp = C_GAUSS * wl * z / aperture
        return {"n_patterns": n, "contrast": np.array(c), "mean_contrast": float(np.mean(c)),
                "std_contrast": float(np.std(c)), "ks": Ks(100 * n), "ks_rejects_5pct": False,
                "ks_stride": (4, 4), "correlation": np.eye(n), "speckle_size": np.full((n, 2), exp * 1.02),
                "speckle_size_mean": exp * 1.02, "speckle_size_expected": exp, "speckle_size_rel_error": 0.02}

    def monotone_decreasing(values, tolerance=0.0):
        return all(b <= a + tolerance for a, b in zip(values, values[1:]))

    m = types.ModuleType("specklebem.speckle")
    m.observation_plane_size, m.ensemble_statistics, m.monotone_decreasing = (
        observation_plane_size, ensemble_statistics, monotone_decreasing)
    return m


@pytest.fixture
def fake_library(monkeypatch):
    pkg = types.ModuleType("specklebem")
    pkg.speckle = fake_speckle_module()
    monkeypatch.setitem(sys.modules, "specklebem", pkg)
    monkeypatch.setitem(sys.modules, "specklebem.speckle", pkg.speckle)
    return pkg


class FakeSb:
    """Stand-ins for the calls of the observable; the field is a deterministic function of the point."""

    def plane_grid(self, origin, u, v, nu, nv):
        o, u, v = (np.asarray(a, float) for a in (origin, u, v))
        i, j = np.meshgrid(np.linspace(0, 1, nu), np.linspace(0, 1, nv), indexing="ij")
        return o + i.reshape(-1, 1) * u + j.reshape(-1, 1) * v

    def polarized_intensity(self, E, co_pol):
        co = np.abs(np.asarray(E) @ np.asarray(co_pol, float)) ** 2
        return co, np.linalg.norm(E, axis=1) ** 2 - co

    def speckle_contrast(self, I):
        I = np.asarray(I)
        return float(I.std() / I.mean())

    def speckle_size_expected(self, wl, z, aperture, shape):
        return C_GAUSS * wl * z / aperture


class FakeSim:
    def __init__(self):
        self.field_points = self.directions = None

    def field(self, pts, kind="total"):
        assert kind == "scattered"
        self.field_points = np.asarray(pts)
        rng = np.random.default_rng(3)
        E = rng.normal(size=(len(pts), 3)) + 1j * rng.normal(size=(len(pts), 3))
        return E, E

    def far_field(self, directions):
        self.directions = np.asarray(directions)
        rng = np.random.default_rng(3)
        return rng.normal(size=(len(directions), 3)) + 1j * rng.normal(size=(len(directions), 3))


def params(**kw):
    s = SpeckleStatistics.schema()
    return s.to_si(s.defaults() | {"n_speckles": 6, "n_pixels": 25} | kw)


def ctx(theta=0.0, pml=False, sigma=1.5e-7):
    exc = {"waist_mode": "manual", "waist": 0.5e-6, "incidence_angle": theta, "polarization": "p"}
    meta = {"kind": "substrate", "lateral_size": 3e-6, "sigma_measured": sigma}
    if pml:
        meta["open_surface"] = True
    return {"wavelength": LAM, "n_background": 1.0, "excitation_params": exc, "meta": meta, "rules": RULES,
            "co_pol": [1.0, 0.0, 0.0]}


def test_plane_is_sized_for_the_requested_speckles_and_centred_on_the_specular_reflection():
    side, pixel, x0, angle = speckle_plane({"distance": 1e-3, "n_speckles": 20, "n_pixels": 101}, LAM, 1e-6,
                                           C_GAUSS, math.radians(10))
    assert side == pytest.approx(20 * C_GAUSS * LAM * 1e-3 / 1e-6)  # 10.6 mm
    assert pixel == pytest.approx(side / 100) and x0 == pytest.approx(1e-3 * math.tan(math.radians(10)))
    assert angle == pytest.approx(math.degrees(math.atan(side / 2e-3)))


def test_closed_route_evaluates_the_exact_scattered_field_on_the_plane(fake_library):
    sim = FakeSim()
    out = SpeckleStatistics().compute(FakeSb(), sim, params(), ctx(theta=math.radians(5)))
    pts = sim.field_points
    assert pts.shape == (25 * 25, 3) and np.allclose(pts[:, 2], -1e-3)  # z = -distance (reflection side)
    assert out["intensity"].shape == (25, 25) and np.all(out["intensity"] >= 0)
    side = out["side"]
    assert pts[:, 1].min() == pytest.approx(-side / 2) and pts[:, 1].max() == pytest.approx(side / 2)
    assert 0.5 * (pts[:, 0].min() + pts[:, 0].max()) == pytest.approx(1e-3 * math.tan(math.radians(5)))
    assert out["aperture"] == pytest.approx(1e-6)  # D = 2 w0
    assert out["pixel_size"] == pytest.approx(side / 24)
    assert out["contrast"] > 0 and out["ks_n"] == 100 and out["ks_rejects"] is False
    assert out["coherent_fraction"] == pytest.approx(coherent_fraction(1.5e-7, LAM))


def test_pml_route_uses_the_far_field_in_unit_directions(fake_library):
    sim = FakeSim()
    out = SpeckleStatistics().compute(FakeSb(), sim, params(), ctx(pml=True))
    assert sim.field_points is None  # sim.field raises on the PML route
    d = sim.directions
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0) and np.all(d[:, 2] < 0)  # reflection hemisphere
    assert out["intensity"].shape == (25, 25)


def test_missing_statistics_keep_intensity_and_contrast(fake_library):
    def boom(*a, **k):
        raise ValueError("ks_test_exponential: n = 12 < 50 independent samples")

    fake_library.speckle.ensemble_statistics = boom
    out = SpeckleStatistics().compute(FakeSb(), FakeSim(), params(), ctx())
    assert "stats_error" in out and out["contrast"] > 0 and "ks_modified" not in out
    notes = SpeckleStatistics.notes(out)
    assert len(notes) == 1 and "n = 12" in notes[0]
    assert SpeckleStatistics.summary(out)["Kontrast std(I)/⟨I⟩"] == out["contrast"]


def test_plane_wave_is_refused(fake_library):
    c = ctx()
    c["excitation_params"] = {"polarization": "p", "incidence_angle": 0.0}
    with pytest.raises(ValueError, match="Gaußstrahl"):
        SpeckleStatistics().compute(FakeSb(), FakeSim(), params(), c)


def test_notes_do_not_overinterpret_partially_developed_speckle(fake_library):
    out = SpeckleStatistics().compute(FakeSb(), FakeSim(), params(), ctx(sigma=5e-8))  # coherent fraction 0.21
    note = SpeckleStatistics.notes(out)[0]
    assert "wird nicht verworfen" in note and "teilweise entwickelt" in note
    out = SpeckleStatistics().compute(FakeSb(), FakeSim(), params(), ctx(sigma=2e-7))
    assert "teilweise" not in SpeckleStatistics.notes(out)[0]


def test_figures_render_without_the_library(fake_library):
    out = SpeckleStatistics().compute(FakeSb(), FakeSim(), params(), ctx())
    figs = SpeckleStatistics().figures(out, {})
    assert len(figs) == 2 and figs[0].data[0].z.shape == (25, 25)


# -- pre-flight rules -----------------------------------------------------------------------------------


def cfg_speckle(rules=RULES, sigma=150.0, **obs):
    cfg = default_config()
    cfg["mesh"]["h"] = 125.0
    cfg["geometry"] = {"type": "rough_surface", "params": RoughSurface.schema().defaults() | {
        "termination": "box", "L": 3.0, "sigma": sigma, "Lc": 500.0}}
    cfg["excitation"] = {"type": "gaussian_beam", "params": {
        "beam_model": "rigorous", "polarization": "p", "incidence_angle": 0.0, "waist_mode": "manual",
        "waist": 0.5}}
    cfg["observables"] = [{"type": "speckle_statistics", "params": SpeckleStatistics.schema().defaults() | obs}]
    return cfg, rules


def texts(cfg, rules, level):
    return [i.msg for i in collect_issues(cfg, rules) if i.level == level]


def test_library_example_configuration_is_flagged_for_its_known_limits():
    cfg, rules = cfg_speckle(distance=1.0, n_speckles=20, n_pixels=101, sigma=50.0)
    w = texts(cfg, rules, "warning")
    # w0 = 0.5 um -> D = 1 um: 20 speckles need a 10.6 mm plane at 1 mm, theta = atan(5.3) = 79 deg (the library's
    # own example 02 quotes 12.7 mm and 81 deg for D = 0.83 um)
    assert any("reicht bis θ = 79°" in m and "nicht vom Abstand" in m for m in w)
    assert any("kohärenter Anteil" in m for m in texts(cfg, rules, "info"))  # sigma = 50 nm: 0.21


def test_the_library_target_case_has_no_plane_warnings():
    # L = 30 um, w0 = L/6 = 5 um -> D = 10 um: 20 speckles span tan(theta) = 20 c lambda / (2 D) = 0.53, 28 deg
    cfg, rules = cfg_speckle(distance=1.0, n_speckles=20, n_pixels=101)
    cfg["geometry"]["params"]["L"] = 30.0
    cfg["excitation"]["params"]["waist"] = 5.0
    assert not [m for m in texts(cfg, rules, "warning") if "h =" not in m]
    assert not any("kohärenter Anteil" in m for m in texts(cfg, rules, "info"))  # sigma 150 nm: 1.4e-4 < 1e-2


def test_sampling_rules():
    cfg, rules = cfg_speckle(distance=50.0, n_speckles=20, n_pixels=41)  # 2 px per speckle
    assert any("Pixel pro Speckle" in m for m in texts(cfg, rules, "warning"))
    cfg, rules = cfg_speckle(distance=50.0, n_speckles=10, n_pixels=61)  # (10/2)^2 = 25 < 50 samples
    assert any("unabhängige Stichproben" in m for m in texts(cfg, rules, "warning"))


def test_plane_wave_excitation_is_an_error():
    cfg, rules = cfg_speckle()
    cfg["excitation"] = {"type": "plane_wave", "params": {"polarization": "p", "incidence_angle": 0.0}}
    assert any("Gaußstrahl" in m for m in texts(cfg, rules, "error"))


def test_without_library_rules_the_plane_checks_are_skipped_with_a_note():
    cfg, rules = cfg_speckle(rules={k: v for k, v in RULES.items() if k != "speckle_constant_gaussian"})
    assert any("Regeln der Bibliothek nicht erreichbar" in m for m in texts(cfg, rules, "info"))
    assert not any("reicht bis" in m for m in texts(cfg, rules, "warning"))


def test_pml_route_far_zone_rule():
    cfg, rules = cfg_speckle(distance=0.05, n_speckles=20, n_pixels=101)
    cfg["geometry"]["params"] |= {"termination": "pml"}
    cfg["geometry"]["params"]["Lc"] = 250.0
    assert any("Fernfeld" in m and "L²/λ" in m for m in texts(cfg, rules, "warning"))  # 0.05 mm < 5 L²/λ = 0.09 mm
    cfg["observables"][0]["params"]["distance"] = 1.0
    assert not any("L²/λ" in m for m in texts(cfg, rules, "warning"))


def test_observable_only_for_substrates():
    cfg, rules = cfg_speckle()
    assert SpeckleStatistics.applies_to == ("substrate",)
    cfg["geometry"] = {"type": "sphere", "params": {}}
    assert any("passt nicht" in m for m in texts(cfg, rules, "error"))


# -- ensemble command ---------------------------------------------------------------------------------


def write_run(path, intensity, pixel=1e-4, wl=LAM, z=1e-3, D=1e-6, prefix="obs0__"):
    path.mkdir()
    np.savez_compressed(path / "results.npz", **{
        prefix + "intensity": intensity, prefix + "pixel_size": pixel, prefix + "wavelength_medium": wl,
        prefix + "distance": z, prefix + "aperture": D})
    return path


def test_ensemble_command_pools_runs_and_checks_the_trend_over_sigma(fake_library, tmp_path):
    rng = np.random.default_rng(1)
    runs = [write_run(tmp_path / f"r{i}", rng.exponential(size=(32, 32)) + k) for i, k in enumerate((0.0, 0.0, 3.0))]
    out = worker.cmd_speckle_ensemble({"runs": [str(r) for r in runs], "sigmas": [5e-8, 5e-8, 1e-7]})
    json.dumps(out)  # the payload goes through stdout
    assert out["n_patterns"] == 3 and len(out["contrast"]) == 3
    assert out["by_sigma"]["sigma"] == [5e-8, 1e-7]
    assert out["by_sigma"]["monotone_decreasing"] is True  # an offset lowers the contrast
    out = worker.cmd_speckle_ensemble({"runs": [str(r) for r in runs], "sigmas": [1e-7, 1e-7, 5e-8]})
    assert out["by_sigma"]["monotone_decreasing"] is False


def test_ensemble_command_rejects_incomparable_runs(fake_library, tmp_path):
    a = write_run(tmp_path / "a", np.ones((16, 16)))
    b = write_run(tmp_path / "b", np.ones((16, 16)), z=2e-3)
    with pytest.raises(ValueError, match="andere Beobachtungsebene"):
        worker.cmd_speckle_ensemble({"runs": [str(a), str(b)]})
    c = write_run(tmp_path / "c", np.ones((20, 20)))
    with pytest.raises(ValueError, match="Pixelzahlen"):
        worker.cmd_speckle_ensemble({"runs": [str(a), str(c)]})
    d = tmp_path / "d"
    d.mkdir()
    np.savez(d / "results.npz", obs0__sigma=np.ones(3))
    with pytest.raises(ValueError, match="keine Speckle-Intensität"):
        worker.cmd_speckle_ensemble({"runs": [str(d)]})


def test_ensemble_request_takes_sigma_from_the_configs():
    from sbgui.sweeps import ensemble_request, has_speckle

    cfgs = [{"geometry": {"params": {"sigma": 50.0}}}, {"geometry": {"params": {"sigma": 100.0}}}]
    req = ensemble_request(["a", "b"], cfgs)
    assert req["runs"] == ["a", "b"] and req["sigmas"] == pytest.approx([5e-8, 1e-7])
    assert "sigmas" not in ensemble_request(["a"], [{"geometry": {"params": {}}}])
    assert has_speckle({"observables": [{"type": "speckle_statistics"}]}) and not has_speckle({"observables": []})


@pytest.mark.needs_library
def test_library_harness_accepts_the_saved_arrays(tmp_path):
    pytest.importorskip("specklebem.speckle")
    rng = np.random.default_rng(2)
    runs = [write_run(tmp_path / f"r{i}", rng.exponential(size=(101, 101)), pixel=1e-4, z=1e-3, D=1e-6)
            for i in range(2)]
    out = worker.cmd_speckle_ensemble({"runs": [str(r) for r in runs]})
    assert out["n_patterns"] == 2 and 0.8 < out["mean_contrast"] < 1.2  # exponential statistics: contrast 1
