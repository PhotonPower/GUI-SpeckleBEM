# Contributing

1. Branch `wp/<id>-<slug>` from `main` (ids: see `docs/backlog.md`).
2. Commit messages `<layer>: <imperative summary>`; layers: core, meshing, plugins, runtime, ui, tests,
   docs, tooling.
3. Before pushing: `ruff check .` and `python -m pytest tests -q -m "not slow"`.
4. New functionality needs tests; a new plugin needs schema, `validate` and build tests (see
   `docs/02_plugin_guide.md`).
5. Update `CHANGELOG.md` and `docs/backlog.md`.
6. No tokens, credentials or machine-specific paths in the repository.

Rules of the library (box depth, beam waist, mesh size) belong to SpeckleBem; do not copy them here, query
them (`sbgui.bridge.rules`).
