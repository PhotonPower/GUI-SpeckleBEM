"""G21: library-made meshes - unknown count of open surfaces, mesh.npz writer, job-runner hand-off."""

import json

import numpy as np

from sbgui.base import Geometry, MeshResult
from sbgui.checks import collect_issues
from sbgui.config import default_config
from sbgui.meshing.common import icosphere, save_mesh

SQUARE = (np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float), np.array([[0, 1, 2], [0, 2, 3]]))


def test_unknowns_closed_vs_open():
    v, f = icosphere(1.0, 0.5)
    assert MeshResult(v, f).n_unknowns == 3 * len(f)
    assert MeshResult(*SQUARE, {"open_surface": True}).n_unknowns == 2  # one interior edge, [J; M]
    assert MeshResult(*SQUARE).n_unknowns == 6  # without the flag the closed-mesh rule applies


def test_save_mesh_records_stats_and_the_open_flag(tmp_path):
    meta = save_mesh(tmp_path / "mesh.npz", MeshResult(*SQUARE, {"open_surface": True, "kind": "substrate"}), 0.5)
    with np.load(tmp_path / "mesh.npz") as z:
        stored = json.loads(str(z["meta"]))
        assert z["triangles"].shape == (2, 3)
    assert stored == meta
    assert meta["n_unknowns"] == 2 and meta["mesh_stats"]["open_surface"] and not meta["mesh_stats"]["closed"]
    assert meta["max_radius"] == np.sqrt(2) and meta["kind"] == "substrate"


def test_open_surface_is_not_a_closedness_error():
    cfg = default_config()
    stats = {"closed": False, "open_surface": True, "angle_min_deg": 30.0}
    assert not any("geschlossen" in i.msg for i in collect_issues(cfg, None, None, stats))
    stats["open_surface"] = False
    assert any("geschlossen" in i.msg for i in collect_issues(cfg, None, None, stats))


def test_default_geometries_mesh_in_the_gui():
    assert Geometry.mesher == "gui"
    from sbgui.registry import GEOMETRIES, load_plugins

    load_plugins()
    assert {g.id for g in GEOMETRIES.all() if g.mesher == "gui"} >= {"sphere", "ellipsoid", "isolated_line"}
