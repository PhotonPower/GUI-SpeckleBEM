# Changelog

All notable changes. Format: Keep a Changelog; versions follow the GUI, the tested library version is
named per entry.

## [Unreleased]

### Fixed
- MLFMM on lossy regions (Si) failed with `cannot represent region R2 to 10^-3` when large basis functions
  (long wall triangles of a tall line on the height map) pushed the leaves to a box size where the loss
  spoils the expansion. New solver setting "MLFMM-Blattgröße" (`min_box_size_lambda`: auto, 0.5–4 λ); on
  this error the worker retries once with leaves ≥ 2 λ (noted in the status), otherwise explains the
  options. Reproduced: Si line, PML route, h = λ/3, H = 180 nm (r_max 259 nm): default fails at R2 level 4
  (error 0.116), ≥ 2 λ passes every level; ≥ 4 λ passes too but makes the near field almost dense.
- A plane wave on the PML route reached the library and failed with "no dark band" (|E_inc| at the PML start
  equals its patch maximum). It is now a pre-flight error on the PML route; the paraxial beam model gets a
  warning there (validated: rigorous AngularSpectrumBeam).
- Line/trench on the PML route failed at `Simulation.with_pml` ("the patch is rough; set
  PmlTermination::correlation_length"): the GUI passed Lc = 0 for a structured patch. It now passes the CD as
  the lateral scale and checks W_t ≥ CD before the run. A new library test constructs `with_pml` for flat,
  rough, ridge and trench patches.
- PML route with MLFMM on SpeckleBem builds before WP-PML5b (2026-10-20) failed with `with_pml(): incompatible
  function arguments` (the GUI passed the `mlfmm` dict). The worker now tells three library generations
  apart (`pml_mlfmm`, `pml_mlfmm_params`): before WP-PML5a dense only (pre-flight error), WP-PML5a MLFMM with
  default parameters and the exact PML ring (dict dropped, warning before and during the run), WP-PML5b full.
- Preview of height-map surfaces (rough surface, line with library meshing) failed for large meshes
  (`make_open_surface_mesh: the height map ... does not cover the patch and the taper`): the preview
  coarsened h by a non-integer factor, so L, W_t, gap and PML were off the grid. It now coarsens by an
  integer divisor of their common cell count (`Geometry.preview_mesh_size`); an off-grid spacing gives a
  clear GUI message instead of the library error.

### Added
- **Library sync 2 (2026-10-26, SpeckleBem main 6c431f6; stand-in tests only, no real-build run yet):**
  - G24: solver setting "Vorkonditionierer" offers `block_diagonal` (near-field block LU, library WP-PC1,
    ADR 0011) with `block_level` (octree leaves or one level up). "auto" stays the library's choice (block-diagonal
    on the PML route with MLFMM, otherwise Jacobi for metals). Block-diagonal is a GMRES preconditioner: the
    "auto" solver resolves to GMRES, an explicit direct LU is a pre-flight error, a library without it is reported
    before the run (probe `block_preconditioner`). The status records the preconditioner the library actually used.
  - G25: PML far-field source (library WP-PML6, ADR 0010): "Ströme im Fenster" (default, validated) or "Huygens-Ebene"
    (diagnostic, with z_H and grid spacing, 0 = automatic). The keywords are only sent for Huygens, so older builds
    keep working; the results page shows the source, L and the gap. New rule from ADR 0010 decision 3 / WP-PML6b:
    metal with roughness or structure on the PML route needs a flat gap ≥ 6 λ (warning below), quantitative only in
    the cone θ ≤ 30°; the L dependence is documented as physical. The outdated "PML route not connected" and
    "Huygens plane open" texts are gone.
  - G15: observable "Speckle-Statistik" (library WP-S1): co-polarised intensity on a plane at z below the surface
    (size from n_speckles · c·λz/D, centred on the specular reflection), contrast, Stephens-KS against exp(−x),
    speckle size against c·λz/D. Box route: exact field; PML route: far field (far zone only). Pre-flight rules for
    the plane (angle, pixels per speckle, number of independent samples, coherent fraction exp(−(2kσ)²)).
  - G14a: series over σ and seed ("Berechnung" page, ≤ 64 runs, one background process, runs strictly one after
    another, a cancel or crash of one run does not stop the others). The results page combines several runs into a
    speckle ensemble (pooled KS, contrast per σ with the monotonicity check, correlation of the patterns) through
    the new worker command `speckle_ensemble`.
- Progress during long steps: the run pages show the step the library is in (from the tail of `run.log`: beam,
  MLFMM far operators, near matrix, PML near ring, PML far ring/ACA, ...), the time since its last message and the
  last 12 library lines. spdlog only prints a step at its start or end, so the silence is shown explicitly.
  Measured on a real PML + MLFMM run (2N = 172 720): near ring 1134 s, followed by a silent ACA far ring.
- G23: isolated line/trench can be meshed on the library height map ("Vernetzung: Höhenkarte der Bibliothek"):
  square patch L = Lx, profile sampled at the grid spacing h, then the box (uniform or graded, fine band
  3δ + H, trench depth added) or the PML termination. Box/PML logic of the rough surface moved to
  `sbgui/heightmap_route.py` and shared; `Geometry.mesher_for(p)` lets a geometry pick its mesher per
  parameter set. Sampling rules: a wall inside one grid cell is reported with its effective angle, roundings
  below h are not visible. The gmsh mesher stays the default (exact edges).
