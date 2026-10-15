# 01 Concept and architecture

## Goal

A GUI that is useful with the current SpeckleBem (spheres, ellipsoids, isolated lines/trenches on Si) and
that grows with the library (PML route, near fields, speckle statistics, GPU, server) without rewriting the
pages.

## Process model

```
 GUI process (Streamlit, numpy, gmsh, plotly)              Worker process (specklebem, numpy)
 ┌────────────────────────────────────────┐                ┌───────────────────────────────┐
 │ ui/pages  Modell · Berechnung · Erg.   │                │ worker.py  info | rules | run │
 │ plugins/  geometry, material,          │   files        │  Material.build               │
 │           excitation, observable       │ ─────────────► │  Excitation.build             │
 │ checks.py rules, memory, cost          │ config.json    │  sb.Simulation, solve         │
 │ jobrunner.py  mesh → start worker      │ mesh.npz       │  Observable.compute           │
 │ bridge.py  subprocess + settings       │ ◄───────────── │                               │
 └────────────────────────────────────────┘ status.json    └───────────────────────────────┘
                                            results.npz
```

Reasons (ADR 0001): the library on the Windows development machine is an MSYS2 UCRT64 build where
Streamlit and the gmsh wheel are not available; a solver crash or out-of-memory must not take the GUI down;
a remote server run must be the same contract with a different start command; the GUI must survive library
changes (capabilities are queried, not assumed).

Two worker entry points are cheap queries (a few seconds, cached by the GUI): `info` returns version and
capabilities, `rules` returns library rule values for the current optics/materials (box depth, waist
fraction, plasmonic, weak absorber, field decay length). `run <run_dir>` is the long job.

## Run directory (the contract)

```
<runs_dir>/<YYYYmmdd-HHMMSS>_<name>/
    config.json    full record incl. "resolved": library rules, library capabilities, GUI version
    mesh.npz       vertices [m], triangles, meta (JSON string: kind, lateral_size, max_radius, mesh_stats)
    status.json    state: queued → meshing → solving → postprocessing → done | error | cancelled,
                   plus n_unknowns, iteration/residual (live), iterations, true_residual, pids, traceback
    results.npz    arrays named obs<i>__<name> (i = index in config.observables) and residual_history
    report.txt     Simulation.report()
    run.log        stdout/stderr of job runner and worker
    currents.h5    optional
```

`status.json` is replaced atomically (`store.write_status`); readers never see a half-written file.

## Data flow of a run

1. GUI: `checks.collect_issues` (blocking errors disable "Lauf starten"); `bridge.start_run` writes
   `config.json` and spawns the detached job runner (GUI interpreter, no worker PYTHONPATH).
2. Job runner: materialise config → `Geometry.build` → `mesh.npz` → quality gate → spawn worker with the
   worker interpreter and PYTHONPATH → wait → if the worker died without reporting, mark `error`.
3. Worker: build materials and excitation, `sb.TriangleMesh`, `sb.Simulation`, `solve` with a throttled
   progress callback, `Observable.compute` for every configured observable, `results.npz`.
4. GUI results page: load arrays, `Observable.figures`, export, "use as template".

## Module map

| Module | Responsibility | Process |
|---|---|---|
| `params.py` | `Field`, `Schema`: widgets, validation, SI conversion from one declaration | both |
| `registry.py`, `base.py` | four registries, plugin base classes, `Issue`, `MeshResult`, plugin discovery | both |
| `config.py` | config dict, `schema_version`, migration, `materialise` | both |
| `checks.py` | all pre-flight rules, memory/cost estimate, solver "auto" resolution | GUI/job |
| `meshing/` | icosphere, 2-D profile with fillets, gmsh extrusion, orientation, quality | GUI/job |
| `plugins/` | concrete geometries, materials, excitations, observables | both |
| `store.py` | run directories, atomic status | all |
| `bridge.py` | worker interpreter/env, queries, start, cancel | GUI |
| `jobrunner.py`, `worker.py` | detached pipeline | job / worker |
| `ui/` | Streamlit pages, generic schema widgets | GUI |

## Extension points

New geometry/material/excitation/observable = one class in `sbgui/plugins/` (`docs/02_plugin_guide.md`).
New library capability = report it in `worker.cmd_info()["features"]`, gate UI and checks on it. New config
fields = bump `SCHEMA_VERSION` and add a block to `config.migrate`. Remote execution = change
`bridge._worker_argv` and `bridge.start_run`; the contract stays.
