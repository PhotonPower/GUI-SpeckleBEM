# 04 Testing

## CI (GitHub Actions, no specklebem)

`ruff check .` and `pytest -m "not slow"` on Ubuntu (Python 3.10 and 3.12) and Windows. The workflow sets
`SBGUI_WORKER_PYTHON=nonexistent-python`, so the pages are tested in their "library missing" state: they must
render, show the error banner, and keep geometry preview and checks working. Tests marked `needs_library`
skip. On Linux the gmsh wheel needs `libglu1-mesa` (installed in the workflow).

| File | Covers |
|---|---|
| `tests/test_geometry.py` | profile areas and widths, fillet geometry, invalid profiles, icosphere/ellipsoid volumes, closed outward-oriented structure meshes with analytic volume (ridge and trench), triangle estimate |
| `tests/test_core.py` | plugin discovery, schema conversion and ranges, config round trip and migration, issues (mesh size, material table, observable/geometry mismatch, beam waist rule), solver auto-resolution, memory rule, atomic status |
| `tests/test_pages.py` | headless Streamlit `AppTest` of all pages without library, geometry switching, impossible profile |
| `tests/test_e2e.py` (slow) | sphere through job runner and worker: σ(θ) within 2 % of Mie (measured 0.5 %), C_sca within 2 % |

## Manual: solver round trip

```bash
SBGUI_RUNS_DIR=/tmp/runs python -m pytest tests/test_e2e.py -q -m slow      # ~30 s, one core
```

## Building specklebem for the worker (Linux)

```bash
sudo apt-get install -y libeigen3-dev libopenblas-dev
pip install "pybind11<3" scikit-build-core cmake ninja numpy
pip install --no-build-isolation ./python         # in the SpeckleBem checkout
```

`pybind11` 3.x fails to compile `python/src/bind_excitation.cpp:151` (inconsistent lambda return types in
`py::make_tuple`); pip's build isolation pulls the newest pybind11 because `pyproject.toml` only requires
`>=2.13`. On the Windows development machine use the MSYS2 build and point the GUI at it
(`SBGUI_WORKER_PYTHON`, `SBGUI_WORKER_PYTHONPATH`).

## Not covered yet

Real browser use (all UI tests are headless), the Windows/MSYS2 worker path, structures with MLFMM at
production size, physical validation of structures against an independent method (RCWA/FDTD), gmsh meshes
above ~10⁶ triangles. See `docs/backlog.md`.
