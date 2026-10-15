import math

import numpy as np
import pytest

from sbgui.meshing.common import icosphere, is_closed, mesh_stats, signed_volume
from sbgui.meshing.profile2d import fillet_polyline, line_profile, line_widths, polygon_area

NM = 1e-9


# ---------------------------------------------------------------- 2-D profile ------------------
def test_sharp_trapezoid_area_and_widths():
    cd, H, swa = 200 * NM, 100 * NM, math.radians(80)
    hw_near, hw_far = line_widths(cd, H, swa)
    c = 1 / math.tan(swa)
    assert hw_near - hw_far == pytest.approx(H * c)
    assert (hw_near + hw_far) == pytest.approx(cd)  # CD is the width at half height
    prof = line_profile("ridge", cd, H, swa, 0, 0, 4e-6, 50 * NM)
    assert polygon_area(prof) == pytest.approx(cd * H, rel=1e-12)  # trapezoid area = CD * H


def test_vertical_wall_is_a_rectangle():
    prof = line_profile("ridge", 200 * NM, 100 * NM, math.pi / 2, 0, 0, 4e-6, 50 * NM)
    assert polygon_area(prof) == pytest.approx(200 * NM * 100 * NM)
    xs = prof[:, 0]
    assert np.isclose(xs, -100 * NM).sum() == 2  # two vertices on the left wall


def test_fillet_removes_expected_corner_area():
    # 90 degree convex corner of a square: rounding removes r^2 (1 - pi/4)
    r = 10 * NM
    pts = np.array([[-1.0, 0.0], [0.0, 0.0], [0.0, 1.0]]) * 1e-6
    out = fillet_polyline(pts, [r], seg=1 * NM)
    # compare areas under a closed polygon: sharp corner vs rounded corner
    closed_sharp = np.vstack([pts, [[-1e-6, 1e-6], pts[0]]])
    closed_round = np.vstack([out, [[-1e-6, 1e-6], out[0]]])

    def shoelace(p):
        x, y = p[:, 0], p[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    assert shoelace(closed_sharp) - shoelace(closed_round) == pytest.approx(r * r * (1 - math.pi / 4), rel=1e-3)
    d = np.hypot(*(out[1:-1] - np.array([-r, r])).T)
    assert np.allclose(d, r, atol=1e-12)  # arc points lie on the circle
    assert np.linalg.norm(np.diff(out, axis=0), axis=1).max() < 1e-6  # no jumps


def test_trench_is_mirror_of_ridge_in_z():
    kw = dict(cd=200 * NM, height=80 * NM, swa=math.radians(85), r_top=10 * NM, r_bottom=20 * NM,
              Lx=4e-6, seg=20 * NM)
    ridge, trench = line_profile("ridge", **kw), line_profile("trench", **kw)
    assert polygon_area(ridge) > 0 > polygon_area(trench)
    # ridge top corners have r_top, foot has r_bottom; for the trench the roles swap: the arc
    # lengths of the high-z corners (opening edges) must still be governed by r_top
    assert ridge[:, 1].max() == pytest.approx(80 * NM) and trench[:, 1].min() == pytest.approx(-80 * NM)


@pytest.mark.parametrize("kw, msg", [
    (dict(cd=200 * NM, height=400 * NM, swa=math.radians(60)), "spitz"),  # taper closes the profile
    (dict(cd=200 * NM, height=100 * NM, swa=math.radians(85), r_top=150 * NM), "Rundung"),  # too big
    (dict(cd=200 * NM, height=100 * NM, swa=math.radians(95)), "Seitenwandwinkel"),
])
def test_invalid_profiles_raise(kw, msg):
    base = dict(kind="ridge", r_top=0, r_bottom=0, Lx=4e-6, seg=20 * NM)
    base.update(kw)
    with pytest.raises(ValueError, match=msg):
        line_profile(**base)


# ---------------------------------------------------------------- bodies -----------------------
def test_icosphere_volume_and_edges():
    v, f = icosphere(500 * NM, 50 * NM)
    assert is_closed(f) and signed_volume(v, f) > 0
    s = mesh_stats(v, f)
    assert s["edge_max"] <= 50 * NM
    assert s["volume"] == pytest.approx(4 / 3 * math.pi * (500 * NM) ** 3, rel=0.01)
    assert np.allclose(np.linalg.norm(v, axis=1), 500 * NM)


def test_ellipsoid_plugin_volume_and_mie_flag():
    from sbgui.plugins.geometry_bodies import Ellipsoid

    g = Ellipsoid()
    p = g.schema().to_si({"a": 400, "b": 250, "c": 250, "tilt_y": 0, "rot_z": 30})
    m = g.build(p, 60 * NM)
    assert m.meta["kind"] == "object" and "mie_sphere" not in m.meta
    assert signed_volume(m.vertices, m.triangles) == pytest.approx(
        4 / 3 * math.pi * 400 * 250 * 250 * NM**3, rel=0.02)
    sph = g.schema().to_si({"a": 300, "b": 300, "c": 300, "tilt_y": 0, "rot_z": 0})
    assert "mie_sphere" in g.build(sph, 80 * NM).meta  # a = b = c reduces to the Mie reference


# ---------------------------------------------------------------- substrate line --------------
gmsh = pytest.importorskip("gmsh")


@pytest.mark.parametrize("feature", ["ridge", "trench"])
def test_isolated_line_mesh_is_closed_outward_and_has_right_volume(feature):
    from sbgui.plugins.geometry_line import IsolatedLine

    g = IsolatedLine()
    disp = {"feature": feature, "cd": 300, "height": 150, "swa": 80, "r_top": 20, "r_bottom": 20,
            "Lx": 2.0, "Ly": 1.5, "depth_mode": "manual", "depth": 1.0, "refine_profile": 1.0}
    p = g.schema().to_si(disp)
    mesh = g.build(p, 100 * NM)
    s = mesh_stats(mesh.vertices, mesh.triangles)
    assert s["closed"]
    assert mesh.meta["kind"] == "substrate" and mesh.meta["lateral_size"] == pytest.approx(1.5e-6)
    # library frame: material occupies z in [xi(x), depth]; volume = Lx*Ly*depth + Ly * profile area
    # (profile_area > 0 for a ridge: more material toward -z, < 0 for a trench)
    expected = p["Lx"] * p["Ly"] * p["depth"] + p["Ly"] * mesh.meta["profile_area"]
    assert s["volume"] == pytest.approx(expected, rel=2e-3)
    assert (mesh.meta["profile_area"] > 0) == (feature == "ridge")
    assert s["angle_min_deg"] > 3
    # structure is above/below the plane z = 0 in the library frame as documented
    zmin, zmax = mesh.vertices[:, 2].min(), mesh.vertices[:, 2].max()
    if feature == "ridge":
        assert zmin == pytest.approx(-150 * NM, abs=1e-12)
    else:
        assert zmax == pytest.approx(p["depth"])


def test_line_estimate_is_within_a_factor_of_the_real_count():
    from sbgui.plugins.geometry_line import IsolatedLine

    g = IsolatedLine()
    p = g.schema().to_si({"feature": "ridge", "cd": 300, "height": 100, "swa": 85, "r_top": 20,
                          "r_bottom": 20, "Lx": 2.0, "Ly": 2.0, "depth_mode": "manual", "depth": 1.0,
                          "refine_profile": 1.0})
    real = g.build(p, 100 * NM).n_triangles
    est = g.estimate_triangles(p, 100 * NM)
    assert 0.6 < est / real < 1.6, (est, real)
