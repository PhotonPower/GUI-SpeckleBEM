# Backlog

Work packages (WP) for the GUI. Status values: `todo`, `in progress`, `review`, `done`. One WP = one branch
`wp/<id>-<slug>`, typically 200–800 lines including tests. Acceptance criteria are measurable; "library"
means SpeckleBem.

## Done (initial implementation, 2026-10-15)

| WP | Title | Acceptance (met) | Status |
|---|---|---|---|
| G1 | Schemas, registries, config, store | plugin discovery, SI conversion, ranges, config migration, atomic status (tests/test_core.py) | done |
| G2 | Meshing: icosphere, 2-D profile with fillets, gmsh extrusion, orientation, quality | closed, outward, analytic volume for ridge and trench; widths/areas of profiles exact (tests/test_geometry.py) | done |
| G3 | Plugins: sphere, ellipsoid, isolated line/trench; materials; excitations; observables | forms from schemas; Mie flag for a = b = c; waist rule enforced | done |
| G4 | Runtime: bridge, job runner, worker (`info`, `rules`, `run`) | sphere σ(θ) 0.5 % and C_sca 0.4 % vs Mie through the full pipeline (tests/test_e2e.py) | done |
| G5 | UI pages: Modell, Berechnung, Ergebnisse | headless render without library, geometry switching, error reporting (tests/test_pages.py) | done (headless only) |
| G6 | Repository, CI, documentation, ADRs | lint + tests on Linux py3.10/3.12 and Windows | done (first CI run green on all three runners, 2026-10-15) |

## Library sync and new features (2026-10-20)

| WP | Title | Acceptance | Status |
|---|---|---|---|
| G20 | Library sync: feature probes, library warnings in the UI, ADR 0006 tolerance choices | probes true on fa856af; spdlog warnings parsed (tests/test_library_sync.py); sphere e2e green against fa856af | done |
| G21 | Library-made meshes in the worker (`Geometry.mesher = "library"`, `build_lib`, worker `mesh` command, preview through the bridge) | rough surface meshes in the worker for run and preview; open-surface unknown count (tests/test_library_meshing.py) | done |
| G22 | Energy observables: incident power, library reflectance as cross-check | R from the DRC quadrature equals `sim.reflectance` within the quadrature error | done (fake-sim tests; real: line on graded box, 2N = 3 600: R = 0.317861 both, difference 3e-15) |
| G23 | Line/trench on the library height map: box grading, fine band, PML termination | G12 | ridge/trench orientation on both routes; small real run (graded box) | done 2026-10-20 (tests/test_line_termination.py; 2N = 3 600 run) |

## Library sync 2 (2026-10-26, library main 6c431f6)

| WP | Title | Acceptance | Status |
|---|---|---|---|
| G24 | Block-diagonal preconditioner (WP-PC1, ADR 0011): solver setting, `block_level`, GMRES-only rule, probe | stand-in tests (tests/test_preconditioner.py); **open: one real run** on a rough Ag PML case, iterations "block" vs "diagonal" (library: 3.2× fewer) | merged-ready, not run against a real build |
| G25 | PML far-field source (WP-PML6) and the rough-metal gap rule ≥ 6 λ (ADR 0010 decision 3, WP-PML6b); stale PML texts removed | tests/test_far_field_source.py; **open: a real Huygens run** (flat Si, `with_pml` accepts the keywords, `sim.far_field_source == "huygens"`) | merged-ready, not run against a real build |
| G15 | Speckle statistics observable and ensemble (WP-S1) | tests/test_speckle.py with stand-ins; **open: one real small run** (library example 02: Si L = 2.5 µm) and the slow harness test | merged-ready, not run against a real build |
| G14a | Series over σ and seed, ensemble over runs | tests/test_series.py, tests/test_pages.py; **open:** a real series of ≥ 2 runs from the browser (G7) | merged-ready, not run in a browser |

## Next

