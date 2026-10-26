# Handover: state of the project and how to continue

Updated 2026-10-20 at the end of the second session (library sync and new features). Read this first, then
`CLAUDE.md` and `docs/backlog.md`.

## Session 3 (2026-10-26): sync with SpeckleBem main 6c431f6

Branch `wp/g24-library-sync-2` (G24 block-diagonal preconditioner, G25 Huygens far field + gap rule, G15 speckle
statistics, G14a series). What changed is in `CHANGELOG.md`; the calls are in `docs/05_library_interface.md`.

- **Verified:** lint, 114 tests without a library (stand-ins for `sb`, `sim` and `specklebem.speckle`), headless
  rendering of the run, model and results pages including a speckle results page and the ensemble error path.
- **NOT verified:** everything against a real library build. This sandbox (1 core, 3 GB, no cmake, processes do not
  survive between turns) could not build SpeckleBem. Behaviour of the new calls comes from
  `docs/10_python_api.md` and the pybind sources of the library. First thing to do on the development machine:
  1. `pytest -m "needs_library or slow"` with a build of main 6c431f6 or newer (the slow harness test
     `test_library_harness_accepts_the_saved_arrays` is skipped without it).
  2. Probes: `python -m sbgui.worker info` must show `block_preconditioner`, `huygens`, `speckle` true. The
     `block_preconditioner` probe looks for `block_level` in `Simulation.__init__.__doc__` (pybind signature text);
     if it reports false on a current build, change the probe, not the feature.
  3. One small real run per feature (see the G24/G25/G15/G14a rows of the backlog).
- **Decisions taken here that you may want to reverse:** the default far-field source stays "currents" (ADR 0010);
  the PML defaults (gap 0.5 µm, PML 1 µm) are **not** scaled with λ and not raised to the 6 λ rule, the GUI warns
  instead (a default of 3 µm would make every flat-Si PML run 2.7× larger); a series runs its jobs strictly one
  after another (memory), so a σ × seed series of 10 large runs takes the sum of their times.
- **Answers to the earlier lead questions that the library has settled:** rough Ag on the PML route stays selectable
  (warning below the 6 λ gap, info above; ADR 0010 decision 1 accepts the L dependence as physical). Still open:
  scaling the PML defaults with λ, rough-Si mesh rule (library 7e finding: far field not converged at λ/4–λ/10).
- **Known limits of the speckle observable:** one incidence angle per run (no γ₁₂ between angles yet); the PML route
  uses the far field, so z must be ≫ L²/λ; the plane size follows the paraxial model and reaches large angles for
  small illuminated spots (the GUI warns above 30°); the ensemble needs identical observation planes.

## Where things stand (end of session 2, 2026-10-20)

- **Library:** verified against SpeckleBem `main` fa856af (Linux build, 1 core, 3 GB RAM sandbox). The
  library reports 0.1.0 for every commit; the worker probes features instead (`worker.library_features`).
- **Merged on `main` (2026-10-20, each after green CI, squash):**
  - G20 (#1): feature probes, library warnings (`run.log` → `status.library_messages`), ADR 0006 tolerances.
  - G21 (#2): library-made meshes in the worker (`Geometry.mesher = "library"`, `build_lib`, worker `mesh`).
  - G10 (#3): Gaussian rough surface, Fresnel reference for σ = 0.
  - G22 (#5): incident power, optional `sim.reflectance` cross-check (fake-sim test only).
  - G13 (#6): near field with Mie error map; sphere r = 300 nm, n = 1.5, h = 80 nm: max e = 0.026 (< 0.1).
  - G19 (#7): CSV per observable, HDF5 in the library format with GUI metadata, `load_hdf5` check.
- **G12 (PML route, PR #4, branch `wp/g12-pml-route`):** box | PML termination of the rough surface on one
  shared height map (box = central crop; patch heights bitwise equal on both routes, as the library's 7e).
  Verified: mesh, zones, `Simulation.with_pml` construction, dark band 1.3e-5, pre-flight rules. Solve: see
  the backlog row G12 for the state of the end-to-end run.
- **Verified end to end in this session:** sphere vs Mie (old e2e, green against fa856af), small flat Si box
  through the rough-surface plugin (pipeline only; deliberately coarse), sphere near field, HDF5 round trip.
- **Not verified:** production sizes (rough Si 4.5 µm: 2N = 3.4·10⁵, ≈ 24 GB), the PML route at the
  validated 7a size (≈ 4 GB dense), MLFMM through the GUI at size, the Windows worker, a real browser session
  of the new pages (headless AppTest only).

## Findings of this session

1. **Processes do not survive between turns in the sandbox.** A detached run started in one turn is gone in
   the next (status stays "solving"; `store.live_status` reports it as crashed). Start long runs and poll
   them within one turn, or run them on the development machine.
2. **Dense PML assembly is very slow on one core:** 2N = 6 402 (flat Si, h = λ/3, 2 178 triangles) was still
   assembling after 50 min. The MLFMM route (`compression = "mlfmm"`, ACA ring) is the practical choice even
   at small sizes; the near ring of a small patch is dominated by PML functions (60 % stretched).
3. **SpeckleBem docs/10 vs build:** `RoughSurface.height_map` is the array and `.heights` the `HeightMap`
   (docs say the opposite); a manual `box_depth` above which the automatic fine band ends raises
   `ValueError` (the GUI drops the band like the library's automatic rule); `TriangleMesh.num_edges` counts
   interior edges only. Candidates for library issues.
4. **G12 changes G10's surfaces:** the box route meshes the crop of the map generated on L + 2 W_t, so a
   seed gives a different (equally distributed) realisation than before G12.
5. Stacked branches with squash merges: rebase each follower with `git rebase --onto main <old base>`; the
   doc files (CHANGELOG, backlog, docs/05) conflict at the same anchor every time - keep both sides.

## Open questions for the project lead (new)

1. Rough Ag: the GUI warns on both routes (box: WP-V3; PML: WP-PML6 open). Hide rough Ag until the library's
   PML6 decision, or keep the warning?
2. PML defaults are the 500 nm values (gap 0.5 µm, PML 1 µm); scale them with λ (gap = λ, PML = 2λ)?

## Findings that cost time (first session) (keep them in mind)

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

## Open questions for the project lead (first session)

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
   `SBGUI_WORKER_PYTHON` at the interpreter with specklebem (and h5py for HDF5).
2. G12 on the development machine: (a) 7a flat Si, PML, L = 1.5 µm, h = 125 nm, w₀ = 0.5 µm (manual),
   dense direct ≈ 4 GB: R within a few 1e-3 of the plane-wave Fresnel value (library: ≤ 0.28 % vs the beam
   reflectance); (b) 7e rough Si σ = 50 nm, Lc = 500 nm, seed 1, L = 4.5 µm, h = 125 nm, auto waist, once Box
   and once PML: DRC difference ≈ 0.15 % (library). Record the numbers in the backlog row G12, then merge #4.
3. Then G8 (Windows worker), G9 (calibrate the cost panel, now also for the PML route), G14 (sweeps and seed
   ensembles - the rough surface makes this the next useful feature), G16 (server start).
4. Keep `CHANGELOG.md`, `docs/backlog.md`, `docs/05_library_interface.md` and this file current.

## Environment of the first session

Sandbox: Linux, 1 core, 3 GB RAM, Python 3.12.3, streamlit 1.66, plotly 7.1, gmsh 4.15.2, numpy 2.4.4.
SpeckleBem built with `pip install --no-build-isolation ./python` after pinning `pybind11 2.13.6`.
