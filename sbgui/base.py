"""Base classes of the four plugin kinds and the small data types they exchange.

Process split (see README): ``Geometry.build`` runs in the GUI/job process (numpy, gmsh);
``Material.build``, ``Excitation.build`` and ``Observable.compute`` run in the worker process,
which gets the ``specklebem`` module passed in as ``sb``; ``Observable.figures`` runs in the
GUI. All ``p`` arguments are SI dictionaries (``Schema.to_si``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from .registry import Plugin


@dataclass
class Issue:
    level: str  # "error" blocks the run, "warning" and "info" do not
    msg: str


@dataclass
class MeshResult:
    vertices: np.ndarray  # (V, 3) float64, metres, library frame (docs/06)
    triangles: np.ndarray  # (F, 3) int64, counter-clockwise seen from R1 (normals out of R2)
    meta: dict[str, Any] = field(default_factory=dict)  # JSON-serialisable

    @property
    def n_triangles(self) -> int:
        return int(len(self.triangles))

    @property
    def n_unknowns(self) -> int:
        """2N = 2 x the number of interior edges (unknown vector [J; M]); 3F for a closed mesh.
        Open surfaces (PML route) have boundary edges without a basis function."""
        if bool(self.meta.get("open_surface")):
            f = np.asarray(self.triangles)
            e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
            _, counts = np.unique(e, axis=0, return_counts=True)
            return int(2 * np.count_nonzero(counts == 2))
        return 3 * self.n_triangles


@dataclass
class LibraryMesh:
    """A mesh made by the library inside the worker (``Geometry.mesher == "library"``)."""

    result: MeshResult  # vertices/triangles for mesh.npz, stats and preview
    handle: Any  # the library object handed to the Simulation (TriangleMesh, OpenSurfaceMesh)
    route: str = "closed"  # "closed": sb.Simulation(...); "pml": sb.Simulation.with_pml(...)
    options: dict[str, Any] = field(default_factory=dict)  # route extras, e.g. {"pml": PmlTermination kwargs}


class Geometry(Plugin):
    kind: ClassVar[str] = "object"  # "object" (isolated body) | "substrate" (patch with closing box)
    # "gui": ``build`` runs in the job runner (numpy/gmsh). "library": ``build_lib`` runs in the worker
    # and the library makes the mesh (rough surfaces, open surfaces for the PML route).
    mesher: ClassVar[str] = "gui"

    def resolve(self, p: dict, rules: dict | None) -> dict:
        """Fill parameters that depend on the library rules (e.g. automatic box depth)."""
        return p

    def meta_hint(self, p: dict) -> dict:
        """Cheap subset of ``MeshResult.meta`` (kind, lateral_size) without meshing."""
        return {"kind": self.kind}

    def validate(self, p: dict, ctx: dict) -> list[Issue]:
        return []

    def estimate_triangles(self, p: dict, h: float) -> int:
        raise NotImplementedError

    def build(self, p: dict, h: float) -> MeshResult:
        raise NotImplementedError

    def build_lib(self, sb, p: dict, h: float, ctx: dict) -> LibraryMesh:
        """Worker side, ``mesher == "library"`` only. ``ctx``: wavelength, h, rules, object and
        background (library materials)."""
        raise NotImplementedError

    def outline(self, p: dict) -> dict | None:
        """Optional cheap 2-D preview: {"x": [...], "z": [...], "title": str} in metres."""
        return None


class Material(Plugin):
    def validate(self, p: dict, wavelength: float) -> list[Issue]:
        return []

    def build(self, sb, p: dict, wavelength: float):
        raise NotImplementedError

    def refractive_index(self, p: dict, wavelength: float) -> complex | None:
        """n - jk (library convention) if known without the library, else None."""
        return None


class Excitation(Plugin):
    def validate(self, p: dict, ctx: dict) -> list[Issue]:
        return []

    def build(self, sb, p: dict, ctx: dict, background):
        raise NotImplementedError

    def describe(self, p: dict, ctx: dict) -> str:
        return ""


class Observable(Plugin):
    applies_to: ClassVar[tuple[str, ...]] = ("object", "substrate")

    def compute(self, sb, sim, p: dict, ctx: dict) -> dict[str, Any]:
        raise NotImplementedError

    def figures(self, data: dict, ctx: dict) -> list:
        return []