| WP | Title | Depends on | Acceptance criterion | Status |
|---|---|---|---|---|
| G7 | First interactive use: run the GUI in a real browser, fix what headless tests cannot see (layout, widget state across pages, long runs, live status) | — | a Si trench 4×4 µm, h = 50 nm, MLFMM completes from the browser; findings recorded in `docs/handover.md` | todo |
| G8 | Windows/MSYS2 worker path | G7 | GUI in a normal Windows Python, worker = `C:/msys64/ucrt64/bin/python.exe`; sphere vs Mie e2e green; cancel kills the process tree | todo |
| G9 | Calibrate the cost panel | G7 | estimated vs measured memory and time for 3 sizes (Si, MLFMM) recorded; constants in `checks.py` updated with the measurement | todo |
| G10 | Rough-surface plugin (`RoughSurface`, `rough_surface_box_params`) | G21 | Si patch σ = 50 nm, Lc = 500 nm: box depth/fine band from the library, waist rule, DRC; unit test of the plugin | done 2026-10-20 (tests/test_rough_surface.py; pipeline run on a small flat Si patch; production size not run here: 3 GB sandbox) |
| G11 | Physical validation of structures | G7 | DRC of a periodic-like trench/line against an independent method (RCWA/FDTD), deviations documented; or reduction to a documented uncertainty | todo |
| G12 | Connect the PML route (library `Simulation.with_pml`, `make_open_surface_mesh`) | library WP-PML5b | flat Si/Ag Fresnel check (7a) and rough-Si box vs PML (7e) reproduced through the GUI | merged 2026-10-20 without an end-to-end solve (lead decision): mesh, zones, `with_pml` construction, dark band 1.3e-5 and shared height map (bitwise) verified; the sandbox solve (flat Si, h = λ/3, 2N = 6 402, MLFMM) did not finish (near ring 787 s on 1 core, killed between turns). **Open: 7a and 7e on the development machine** (docs/handover.md, How to continue 2). Line/trench on the open surface not done (G12c). |
| G13 | Near-field observable (`sb.plane_grid`, `sim.field`) with xz/yz cross sections | — | sphere near field vs Mie in the xz plane (library WP24 criterion) | done 2026-10-20 (max 0.026 < 0.1; tests/test_near_field.py, slow e2e) |
| G14 | Parameter sweeps and seed ensembles (series of runs, comparison page) | G10 | sweep of CD and swa with a table and plot over runs; seed ensemble for rough surfaces | partly: G14a (σ × seed series, speckle ensemble); todo: other parameters (CD, swa), comparison page for non-speckle observables |
| G15 | Speckle statistics observables (contrast, field correlation) | library Phase 6 | matches the library's reference statistics | partly: contrast, KS, speckle size (see G15 above); todo: angular correlation γ₁₂ (two incidence angles), intensity PDF test on real runs |
| G16 | Remote/server start (ssh or queue) behind `bridge.start_run` | G8 | run on the 1 TB server from the GUI, status polled from a synced run directory | todo |
| G17 | More geometries: cylinder, hole, post, multi-line gratings (finite) | — | each with schema, validate, build test with analytic volume | todo |
| G18 | Geometry meshing robustness: gmsh in a subprocess, meshes > 10⁶ triangles, radii below the current limit via local refinement fields | — | no gmsh crash can take the GUI down; 10×10 µm at h = 50 nm meshes in < 1 min | todo |
| G19 | Results: HDF5 export (`io.save_hdf5` format), figure export (PNG/CSV) | — | exported file reloads with `specklebem.io.load_hdf5` | done 2026-10-20 (sphere run: reload 3 840 currents + GUI metadata; CSV per observable; PNG via the Plotly toolbar) |

## Upstream items (SpeckleBem repository, not part of this code base)

| Item | Detail |
|---|---|
| Pin pybind11 | `python/pyproject.toml` requires `pybind11>=2.13`; 3.x fails at `bind_excitation.cpp:151`. Pin `<3` or fix the lambda return type |
| `default_box_depth` for lossless objects | raises; a documented default (e.g. the ADR 0006 minimum of 2 µm) would make the GUI rule uniform |
