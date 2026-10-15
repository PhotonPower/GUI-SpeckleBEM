"""Isolated line (ridge) or trench on a flat substrate: sidewall angle, rounded corners, depth.

The cross-section is extruded along y over the whole patch, so the feature is "infinitely
long but finitely illuminated" (the beam waist must stay well inside Ly, see the excitation
checks). The patch is closed by side walls and a bottom plate (ADR 0006 box).
"""

from __future__ import annotations

from ..base import Geometry, Issue, MeshResult
from ..meshing.extrude import extruded_profile_box
from ..meshing.profile2d import line_profile, polygon_area
from ..params import Field
from ..registry import GEOMETRIES

_FALLBACK_DEPTH = 2e-6  # ADR 0006 minimum, used when the library rules are not available


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
        Field("Lx", "Gebiet quer zur Linie (Lx)", "float", 4.0, "µm", min=0.5, max=100.0, step=0.5),
        Field("Ly", "Gebiet entlang der Linie (Ly)", "float", 4.0, "µm", min=0.5, max=100.0, step=0.5),
        Field("depth_mode", "Substrattiefe", "choice", "auto",
              choices=(("auto", "automatisch (ADR 0006)"), ("manual", "manuell"))),
        Field("depth", "Substrattiefe (manuell)", "float", 2.0, "µm", min=0.1, max=50.0, step=0.5,
              visible_if=lambda v: v.get("depth_mode") == "manual"),
        Field("refine_profile", "Verfeinerung am Profil (Faktor auf h)", "float", 1.0, "-",
              min=0.2, max=1.0, step=0.1,
              help="1 = einheitliches Netz (empfohlen für quantitative Läufe), <1 = feiner am Profil."),
    )

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

    def meta_hint(self, p):
        return {"kind": "substrate", "lateral_size": float(min(p["Lx"], p["Ly"]))}

    def estimate_triangles(self, p, h):
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

    def outline(self, p):
        try:
            prof = line_profile(p["feature"], p["cd"], p["height"], p["swa"], p["r_top"],
                                p["r_bottom"], p["Lx"], max(p["cd"] / 40, 1e-9), min_arc_points=6)
        except ValueError:
            return None
        return {"x": prof[:, 0].tolist(), "z": prof[:, 1].tolist(),
                "title": "Profil (Luft oben, Substrat unten)"}