- G20 (tested against SpeckleBem main fa856af, 2026-10-20): the worker probes the optional library features
  (`rough_surface`, `pml`, `pml_mlfmm`, `near_field`, `absolute_drc`, `hdf5`) instead of relying on the
  version number (the library reports 0.1.0 for every commit); library warnings and errors (spdlog lines in
  `run.log`) are stored in `status.json` as `library_messages` and shown on Berechnung and Ergebnisse;
  GMRES tolerance choices follow ADR 0006 (≤ 1e-5 for quantitative Ag, with a pre-flight hint).
- G21: geometries can let the library mesh inside the worker (`Geometry.mesher = "library"`,
  `build_lib`, `LibraryMesh`); worker command `mesh` and `bridge.preview_mesh` for the 3-D preview;
  `save_mesh` shared by job runner and worker; unknown count of open surfaces (interior edges).
- G22: the DRC observable stores the incident power (`sim.incident_power()`, beams only) and optionally
  cross-checks R against `sim.reflectance(90, 180)` (the library's 1° Gauss–Legendre grid).
- G13: near-field observable for bodies: |E| (total or scattered) on an xz/yz/xy grid via `sb.plane_grid` and
  `sim.field`; points closer than 0.5 h to the surface are left out before the call (the library raises
  below 1e-3 h, the error rises below h/2, WP24); for spheres a Mie error map and max/median error outside.
  Sphere r = 300 nm, n = 1.5, h = 80 nm: max 0.026, median 0.006 (library WP24 criterion < 0.1).
- G19: export: CSV per observable (`sbgui/export.py`), downloads of `mesh.npz` and the HDF5 file; HDF5 in the
  library format via `Simulation.save` with the GUI config, rules and library version as `/metadata`; a
  missing h5py no longer fails the run (status `hdf5_error`, hint on Berechnung); worker command `h5info`
  reloads the file with `specklebem.io.load_hdf5` (button on Ergebnisse).
- G10: geometry "Raue Oberfläche (Gauß)": `sb.RoughSurface` with the box of `sb.rough_surface_box_params`
  (uniform by default, graded optional, manual depth drops a fine band that would reach the bottom plate);
  rules from the library findings (rough Ag in the box, σ > 50 nm edge uncertainty, rough-Si mesh
  convergence); preview shows the measured σ; for σ = 0 the DRC observable reports the plane-wave Fresnel
  reflectance and the relative deviation.
- G12: PML route (ADR 0009) for the rough surface: termination "Box" or "PML" (`make_open_surface_mesh`,
  `Simulation.with_pml`, `PmlTermination`; dense or MLFMM); one height map on L + 2 W_t for both routes
  (box = central crop, bitwise identical patch heights as in the library's 7e); validated defaults (taper,
  gap 0.5 µm, PML 1 µm, σ_max 4, m 2, dark band 1e-4); PML waist rule instead of the box rim rule; beam
  region 1.02 √2 pml_start; dark-band ratio in the status; rough-Ag warning names the open WP-PML6; MLFMM
  with the direct solver is a pre-flight error.

### Changed
- G12: the box route of the rough surface now meshes the central crop of the shared height map
  (`make_mesh_from_height_map`) instead of `sb.RoughSurface(L, …)`: a given seed gives a different (equally
  distributed) realisation than in G10.
- Initial implementation, tested against SpeckleBem 0.1.0 (main 62ece8b, 2026-10-15).
- Architecture: GUI process (Streamlit, gmsh) and worker process (specklebem) exchange only files; detached
  job runner; run directories with `config.json`, `mesh.npz`, `status.json`, `results.npz`.
- Plugin registries (geometry, material, excitation, observable) with declarative parameter schemas;
  automatic plugin discovery and `sbgui.plugins` entry points.
- Geometries: sphere, ellipsoid (tilt/rotation), isolated line or trench (CD at half height, sidewall angle,
  rounded top and bottom corners, substrate depth) meshed as a closed ADR 0006 box with gmsh.
- Materials: library table (vacuum, Si/Ag at 500 nm), constant n + ik, user table (lambda, n, k).
- Excitations: plane wave, Gaussian beam (rigorous angular-spectrum or paraxial) with the library's waist rule.
- Observables: bistatic RCS with automatic Mie comparison; DRC over the reflection hemisphere with
  reflectance and co/cross polarisation.
- Pre-flight checks: schema ranges, mesh size, beam waist rule, memory estimate against installed RAM,
  plasmonic-material warning, mesh quality gate; "auto" solver resolution in one place.
- Pages: Modell (forms, 2-D profile, 3-D mesh preview, cost panel), Berechnung (start, live status, cancel),
  Ergebnisse (plots, export, reuse as template).
- Tests (28 + 1 slow), CI (lint + tests, Linux and Windows), documentation and ADRs.

### Known limits
- Ag on a finite substrate block only with a warning; the library's PML route is not connected yet.
- Not yet validated physically for structures (no RCWA/FDTD comparison); not used on the Windows/MSYS2
  development machine yet. See `docs/handover.md`.
