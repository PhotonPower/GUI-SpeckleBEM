"""Closed surface mesh of a substrate block whose top face follows an extruded 2-D profile.

The block is  x in [-Lx/2, Lx/2],  y in [-Ly/2, Ly/2],  and in the *library* frame
z in [xi(x), depth] with xi(x) = -z_phys(x): object on the +z side, light from z < 0
(docs/06). Top face, side walls and bottom plate are meshed with one uniform target size
(the "uniform box" that ADR 0006 recommends for quantitative runs); only the profile
points can be refined.

gmsh is a global C library: access is serialised with a lock and it is initialised
non-interruptible so that it also works from Streamlit script threads.
"""

from __future__ import annotations

import threading

import numpy as np

from .common import orient_outward

_GMSH_LOCK = threading.Lock()


def extruded_profile_box(profile_xz: np.ndarray, Ly: float, depth: float, h: float,
                         h_profile: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, triangles) of the closed, outward-oriented block (library frame)."""
    import gmsh  # noqa: PLC0415 - optional dependency of the GUI process only

    S = 1e6  # gmsh works in micrometres: its geometry tolerance (1e-8 model units) would be 10 nm in metres
    h_profile = h if h_profile is None else h_profile
    profile_xz, Ly, depth, h, h_profile = profile_xz * S, Ly * S, depth * S, h * S, h_profile * S
    x0, x1 = float(profile_xz[0, 0]), float(profile_xz[-1, 0])
    if depth <= 0 or Ly <= 0:
        raise ValueError("depth and Ly must be positive")
    if -profile_xz[:, 1].max() > depth:  # xi = -z_phys must stay above the bottom plate
        raise ValueError("Strukturhöhe größer als die Substrattiefe")

    with _GMSH_LOCK:
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.MeshSizeMax", h)
            gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
            gmsh.option.setNumber("Mesh.Algorithm", 6)  # frontal-Delaunay: near-equilateral
            gmsh.model.add("profile_box")
            g = gmsh.model.geo
            y0 = -Ly / 2
            # Mesh size at a profile point follows the local segment length (capped by h_profile):
            # a 7 nm arc segment extruded over Ly would otherwise become a 7 nm x Ly sliver strip
            # that cannot be meshed with 100 nm elements.
            seg = np.linalg.norm(np.diff(profile_xz, axis=0), axis=1)
            ids = []
            for i, (x, z) in enumerate(profile_xz):
                if i in (0, len(profile_xz) - 1):
                    size = h
                else:
                    size = min(h_profile, 0.5 * (seg[i - 1] + seg[i]))
                ids.append(g.addPoint(float(x), y0, float(-z), size))
            br, bl = g.addPoint(x1, y0, depth, h), g.addPoint(x0, y0, depth, h)
            lines = [g.addLine(a, b) for a, b in zip(ids[:-1], ids[1:])]
            lines += [g.addLine(ids[-1], br), g.addLine(br, bl), g.addLine(bl, ids[0])]
            surf = g.addPlaneSurface([g.addCurveLoop(lines)])
            g.extrude([(2, surf)], 0.0, Ly, 0.0)
            g.synchronize()
            # The extruded copies of the points carry no size of their own; give every point the
            # size of the nearest profile point, otherwise the y-edges of thin arc strips grade
            # from e.g. 3 nm to h and the strips degenerate into unmeshable slivers.
            ref = np.vstack([np.c_[profile_xz[:, 0], -profile_xz[:, 1]], [[x1, depth], [x0, depth]]])
            ref_size = np.r_[[h if i in (0, len(profile_xz) - 1) else min(h_profile, 0.5 * (seg[i - 1] + seg[i]))
                              for i in range(len(profile_xz))], h, h]
            for dim, tag in gmsh.model.getEntities(0):
                px, _, pz = gmsh.model.getValue(0, tag, [])
                nearest = int(np.argmin(np.hypot(ref[:, 0] - px, ref[:, 1] - pz)))
                gmsh.model.mesh.setSize([(dim, tag)], float(ref_size[nearest]))
            gmsh.model.mesh.generate(2)

            tags, coords, _ = gmsh.model.mesh.getNodes()
            etypes, _, enodes = gmsh.model.mesh.getElements(dim=2)
            tri_tags = np.concatenate([n for t, n in zip(etypes, enodes) if t == 2]).reshape(-1, 3)
            coords = np.asarray(coords).reshape(-1, 3)
            lut = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
            lut[tags.astype(np.int64)] = np.arange(len(tags))
            f = lut[tri_tags.astype(np.int64)]
        finally:
            gmsh.finalize()

    used, inv = np.unique(f, return_inverse=True)
    v = coords[used] / S
    f = inv.reshape(-1, 3).astype(np.int64)
    return v, orient_outward(v, f)
