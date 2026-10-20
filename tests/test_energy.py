"""G22: incident power and the library reflectance cross-check in the DRC observable."""

import types

import numpy as np
import pytest

from sbgui.plugins.observables import DrcHemisphere


class FakeSim:
    def __init__(self, beam=True):
        self.beam = beam

    def drc(self, d, co_pol=None):
        D = np.full(len(d), 0.35 / (2 * np.pi))  # uniform DRC -> R = 0.35 on any exact hemisphere rule
        return (D, 0 * D) if co_pol is not None else D

    def incident_power(self):
        if not self.beam:
            raise RuntimeError("plane wave: infinite power")
        return 2.5e-15

    def reflectance(self, n_theta, n_phi):
        return 0.35


def fake_sb():
    def hemisphere_grid(sign, nt, nph):
        mu, w = np.polynomial.legendre.leggauss(nt)
        ct, wt = (mu + 1) / 2, w / 2  # cos(theta) on (0, 1)
        ph = np.arange(nph) * 2 * np.pi / nph
        C, P = np.meshgrid(ct, ph, indexing="ij")
        S = np.sqrt(1 - C**2)
        d = np.stack([S * np.cos(P), S * np.sin(P), sign * C], axis=-1).reshape(-1, 3)
        return types.SimpleNamespace(directions=d, weights=np.repeat(wt, nph) * 2 * np.pi / nph)

    return types.SimpleNamespace(hemisphere_grid=hemisphere_grid)


def ctx():
    return {"meta": {"kind": "substrate"}, "co_pol": None}


def test_cross_check_and_incident_power():
    p = DrcHemisphere.schema().to_si(DrcHemisphere.schema().defaults() | {"r_check": True, "n_theta": 16, "n_phi": 32})
    out = DrcHemisphere().compute(fake_sb(), FakeSim(), p, ctx())
    assert out["reflectance"] == pytest.approx(0.35, rel=1e-12)
    s = DrcHemisphere.summary(out)
    assert s["R Bibliothek (1°-Gitter)"] == 0.35 and abs(s["R / R_Bibliothek − 1"]) < 1e-12
    assert s["einfallende Leistung P_inc [W]"] == 2.5e-15


def test_plane_wave_has_no_incident_power_and_no_cross_check():
    p = DrcHemisphere.schema().to_si(DrcHemisphere.schema().defaults() | {"r_check": True, "n_theta": 16, "n_phi": 32})
    out = DrcHemisphere().compute(fake_sb(), FakeSim(beam=False), p, ctx())
    assert "P_inc" not in out and "R_library" not in out and "P_inc_error" in out
    assert "R Bibliothek (1°-Gitter)" not in DrcHemisphere.summary(out)
