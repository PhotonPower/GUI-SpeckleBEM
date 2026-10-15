# 03 Conventions

## Units and storage

Config values are stored in display units (nm, µm, deg); plugins and the library see SI (metres, radians).
The `unit` of a `Field` decides the conversion; fields of kind `choice`, `bool`, `text`, `int` are passed
unchanged.

## Frame (binding, from SpeckleBem docs/06)

- Time convention `exp(+jωt)`; passive media `Im(ε_r) ≤ 0`; optics input `n + ik` is converted to `n − jk`.
- Object (R2) occupies `z > ξ(x, y)`; light comes from `z < 0` travelling in `+z`; surface normals point out of
  R2 into R1; triangles are counter-clockwise seen from R1 (`orient_outward` enforces consistency and positive
  volume).
- Spheres/ellipsoids are centred at the origin; plane wave in `+z`.
- GUI presentation of substrate structures: air on top. Internally `z_lib = −z_phys`; profile code
  (`meshing/profile2d.py`) works in the physical frame (z up), `meshing/extrude.py` maps to the library frame.
  The mapping never appears in the config.
- Polarisation: p = E in the plane of incidence (xz), s = E along y. DRC co-pol vector is the lab-frame
  polarisation of the incident beam.

## Isolated line / trench (`isolated_line`)

- `cd`: width at half height (CD_mid), independent of the sidewall angle.
- `height`: ridge height or trench depth.
- `swa`: sidewall angle against the substrate plane, 90° = vertical. For swa < 90° the feature is wider at
  the substrate plane (ridge foot, trench opening) than at its far end (ridge top, trench floor).
- `r_top`: corners at the higher z (ridge top corners, trench opening edges). `r_bottom`: corners at the
  lower z (ridge feet, trench floor corners).
- The profile is extruded along y over the whole patch ("infinitely long, finitely illuminated"); the patch is
  closed by side walls and a bottom plate with one uniform target size (ADR 0006 uniform box).
- Automatic substrate depth: library `default_box_depth` (+ trench depth for trenches). Lossless substrates
  have no rule (library raises); the GUI then uses 2 µm and says so.
- Limits: arcs shorter than the profile mesh size become chamfers (warning); radii below `h_profile / 10` are
  rejected (extruded slivers cannot be meshed); `swa ∈ [45°, 90°]`; the profile must not close (error).

## Mesh generation

- Sphere/ellipsoid: numpy icosphere subdivided until the longest edge ≤ h (ellipsoid: based on the longest
  axis, so short axes get finer than h).
- Structures: gmsh (frontal-Delaunay) in micrometres; point sizes follow the local profile segment length,
  extruded end points get the size of the nearest profile point (ADR 0002).
- Quality gate: closed mesh required; warning below 5° minimum angle.

## GUI heuristics (not from the SpeckleBem documentation)

| Constant | Value | Where | Meaning |
|---|---|---|---|
| `DENSE_LIMIT` | 2N ≤ 20 000 | `checks.py` | "auto" matrix: dense below, MLFMM above |
| `DIRECT_LIMIT` | 2N ≤ 12 000 | `checks.py` | "auto" solver: direct LU below, GMRES above (dense only) |
| mesh-size warnings | h > λ/6 warning, h > λ/3 error | `checks.py` | project validations use λ/10 and finer |
| MLFMM memory | 70–120 kB per unknown | `checks.py` | derived from recorded Si runs (SpeckleBem docs/handover) |
| min rounding | `h_profile / 10` | `geometry_line.py` | gmsh robustness limit found in testing |
| auto waist | 0.999 · L · cosθ · f | `excitations.py` | f = library `beam_waist_fraction` (1/6 weak absorbers, 1/4 else) |

Change them only with a measurement and record it in `docs/handover.md`.
