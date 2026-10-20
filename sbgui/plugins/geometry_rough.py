"""Gaussian rough surface patch, meshed by the library, closed by the ADR 0006 box or opened onto a
PML (ADR 0009, complex coordinate stretching).

The height map is generated once on (L + 2 W_t) x (L + 2 W_t) with the mesh spacing h. The box route
meshes its central L x L crop (``make_mesh_from_height_map`` with the box of
``rough_surface_box_params``); the PML route meshes the whole map with ``make_open_surface_mesh``
(patch L, raised-cosine taper W_t, flat gap and PML). Same seed and h therefore give the same surface on
both routes - the set-up of the library's cross-check 7e (benchmarks/results/pml_si_crosscheck.md).
sigma = 0 gives a flat patch, the validated reference case (reflectance against Fresnel).
"""

from __future__ import annotations

import math

from ..base import Geometry, Issue, LibraryMesh, MeshResult
from ..params import Field
from ..registry import GEOMETRIES

_FALLBACK_DEPTH = 2e-6  # ADR 0006 minimum, only for the size estimate without library rules


def _pml(v):
    return v.get("termination") == "pml"


@GEOMETRIES.register
class RoughSurface(Geometry):
    id = "rough_surface"
    label = "Raue Oberfläche (Gauß)"
    kind = "substrate"
    mesher = "library"
    description = (
        "Quadratisches Gebiet L × L mit gaußscher Rauheit (RMS σ, Korrelationslänge Lc), von der "
        "Bibliothek vernetzt. Abschluss: geschlossene Box (ADR 0006) oder offene Oberfläche mit PML "
        "(ADR 0009). Gleicher Seed und gleiches h ergeben auf beiden Wegen dieselbe Oberfläche. σ = 0 "
        "ergibt eine flache Oberfläche (Referenzfall: Reflexion gegen Fresnel)."
    )
    fields = (
        Field("L", "Kantenlänge L", "float", 4.5, "µm", min=0.5, max=60.0, step=0.5),
        Field("sigma", "RMS-Rauheit σ", "float", 50.0, "nm", min=0.0, max=1000.0, step=5.0),
        Field("Lc", "Korrelationslänge Lc", "float", 500.0, "nm", min=10.0, max=50000.0, step=50.0),
        Field("seed", "Seed (Realisierung)", "int", 1, "-", min=0, max=2**31 - 1, step=1,
              help="Gleicher Seed = gleiche Oberfläche. 0 = zufällig (nicht reproduzierbar)."),
        Field("termination", "Abschluss", "choice", "box",
              choices=(("box", "geschlossene Box (ADR 0006)"), ("pml", "offene Oberfläche mit PML (ADR 0009)"))),
        Field("taper", "Übergangszone W_t", "float", 0.5, "µm", min=0.0, max=10.0, step=0.125,
              help="Höhen gehen per Kosinus auf 0. Bestimmt auch das Generierungsgebiet L + 2 W_t (die Box "
                   "nutzt den mittleren L × L-Ausschnitt). PML-Route: W_t ≥ Lc."),
        Field("gap", "Flache Lücke W_g (PML)", "float", 0.5, "µm", min=0.0, max=10.0, step=0.125,
              visible_if=_pml, help="Validiert: 0,5 µm = λ (Fernfeld-Fenster liegt in der Lücke)."),
        Field("pml_width", "PML-Breite", "float", 1.0, "µm", min=0.125, max=20.0, step=0.125,
              visible_if=_pml, help="Validiert: 2 λ (7b: SPP-Reflexion am Messrauschen)."),
        Field("pml_sigma_max", "PML σ_max", "float", 4.0, "-", min=0.5, max=16.0, step=0.5, visible_if=_pml),
        Field("pml_order", "PML-Profilordnung m", "float", 2.0, "-", min=1.0, max=4.0, step=1.0, visible_if=_pml),
        Field("dark_band", "Dark-Band-Toleranz", "choice", 1e-4, visible_if=_pml,
              choices=((1e-4, "1e-4 (Default)"), (1e-3, "1e-3"), (1e-2, "1e-2 (gelockert)")),
              help="Maximales |E_inc| am PML-Start relativ zum Patch. Wird es überschritten, bricht der Lauf ab "
                   "(Taille verkleinern oder Lücke vergrößern)."),
        Field("grading", "Box-Vernetzung", "choice", "uniform", visible_if=lambda v: not _pml(v),
              choices=(("uniform", "einheitlich (Default, für quantitative Läufe)"),
                       ("graded", "gradiert (billiger, Studien/Konvergenz)"))),
        Field("depth_mode", "Boxtiefe", "choice", "auto", visible_if=lambda v: not _pml(v),
              choices=(("auto", "automatisch (Bibliothek)"), ("manual", "manuell"))),
        Field("depth", "Boxtiefe (manuell)", "float", 2.0, "µm", min=0.1, max=50.0, step=0.5,
              visible_if=lambda v: not _pml(v) and v.get("depth_mode") == "manual"),
    )

    # -- geometry of the zones -----------------------------------------------------------------
    @staticmethod
    def zones(p) -> dict:
        """Half widths [m] of the open surface (patch, taper end, PML start, outer edge)."""
        half = p["L"] / 2
        taper_end = half + p["taper"]
        pml_start = taper_end + p["gap"]
        return {"patch_half": half, "taper_end": taper_end, "pml_start": pml_start,
                "outer_half": pml_start + p["pml_width"]}

    # -- GUI side ----------------------------------------------------------------------------
    def meta_hint(self, p):
        meta = {"kind": "substrate", "lateral_size": float(p["L"]), "rough": True, "flat": p["sigma"] == 0.0,
                "termination": p["termination"]}
        if _pml(p):
            z = self.zones(p)
            meta.update({k: float(v) for k, v in z.items()})
            # region of controlled incident field: 1.02 sqrt(2) pml_start (the unmasked part, library 7a/7e)
            meta["beam_region_radius"] = 1.02 * math.sqrt(2.0) * z["pml_start"]
        return meta

    def _depth(self, p, rules) -> float:
        if p["depth_mode"] == "manual":
            return p["depth"]
        return float(rules["box_depth"]) if rules and rules.get("box_depth") else _FALLBACK_DEPTH

    def resolve(self, p, rules):
        p = dict(p)
        p["depth_estimate"] = self._depth(p, rules)
        return p

    def estimate_triangles(self, p, h):
        if _pml(p):  # one grid over the whole open surface, two triangles per cell
            n = max(1, round(2 * self.zones(p)["outer_half"] / h))
            return int(2 * n * n)
        L, depth = p["L"], p.get("depth_estimate") or self._depth(p, None)
        n = max(1, round(L / h))
        top = 2 * n * n  # structured height-map grid, two triangles per cell
        hc = h if p["grading"] == "uniform" else 4 * h  # graded: coarser walls and bottom (rough guess)
        walls = 4 * 2 * max(1, round(L / hc)) * max(1, round(depth / hc))
        bottom = 2 * max(1, round(L / hc)) ** 2
        return int(top + walls + bottom)

    def validate(self, p, ctx):
        out, h, lam = [], ctx.get("h"), ctx.get("wavelength")
        rules = ctx.get("rules") or {}
        pml = _pml(p)
        if h:
            for name, label in (("L", "L"), ("taper", "W_t")):
                cells = p[name] / h
                if abs(cells - round(cells)) > 1e-6:
                    out.append(Issue("error", f"{label} = {p[name] * 1e6:.4g} µm ist kein Vielfaches von "
                                     f"h = {h * 1e9:.0f} nm (Box und PML teilen ein Gitter)."))
        if p["sigma"] > 0 and p["Lc"] < 2 * (h or 0):
            out.append(Issue("warning", f"Lc = {p['Lc'] * 1e9:.0f} nm ist mit h = {h * 1e9:.0f} nm kaum "
                             "aufgelöst (weniger als 2 Elemente pro Korrelationslänge)."))
        if p["sigma"] > 0 and p["Lc"] > p["L"] / 4:
            out.append(Issue("info", "Lc > L/4: nur wenige Korrelationslängen im Gebiet, die Statistik "
                             "einer Realisierung ist entsprechend grob."))
        if p["seed"] == 0:
            out.append(Issue("info", "Seed 0: die Oberfläche ist bei jedem Lauf anders (nicht reproduzierbar)."))
        if p["sigma"] == 0:
            out.append(Issue("info", "σ = 0: flache Oberfläche. Die DRC-Auswertung zeigt die Fresnel-"
                             "Reflexion als Referenz."))
        if pml:
            out += self._validate_pml(p, ctx, rules)
        else:
            out += self._validate_box(p, rules)
        if p["sigma"] > 0 and not rules.get("plasmonic") and h and lam and h > lam / 20:
            out.append(Issue("info", "Fernfeld rauer Si-Oberflächen ist erst bei feinem Netz konvergiert "
                             "(Bibliothek WP-PML4c: ca. 4 % bei λ/4, 2 % bei λ/6, 0,7 % bei λ/10)."))
        return out

    def _validate_box(self, p, rules):
        out = []
        if p["depth_mode"] == "manual" and rules.get("box_depth") and p["depth"] < 0.999 * rules["box_depth"]:
            out.append(Issue("warning", f"Boxtiefe {p['depth'] * 1e6:.2f} µm liegt unter der Regel der Bibliothek "
                             f"({rules['box_depth'] * 1e6:.2f} µm, ADR 0006): Rückseitenreflexe möglich."))
        if p["depth_mode"] == "auto" and "box_depth_error" in rules:
            out.append(Issue("error", "Die Bibliothek bestimmt für dieses Material keine Boxtiefe "
                             f"({rules['box_depth_error']}). Boxtiefe manuell setzen."))
        if p["sigma"] > 0 and rules.get("plasmonic"):
            out.append(Issue("warning", "Raues plasmonisches Material (Ag) in der Box: die Box-Prüfungen "
                             "der Bibliothek scheitern (0,8–8 %, Oberflächenplasmonen, WP-V3). Ergebnisse "
                             "nicht quantitativ verwenden; dafür den Abschluss „PML“ wählen."))
        elif p["sigma"] > 50.5e-9:  # rule is "sigma <= 50 nm"; nm -> m conversion is not exact
            out.append(Issue("info", "σ > 50 nm: die Bibliothek gibt für die Box ca. 1,2–1,3 % "
                             "Randunsicherheit an (WP-V2b, ADR 0006 vom 2026-10-13)."))
        if p["grading"] == "graded":
            out.append(Issue("info", "Gradierte Box: billiger, aber nur für Studien; quantitative Läufe "
                             "nutzen die einheitliche Box (ADR 0006, 2026-10-12b)."))
        return out

    def _validate_pml(self, p, ctx, rules):
        out, lam = [], ctx.get("wavelength")
        if p["gap"] <= 0:
            out.append(Issue("error", "Die PML-Route braucht eine flache Lücke W_g > 0 (Fernfeld-Fenster)."))
        if p["sigma"] > 0 and p["taper"] < p["Lc"] * (1 - 1e-9):
            out.append(Issue("error", f"W_t = {p['taper'] * 1e6:.3g} µm < Lc = {p['Lc'] * 1e6:.3g} µm: die "
                             "Bibliothek verlangt eine Übergangszone von mindestens einer Korrelationslänge."))
        if lam and p["pml_width"] < 2 * lam * 0.999:
            out.append(Issue("info", f"PML-Breite {p['pml_width'] * 1e6:.3g} µm < 2 λ: validiert ist 2 λ "
                             "(W = λ besteht 7b auch, schwankt aber stark mit σ_max und h)."))
        if (p["pml_sigma_max"], p["pml_order"]) != (4.0, 2.0):
            out.append(Issue("info", "PML-Profil abweichend vom validierten Default σ_max = 4, m = 2."))
        if p["dark_band"] > 1e-4:
            out.append(Issue("info", "Gelockerte Dark-Band-Toleranz: R ändert sich laut Bibliothek kaum "
                             "(≤ 5e-4 bei 1e-2), quantitativ ist 1e-4."))
        if p["sigma"] > 0 and rules.get("plasmonic"):
            out.append(Issue("warning", "Raues Ag auf der PML-Route: das Fernfeld hängt derzeit um 1–3 % vom "
                             "Fenster und der Lücke ab (Oberflächenplasmonen in der Lücke, Bibliothek "
                             "WP-PML4b/7d; Huygens-Ebene WP-PML6 noch offen). Ergebnisse mit L, Lücke und "
                             "Fenster angeben."))
        return out

    # -- worker side ---------------------------------------------------------------------------
    def build_lib(self, sb, p, h, ctx):
        import numpy as np  # noqa: PLC0415

        L, taper = p["L"], p["taper"]
        full = sb.generate_gaussian_height_map(L=L + 2 * taper, sigma=p["sigma"], Lc=p["Lc"], mesh_size=h,
                                               seed=int(p["seed"]))
        z = np.asarray(full.z, dtype=float)
        base = {"kind": "substrate", "lateral_size": float(L), "rough": True, "flat": p["sigma"] == 0.0,
                "seed": int(p["seed"]), "termination": p["termination"]}
        off, n = round(taper / full.dx), round(L / full.dx)
        patch = z[off:off + n + 1, off:off + n + 1]
        base["sigma_measured"] = float(np.sqrt(np.mean(patch * patch)))
        if _pml(p):
            om = sb.make_open_surface_mesh(full, sb.OpenSurfaceParams(
                patch_size=L, taper_width=taper, gap_width=p["gap"], pml_width=p["pml_width"]))
            meta = {**base, **self.meta_hint(p), "open_surface": True,
                    "patch_half": float(om.patch_half), "taper_end": float(om.taper_end),
                    "pml_start": float(om.pml_start), "outer_half": float(om.outer_half)}
            mesh = om.mesh
            res = MeshResult(np.array(mesh.vertices, dtype=float), np.array(mesh.triangles, dtype=np.int64), meta)
            term = {"sigma_max": float(p["pml_sigma_max"]), "order": float(p["pml_order"]),
                    "correlation_length": float(p["Lc"]) if p["sigma"] > 0 else 0.0,
                    "dark_band_tolerance": float(p["dark_band"])}
            return LibraryMesh(res, om, "pml", {"pml": term})

        box = sb.rough_surface_box_params(ctx["object"], ctx["background"], ctx["wavelength"], p["sigma"], h,
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
        mesh = sb.make_mesh_from_height_map(sb.HeightMap(np.ascontiguousarray(patch), full.dx, full.dy), **kw)
        meta = {**base, "depth": float(kw.get("box_depth") or 0.0),
                "box_fine_depth": _opt(kw.get("box_fine_depth")), "box_mesh_size": _opt(kw.get("box_mesh_size")),
                "grading": p["grading"], "uniform_fallback": fallback,
                "beam_waist_fraction": float(box.beam_waist_fraction)}
        res = MeshResult(np.array(mesh.vertices, dtype=float), np.array(mesh.triangles, dtype=np.int64), meta)
        return LibraryMesh(res, mesh, "closed")


def _opt(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
