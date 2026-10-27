# SpeckleBem-GUI

Streamlit-Oberfläche für [SpeckleBem](https://github.com/PhotonPower/SpeckleBem): Kugel, Ellipsoid und
isolierte Stege/Gräben (Seitenwandwinkel, Rundungen an Ober- und Unterkante, Tiefe) definieren,
Kosten und Regelverstöße sofort sehen, rechnen, Ergebnisse ansehen. Gebaut, um mit der Bibliothek zu
wachsen, ohne dass die Oberfläche umgeschrieben werden muss.

**Stand:** erste lauffähige Version (0.1.0, Entwicklung). Getestet gegen SpeckleBem 0.1.0 (main 62ece8b);
Kugel gegen Mie validiert (σ(θ) 0,5 %), Strukturen laufen durch die Pipeline, sind aber physikalisch noch nicht
validiert. Details: [docs/handover.md](docs/handover.md), Aufgaben: [docs/backlog.md](docs/backlog.md),
Änderungen: [CHANGELOG.md](CHANGELOG.md).

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/01_concept.md](docs/01_concept.md) | Architektur, Prozessmodell, Lauf-Ordner als Vertrag, Modulübersicht |
| [docs/02_plugin_guide.md](docs/02_plugin_guide.md) | Plugins schreiben (Geometrie, Material, Anregung, Auswertung) |
| [docs/03_conventions.md](docs/03_conventions.md) | Einheiten, Koordinaten, Definition von CD/Seitenwand/Rundung, GUI-Heuristiken |
| [docs/04_testing.md](docs/04_testing.md) | CI, Tests, Bauen der Bibliothek für den Worker |
| [docs/05_library_interface.md](docs/05_library_interface.md) | genutzte Bibliotheksaufrufe und was davon verifiziert ist |
| [docs/adr/](docs/adr/) | Architekturentscheidungen |
| [docs/backlog.md](docs/backlog.md), [docs/handover.md](docs/handover.md) | Arbeitspakete und Übergabestand |
| [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Regeln für Sitzungen und Beiträge |

## Start

```bash
pip install -e ".[dev,system]"            # GUI-Umgebung (normales Python; Linux: libglu1-mesa für gmsh)
export SBGUI_WORKER_PYTHON=/pfad/zu/python        # Interpreter MIT specklebem (Standard: derselbe)
export SBGUI_WORKER_PYTHONPATH=build/win-release/python;python   # optional, z. B. MSYS2-Build
streamlit run app.py
```

Windows/MSYS2 (Entwicklungsrechner): GUI in einem normalen Windows-Python, Worker =
`C:/msys64/ucrt64/bin/python.exe` mit `SBGUI_WORKER_PYTHONPATH` wie in `CLAUDE.md`. Läufe liegen in
`~/sbgui_runs` (`SBGUI_RUNS_DIR`). Tests: `python -m pytest tests -q`.

Hinweis zum Bauen: `pip install ./python` zieht ungepinnt pybind11 3.x, womit `bind_excitation.cpp:151`
nicht kompiliert. Bis das im Projekt gepinnt ist: `pip install "pybind11<3"` und
`pip install --no-build-isolation ./python`.

## Architektur

```
 GUI-Prozess (Streamlit, numpy, gmsh, plotly)          Worker-Prozess (specklebem, numpy)
 ┌──────────────────────────────────────┐              ┌──────────────────────────────┐
 │ ui/pages: Modell · Berechnung · Erg. │  Dateien     │ worker.py  info | rules | run│
 │ plugins/: Geometrie, Material,       │ ───────────► │  Material.build, Excitation. │
 │           Anregung, Auswertung       │ config.json  │  build, Simulation, solve,   │
 │ checks.py (Regeln, Speicher, Kosten) │ mesh.npz     │  Observable.compute          │
 │ jobrunner.py: Netz → Worker starten  │ ◄─────────── │                              │
 └──────────────────────────────────────┘ status.json  └──────────────────────────────┘
                                          results.npz
```

* **Die GUI importiert `specklebem` nie.** Alles, was die Bibliothek wissen muss (Boxtiefe, erlaubte
  Strahltaille, Plasmonik-Test, Fähigkeiten), fragt `bridge.py` über den Worker ab. Dadurch dürfen
  GUI- und Rechenumgebung verschieden sein, ein Absturz (z. B. Speicher) trifft nur einen Lauf, und
  ein Lauf auf dem Server ist derselbe Vertrag mit anderem Startbefehl (`bridge._worker_argv`).
* **Lauf-Ordner = Vertrag und Protokoll:** `config.json` (inkl. der verwendeten Bibliotheksregeln und
  -version), `mesh.npz`, `status.json`, `results.npz`, `report.txt`, `run.log`.
* **Regeln stehen an genau einer Stelle:** `checks.py` (Netzweite, Speicher, Ag-Warnung,
  Solver-„auto“) und die Plugins (`validate`). Die Seiten zeigen nur an.
* Plugin-Module importieren oben nur stdlib und numpy (gmsh/plotly/specklebem erst in Methoden), damit
  GUI und Worker dieselben Module laden können.

## Konventionen

* Konfiguration in Anzeigeeinheiten (nm, °), Plugins bekommen SI (`Schema.to_si`).
* Bibliotheks-Rahmen (docs/06): Objekt bei z > ξ, Licht läuft in +z, `exp(+jωt)`. Die GUI zeigt
  Substratstrukturen „Luft oben“ (z-Achse gespiegelt); intern z_lib = −z_phys.
* Steg/Graben: **CD = Breite auf halber Höhe**, Seitenwandwinkel gegen die Substratebene
  (90° senkrecht; < 90° = breiter an der Substratebene), „Oberkante“ = Ecken bei höherem z,
  „Unterkante“ = Ecken bei tieferem z (Steg: Kopf/Fuß, Graben: Öffnung/Boden).

## Erweiterungsrezepte

**Neue Geometrie** (`sbgui/plugins/meine_form.py`, sonst nichts anfassen):

```python
from ..base import Geometry, MeshResult
from ..params import Field
from ..registry import GEOMETRIES

@GEOMETRIES.register
class Zylinder(Geometry):
    id = "cylinder"; label = "Zylinder"; kind = "object"       # oder "substrate"
    fields = (Field("radius", "Radius", "float", 200.0, "nm", min=10, max=5000),
              Field("height", "Höhe", "float", 300.0, "nm", min=10, max=5000))
    def meta_hint(self, p): return {"kind": "object", "lateral_size": 2 * p["radius"]}
    def estimate_triangles(self, p, h): ...
    def build(self, p, h): ...  # -> MeshResult(vertices[m], triangles, meta); Normalen nach außen
```

Das Formular, die Bereichsprüfung, die Vorschau, die Kosten und die Konfiguration entstehen daraus
automatisch. Optional: `validate` (Issues), `resolve` (von Bibliotheksregeln abhängige Werte),
`outline` (2-D-Vorschau).

**Neue Auswertung:** Klasse `Observable` mit `compute(sb, sim, p, ctx)` (Worker, gibt numpy-Arrays
zurück) und `figures(data, ctx)` (GUI, Plotly). `applies_to` legt fest, zu welchen Geometrie-Arten sie
angeboten wird. Beispiele: Nahfeld auf `sb.plane_grid`, Speckle-Kontrast und Autokorrelation (Phase 6).

**Neues Material / neue Anregung:** analog (`Material.build`, `Excitation.build`).

**Neue Bibliotheksfunktion** (PML, GPU, ACA, Server): `worker.cmd_info` meldet sie unter `features`,
Plugins und `checks.py` schalten daran (`caps["features"]["pml"]`). Neue Felder in der Konfiguration:
`SCHEMA_VERSION` erhöhen und in `config.migrate` einen Block ergänzen.

**Plugins von außen:** Entry-Point-Gruppe `sbgui.plugins`.

## Bekannte Grenzen (Stand dieser Version)

* Substrat-Strukturen laufen auf der **geschlossenen Box** der Bibliothek. Si ist gemäß Projektregeln
  nutzbar (w₀ ≤ L·cosθ/6); für **Ag** zeigt die GUI eine Warnung (WP-V3: Oberflächenwellen verfälschen
  die Box-Rechnung); dafür ist der Abschluss „PML“ (offene Oberfläche) da. Raues Metall ist auf der PML-Route nur
  im Kegel θ ≤ 30° und mit Lücke ≥ 6 λ quantitativ (ADR 0010).
* Gebiete sind teuer: 4×4 µm bei h = 50 nm ≈ 62 000 Dreiecke (2N ≈ 1,9·10⁵, MLFMM). Die dichte Matrix
  endet bei 2N ≈ 2·10⁴.
* Rundungen: Radius < h_Profil/10 wird abgelehnt (Gmsh-Streifen), Radius < h_Profil wird nur als Fase
  abgebildet (Warnung). Aufgelöste Rundungen kosten Unbekannte („Verfeinerung am Profil“).
* Der Steg/Graben ist über das ganze Gebiet entlang y extrudiert (lang, endlich beleuchtet);
  keine Hinterschneidungen, keine Löcher/Pfosten, keine Periodizität.
* Heuristiken, die **nicht** aus der Projektdokumentation stammen: `DENSE_LIMIT`, `DIRECT_LIMIT` und die
  Netzweiten-Warnschwellen in `checks.py`; Speicher-Faustregel aus den Messungen in `docs/handover.md`.
* gmsh ist eine globale C-Bibliothek: Zugriff wird per Lock serialisiert; Netze laufen im Job-Prozess.

## Roadmap, passend zu den Bibliotheksphasen

1. ~~PML-Route (offene Fläche) als zweite Terminierungsart~~ (angebunden, G12/G23/G25).
2. ~~Nahfeld-Auswertung~~ (G13).
3. Phase 6: Speckle-Statistik (G15) und Serien über σ und Seed (G14a) sind angebunden, **noch nicht gegen einen
   echten Bibliotheks-Build gelaufen**; offen: Parameter-Sweeps über weitere Größen (G14), Winkelkorrelation γ₁₂.
4. Server-Start (ssh/Queue) hinter `bridge.start_run`, Fortschritt per `status.json`.
5. Periodische oder viel-Perioden-Gitter, Löcher/Pfosten als weitere Geometrie-Plugins.
