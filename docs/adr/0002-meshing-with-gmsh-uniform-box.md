# ADR 0002 — Structure meshes from gmsh, uniform box, own profile builder

Status: accepted (2026-10-15)

## Context
Sidewall angle and rounded corners must be represented in the surface mesh. The library's
`make_mesh_from_height_map` samples z = f(x, y) on a grid; a steep flank inside one cell is flattened to
atan(H/h) without warning, so a sidewall angle cannot be honoured at h = 50 nm.

## Decision
Build the 2-D profile (`meshing/profile2d.py`: trapezoid, CD at half height, fillets, physical frame) and
mesh the extruded closed block with gmsh (`meshing/extrude.py`): top, side walls and bottom with one target
size (ADR 0006 of SpeckleBem: uniform box for quantitative runs); only profile points may be refined.
Orientation is repaired in numpy (`orient_outward`).

Findings that shaped the implementation (all reproduced in tests or the code comments):
- gmsh collapses edges shorter than its geometry tolerance 1e-8 *model units*: work in micrometres.
- Extruded end points carry no size; set sizes on all points or arc strips of a few nm × Ly become
  unmeshable slivers.
- Rounding radii below `h_profile / 10` still fail (NULL points); arcs shorter than the profile size become
  chamfers by design (warning).

## Consequences
+ sidewall angle and roundings are exact in the geometry; closed, outward-oriented, analytic volume tested
− adds gmsh (GUI environment only) as a dependency; global C library, access serialised by a lock
− rounded corners below the mesh size are chamfers or cost many triangles
− at 4×4 µm and h = 50 nm: ≈ 62 000 triangles (2N ≈ 1.9·10⁵), so structures start in MLFMM territory
