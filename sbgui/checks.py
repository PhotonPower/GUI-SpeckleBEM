"""All pre-flight checks in one place: plugin validation, mesh-size rules, memory/cost estimates
and the resolution of the "auto" solver choices. Pure Python (no library, no gmsh)."""

from __future__ import annotations

import os

from .base import Issue
from .config import MESH, OPTICS, SOLVER, materialise
from .registry import load_plugins

# Rough memory rule of thumb for MLFMM, from the recorded runs (docs/handover, WP22b/22d/22e):
# Si 2N = 1.0e6 -> 75 GB, 1.1e6 -> 89.5 GB, 5.95e6 -> 697 GB, i.e. ~ 70-120 kB per unknown.
MLFMM_BYTES_PER_UNKNOWN = (7.0e4, 1.2e5)
DENSE_LIMIT = 20_000  # 2N up to which "auto" takes the dense operator (6.4 GB, docs/backlog)
DIRECT_LIMIT = 12_000  # 2N up to which "auto" takes the direct LU instead of GMRES


def system_memory_gb() -> float | None:
    try:
        import psutil  # noqa: PLC0415

        return psutil.virtual_memory().total / 1e9
    except ImportError:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return None


def resolve_solver(solver_cfg: dict, n_unknowns: int) -> dict:
    """Turn the "auto" entries into concrete library arguments (single place for these heuristics)."""
    s = SOLVER.fill(solver_cfg)
    comp = s["compression"]
    if comp == "auto":
        comp = "dense" if n_unknowns <= DENSE_LIMIT else "mlfmm"
    solver = s["solver"]
    if solver == "auto":
        # the block-diagonal preconditioner is a GMRES preconditioner (library: GMRES only)
        direct = comp == "dense" and n_unknowns <= DIRECT_LIMIT and s["preconditioner"] != "block_diagonal"
        solver = "direct" if direct else "gmres"
    return {"compression": comp, "solver": solver, "formulation": s["formulation"],
            "preconditioner": s["preconditioner"], "block_level": int(s["block_level"]), "tol": float(s["tol"]),
            "mlfmm_digits": int(s["mlfmm_digits"]), "mlfmm_leaf": float(s.get("mlfmm_leaf") or 0.0),
            "threads": int(s["threads"]),
            "save_hdf5": bool(s["save_hdf5"])}


def estimate_memory_gb(n_unknowns: int, compression: str, solver: str) -> tuple[float, float]:
    if compression == "dense":
        gb = 16.0 * n_unknowns**2 / 1e9 * (2.0 if solver == "direct" else 1.0)
        return gb, gb
    lo, hi = MLFMM_BYTES_PER_UNKNOWN
    return n_unknowns * lo / 1e9, n_unknowns * hi / 1e9


