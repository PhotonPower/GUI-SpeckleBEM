# ADR 0001 — GUI and solver in separate processes, coupled by files

Status: accepted (2026-10-15)

## Context
The library is built on the development machine (Windows 11) as an MSYS2 UCRT64 Python module; Streamlit and
the gmsh wheel are not available there. Solves take minutes to hours and can exhaust memory (up to hundreds of
GB). A server run on the lead's 1 TB machine is planned.

## Decision
The GUI process never imports `specklebem`. Meshing runs in a detached job runner in the GUI environment;
the solve runs in a worker in an interpreter chosen by `SBGUI_WORKER_PYTHON` / `SBGUI_WORKER_PYTHONPATH`.
Everything exchanged is a file in the run directory; short queries (`info`, `rules`) go through the worker
CLI with JSON on stdout (last line).

## Consequences
+ independent environments, crash isolation, restart-safe runs, same contract for a remote start
+ GUI works (preview, checks) without the library
− each query costs a process start (seconds; cached by Streamlit)
− plugin modules must import in both environments (stdlib and numpy at module level)
− progress is polled from `status.json`, not pushed
