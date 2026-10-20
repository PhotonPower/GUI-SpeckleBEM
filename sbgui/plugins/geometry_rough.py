"""Gaussian rough surface patch (library mesh): ``sb.RoughSurface`` closed by the box that
``sb.rough_surface_box_params`` chooses from the materials (ADR 0006 with its amendments).

The library makes the mesh inside the worker (``mesher = "library"``); this module only knows the
parameters, a cheap size estimate and the pre-flight rules. sigma = 0 gives a flat patch, the
validated reference case (reflectance against Fresnel, library WP22c).
"""

from __future__ import annotations

import math

from ..base import Geometry, Issue, LibraryMesh, MeshResult
from ..params import Field
from ..registry import GEOMETRIES

_FALLBACK_DEPTH = 2e-6  # ADR 0006 minimum, only for the size estimate without library rules


@GEOMETRIES.register
class RoughSurface(Geometry):
    id = "rough_surface"
    label = "Raue Oberfläche (Gauß)"
    kind = "substrate"
    mesher = "library"
    description = (
        "Quadratisches Gebiet L × L mit gaußscher Rauheit (RMS σ, Korrelationslänge Lc), von der "
        "Bibliothek vernetzt und mit der Box nach ADR 0006 geschlossen. σ = 0 ergibt eine flache "
        "Oberfläche (Referenzfall: Reflexion gegen Fresnel)."
    )
    fields = (
        Field("L", "Kantenlänge L", "float", 4.5, "µm", min=0.5, max=60.0, step=0.5),
        Field("sigma", "RMS-Rauheit σ", "float", 50.0, "nm", min=0.0, max=1000.0, step=5.0),
        Field("Lc", "Korrelationslänge Lc", "float", 500.0, "nm", min=10.0, max=50000.0, step=50.0),
        Field("seed", "Seed (Realisierung)", "int", 1, "-", min=0, max=2**31 - 1, step=1,
              help="Gleicher Seed = gleiche Oberfläche. 0 = zufällig (nicht reproduzierbar)."),
        Field("grading", "Box-Vernetzung", "choice", "uniform",
              choices=(("uniform", "einheitlich (Default, für quantitative Läufe)"),
                       ("graded", "gradiert (billiger, Studien/Konvergenz)"))),
        Field("depth_mode", "Boxtiefe", "choice", "auto",
              choices=(("auto", "automatisch (Bibliothek)"), ("manual", "manuell"))),
        Field("depth", "Boxtiefe (manuell)", "float", 2.0, "µm", min=0.1, max=50.0, step=0.5,
              visible_if=lambda v: v.get("depth_mode") == "manual"),
    )

    # -- GUI side ----------------------------------------------------------------------------
    def meta_hint(self, p):
        return {"kind": "substrate", "lateral_size": float(p["L"]), "rough": True,
                "flat": p["sigma"] == 0.0}

    def _depth(self, p, rules) -> float:
        if p["depth_mode"] == "manual":
            return p["depth"]
        return float(rules["box_depth"]) if rules and rules.get("box_depth") else _FALLBACK_DEPTH

    def resolve(self, p, rules):
        p = dict(p)
        p["depth_estimate"] = self._depth(p, rules)
        return p

    def estimate_triangles(self, p, h):
        L, depth = p["L"], p.get("depth_estimate") or self._depth(p, None)
        n = max(1, round(L / h))
        top = 2 * n * n  # structured height-map grid, two triangles per cell
        hc = h if p["grading"] == "uniform" else max(h, 4 * h)  # graded: coarser walls and bottom (rough)
        walls = 4 * 2 * max(1, round(L / hc)) * max(1, round(depth / hc))
        bottom = 2 * max(1, round(L / hc)) ** 2
        return int(top + walls + bottom)

    def validate(self, p, ctx):
        out, h, lam = [], ctx.get("h"), ctx.get("wavelength")
        rules = ctx.get("rules") or {}
        if p["sigma"] > 0 and p["Lc"] < 2 * (h or 0):
            out.append(Issue("warning", f"Lc = {p['Lc'] * 1e9:.0f} nm ist mit h = {h * 1e9:.0f} nm kaum "
                             "aufgelöst (weniger als 2 Elemente pro Korrelationslänge)."))
        if p["sigma"] > 0 and p["Lc"] > p["L"] / 4:
            out.append(Issue("info", "Lc > L/4: nur wenige Korrelationslängen im Gebiet, die Statistik "
                             "einer Realisierung ist entsprechend grob."))
        if p["seed"] == 0:
            out.append(Issue("info", "Seed 0: die Oberfläche ist bei jedem Lauf anders (nicht reproduzierbar)."))
        if p["depth_mode"] == "manual" and rules.get("box_depth") and p["depth"] < 0.999 * rules["box_depth"]:
            out.append(Issue("warning", f"Boxtiefe {p['depth'] * 1e6:.2f} µm liegt unter der Regel der Bibliothek "
                             f"({rules['box_depth'] * 1e6:.2f} µm, ADR 0006): Rückseitenreflexe möglich."))
        if p["depth_mode"] == "auto" and "box_depth_error" in rules:
            out.append(Issue("error", "Die Bibliothek bestimmt für dieses Material keine Boxtiefe "
                             f"({rules['box_depth_error']}). Boxtiefe manuell setzen."))
        if p["sigma"] == 0:
            out.append(Issue("info", "σ = 0: flache Oberfläche. Die DRC-Auswertung zeigt die Fresnel-"
                             "Reflexion als Referenz."))
        elif rules.get("plasmonic"):
            out.append(Issue("warning", "Raues plasmonisches Material (Ag) in der Box: die Box-Prüfungen "
                             "der Bibliothek scheitern (0,8–8 %, Oberflächenplasmonen, WP-V3). Ergebnisse "
                             "nicht quantitativ verwenden; PML-Route folgt (G12)."))
        else:
            if p["sigma"] > 50.5e-9:  # rule is "sigma <= 50 nm"; nm -> m conversion is not exact
                out.append(Issue("info", "σ > 50 nm: die Bibliothek gibt für die Box ca. 1,2–1,3 % "
                                 "Randunsicherheit an (WP-V2b, ADR 0006 vom 2026-10-13)."))
            if h and lam and h > lam / 20:
                out.append(Issue("info", "Fernfeld rauer Si-Oberflächen ist erst bei feinem Netz konvergiert "
                                 "(Bibliothek WP-PML4c: ca. 4 % bei λ/4, 2 % bei λ/6, 0,7 % bei λ/10)."))
        if p["grading"] == "graded":
            out.append(Issue("info", "Gradierte Box: billiger, aber nur für Studien; quantitative Läufe "
                             "nutzen die einheitliche Box (ADR 0006, 2026-10-12b)."))
        return out

    # -- worker side ---------------------------------------------------------------------------
    def build_lib(self, sb, p, h, ctx):
        lam = ctx["wavelength"]
        box = sb.rough_surface_box_params(ctx["object"], ctx["background"], lam, p["sigma"], h,
                                          grading=p["grading"])
        kw = dict(box.kwargs())
        fallback = bool(getattr(box, "uniform_fallback", False))
        if p["depth_mode"] == "manual":
            kw["box_depth"] = p["depth"]
            fine = kw.get("box_fine_depth")
            if fine is not None and fine >= p["depth"]:
                # same rule as the library's automatic box: a band reaching the bottom plate is
                # dropped, and a graded box becomes uniform (docs/10, rough_surface_box_params)
                kw["box_fine_depth"] = None
                if kw.get("box_mesh_size") is None:
                    kw["box_mesh_size"], fallback = h, True
        surf = sb.RoughSurface(p["L"], p["sigma"], p["Lc"], h, int(p["seed"]), **kw)
        mesh = surf.mesh
        import numpy as np  # noqa: PLC0415

        z = _heights(surf)
        meta = {
            "kind": "substrate", "lateral_size": float(p["L"]), "rough": True,
            "flat": p["sigma"] == 0.0, "depth": float(kw.get("box_depth") or 0.0),
            "box_fine_depth": _opt(kw.get("box_fine_depth")), "box_mesh_size": _opt(kw.get("box_mesh_size")),
            "grading": p["grading"], "uniform_fallback": fallback,
            "beam_waist_fraction": float(box.beam_waist_fraction),
            "sigma_measured": float(np.sqrt(np.mean(z * z))), "seed": int(p["seed"]),
        }

        res = MeshResult(np.array(mesh.vertices, dtype=float), np.array(mesh.triangles, dtype=np.int64), meta)
        return LibraryMesh(res, mesh, "closed")


def _opt(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _heights(surf):
    """Height samples as an array; ``height_map`` / ``heights`` are an ndarray or a ``HeightMap``
    (with ``.z``) depending on the binding (docs/10 and the build disagree)."""
    import numpy as np  # noqa: PLC0415

    for name in ("height_map", "heights"):
        v = getattr(surf, name, None)
        if v is None:
            continue
        v = getattr(v, "z", v)
        try:
            return np.asarray(v, dtype=float)
        except (TypeError, ValueError):
            continue
    raise RuntimeError("RoughSurface liefert keine Höhenwerte")
