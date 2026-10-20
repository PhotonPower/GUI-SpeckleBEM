"""Run configuration: a plain JSON-serialisable dict with a schema version.

The config is the single hand-over object between GUI, job runner and worker, and the
reproducibility record stored with every run. Values are kept in display units (nm, deg, ...);
``materialise`` converts them to SI through the plugin schemas.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .params import Field, Schema
from .registry import EXCITATIONS, GEOMETRIES, MATERIALS, OBSERVABLES, load_plugins

SCHEMA_VERSION = 1

OPTICS = Schema((
    Field("wavelength", "Wellenlänge (Vakuum)", "float", 500.0, "nm", min=100.0, max=5000.0, step=10.0),
))
MESH = Schema((
    Field("h", "Netzweite h", "float", 50.0, "nm", min=2.0, max=2000.0, step=5.0,
          help="Zielkantenlänge. Faustregel der Projekt-Validierung: λ/10 oder feiner."),
))

SOLVER = Schema((
    Field("compression", "Matrix", "choice", "auto",
          choices=(("auto", "automatisch"), ("dense", "dicht"), ("mlfmm", "MLFMM"))),
    Field("solver", "Löser", "choice", "auto",
          choices=(("auto", "automatisch"), ("gmres", "GMRES"), ("direct", "direkt (LU)"))),
    Field("formulation", "Formulierung", "choice", "auto",
          choices=(("auto", "automatisch (Empfehlung der Bibliothek)"), ("PMCHWT", "PMCHWT"),
                   ("ICTF", "ICTF"), ("MCTF", "MCTF"))),
    Field("preconditioner", "Vorkonditionierer", "choice", "auto",
          choices=(("auto", "automatisch"), ("diagonal", "Jacobi"), ("none", "keiner"))),
    Field("tol", "GMRES-Toleranz", "choice", 1e-3,
          choices=((1e-3, "1e-3 (Standard, qualitativ)"), (1e-4, "1e-4 (Nahfeld-Akzeptanz)"),
                   (1e-5, "1e-5 (quantitativ Ag, ADR 0006)"), (1e-6, "1e-6")),
          help="ADR 0006: quantitative Ag-Rechnungen brauchen ≤ 1e-5; der Nahfeldvergleich mit Mie "
               "(WP24) läuft bei 1e-4."),
    Field("mlfmm_digits", "MLFMM-Genauigkeit d₀", "int", 3, "-", min=2, max=5, step=1,
          help="3 genügt für Leaf ≥ λ/4; 5 wurde für Leaf ≥ λ/2 verifiziert (ADR 0008)."),
    Field("mlfmm_leaf", "MLFMM-Blattgröße (min. Boxkante)", "choice", 0.0,
          visible_if=lambda v: v.get("compression") != "dense",
          choices=((0.0, "automatisch (Blattregel der Bibliothek)"), (0.5, "≥ 0,5 λ"), (1.0, "≥ 1 λ"),
                   (2.0, "≥ 2 λ"), (4.0, "≥ 4 λ")),
          help="min_box_size_lambda (in Außenwellenlängen). Größere Blätter: mehr exaktes Nahfeld (Speicher, Zeit), "
               "dafür stabil bei verlustbehafteten Gebieten (Si). Scheitert die Entwicklung eines Gebiets, wiederholt "
               "der Worker automatisch mit größeren Blättern."),
    Field("threads", "OpenMP-Threads (0 = alle)", "int", 0, "-", min=0, max=1024, step=1),
    Field("save_hdf5", "HDF5 speichern (Netz, Ströme, Konfiguration; groß)", "bool", False,
          help="Format der Bibliothek (specklebem.io.load_hdf5); braucht h5py im Worker."),
))

SECTIONS = ("optics", "mesh", "geometry", "object", "background", "excitation", "solver", "observables")


def default_config() -> dict:
    load_plugins()
    geom = GEOMETRIES.get("sphere")
    return {
        "schema_version": SCHEMA_VERSION,
        "name": "lauf",
        "optics": OPTICS.defaults(),
        "mesh": MESH.defaults(),
        "geometry": {"type": geom.id, "params": geom.schema().defaults()},
        "object": {"type": "library", "params": {"name": "silicon_500nm"}},
        "background": {"type": "library", "params": {"name": "vacuum"}},
        "excitation": {"type": "plane_wave", "params": EXCITATIONS.get("plane_wave").schema().defaults()},
        "solver": SOLVER.defaults(),
        "observables": [{"type": "bistatic_rcs", "params": OBSERVABLES.get("bistatic_rcs").schema().defaults()}],
        "resolved": {},
    }


def migrate(cfg: dict) -> dict:
    """Bring an older config up to ``SCHEMA_VERSION`` (add one ``if v < n`` block per change)."""
    cfg = copy.deepcopy(cfg)
    v = int(cfg.get("schema_version", 0))
    if v > SCHEMA_VERSION:
        raise ValueError(f"config schema {v} is newer than this GUI ({SCHEMA_VERSION})")
    # if v < 2: cfg["new_section"] = ...; v = 2
    cfg["schema_version"] = SCHEMA_VERSION
    return cfg


def save_config(cfg: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_config(path: Path) -> dict:
    return migrate(json.loads(Path(path).read_text(encoding="utf-8")))


def config_hash(cfg: dict, keys=("optics", "mesh", "geometry", "object", "background", "excitation")) -> str:
    blob = json.dumps({k: cfg.get(k) for k in keys}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def materialise(cfg: dict, rules: dict | None = None) -> dict:
    """Instantiate plugins and convert all parameters to SI.

    Returns a dict with ``wavelength``, ``h`` [m] and, per section, ``(plugin_instance, p_si)``
    pairs; the geometry parameters are passed through ``Geometry.resolve(p, rules)``.
    """
    load_plugins()
    cfg = migrate(cfg)

    def inst(reg, spec):
        cls = reg.get(spec["type"])
        return cls(), cls.schema().to_si(spec.get("params", {}))

    out = {
        "wavelength": OPTICS.to_si(cfg["optics"])["wavelength"],
        "h": MESH.to_si(cfg["mesh"])["h"],
    }
    geom, pg = inst(GEOMETRIES, cfg["geometry"])
    out["geometry"] = (geom, geom.resolve(pg, rules))
    out["object"] = inst(MATERIALS, cfg["object"])
    out["background"] = inst(MATERIALS, cfg["background"])
    out["excitation"] = inst(EXCITATIONS, cfg["excitation"])
    out["observables"] = [inst(OBSERVABLES, o) for o in cfg.get("observables", [])]
    return out
