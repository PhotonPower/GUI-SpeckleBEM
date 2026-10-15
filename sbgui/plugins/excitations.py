"""Excitations: plane wave (isolated bodies) and Gaussian beams (finite patches).

``ctx`` carries: wavelength [m], h [m], meta (geometry meta incl. ``kind`` and ``lateral_size``),
rules (dict from the library via the worker, or None if the library is not reachable).
Light travels in +z, p = E in the plane of incidence (xz), s = E along y (docs/06).
"""

from __future__ import annotations

import math

import numpy as np

from ..base import Excitation, Issue
from ..params import Field
from ..registry import EXCITATIONS

_POL = (("p", "p (E in der Einfallsebene xz)"), ("s", "s (E senkrecht dazu, y)"))
_FALLBACK_WAIST_FRACTION = 1.0 / 6.0  # most conservative library rule (weak absorbers)


def pol_vector(pol: str, theta: float) -> np.ndarray:
    return np.array([math.cos(theta), 0.0, -math.sin(theta)]) if pol == "p" else np.array([0.0, 1.0, 0.0])


def waist_limit(ctx: dict, theta: float) -> float:
    frac = (ctx.get("rules") or {}).get("waist_fraction") or _FALLBACK_WAIST_FRACTION
    return ctx["meta"]["lateral_size"] * math.cos(theta) * frac


def resolve_waist(p: dict, ctx: dict) -> float:
    if p["waist_mode"] == "manual":
        return p["waist"]
    return 0.999 * waist_limit(ctx, p["incidence_angle"])


@EXCITATIONS.register
class PlaneWave(Excitation):
    id = "plane_wave"
    label = "Ebene Welle"
    description = "Unendlich ausgedehnte Welle; für isolierte Körper (Kugel, Ellipsoid)."
    fields = (
        Field("polarization", "Polarisation", "choice", "p", choices=_POL),
        Field("incidence_angle", "Einfallswinkel", "float", 0.0, "deg", min=0.0, max=89.0, step=1.0),
    )

    def validate(self, p, ctx):
        if ctx["meta"].get("kind") == "substrate":
            return [Issue("warning", "Ebene Welle auf einem endlichen Substratgebiet beugt am Rand der "
                          "Box und verfälscht das Ergebnis. Für Strukturen auf Substrat einen "
                          "Gaußstrahl verwenden.")]
        return []

    def build(self, sb, p, ctx, background):
        th = p["incidence_angle"]
        return sb.PlaneWave(wavelength=ctx["wavelength"], direction=[math.sin(th), 0.0, math.cos(th)],
                            polarization=pol_vector(p["polarization"], th).tolist(),
                            background=background)

    def describe(self, p, ctx):
        return f"ebene Welle, {p['polarization']}-polarisiert, {math.degrees(p['incidence_angle']):g}°"


@EXCITATIONS.register
class GaussianBeam(Excitation):
    id = "gaussian_beam"
    label = "Gaußstrahl"
    description = ("'streng' = Winkelspektrum-Strahl (quantitative Rechnungen); 'paraxial' ist nur "
                   "qualitativ (ca. 2,8 % Reflexionsfehler bei w₀ = 0,67 µm, ADR 0006).")
    fields = (
        Field("beam_model", "Strahlmodell", "choice", "rigorous",
              choices=(("rigorous", "streng (Winkelspektrum)"), ("paraxial", "paraxial (qualitativ)"))),
        Field("polarization", "Polarisation", "choice", "p", choices=_POL),
        Field("incidence_angle", "Einfallswinkel", "float", 0.0, "deg", min=0.0, max=80.0, step=1.0),
        Field("waist_mode", "Strahltaille w₀", "choice", "auto",
              choices=(("auto", "automatisch (größte erlaubte, Regel der Bibliothek)"),
                       ("manual", "manuell"))),
        Field("waist", "w₀ (manuell)", "float", 0.6, "µm", min=0.1, max=50.0, step=0.1,
              visible_if=lambda v: v.get("waist_mode") == "manual"),
    )

    def validate(self, p, ctx):
        out = []
        if ctx["meta"].get("kind") != "substrate":
            return out
        th, lam = p["incidence_angle"], ctx["wavelength"]
        w0, limit = resolve_waist(p, ctx), waist_limit(ctx, th)
        if w0 > limit * (1 + 1e-9):
            out.append(Issue("error", f"w₀ = {w0 * 1e6:.2f} µm überschreitet die Randregel "
                             f"w₀ ≤ L·cosθ·f = {limit * 1e6:.2f} µm (ADR 0006). Gebiet vergrößern "
                             "oder w₀ verkleinern."))
        if w0 * math.cos(th) < lam:
            out.append(Issue("warning", "w₀·cosθ < λ: Strahl ist stark fokussiert; die validierten Regeln "
                             "(w₀·cosθ ≳ λ) gelten dort nicht."))
        if not ctx.get("rules"):
            out.append(Issue("warning", "Regeln der Bibliothek nicht erreichbar; es gilt die "
                             "konservative Näherung w₀ ≤ L·cosθ/6."))
        if p["beam_model"] == "paraxial":
            out.append(Issue("warning", "Paraxialer Strahl: nur qualitativ verwenden."))
        return out

    def build(self, sb, p, ctx, background):
        th, w0 = p["incidence_angle"], resolve_waist(p, ctx)
        if ctx["meta"].get("kind") == "substrate":
            frac = (ctx.get("rules") or {}).get("waist_fraction") or _FALLBACK_WAIST_FRACTION
            sb.check_beam_waist(ctx["meta"]["lateral_size"], w0, incidence_angle=th, max_fraction=frac)
        kw = dict(wavelength=ctx["wavelength"], waist=w0, polarization=p["polarization"],
                  incidence_angle=th, background=background)
        if p["beam_model"] == "rigorous":
            # the library requires the field-controlled region to cover the whole mesh
            if ctx["meta"].get("max_radius"):
                kw["region_radius"] = 1.01 * ctx["meta"]["max_radius"]
            return sb.AngularSpectrumBeam(**kw)
        return sb.GaussianBeam(**kw)

    def describe(self, p, ctx):
        return f"Gaußstrahl ({p['beam_model']}), w₀ = {resolve_waist(p, ctx) * 1e6:.2f} µm"