def collect_issues(cfg: dict, rules: dict | None, n_unknowns: int | None = None,
                   mesh_stats: dict | None = None) -> list[Issue]:
    """Every reason not to start (errors) or to be careful (warnings) for this config."""
    load_plugins()
    issues: list[Issue] = []
    try:
        m = materialise(cfg, rules)
    except (KeyError, ValueError) as e:
        return [Issue("error", f"Konfiguration unvollständig: {e}")]
    lam, h = m["wavelength"], m["h"]

    for e in OPTICS.errors(cfg["optics"]) + MESH.errors(cfg["mesh"]):
        issues.append(Issue("error", e))
    sections = [("Geometrie", cfg["geometry"]), ("Objekt-Material", cfg["object"]),
                ("Hintergrund", cfg["background"]), ("Anregung", cfg["excitation"])]
    from .registry import EXCITATIONS, GEOMETRIES, MATERIALS  # noqa: PLC0415

    regs = [GEOMETRIES, MATERIALS, MATERIALS, EXCITATIONS]
    for (title, spec), reg in zip(sections, regs):
        for e in reg.get(spec["type"]).schema().errors(spec["params"]):
            issues.append(Issue("error", f"{title}: {e}"))
    if any(i.level == "error" for i in issues):
        return issues  # plugin validators assume in-range values

    geom, pg = m["geometry"]
    meta = geom.meta_hint(pg)
    ctx = {"wavelength": lam, "h": h, "meta": meta, "rules": rules}
    issues += geom.validate(pg, ctx)
    for key in ("object", "background"):
        mat, pm = m[key]
        issues += [Issue(i.level, f"{key}: {i.msg}") for i in mat.validate(pm, lam)]
    exc, pe = m["excitation"]
    issues += exc.validate(pe, ctx)
    n_bg = m["background"][0].refractive_index(m["background"][1], lam)
    octx = {**ctx, "excitation_params": m["excitation"][1], "geometry_params": pg,
            "n_background": float(n_bg.real) if n_bg is not None else 1.0}
    for obs, po in m["observables"]:
        if meta["kind"] not in obs.applies_to:
            issues.append(Issue("error", f"Auswertung '{obs.label}' passt nicht zu dieser Geometrie."))
        else:
            issues += obs.validate(po, octx)

    if h > lam / 3:
        issues.append(Issue("error", f"h = {h * 1e9:.0f} nm > λ/3: viel zu grob."))
    elif h > lam / 6:
        issues.append(Issue("warning", f"h = {h * 1e9:.0f} nm > λ/6: Validierung in docs/05 nutzt λ/10 "
                            "und feiner."))
    if rules and rules.get("plasmonic") and meta["kind"] == "substrate" and meta.get("termination") != "pml":
        issues.append(Issue("warning", "Plasmonisches Material (Ag) auf endlichem Substratblock: "
                            "Oberflächenwellen verfälschen die Box-Rechnung (WP-V3, 0,8–8 %). Für Ag den Abschluss "
                            "„PML“ wählen (offene Oberfläche, ADR 0009)."))
    tol = float(SOLVER.fill(cfg["solver"])["tol"])
    if rules and rules.get("plasmonic") and tol > 1e-5:
        issues.append(Issue("info", f"GMRES-Toleranz {tol:g}: für quantitative Ergebnisse mit plasmonischem "
                            "Material (Ag) verlangt ADR 0006 ≤ 1e-5."))
    if n_unknowns:
        r = resolve_solver(cfg["solver"], n_unknowns)
        if r["compression"] == "mlfmm" and r["solver"] == "direct":
            issues.append(Issue("error", "MLFMM rechnet nur mit GMRES; für den direkten Löser „dicht“ wählen."))
        if r["preconditioner"] == "block_diagonal" and r["solver"] == "direct":
            issues.append(Issue("error", "Der Block-Diagonal-Vorkonditionierer gehört zu GMRES; mit dem direkten "
                                "Löser (LU) wird er von der Bibliothek abgelehnt. Löser „GMRES“ wählen."))
        if r["compression"] == "dense" and r["solver"] == "gmres" and n_unknowns > DENSE_LIMIT:
            issues.append(Issue("warning", "Dichte Matrix mit sehr vielen Unbekannten gewählt."))
        lo, hi = estimate_memory_gb(n_unknowns, r["compression"], r["solver"])
        have = system_memory_gb()
        if have and lo > 0.9 * have:
            issues.append(Issue("error", f"Speicherbedarf ≈ {lo:.0f} GB, verfügbar {have:.0f} GB."))
        elif have and hi > 0.9 * have:
            issues.append(Issue("warning", f"Speicherbedarf {lo:.0f}–{hi:.0f} GB bei {have:.0f} GB RAM: "
                                "knapp."))
    if mesh_stats:
        if not mesh_stats["closed"] and not mesh_stats.get("open_surface"):
            issues.append(Issue("error", "Netz ist nicht geschlossen."))
        if mesh_stats["angle_min_deg"] < 5:
            issues.append(Issue("warning", f"Kleinster Dreieckswinkel {mesh_stats['angle_min_deg']:.1f}°: "
                                "Netz hat Splitter, Konditionierung der Matrix leidet."))
    return issues


def capability_issues(cfg: dict, caps: dict | None, meta: dict, n_unknowns: int | None) -> list[Issue]:
    """Rules that depend on the installed library build (``worker.cmd_info`` feature probes)."""
    feats = (caps or {}).get("features") or {}
    out: list[Issue] = []
    s = SOLVER.fill(cfg["solver"])
    if s["preconditioner"] == "block_diagonal" and feats.get("block_preconditioner") is False:
        out.append(Issue("error", "Diese SpeckleBem-Version kennt den Block-Diagonal-Vorkonditionierer nicht "
                         "(vor WP-PC1, 2026-10-25): „automatisch“, „Jacobi“ oder „keiner“ wählen oder die "
                         "Bibliothek aktualisieren."))
    if meta.get("termination") == "pml" and feats.get("huygens") is False:
        geom_params = cfg["geometry"].get("params", {})
        if geom_params.get("far_field_source") == "huygens":
            out.append(Issue("error", "Diese SpeckleBem-Version hat keine Huygens-Ebene (vor WP-PML6, 2026-10-20): "
                             "Fernfeld-Quelle „Ströme im Fenster“ wählen oder die Bibliothek aktualisieren."))
    if any(o["type"] == "speckle_statistics" for o in cfg.get("observables", [])) \
            and feats.get("speckle") is False:
        out.append(Issue("error", "Diese SpeckleBem-Version hat kein Speckle-Statistik-Modul (vor WP-S1, "
                         "2026-10-26): Auswertung „Speckle-Statistik“ entfernen oder die Bibliothek aktualisieren."))
    if meta.get("termination") == "pml":
        if not feats.get("pml", True):
            return [Issue("error", "Diese SpeckleBem-Version hat keine PML-Route (Simulation.with_pml).")]
        r = resolve_solver(cfg["solver"], n_unknowns or 0)
        if r["compression"] == "mlfmm" and "pml_mlfmm" in feats:
            if not feats["pml_mlfmm"]:
                out.append(Issue("error", "Diese SpeckleBem-Version rechnet die PML-Route nur dicht (vor WP-PML5a, "
                                 "2026-10-19): Matrix „dicht“ wählen oder die Bibliothek aktualisieren."))
            elif not feats.get("pml_mlfmm_params", True):
                out.append(Issue("warning", "SpeckleBem vor WP-PML5b (2026-10-20): PML mit MLFMM läuft mit "
                                 "Standardwerten und exaktem PML-Ring ohne ACA, also mit deutlich mehr Speicher als "
                                 "geschätzt. Bibliothek auf den aktuellen Stand bringen empfohlen."))
    return out
