"""G13: near-field observable - distance mask, figures and summary without the library."""

import numpy as np

from sbgui.plugins.observables import NearField, _surface_distance


def test_surface_distance_is_the_nearest_vertex_distance():
    v = np.array([[0.0, 0, 0], [1.0, 0, 0]])
    p = np.array([[0.0, 0, 2], [0.6, 0, 0], [3.0, 4, 0]])
    assert np.allclose(_surface_distance(p, v, chunk=2), [2.0, 0.4, np.hypot(2, 4)])


def test_figures_and_summary_from_stored_arrays():
    n = 11
    xs = np.linspace(-1e-6, 1e-6, n)
    pts = np.array([[x, 0.0, z] for x in xs for z in xs])
    err = np.full(n * n, 0.01)
    err[0] = np.nan
    data = {"points": pts, "absE": np.hypot(pts[:, 0], pts[:, 2]), "n": np.asarray(n), "plane": np.asarray("xz"),
            "kind": np.asarray("total"), "d_min": np.asarray(4e-8), "err": err,
            "err_max_outside": np.asarray(0.02), "err_median_outside": np.asarray(0.006)}
    figs = NearField().figures(data, {})
    assert len(figs) == 2 and figs[0].data[0].z.shape == (n, n)
    assert np.allclose(figs[0].data[0].x, xs * 1e6)
    s = NearField.summary(data)
    assert s["max. Fehler außen (vs. Mie)"] == 0.02 and s["Mindestabstand [nm]"] == 40.0


def test_schema_defaults():
    d = NearField.schema().defaults()
    assert d["plane"] == "xz" and d["kind"] == "total" and d["min_distance"] == 0.5
    assert NearField.applies_to == ("object",)
