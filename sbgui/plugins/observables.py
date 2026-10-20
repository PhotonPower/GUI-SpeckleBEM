"""Observables. ``compute`` runs in the worker (gets ``sb`` and the solved ``sim``) and returns
plain numpy arrays / floats / strings, which go to ``results.npz``. ``figures`` runs in the GUI
and builds Plotly figures from those arrays; it must not need the library."""

from __future__ import annotations

import math

import numpy as np

from ..base import Observable
from ..params import Field
from ..registry import OBSERVABLES

ETA0 = 376.730313668  # vacuum impedance [Ohm]


@OBSERVABLES.register
class BistaticRCS(Observable):
    id = "bistatic_rcs"
    label = "Bistatischer Streuquerschnitt (Körper)"
    description = "σ(θ) in einer Schnittebene und C_sca; bei Kugel automatischer Vergleich mit Mie."
    applies_to = ("object",)
    fields = (
        Field("n_theta", "Winkelpunkte", "int", 181, "-", min=19, max=1441, step=10),
        Field("plane", "Schnittebene", "choice", "xz", choices=(("xz", "xz (E-Ebene)"), ("yz", "yz (H-Ebene)"))),
    )

    def compute(self, sb, sim, p, ctx):
        theta = np.linspace(0.0, math.pi, int(p["n_theta"]))
        out = {"theta": theta, "sigma": np.asarray(sim.bistatic_rcs(theta, plane=p["plane"]), dtype=float)}
        try:  # C_sca = P_sca / (|E0|^2 / (2 eta_1)), |E0| = 1 V/m for the library plane wave
            P = float(sim.scattered_power(64, 128))
            out["C_sca"] = P * 2.0 * ETA0 / ctx["n_background"]
        except Exception as e:  # noqa: BLE001 - e.g. lossy background; keep the RCS
            out["C_sca_error"] = str(e)
        ref = ctx["meta"].get("mie_sphere")
        if ref:
            mie = sb.Mie(radius=ref["radius"], wavelength=ctx["wavelength"], material=ctx["object"],
                         exterior=ctx["background"])
            phi = 0.0 if p["plane"] == "xz" else math.pi / 2
            out["sigma_mie"] = np.asarray(mie.bistatic_rcs(theta, phi), dtype=float)
            out["C_sca_mie"] = float(mie.scattering_cross_section())
            out["rel_l2_error"] = float(np.linalg.norm(out["sigma"] - out["sigma_mie"])
                                        / np.linalg.norm(out["sigma_mie"]))
        return out

    def figures(self, data, ctx):
        import plotly.graph_objects as go  # noqa: PLC0415

        th = np.degrees(data["theta"])
        fig = go.Figure(go.Scatter(x=th, y=data["sigma"], name="BEM", mode="lines"))
        if "sigma_mie" in data:
            fig.add_trace(go.Scatter(x=th, y=data["sigma_mie"], name="Mie", mode="lines",
                                     line={"dash": "dash"}))
        fig.update_layout(title="Bistatischer Streuquerschnitt", xaxis_title="Streuwinkel θ [°]",
                          yaxis_title="σ [m²]", yaxis_type="log", height=420)
        return [fig]

    @staticmethod
    def summary(data) -> dict:
        s = {}
        if "C_sca" in data:
            s["C_sca [m²]"] = float(data["C_sca"])
        if "C_sca_mie" in data:
            s["C_sca Mie [m²]"] = float(data["C_sca_mie"])
            s["rel. L2-Abweichung σ(θ) vs. Mie"] = float(data["rel_l2_error"])
        return s


def fresnel_reflectance(n1: complex, n2: complex, theta: float, pol: str) -> float:
    """Plane-wave power reflectance |r|^2 of the flat interface n1 -> n2 at angle theta (from the
    normal, in n1). Same value for n - jk and n + jk (|r|^2 is invariant under conjugation)."""
    n1, n2 = complex(n1), complex(n2)
    c1 = math.cos(theta)
    s2 = n1 * math.sin(theta) / n2
    c2 = np.sqrt(1 - s2 * s2 + 0j)
    if c2.imag > 0:  # decaying branch, whichever sign convention n2 uses
        c2 = -c2
    c2 = c2 if c2.real >= 0 else -c2
    if pol == "s":
        r = (n1 * c1 - n2 * c2) / (n1 * c1 + n2 * c2)
    else:
        r = (n2 * c1 - n1 * c2) / (n2 * c1 + n1 * c2)
    return float(abs(r) ** 2)


