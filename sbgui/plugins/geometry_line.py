"""Isolated line (ridge) or trench on a flat substrate: sidewall angle, rounded corners, depth.

The cross-section is extruded along y over the whole patch, so the feature is "infinitely
long but finitely illuminated" (the beam waist must stay well inside Ly, see the excitation
checks). Two meshers:

- "gui" (default): gmsh/numpy mesh with exact profile edges, closed by a uniform ADR 0006 box.
- "library": the profile sampled onto the library's height-map grid (spacing h) on a square patch
  L = Lx, then the shared box (uniform or graded, fine band) or PML termination of
  ``sbgui.heightmap_route``. Walls and roundings are only resolved down to the grid spacing.
"""

from __future__ import annotations

import math

from .. import heightmap_route as hr
from ..base import Geometry, Issue, MeshResult
from ..meshing.extrude import extruded_profile_box
from ..meshing.profile2d import line_profile, polygon_area
from ..params import Field
from ..registry import GEOMETRIES

_FALLBACK_DEPTH = 2e-6  # ADR 0006 minimum, used when the library rules are not available


def _lib(v):
    return v.get("meshing") == "library"


@GEOMETRIES.register
class IsolatedLine(Geometry):
    id = "isolated_line"
    label = "Isolierter Steg / Graben"
    kind = "substrate"
    description = (
        "Querschnitt mit Seitenwandwinkel und Rundungen an Ober- und Unterkante, entlang y "
        "extrudiert. CD = Breite auf halber Höhe. Seitenwandwinkel < 90° heißt: breiter an der "
        "Substratebene (Steg-Fuß bzw. Graben-Öffnung)."
    )
    fields = (
        Field("feature", "Typ", "choice", "ridge", choices=(("ridge", "Steg (ragt in die Luft)"),
                                                            ("trench", "Graben (eingeätzt)"))),
        Field("cd", "CD (Breite auf halber Höhe)", "float", 200.0, "nm", min=20.0, max=20000.0, step=10.0),
        Field("height", "Höhe bzw. Tiefe", "float", 100.0, "nm", min=5.0, max=5000.0, step=5.0),
        Field("swa", "Seitenwandwinkel", "float", 85.0, "deg", min=45.0, max=90.0, step=1.0,
              help="90° = senkrecht. Gemessen gegen die Substratebene."),
        Field("r_top", "Rundung Oberkante", "float", 10.0, "nm", min=0.0, max=2000.0, step=1.0,
              help="Steg: Kopfkanten. Graben: Öffnungskanten."),
        Field("r_bottom", "Rundung Unterkante", "float", 10.0, "nm", min=0.0, max=2000.0, step=1.0,
              help="Steg: Fußkehle. Graben: Bodenkanten."),
        Field("meshing", "Vernetzung", "choice", "gui",
              choices=(("gui", "GUI (gmsh): exakte Kanten, einheitliche Box"),
                       ("library", "Höhenkarte der Bibliothek: Box gradiert/Feinband oder PML")),
              help="Höhenkarte: das Profil wird auf das Gitter (Abstand h) abgetastet; Flanken und Rundungen "
                   "sind nur bis zur Gitterweite aufgelöst. Dafür gibt es Box-Gradierung und den PML-Abschluss."),
        Field("Lx", "Gebiet quer zur Linie (Lx)", "float", 4.0, "µm", min=0.5, max=100.0, step=0.5,
              help="Bei Vernetzung über die Höhenkarte: Kantenlänge L des quadratischen Gebiets."),
        Field("Ly", "Gebiet entlang der Linie (Ly)", "float", 4.0, "µm", min=0.5, max=100.0, step=0.5,
              visible_if=lambda v: not _lib(v)),
        *hr.termination_fields(visible=_lib),
        Field("depth_mode", "Substrattiefe", "choice", "auto", visible_if=lambda v: not (_lib(v) and hr.is_pml(v)),
              choices=(("auto", "automatisch (ADR 0006)"), ("manual", "manuell"))),
        Field("depth", "Substrattiefe (manuell)", "float", 2.0, "µm", min=0.1, max=50.0, step=0.5,
              visible_if=lambda v: v.get("depth_mode") == "manual" and not (_lib(v) and hr.is_pml(v))),
        Field("refine_profile", "Verfeinerung am Profil (Faktor auf h)", "float", 1.0, "-",
              min=0.2, max=1.0, step=0.1, visible_if=lambda v: not _lib(v),
              help="1 = einheitliches Netz (empfohlen für quantitative Läufe), <1 = feiner am Profil."),
    )

    def mesher_for(self, p):
        return "library" if _lib(p) else "gui"

    # -- helpers ---------------------------------------------------------------------------
    def resolve(self, p, rules):
        p = dict(p)
        if p["depth_mode"] == "auto":
            base = float(rules["box_depth"]) if rules and rules.get("box_depth") else _FALLBACK_DEPTH
            p["depth"] = base + (p["height"] if p["feature"] == "trench" else 0.0)
        return p

    @staticmethod
    def r_min(h_profile):
        """Smallest rounding that can be meshed robustly: its chord must stay >= h_profile / 8."""
        return h_profile / 10.0

    def _profile(self, p, h_profile):
        """Profile polyline sampled for mesh size ``h_profile`` (arcs: chords <= h_profile / 2)."""
        # p is in SI: swa is already in radians
        for name in ("r_top", "r_bottom"):
            if 0 < p[name] < self.r_min(h_profile):
                raise ValueError(
                    f"Rundung {p[name] * 1e9:.1f} nm ist bei der Profil-Netzweite "
                    f"{h_profile * 1e9:.0f} nm nicht abbildbar (Minimum {self.r_min(h_profile) * 1e9:.1f} nm). "
                    "Radius auf 0 setzen, vergrößern oder h bzw. den Verfeinerungsfaktor verkleinern.")
        return line_profile(p["feature"], p["cd"], p["height"], p["swa"],
                            p["r_top"], p["r_bottom"], p["Lx"], h_profile / 2)

    # -- plugin interface ------------------------------------------------------------------
    def validate(self, p, ctx):
        if _lib(p):
            return self._validate_lib(p, ctx)
        out, h = [], ctx.get("h")
        try:
            self._profile(p, (h or p["cd"] / 10) * p["refine_profile"])
        except ValueError as e:
            return [Issue("error", str(e))]
        if h:
            if p["cd"] < 4 * h:
                out.append(Issue("warning", f"CD = {p['cd'] * 1e9:.0f} nm ist nur mit {p['cd'] / h:.1f} "
                                 "Elementen aufgelöst; Netzweite verkleinern."))
            if p["height"] < h:
                out.append(Issue("warning", "Höhe kleiner als die Netzweite: Flanken sind nicht aufgelöst."))
            hp = h * p["refine_profile"]
            small = [r for r in (p["r_top"], p["r_bottom"]) if 0 < r < hp]
            if small:
                out.append(Issue("warning", f"Rundung {min(small) * 1e9:.0f} nm < Profil-Netzweite "
                                 f"{hp * 1e9:.0f} nm: sie wird nur als Fase/grobe Sehne abgebildet. "
                                 "Für aufgelöste Rundungen 'Verfeinerung am Profil' verkleinern "
                                 "(mehr Unbekannte)."))
        rules = ctx.get("rules") or {}
        if p["depth_mode"] == "auto" and "box_depth_error" in rules:
            out.append(Issue("info", "Boxtiefe nicht automatisch bestimmbar (verlustfreies Substrat); "
                             "es werden 2 µm angesetzt. Tiefe ggf. manuell prüfen."))
        if p["Ly"] < p["Lx"] / 2:
            out.append(Issue("info", "Ly deutlich kleiner als Lx: die Linie ist dann kurz; Randeffekte "
                             "am Ende des Gebiets nehmen zu."))
        return out

    def _validate_lib(self, p, ctx):
        out, h = [], ctx.get("h")
        rules = ctx.get("rules") or {}
        try:
            self._profile(p, max(p["cd"] / 40, 1e-9))
        except ValueError as e:
            return [Issue("error", str(e))]
        # the library treats a structured patch as rough and checks W_t >= Lc; the line's lateral scale is its CD
        out += hr.validate(p["Lx"], p, ctx, correlation_length=p["cd"], lc_label="CD (als Lc)")
        if h:
            if p["cd"] < 4 * h:
                out.append(Issue("warning", f"CD = {p['cd'] * 1e9:.0f} nm ist nur mit {p['cd'] / h:.1f} "
                                 "Gitterpunkten abgetastet; Netzweite verkleinern."))
            run = p["height"] / math.tan(p["swa"]) if p["swa"] < math.pi / 2 - 1e-9 else 0.0
            if run < h:
                eff = math.degrees(math.atan2(p["height"], h))
                out.append(Issue("warning", f"Höhenkarte: die Flanke liegt innerhalb einer Gitterzelle "
                                 f"(h = {h * 1e9:.0f} nm) und wird zur Schräge mit ca. {eff:.0f}° statt "
                                 f"{math.degrees(p['swa']):.0f}°. Für exakte Flanken die GUI-Vernetzung nutzen."))
            small = [r for r in (p["r_top"], p["r_bottom"]) if 0 < r < h]
            if small:
                out.append(Issue("info", f"Rundungen unter h = {h * 1e9:.0f} nm sind auf der Höhenkarte "
                                 "nicht sichtbar."))
        if not hr.is_pml(p):
            if p["depth_mode"] == "auto" and "box_depth_error" in rules:
                out.append(Issue("error", "Die Bibliothek bestimmt für dieses Material keine Boxtiefe "
                                 f"({rules['box_depth_error']}). Tiefe manuell setzen."))
            if rules.get("plasmonic"):
                out.append(Issue("warning", "Ag mit Struktur in der Box: die Box-Prüfungen der Bibliothek "
                                 "scheitern bei Struktur (Oberflächenplasmonen, WP-V3); dafür den Abschluss "
                                 "„PML“ wählen."))
        else:
            out.append(Issue("info", "PML-Route: die Linie endet in y in der Übergangszone (Höhen gehen per "
                             "Kosinus auf 0), wie an der Boxwand der GUI-Vernetzung."))
        return out

    def meta_hint(self, p):
        if _lib(p):
            return {**hr.meta_hint(p["Lx"], p), "feature": p["feature"]}
        return {"kind": "substrate", "lateral_size": float(min(p["Lx"], p["Ly"]))}

    def preview_mesh_size(self, p, h, est_triangles, target=40_000):
        if _lib(p):
            return hr.preview_mesh_size(p["Lx"], p, h, est_triangles, target)
        return super().preview_mesh_size(p, h, est_triangles, target)

    def estimate_triangles(self, p, h):
        if _lib(p):
            return hr.estimate_triangles(p["Lx"], p, h, p.get("depth") or _FALLBACK_DEPTH)
        depth = p.get("depth") or _FALLBACK_DEPTH
        Lx, Ly = p["Lx"], p["Ly"]
        area = 2 * Lx * Ly + 2 * Ly * depth + 2 * Lx * depth + 4 * p["height"] * (Lx + Ly) / 2
        return int(1.1 * area / (0.433 * h * h))

    def build(self, p, h):
        hp = h * p["refine_profile"]
        prof = self._profile(p, hp)
        v, f = extruded_profile_box(prof, p["Ly"], p["depth"], h, hp)
        meta = {"kind": "substrate", "lateral_size": float(min(p["Lx"], p["Ly"])),
                "feature": p["feature"], "depth": float(p["depth"]),
                "profile_area": polygon_area(prof)}
        return MeshResult(v, f, meta)

    def build_lib(self, sb, p, h, ctx):
        """Profile sampled onto the height-map grid (library frame: xi = -z_phys), constant along y."""
        import numpy as np  # noqa: PLC0415

        L, taper = p["Lx"], p["taper"]
        n = round((L + 2 * taper) / h)
        dx = (L + 2 * taper) / n
        x = -0.5 * (L + 2 * taper) + dx * np.arange(n + 1)
        prof = self._profile(p, max(min(h, p["cd"]) / 20, 1e-9))
        xp = prof[:, 0] + np.arange(len(prof)) * 1e-15  # vertical walls: keep xp strictly increasing
        z_phys = np.interp(x, xp, prof[:, 1], left=0.0, right=0.0)
        z = np.repeat(-z_phys[:, None], n + 1, axis=1)  # z[i, j] at (x_i, y_j): the line runs along y
        trench = p["feature"] == "trench"
        manual = p["depth"] if p["depth_mode"] == "manual" and not hr.is_pml(p) else None
        meta = {"feature": p["feature"], "profile_area": polygon_area(prof)}
        return hr.build(sb, z, dx, L, p, h, ctx, band_sigma=p["height"] / 3, correlation_length=p["cd"],
                        extra_depth=p["height"] if trench else 0.0, manual_depth=manual, meta=meta)

    def outline(self, p):
        try:
            prof = line_profile(p["feature"], p["cd"], p["height"], p["swa"], p["r_top"],
                                p["r_bottom"], p["Lx"], max(p["cd"] / 40, 1e-9), min_arc_points=6)
        except ValueError:
            return None
        return {"x": prof[:, 0].tolist(), "z": prof[:, 1].tolist(),
                "title": "Profil (Luft oben, Substrat unten)"}
