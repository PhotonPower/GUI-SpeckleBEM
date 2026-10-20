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
        if "R_fresnel" in data:
            rf = float(data["R_fresnel"])
            s["Fresnel R (ebene Welle)"] = rf
            s["Abweichung R / R_Fresnel − 1"] = float(data["reflectance"]) / rf - 1.0
        return s