@OBSERVABLES.register
class DrcHemisphere(Observable):
    id = "drc_hemisphere"
    label = "Winkelaufgelöste Reflexion (DRC, Struktur)"
    description = ("Differentieller Reflexionskoeffizient pro Steradiant über die Reflexionshalbkugel "
                   "(k_z < 0) und Reflektanz R. Beugungsordnungen erscheinen als Maxima.")
    applies_to = ("substrate",)
    fields = (
        Field("n_theta", "Polarwinkel-Knoten", "int", 60, "-", min=8, max=360, step=4),
        Field("n_phi", "Azimut-Knoten", "int", 120, "-", min=8, max=720, step=4),
        Field("r_check", "R-Kreuzcheck mit der Bibliothek (1°-Gitter)", "bool", False,
              help="Zusätzlich sim.reflectance(90, 180): Reflexion auf dem 1°-Gauß-Legendre-Gitter der "
                   "Bibliothek. Kostet etwa eine zweite Fernfeld-Auswertung."),
    )

    def compute(self, sb, sim, p, ctx):
        g = sb.hemisphere_grid(-1, int(p["n_theta"]), int(p["n_phi"]))
        d = np.asarray(g.directions, dtype=float)
        D = np.asarray(sim.drc(d), dtype=float)
        out = {"directions": d, "weights": np.asarray(g.weights, dtype=float), "D": D,
               "reflectance": float(np.asarray(g.weights) @ D), "n_theta": int(p["n_theta"]),
               "n_phi": int(p["n_phi"])}
        pol = ctx.get("co_pol")
        if pol is not None:
            co, cross = sim.drc(d, co_pol=list(pol))
            out["D_co"], out["D_cross"] = np.asarray(co, dtype=float), np.asarray(cross, dtype=float)
        try:  # beams only; a plane wave has infinite power (RuntimeError)
            out["P_inc"] = float(sim.incident_power())
        except Exception as e:  # noqa: BLE001
            out["P_inc_error"] = str(e)
        if p.get("r_check") and "P_inc" in out:
            out["R_library"] = float(sim.reflectance(90, 180))
        exc = ctx.get("excitation_params") or {}
        if ctx["meta"].get("flat") and hasattr(ctx.get("object"), "n") and hasattr(ctx.get("background"), "n"):
            out["R_fresnel"] = fresnel_reflectance(ctx["background"].n, ctx["object"].n,
                                                   float(exc.get("incidence_angle", 0.0)),
                                                   str(exc.get("polarization", "p")))
        return out

    def figures(self, data, ctx):
        import plotly.graph_objects as go  # noqa: PLC0415

        d, D = data["directions"], data["D"]
        figs = []
        floor = max(D.max() * 1e-8, 1e-300)
        fig = go.Figure(go.Scattergl(
            x=d[:, 0], y=d[:, 1], mode="markers",
            marker={"size": 5, "color": np.log10(np.maximum(D, floor)), "colorscale": "Viridis",
                    "colorbar": {"title": "log₁₀ D [1/sr]"}}))
        fig.update_layout(title=f"Reflexionshalbkugel (k_x/k, k_y/k), R = {float(data['reflectance']):.4f}",
                          xaxis_title="k_x / k", yaxis_title="k_y / k", height=520,
                          yaxis_scaleanchor="x")
        figs.append(fig)
        phi = np.arctan2(d[:, 1], d[:, 0])
        theta = np.degrees(np.arccos(np.clip(-d[:, 2], -1, 1)))  # from the reflection pole (-z)
        cuts = go.Figure()
        for name, target in (("φ = 0° (xz, +x)", 0.0), ("φ = 180° (xz, −x)", math.pi),
                             ("φ = 90° (yz)", math.pi / 2)):
            dphi = np.abs((phi - target + math.pi) % (2 * math.pi) - math.pi)
            sel = dphi <= dphi.min() + 1e-9
            order = np.argsort(theta[sel])
            cuts.add_trace(go.Scatter(x=theta[sel][order], y=D[sel][order], mode="lines", name=name))
        cuts.update_layout(title="Schnitte durch die Reflexionsverteilung", xaxis_title="θ vom Pol [°]",
                           yaxis_title="D [1/sr]", yaxis_type="log", height=400)
        figs.append(cuts)
        return figs

    @staticmethod
    def summary(data) -> dict:
        s = {"Reflektanz R": float(data["reflectance"])}
        if "R_library" in data:
            s["R Bibliothek (1°-Gitter)"] = float(data["R_library"])
            s["R / R_Bibliothek − 1"] = float(data["reflectance"]) / float(data["R_library"]) - 1.0
        if "P_inc" in data:
            s["einfallende Leistung P_inc [W]"] = float(data["P_inc"])
        if "R_fresnel" in data:
            rf = float(data["R_fresnel"])
            s["Fresnel R (ebene Welle)"] = rf
            s["Abweichung R / R_Fresnel − 1"] = float(data["reflectance"]) / rf - 1.0
        return s


def _surface_distance(points, vertices, chunk=4096):
    """Distance of each point to the nearest mesh vertex (>= distance to the surface minus h/sqrt(3))."""
    out = np.empty(len(points))
    for i in range(0, len(points), chunk):
        d = points[i:i + chunk, None, :] - vertices[None, :, :]
        out[i:i + chunk] = np.sqrt(np.min(np.einsum("ijk,ijk->ij", d, d), axis=1))
    return out


_PLANES = {"xz": ([1, 0, 0], [0, 0, 1]), "yz": ([0, 1, 0], [0, 0, 1]), "xy": ([1, 0, 0], [0, 1, 0])}


