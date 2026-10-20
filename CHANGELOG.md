# Changelog

All notable changes. Format: Keep a Changelog; versions follow the GUI, the tested library version is
named per entry.

## [Unreleased]

### Added
- G20 (tested against SpeckleBem main fa856af, 2026-10-20): the worker probes the optional library features
  (`rough_surface`, `pml`, `pml_mlfmm`, `near_field`, `absolute_drc`, `hdf5`) instead of relying on the
  version number (the library reports 0.1.0 for every commit); library warnings and errors (spdlog lines in
  `run.log`) are stored in `status.json` as `library_messages` and shown on Berechnung and Ergebnisse;
  GMRES tolerance choices follow ADR 0006 (≤ 1e-5 for quantitative Ag, with a pre-flight hint).
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
