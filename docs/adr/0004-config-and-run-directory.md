# ADR 0004 — Versioned JSON config and self-contained run directories

Status: accepted (2026-10-15)

## Decision
The working model is one JSON-serialisable dict with `schema_version` (`config.migrate` upgrades old files).
A run copies it into its own directory together with the library rules and capabilities used (`resolved`),
the mesh and status/result files. Values stay in display units; SI conversion happens at use.

## Consequences
+ every run is reproducible and can be reloaded as a template ("als Vorlage übernehmen")
+ GUI and worker can be different versions as long as the schema version is understood
− `mesh.npz` and `results.npz` are large and git-ignored; archiving runs is the user's job
