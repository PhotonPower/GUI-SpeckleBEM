# GUI-SpeckleBEM — session guide

Streamlit front end for [SpeckleBem](https://github.com/PhotonPower/SpeckleBem) (C++20 SIE/MLFMM library
with Python bindings). Defines spheres, ellipsoids and isolated lines/trenches, checks the model against
the library's rules, runs it, shows the results. Authoritative documents: `docs/01_concept.md`
(architecture), `docs/02_plugin_guide.md`, `docs/03_conventions.md` (binding conventions),
`docs/05_library_interface.md` (which library calls are used, what was verified), `docs/adr/`,
`docs/backlog.md` (work packages and status), `docs/handover.md` (state at the last session end).

## Build and test

```bash
pip install -e ".[dev,system]"            # GUI environment (gmsh wheel needs libGLU on Linux)
ruff check .                              # must be clean (CI)
SBGUI_WORKER_PYTHON=nonexistent-python python -m pytest tests -q -m "not slow"   # = CI, no library needed
python -m pytest tests -q -m slow         # solver round trip, needs an importable specklebem (~30 s)
streamlit run app.py
```

Solver environment: any Python that can `import specklebem` (build: see `docs/04_testing.md`; note the
pybind11 < 3 pin). Point the GUI at it with `SBGUI_WORKER_PYTHON` and, if needed,
`SBGUI_WORKER_PYTHONPATH` (e.g. the MSYS2 build on the Windows development machine).

## Hard rules (deviations are bugs)

- **The GUI process never imports `specklebem`.** All library knowledge (box depth, waist fraction,
  plasmonic test, capabilities) comes through `bridge.py` / the worker. Plugin modules import only stdlib
  and numpy at module level (gmsh, plotly, specklebem inside methods).
- **Library rules are not re-implemented.** Ask `bridge.rules()`; the only own numbers are the heuristics
  listed in `docs/03_conventions.md` ("GUI heuristics") and they are marked as such in the UI text.
- Config values are stored in display units (nm, deg), plugins receive SI (`Schema.to_si`).
- Library frame (SpeckleBem docs/06): object at z > xi, light in +z, normals out of the object, `exp(+jwt)`.
  The GUI shows substrate structures "air on top"; internally z_lib = -z_phys. Never leak this into the
  config.
- Every pre-flight rule lives in `checks.py` or in a plugin's `validate`; pages only display issues.
- A run directory is the contract between GUI, job runner and worker (`docs/01_concept.md`); status files
  are written atomically (`store.write_status`).
- gmsh works in micrometres inside `meshing/extrude.py` (its geometry tolerance is 1e-8 model units).
- Never commit tokens, credentials, run output (`*.npz`, `*.h5`) or machine-specific paths.
- Every plugin ships with tests: schema defaults, `validate` cases, a build test that checks closedness,
  orientation (positive volume) and an analytic volume.

## Branches, commits, workflow

- `main` stays green (CI: lint + tests on Linux py3.10/3.12 and Windows). Work on `wp/<id>-<slug>` branches,
  one per work package; squash-merge after green CI.
- Commit messages: `<layer>: <imperative summary>` with layers core, meshing, plugins, runtime, ui, tests,
  docs, tooling (e.g. `plugins: add cylinder geometry`).
- Update `CHANGELOG.md` ([Unreleased]), `docs/backlog.md` and, at session end, `docs/handover.md`.
- Related repo: SpeckleBem itself (library). Findings for it go to its issues, not into this code base.
