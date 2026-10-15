## Was ändert sich

<!-- Layer (core, meshing, plugins, runtime, ui, tests, docs, tooling) und kurze Beschreibung -->

## Checkliste

- [ ] `python -m pytest tests -q` grün, `ruff check .` sauber
- [ ] neue Funktion hat Tests (Plugins: Schema, `validate`, Build-Test mit Volumen-/Geschlossenheitsprüfung)
- [ ] `CHANGELOG.md` ([Unreleased]) und `docs/backlog.md` aktualisiert
- [ ] keine Tokens, Zugangsdaten oder maschinenspezifischen Pfade
- [ ] Regeln der Bibliothek nicht dupliziert (über `bridge.rules` holen)
