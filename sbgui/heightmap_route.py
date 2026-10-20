"""Box or PML termination of a surface given as a library height map (rough surface, line/trench).

The height map is sampled on (L + 2 W_t) x (L + 2 W_t) with the mesh spacing h. The box route meshes
its central L x L crop (``make_mesh_from_height_map`` with the box of ``rough_surface_box_params``,
ADR 0006); the PML route meshes the whole map with ``make_open_surface_mesh`` (patch L, raised-cosine
taper W_t, flat gap, PML; ADR 0009). Same map -> same patch on both routes (library cross-check 7e).

Frame: library frame, light in +z, object at z > xi(x, y); a ridge has xi < 0, a trench xi > 0.
GUI side (fields, zones, estimates, rules) is pure Python; ``build`` runs in the worker.
"""

from __future__ import annotations

import math

from .base import Issue, LibraryMesh, MeshResult
from .params import Field

FALLBACK_DEPTH = 2e-6  # ADR 0006 minimum, only for size estimates without library rules


def is_pml(v) -> bool:
    return v.get("termination") == "pml"


def termination_fields(visible=lambda v: True) -> tuple[Field, ...]:
    """Fields of the termination; ``visible`` gates all of them (e.g. only when the library meshes)."""
    def pml(v):
        return visible(v) and is_pml(v)

    def box(v):
        return visible(v) and not is_pml(v)

    return (
        Field("termination", "Abschluss", "choice", "box", visible_if=visible,
              choices=(("box", "geschlossene Box (ADR 0006)"), ("pml", "offene Oberfläche mit PML (ADR 0009)"))),
        Field("taper", "Übergangszone W_t", "float", 0.5, "µm", min=0.0, max=10.0, step=0.125, visible_if=visible,
              help="Höhen gehen per Kosinus auf 0. Bestimmt auch das Generierungsgebiet L + 2 W_t (die Box "
                   "nutzt den mittleren L × L-Ausschnitt). PML-Route bei Rauheit: W_t ≥ Lc."),
        Field("gap", "Flache Lücke W_g (PML)", "float", 0.5, "µm", min=0.0, max=10.0, step=0.125,
              visible_if=pml, help="Validiert: 0,5 µm = λ (Fernfeld-Fenster liegt in der Lücke)."),
        Field("pml_width", "PML-Breite", "float", 1.0, "µm", min=0.125, max=20.0, step=0.125,
              visible_if=pml, help="Validiert: 2 λ (7b: SPP-Reflexion am Messrauschen)."),
        Field("pml_sigma_max", "PML σ_max", "float", 4.0, "-", min=0.5, max=16.0, step=0.5, visible_if=pml),
        Field("pml_order", "PML-Profilordnung m", "float", 2.0, "-", min=1.0, max=4.0, step=1.0, visible_if=pml),
        Field("dark_band", "Dark-Band-Toleranz", "choice", 1e-4, visible_if=pml,
              choices=((1e-4, "1e-4 (Default)"), (1e-3, "1e-3"), (1e-2, "1e-2 (gelockert)")),
              help="Maximales |E_inc| am PML-Start relativ zum Patch. Wird es überschritten, bricht der Lauf ab "
                   "(Taille verkleinern oder Lücke vergrößern)."),
        Field("grading", "Box-Vernetzung", "choice", "uniform", visible_if=box,
              choices=(("uniform", "einheitlich (Default, für quantitative Läufe)"),
                       ("graded", "gradiert (billiger, Studien/Konvergenz)"))),
    )


def grid_lengths(L: float, p) -> list[float]:
    """Lengths that must be whole multiples of the grid spacing (patch, taper; gap and PML on the PML route)."""
    out = [L, p["taper"]]
    if is_pml(p):
        out += [p["gap"], p["pml_width"]]
    return [x for x in out if x > 0]


