# Handover: state of the project and how to continue

Updated 2026-10-15 at the end of the first session. Read this first, then `CLAUDE.md` and `docs/backlog.md`.

## Where things stand

- **Implemented and tested:** everything of work packages G1–G6 (`docs/backlog.md`). 28 CI tests
  (`pytest -m "not slow"`, no library needed) and 1 slow round-trip test; `ruff` clean.
- **Verified against the real library** (SpeckleBem 0.1.0, main 62ece8b, Linux, one core, 3 GB RAM sandbox):
  - Sphere r = 300 nm, n = 1.5, h = 80 nm through GUI core → job runner → worker: σ(θ) deviates 0.5 % (L2)
    from Mie, C_sca 1.1676e-12 vs Mie 1.1723e-12 m².
  - Dielectric trench (2N = 3378, rigorous Gaussian beam, dense direct): pipeline completes, DRC arrays,
    co/cross, weights sum to 2π, results page renders. **R = 0.112 is not a validated number** (w₀ ≈ 0.2 µm < λ;
    the GUI warns).
  - Pages render headless without the library (error banner, preview and checks keep working).
- **Not verified:** use in a real browser; Windows/MSYS2 worker path; the MLFMM path through the GUI (the
  sandbox ran out of memory at 2N = 41 586); Si structures at production size; `DispersiveMaterial` table
  path; `Simulation.save`; physical validation of structures against RCWA/FDTD; the first CI run on GitHub.

## Findings that cost time (keep them in mind)

1. **gmsh geometry tolerance** 1e-8 model units: in metres that is 10 nm and removes arc segments. All
   meshing is done in micrometres (`meshing/extrude.py`). ADR 0002.
2. **Extruded points carry no size**; thin arc strips become slivers and gmsh fails ("NULL points" or
   segmentation faults with algorithms 1 and 2). Sizes are now set on all points.
3. **SpeckleBem needs `pybind11<3`** to build (`bind_excitation.cpp:151`). Upstream item in the backlog.
4. **`AngularSpectrumBeam` needs `region_radius` ≥ mesh extent**; with Si the box is 5.6 µm deep, so the mesh
   reaches 5.9 µm. The radius is set from `meta.max_radius` (more plane waves: 1056 at 1.4 µm → 6032 at 6 µm).
5. **`default_box_depth` raises for lossless objects**; the GUI falls back to 2 µm and says so (info issue).
6. Cost reality check: 4×4 µm at h = 50 nm is ≈ 62 000 triangles, 2N ≈ 1.9·10⁵; the dense matrix ends at
   2N ≈ 2·10⁴, so useful structure runs need MLFMM. A Si trench with 2N = 9444 (dense GMRES) was still
   assembling after 12 minutes on one core and was cancelled.

## Open questions for the project lead

1. **Rounding radii below the mesh size** are chamfers (warning) or rejected below `h_profile / 10`. Is that the
   behaviour you want, or should local refinement fields (G18) be a priority?
2. **Ag on a finite block:** the GUI only warns. Wait for the library's PML route (G12) or hide Ag for
   substrate geometries until then?
3. **Heuristics** in `docs/03_conventions.md` (dense/direct limits, mesh-size warnings): confirm or replace by
   measured values (G9).
4. Definition of **CD**: currently width at half height. If your metrology uses top or bottom width, it is a
   one-line change in `geometry_line.py` plus a docs note.

## How to continue

1. Install (`pip install -e ".[dev,system]"`), run the tests, start `streamlit run app.py`, point
   `SBGUI_WORKER_PYTHON` at the interpreter with specklebem (MSYS2 on the Windows machine, see `docs/04_testing.md`).
2. Do G7 first: a real session in the browser with a Si trench; record what breaks.
3. Then G8 (Windows worker) and G9 (calibrate the cost panel) on the 24-core / 128 GB machine, G10 (rough
   surfaces) as the next feature.
4. Keep `CHANGELOG.md`, `docs/backlog.md`, `docs/05_library_interface.md` (verified-against version) and this
   file current.

## Environment of the first session

Sandbox: Linux, 1 core, 3 GB RAM, Python 3.12.3, streamlit 1.66, plotly 7.1, gmsh 4.15.2, numpy 2.4.4.
SpeckleBem built with `pip install --no-build-isolation ./python` after pinning `pybind11 2.13.6`.
