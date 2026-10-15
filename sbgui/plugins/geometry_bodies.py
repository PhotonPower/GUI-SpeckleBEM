"""Isolated bodies in a homogeneous background: sphere and ellipsoid (kind = "object")."""

from __future__ import annotations

import math

import numpy as np

from ..base import Geometry, Issue, MeshResult
from ..meshing.common import icosphere, icosphere_subdivisions
from ..params import Field
from ..registry import GEOMETRIES


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


@GEOMETRIES.register
class Sphere(Geometry):
    id = "sphere"
    label = "Kugel"
    kind = "object"
    description = "Kugel im Ursprung; Referenz: Mie-Lösung (wird automatisch verglichen)."
    fields = (Field("radius", "Radius", "float", 500.0, "nm", min=10.0, max=50000.0, step=10.0),)

    def meta_hint(self, p):
        return {"kind": "object", "lateral_size": 2 * p["radius"]}

    def estimate_triangles(self, p, h):
        return 20 * 4 ** icosphere_subdivisions(p["radius"], h)

    def validate(self, p, ctx):
        out = []
        if ctx.get("h") and ctx["h"] > p["radius"] / 2:
            out.append(Issue("error", "Netzweite größer als der halbe Radius – Kugel nicht aufgelöst."))
        return out

    def build(self, p, h):
        v, f = icosphere(p["radius"], h)
        return MeshResult(v, f, {"kind": "object", "mie_sphere": {"radius": p["radius"]},
                                 "lateral_size": 2 * p["radius"]})

    def outline(self, p):
        t = np.linspace(0, 2 * np.pi, 200)
        return {"x": (p["radius"] * np.cos(t)).tolist(), "z": (p["radius"] * np.sin(t)).tolist(),
                "title": "Schnitt durch die Kugel"}


@GEOMETRIES.register
class Ellipsoid(Geometry):
    id = "ellipsoid"
    label = "Ellipsoid"
    kind = "object"
    description = ("Halbachsen a (x), b (y), c (z), danach um y gekippt und um z gedreht. Bei a = b = c "
                   "und ohne Drehung wird wie bei der Kugel gegen Mie verglichen.")
    fields = (
        Field("a", "Halbachse a (x)", "float", 500.0, "nm", min=10.0, max=50000.0, step=10.0),
        Field("b", "Halbachse b (y)", "float", 300.0, "nm", min=10.0, max=50000.0, step=10.0),
        Field("c", "Halbachse c (z)", "float", 300.0, "nm", min=10.0, max=50000.0, step=10.0),
        Field("tilt_y", "Kippung um y", "float", 0.0, "deg", min=-90.0, max=90.0, step=5.0),
        Field("rot_z", "Drehung um z", "float", 0.0, "deg", min=-180.0, max=180.0, step=5.0),
    )

    def _axes(self, p):
        return np.array([p["a"], p["b"], p["c"]])

    def meta_hint(self, p):
        return {"kind": "object", "lateral_size": float(2 * self._axes(p).max())}

    def estimate_triangles(self, p, h):
        return 20 * 4 ** icosphere_subdivisions(self._axes(p).max(), h)

    def validate(self, p, ctx):
        ax = self._axes(p)
        out = []
        if ax.max() / ax.min() > 4:
            out.append(Issue("warning", "Achsenverhältnis > 4: die Netzweite richtet sich nach der "
                             "längsten Achse, an der kurzen Achse wird das Netz dadurch sehr fein "
                             "(Unbekannte steigen stark)."))
        if ctx.get("h") and ctx["h"] > ax.min() / 2:
            out.append(Issue("error", "Netzweite größer als die halbe kürzeste Achse."))
        return out

    def build(self, p, h):
        ax = self._axes(p)
        r_ref = float(ax.max())
        v, f = icosphere(r_ref, h)
        v = v * (ax / r_ref)  # positive scaling keeps the orientation
        rot = _rot_z(p["rot_z"]) @ _rot_y(p["tilt_y"])
        v = v @ rot.T
        meta = {"kind": "object", "lateral_size": float(2 * ax.max())}
        if np.allclose(ax, ax[0], rtol=1e-9) and abs(p["tilt_y"]) + abs(p["rot_z"]) < 1e-12:
            meta["mie_sphere"] = {"radius": float(ax[0])}
        return MeshResult(v, f, meta)

    def outline(self, p):
        t = np.linspace(0, 2 * np.pi, 200)
        return {"x": (p["a"] * np.cos(t)).tolist(), "z": (p["c"] * np.sin(t)).tolist(),
                "title": "Schnitt in der xz-Ebene (vor Kippung/Drehung)"}