def preview_mesh_size(L: float, p, h: float, est_triangles: int | None, target: int = 40_000) -> float:
    """Coarser preview spacing k h with an integer k that keeps every ``grid_lengths`` on the grid: the
    smallest divisor k of their common cell count with k >= the wanted factor (else the largest one)."""
    want = max(1.0, (est_triangles / target) ** 0.5) if est_triangles else 1.0
    if want <= 1.0:
        return h
    lengths = grid_lengths(L, p)
    cells = [round(x / h) for x in lengths]
    if any(abs(x / h - c) > 1e-6 or c == 0 for x, c in zip(lengths, cells, strict=True)):
        return h  # not on the grid anyway: the pre-flight check reports it, keep h
    g = math.gcd(*cells)
    divisors = [k for k in range(1, g + 1) if g % k == 0]
    k = next((k for k in divisors if k >= want), divisors[-1])
    return h * k


def zones(L: float, p) -> dict:
    """Half widths [m] of the open surface (patch, taper end, PML start, outer edge)."""
    half = L / 2
    taper_end = half + p["taper"]
    pml_start = taper_end + p["gap"]
    return {"patch_half": half, "taper_end": taper_end, "pml_start": pml_start,
            "outer_half": pml_start + p["pml_width"]}


def meta_hint(L: float, p) -> dict:
    meta = {"kind": "substrate", "lateral_size": float(L), "termination": p.get("termination", "box")}
    if is_pml(p):
        z = zones(L, p)
        meta.update({k: float(v) for k, v in z.items()})
        # region of controlled incident field: 1.02 sqrt(2) pml_start (the unmasked part, library 7a/7e)
        meta["beam_region_radius"] = 1.02 * math.sqrt(2.0) * z["pml_start"]
    return meta


def estimate_triangles(L: float, p, h: float, depth: float) -> int:
    if is_pml(p):  # one grid over the whole open surface, two triangles per cell
        n = max(1, round(2 * zones(L, p)["outer_half"] / h))
        return int(2 * n * n)
    n = max(1, round(L / h))
    hc = h if p.get("grading", "uniform") == "uniform" else 4 * h  # graded: coarser walls/bottom (rough guess)
    walls = 4 * 2 * max(1, round(L / hc)) * max(1, round(depth / hc))
    return int(2 * n * n + walls + 2 * max(1, round(L / hc)) ** 2)


def validate(L: float, p, ctx, *, correlation_length: float = 0.0, lc_label: str = "Lc") -> list[Issue]:
    """Grid and termination rules shared by all height-map surfaces."""
    out, h, lam = [], ctx.get("h"), ctx.get("wavelength")
    rules = ctx.get("rules") or {}
    if h:
        for value, label in ((L, "L"), (p["taper"], "W_t")):
            cells = value / h
            if abs(cells - round(cells)) > 1e-6:
                out.append(Issue("error", f"{label} = {value * 1e6:.4g} µm ist kein Vielfaches von "
                                 f"h = {h * 1e9:.0f} nm (Box und PML teilen ein Gitter)."))
    if not is_pml(p):
        if p.get("grading") == "graded":
            out.append(Issue("info", "Gradierte Box: billiger, aber nur für Studien; quantitative Läufe "
                             "nutzen die einheitliche Box (ADR 0006, 2026-10-12b)."))
        return out
    if p["gap"] <= 0:
        out.append(Issue("error", "Die PML-Route braucht eine flache Lücke W_g > 0 (Fernfeld-Fenster)."))
    if correlation_length > 0 and p["taper"] < correlation_length * (1 - 1e-9):
        out.append(Issue("error", f"W_t = {p['taper'] * 1e6:.3g} µm < {lc_label} = {correlation_length * 1e6:.3g} µm: "
                         "die Bibliothek verlangt eine Übergangszone von mindestens einer Korrelationslänge "
                         "(ADR 0009, Entscheidung 1)."))
    if lam and p["pml_width"] < 2 * lam * 0.999:
        out.append(Issue("info", f"PML-Breite {p['pml_width'] * 1e6:.3g} µm < 2 λ: validiert ist 2 λ "
                         "(W = λ besteht 7b auch, schwankt aber stark mit σ_max und h)."))
    if (p["pml_sigma_max"], p["pml_order"]) != (4.0, 2.0):
        out.append(Issue("info", "PML-Profil abweichend vom validierten Default σ_max = 4, m = 2."))
    if p["dark_band"] > 1e-4:
        out.append(Issue("info", "Gelockerte Dark-Band-Toleranz: R ändert sich laut Bibliothek kaum "
                         "(≤ 5e-4 bei 1e-2), quantitativ ist 1e-4."))
    if rules.get("plasmonic"):
        out.append(Issue("info", "Ag auf der PML-Route: flache Oberflächen sind validiert (7a); bei Struktur "
                         "hängt das Fernfeld um 1–3 % vom Fenster ab (Oberflächenplasmonen in der Lücke, "
                         "WP-PML4b/7d; Huygens-Ebene WP-PML6 offen)."))
    return out


