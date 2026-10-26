"""Gaussian rough surface patch, meshed by the library, closed by the ADR 0006 box or opened onto a
PML (ADR 0009) - see ``sbgui.heightmap_route`` for the shared map and the two routes.

sigma = 0 gives a flat patch, the validated reference case (reflectance against Fresnel).
"""

from __future__ import annotations

from .. import heightmap_route as hr
from ..base import Geometry, Issue
from ..params import Field
from ..registry import GEOMETRIES


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
        *hr.termination_fields(),
        Field("depth_mode", "Boxtiefe", "choice", "auto", visible_if=lambda v: not hr.is_pml(v),
              choices=(("auto", "automatisch (Bibliothek)"), ("manual", "manuell"))),
        Field("depth", "Boxtiefe (manuell)", "float", 2.0, "µm", min=0.1, max=50.0, step=0.5,
              visible_if=lambda v: not hr.is_pml(v) and v.get("depth_mode") == "manual"),
    )

    @staticmethod
    def zones(p) -> dict:
        return hr.zones(p["L"], p)

    # -- GUI side ----------------------------------------------------------------------------
    def meta_hint(self, p):
        return {**hr.meta_hint(p["L"], p), "rough": True, "flat": p["sigma"] == 0.0}

    def _depth(self, p, rules) -> float:
        if p["depth_mode"] == "manual":
            return p["depth"]
        return float(rules["box_depth"]) if rules and rules.get("box_depth") else hr.FALLBACK_DEPTH

    def resolve(self, p, rules):
        p = dict(p)
        p["depth_estimate"] = self._depth(p, rules)
        return p

    def preview_mesh_size(self, p, h, est_triangles, target=40_000):
        return hr.preview_mesh_size(p["L"], p, h, est_triangles, target)

    def estimate_triangles(self, p, h):
        return hr.estimate_triangles(p["L"], p, h, p.get("depth_estimate") or self._depth(p, None))

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
        if p["sigma"] == 0:
            out.append(Issue("info", "σ = 0: flache Oberfläche. Die DRC-Auswertung zeigt die Fresnel-"
                             "Reflexion als Referenz."))
        out += hr.validate(p["L"], p, ctx, correlation_length=p["Lc"] if p["sigma"] > 0 else 0.0)
        if not hr.is_pml(p):
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
        return out

    # -- worker side ---------------------------------------------------------------------------
    def build_lib(self, sb, p, h, ctx):
        import numpy as np  # noqa: PLC0415

        L = p["L"]
        full = sb.generate_gaussian_height_map(L=L + 2 * p["taper"], sigma=p["sigma"], Lc=p["Lc"], mesh_size=h,
                                               seed=int(p["seed"]))
        z = np.asarray(full.z, dtype=float)
        off, n = round(p["taper"] / full.dx), round(L / full.dx)
        patch = z[off:off + n + 1, off:off + n + 1]
        meta = {"rough": True, "flat": p["sigma"] == 0.0, "seed": int(p["seed"]),
                "sigma_measured": float(np.sqrt(np.mean(patch * patch)))}
        manual = p["depth"] if p["depth_mode"] == "manual" and not hr.is_pml(p) else None
        return hr.build(sb, z, full.dx, L, p, h, ctx, band_sigma=p["sigma"],
                        correlation_length=p["Lc"] if p["sigma"] > 0 else 0.0, manual_depth=manual, meta=meta)