@OBSERVABLES.register
class NearField(Observable):
    id = "near_field"
    label = "Nahfeld in einer Schnittebene (Körper)"
    description = ("|E| auf einem ebenen Gitter durch den Ursprung; bei Kugeln Vergleich mit Mie und Fehlerkarte "
                   "e = |ΔE| / |E_Mie|. Punkte näher als h/2 an der Oberfläche werden ausgelassen (dort "
                   "dominiert der Diskretisierungsfehler, Bibliothek WP24).")
    applies_to = ("object",)
    fields = (
        Field("plane", "Schnittebene", "choice", "xz",
              choices=(("xz", "xz (y = 0)"), ("yz", "yz (x = 0)"), ("xy", "xy (z = 0)"))),
        Field("extent", "Gebietsgröße (× größter Radius)", "float", 3.0, "-", min=1.0, max=50.0, step=0.5),
        Field("n", "Punkte pro Achse", "int", 81, "-", min=11, max=401, step=10),
        Field("kind", "Feld", "choice", "total", choices=(("total", "gesamt (einfallend + gestreut)"),
                                                          ("scattered", "gestreut"))),
        Field("min_distance", "Mindestabstand zur Oberfläche (× h)", "float", 0.5, "-", min=0.05, max=5.0,
              step=0.05),
    )

    def compute(self, sb, sim, p, ctx):
        R = float(ctx["meta"].get("max_radius") or 1e-6)
        half = 0.5 * p["extent"] * 2 * R
        u, v = (np.asarray(a, float) * 2 * half for a in _PLANES[p["plane"]])
        n = int(p["n"])
        pts = np.asarray(sb.plane_grid(-(u + v) / 2, u, v, n, n), dtype=float)
        dist = _surface_distance(pts, np.asarray(ctx["vertices"], dtype=float))
        keep = dist >= p["min_distance"] * ctx["h"]
        E = np.full((len(pts), 3), np.nan + 0j)
        Ek, _ = sim.field(pts[keep], kind=p["kind"])
        E[keep] = np.asarray(Ek)
        out = {"points": pts, "absE": np.linalg.norm(E, axis=1), "n": n, "plane": p["plane"],
               "kind": p["kind"], "d_min": float(p["min_distance"] * ctx["h"])}
        ref = ctx["meta"].get("mie_sphere")
        if ref:
            a = float(ref["radius"])
            mie = sb.Mie(radius=a, wavelength=ctx["wavelength"], material=ctx["object"], exterior=ctx["background"])
            r = np.linalg.norm(pts, axis=1)
            out_s, in_s = keep & (r > a), keep & (r < a)
            Em = np.full_like(E, np.nan)
            if out_s.any():
                Em[out_s] = np.asarray(mie.scattered_E(pts[out_s]))
                if p["kind"] == "total":
                    Em[out_s] += np.asarray(ctx["excitation"].electric_field(pts[out_s]))
            if in_s.any():
                Em[in_s] = np.asarray(mie.internal_E(pts[in_s]))  # R2: the library returns the total field
            err = np.linalg.norm(E - Em, axis=1) / np.linalg.norm(Em, axis=1)
            out["err"] = err
            out["err_max_outside"] = float(np.nanmax(err[out_s])) if out_s.any() else float("nan")
            out["err_median_outside"] = float(np.nanmedian(err[out_s])) if out_s.any() else float("nan")
        return out

    def figures(self, data, ctx):
        import plotly.graph_objects as go  # noqa: PLC0415

        n, plane = int(data["n"]), str(data["plane"])
        pts = np.asarray(data["points"]).reshape(n, n, 3) * 1e6
        a, b = ({"xz": (0, 2), "yz": (1, 2), "xy": (0, 1)})[plane]
        xs, ys = pts[:, 0, a], pts[0, :, b]
        figs = []
        for key, title, cs in (("absE", f"|E| ({'gesamt' if str(data['kind']) == 'total' else 'gestreut'}) [V/m]",
                                "Viridis"), ("err", "Fehler gegen Mie e = |ΔE|/|E_Mie| (log₁₀)", "Inferno")):
            if key not in data:
                continue
            zz = np.asarray(data[key], float).reshape(n, n).T
            if key == "err":
                zz = np.log10(np.maximum(zz, 1e-8))
            fig = go.Figure(go.Heatmap(x=xs, y=ys, z=zz, colorscale=cs, colorbar={"title": ""}))
            fig.update_layout(title=f"{title}, Ebene {plane}", xaxis_title=f"{'xyz'[a]} [µm]",
                              yaxis_title=f"{'xyz'[b]} [µm]", height=480, yaxis_scaleanchor="x")
            figs.append(fig)
        return figs

    @staticmethod
    def summary(data) -> dict:
        s = {"Mindestabstand [nm]": float(data["d_min"]) * 1e9}
        if "err_max_outside" in data:
            s["max. Fehler außen (vs. Mie)"] = float(data["err_max_outside"])
            s["Median Fehler außen"] = float(data["err_median_outside"])
        return s