def build(sb, z_full, dx: float, L: float, p, h: float, ctx, *, band_sigma: float, correlation_length: float = 0.0,
          extra_depth: float = 0.0, manual_depth: float | None = None, meta: dict | None = None) -> LibraryMesh:
    """Worker side: mesh ``z_full`` (library frame, (n+1) x (n+1) nodes on L + 2 W_t, spacing dx).

    band_sigma: amplitude used for the box's fine band (3 delta + 3 sigma); extra_depth is added to the
    library's box depth (a trench reaches below z = 0); manual_depth replaces both."""
    import numpy as np  # noqa: PLC0415

    z_full = np.ascontiguousarray(np.asarray(z_full, dtype=float))
    for x in grid_lengths(L, p):
        if abs(x / dx - round(x / dx)) > 1e-6:
            raise ValueError(f"Gitterweite {dx * 1e9:.2f} nm passt nicht zu L/W_t/W_g/PML ({x * 1e6:.4g} µm ist "
                             "kein ganzes Vielfaches); h so wählen, dass alle Längen Vielfache von h sind.")
    off, n = round(p["taper"] / dx), round(L / dx)
    patch = z_full[off:off + n + 1, off:off + n + 1]
    base = {**meta_hint(L, p), **(meta or {}), "z_min": float(patch.min()), "z_max": float(patch.max())}
    full = sb.HeightMap(z_full, dx, dx)
    if is_pml(p):
        om = sb.make_open_surface_mesh(full, sb.OpenSurfaceParams(
            patch_size=L, taper_width=p["taper"], gap_width=p["gap"], pml_width=p["pml_width"]))
        info = {**base, "open_surface": True, "patch_half": float(om.patch_half), "taper_end": float(om.taper_end),
                "pml_start": float(om.pml_start), "outer_half": float(om.outer_half)}
        mesh = om.mesh
        res = MeshResult(np.array(mesh.vertices, dtype=float), np.array(mesh.triangles, dtype=np.int64), info)
        term = {"sigma_max": float(p["pml_sigma_max"]), "order": float(p["pml_order"]),
                "correlation_length": float(correlation_length), "dark_band_tolerance": float(p["dark_band"])}
        return LibraryMesh(res, om, "pml", {"pml": term})

    grading = p.get("grading", "uniform")
    box = sb.rough_surface_box_params(ctx["object"], ctx["background"], ctx["wavelength"], band_sigma, h,
                                      grading=grading)
    kw = dict(box.kwargs())
    fallback = bool(getattr(box, "uniform_fallback", False))
    if manual_depth is not None:
        kw["box_depth"] = manual_depth
    elif extra_depth:
        kw["box_depth"] = float(kw["box_depth"]) + extra_depth
        if kw.get("box_fine_depth") is not None:
            kw["box_fine_depth"] = float(kw["box_fine_depth"]) + extra_depth
    fine = kw.get("box_fine_depth")
    if fine is not None and fine >= kw["box_depth"]:
        # same rule as the library's automatic box: a band reaching the bottom plate is dropped, and a
        # graded box becomes uniform (docs/10, rough_surface_box_params)
        kw["box_fine_depth"] = None
        if kw.get("box_mesh_size") is None:
            kw["box_mesh_size"], fallback = h, True
    mesh = sb.make_mesh_from_height_map(sb.HeightMap(np.ascontiguousarray(patch), dx, dx), **kw)
    info = {**base, "depth": float(kw["box_depth"]), "box_fine_depth": _opt(kw.get("box_fine_depth")),
            "box_mesh_size": _opt(kw.get("box_mesh_size")), "grading": grading, "uniform_fallback": fallback,
            "beam_waist_fraction": float(box.beam_waist_fraction)}
    res = MeshResult(np.array(mesh.vertices, dtype=float), np.array(mesh.triangles, dtype=np.int64), info)
    return LibraryMesh(res, mesh, "closed")


def _opt(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
