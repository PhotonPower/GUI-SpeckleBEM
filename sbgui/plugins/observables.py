"""Observables. ``compute`` runs in the worker (gets ``sb`` and the solved ``sim``) and returns
plain numpy arrays / floats / strings, which go to ``results.npz``. ``figures`` runs in the GUI
and builds Plotly figures from those arrays; it must not need the library."""

from __future__ import annotations

import math

import numpy as np

from ..base import Issue, Observable
from ..params import Field
from ..registry import OBSERVABLES
from .excitations import resolve_waist

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


# -- speckle statistics (G15, library WP-S1) ---------------------------------------------------------

SPECKLE_FULLY_DEVELOPED = 1e-2  # coherent fraction below which the negative-exponential gate applies (WP-S2b)
SPECKLE_MIN_SAMPLES = 50  # the library's KS test needs n >= 50 independent samples
SPECKLE_KS_SPACING = 2.0  # independent samples are taken about two speckle sizes apart (ensemble_statistics)
SPECKLE_MAX_ANGLE_DEG = 30.0  # beyond this the paraxial lambda z / D model of the speckle size is poor


def coherent_fraction(sigma: float, wavelength: float, n_background: float = 1.0) -> float:
    """exp(-(2 k sigma)^2) with k = 2 pi n / lambda: the part of the reflected power that stays coherent
    (specular) for a Gaussian surface of RMS height sigma (library WP-S1/WP-S2 convention)."""
    k = 2.0 * math.pi * n_background / wavelength
    return math.exp(-((2.0 * k * sigma) ** 2))


def speckle_plane(p: dict, wavelength_medium: float, aperture: float, constant: float, incidence: float = 0.0):
    """(side, pixel, x0, max_angle) of the observation plane [m, m, m, deg]: side = n_speckles c lambda z / D,
    centred on the specular reflection. ``constant`` is the library's speckle-size constant of the Gaussian spot
    (``sb.speckle_size_constant``, passed in through the rules)."""
    z = p["distance"]
    side = p["n_speckles"] * constant * wavelength_medium * z / aperture
    pixel = side / (p["n_pixels"] - 1)
    return side, pixel, z * math.tan(incidence), math.degrees(math.atan(side / 2.0 / z))


@OBSERVABLES.register
class SpeckleStatistics(Observable):
    id = "speckle_statistics"
    label = "Speckle-Statistik (Struktur)"
    description = (
        "Co-polarisierte Intensität des gestreuten Feldes auf einer Ebene im Abstand z unter der Oberfläche "
        "(Reflexionsseite, Mitte auf dem Spiegelreflex) und die Statistik der Bibliothek (WP-S1): Kontrast, "
        "KS-Test gegen die negative Exponentialverteilung (Stephens, 5 %), Speckle-Größe gegen c·λ·z/D mit "
        "D = 2 w₀. Die Ebene ist so groß, dass n_speckles Speckles pro Achse hineinpassen. Geschlossene Box: "
        "exaktes Feld (sim.field); PML-Route: Fernfeld (sim.far_field), also nur in der Fernzone gültig. "
        "Mehrere Läufe (Seeds, σ) werden auf der Seite „Ergebnisse“ zum Ensemble zusammengefasst.")
    applies_to = ("substrate",)
    fields = (
        Field("distance", "Abstand der Beobachtungsebene z", "float", 1.0, "mm", min=0.01, max=1000.0, step=0.1),
        Field("n_speckles", "Speckles pro Achse (bestimmt die Ebenengröße)", "int", 20, "-", min=5, max=200,
              step=5),
        Field("n_pixels", "Pixel pro Achse", "int", 101, "-", min=21, max=1001, step=10,
              help="Mindestens 3 Pixel pro Speckle (Bibliothek: Fehler der Speckle-Größe ≤ 1,9 % bei 3 Pixeln). "
                   "Kosten: n² Feldauswertungen gegen alle Quellen."),
    )

    # -- GUI side ------------------------------------------------------------------------------
    def validate(self, p, ctx):
        out: list[Issue] = []
        exc = ctx.get("excitation_params") or {}
        if "waist_mode" not in exc:
            return [Issue("error", "Die Speckle-Statistik braucht einen Gaußstrahl (Strahltaille w₀ legt die "
                          "beleuchtete Fläche D = 2 w₀ fest), keine ebene Welle.")]
        lam, rules = ctx["wavelength"], ctx.get("rules") or {}
        n_bg = float(ctx.get("n_background") or 1.0)
        lam_med = lam / n_bg
        th = float(exc.get("incidence_angle", 0.0))
        if th > 1e-9:
            out.append(Issue("info", "Schräger Einfall: die Beobachtungsebene (parallel zur Oberfläche) ist auf den "
                             "Spiegelreflex zentriert; die Speckle-Größe c·λ·z/D gilt paraxial um die Reflexions"
                             "richtung (D = 2 w₀, nicht projiziert)."))
        constant = rules.get("speckle_constant_gaussian")
        if constant:
            D = 2.0 * resolve_waist(exc, ctx)
            side, pixel, _, angle = speckle_plane(p, lam_med, D, float(constant), th)
            if angle > SPECKLE_MAX_ANGLE_DEG:
                out.append(Issue("warning", f"Die Beobachtungsebene ({side * 1e3:.3g} mm) reicht bis θ = {angle:.0f}° "
                                 f"vom Spiegelreflex: das paraxiale Modell der Speckle-Größe (c·λ·z/D) ist dort "
                                 "schlecht und die Speckles strecken sich außerhalb der Achse. Der Winkel hängt nur "
                                 "von der Speckle-Zahl und der beleuchteten Fläche ab (tan θ = n·c·λ / (2D)), nicht "
                                 "vom Abstand: weniger Speckles pro Achse oder größere Beleuchtung D = 2 w₀ (also "
                                 "größeres L) wählen (Bibliothek, Beispiel 02_rough_surface_speckle)."))
            per_speckle = (p["n_pixels"] - 1) / p["n_speckles"]
            if per_speckle < 3:
                out.append(Issue("warning", f"Nur {per_speckle:.1f} Pixel pro Speckle: die Speckle-Größe wird "
                                 "ungenau (Bibliothek: ≤ 1,9 % bei 3 Pixeln). Mehr Pixel oder weniger Speckles."))
            if (p["n_speckles"] / SPECKLE_KS_SPACING) ** 2 < SPECKLE_MIN_SAMPLES:
                out.append(Issue("warning", f"Bei {p['n_speckles']} Speckles pro Achse bleiben weniger als "
                                 f"{SPECKLE_MIN_SAMPLES} unabhängige Stichproben (Abstand ca. zwei Speckle-Größen): "
                                 "der KS-Test der Bibliothek ist dann nicht möglich oder schwach. Mindestens 15 "
                                 "Speckles pro Achse oder mehrere Läufe zum Ensemble zusammenfassen."))
            if ctx["meta"].get("termination") == "pml":
                L = float(ctx["meta"].get("lateral_size") or 0.0)
                if L and p["distance"] < 5.0 * L * L / lam_med:
                    out.append(Issue("warning", f"PML-Route: das Feld kommt aus dem Fernfeld (sim.far_field). z = "
                                     f"{p['distance'] * 1e3:.3g} mm ist nicht ≫ L²/λ = {L * L / lam_med * 1e3:.3g} mm "
                                     "(GUI-Faustregel z ≥ 5 L²/λ): die Fernfeld-Näherung ist dort ungenau."))
        else:
            out.append(Issue("info", "Regeln der Bibliothek nicht erreichbar: die Prüfungen der Beobachtungsebene "
                             "(Winkel, Pixel pro Speckle, Stichprobenzahl) entfallen."))
        sigma = (ctx.get("geometry_params") or {}).get("sigma")
        if sigma is not None:
            cf = coherent_fraction(float(sigma), lam, n_bg)
            if cf >= SPECKLE_FULLY_DEVELOPED:
                out.append(Issue("info", f"σ = {sigma * 1e9:.0f} nm: kohärenter Anteil exp(−(2kσ)²) = {cf:.2g} ≥ "
                                 f"{SPECKLE_FULLY_DEVELOPED:g}, der Speckle ist nur teilweise entwickelt. Der "
                                 "Spiegelreflex dominiert die Mitte; Kontrast < 1 ist hier die physikalische "
                                 "Erwartung und der KS-Test gegen die negative Exponentialverteilung gilt nur "
                                 "für voll entwickelte Fälle (Lead-Entscheidung WP-S2b)."))
        return out

    # -- worker side ---------------------------------------------------------------------------
    def compute(self, sb, sim, p, ctx):
        from specklebem import speckle  # noqa: PLC0415

        exc = ctx.get("excitation_params") or {}
        if "waist_mode" not in exc:
            raise ValueError("Die Speckle-Statistik braucht einen Gaußstrahl.")
        th = float(exc.get("incidence_angle", 0.0))
        lam_med = ctx["wavelength"] / float(ctx.get("n_background") or 1.0)
        D = 2.0 * resolve_waist(exc, {"meta": ctx["meta"], "rules": ctx.get("rules")})
        n, z = int(p["n_pixels"]), float(p["distance"])
        side = speckle.observation_plane_size(lam_med, z, D, shape="gaussian", n_speckles=int(p["n_speckles"]))
        pixel, x0 = side / (n - 1), z * math.tan(th)
        pts = np.asarray(sb.plane_grid([x0 - side / 2, -side / 2, -z], [side, 0, 0], [0, side, 0], n, n), dtype=float)
        if ctx["meta"].get("open_surface"):  # PML route: no near field; far zone, E ~ F exp(-jkr) / r
            r = np.linalg.norm(pts, axis=1)
            E = np.asarray(sim.far_field(pts / r[:, None])) / r[:, None]
        else:
            E = np.asarray(sim.field(pts, kind="scattered")[0])
        pol = list(ctx.get("co_pol") or [1.0, 0.0, 0.0])
        co, _ = sb.polarized_intensity(E, co_pol=pol)
        I = np.asarray(co, dtype=float).reshape(n, n)
        sigma = ctx["meta"].get("sigma_measured")
        nan = float("nan")
        out = {"intensity": I, "pixel_size": pixel, "wavelength_medium": lam_med, "distance": z, "aperture": D,
               "side": side, "x0": x0, "contrast": float(sb.speckle_contrast(I)),
               "coherent_fraction": coherent_fraction(float(sigma), ctx["wavelength"],
                                                      float(ctx.get("n_background") or 1.0))
               if sigma is not None else nan,
               "speckle_size_expected": float(sb.speckle_size_expected(lam_med, z, D, "gaussian"))}
        try:  # one pattern: pooled KS over the decimated pixels; may fail for too few speckles
            st = speckle.ensemble_statistics([I], pixel, lam_med, z, D, shape="gaussian")
            ks = st["ks"]
            out.update(ks_statistic=float(ks.statistic), ks_p_value=float(ks.p_value), ks_n=int(ks.n),
                       ks_modified=float(ks.modified_statistic), ks_rejects=bool(st["ks_rejects_5pct"]),
                       speckle_size=np.asarray(st["speckle_size"][0], dtype=float),
                       speckle_size_rel_error=float(st["speckle_size_rel_error"]))
        except Exception as e:  # noqa: BLE001 - keep intensity and contrast, report why the rest is missing
            out["stats_error"] = f"{type(e).__name__}: {e}"
        return out

    def figures(self, data, ctx):
        import plotly.graph_objects as go  # noqa: PLC0415

        I = np.asarray(data["intensity"], dtype=float)
        n = I.shape[0]
        side, x0 = float(data["side"]), float(data["x0"])
        xs, ys = (np.linspace(-side / 2, side / 2, n) + x0) * 1e3, np.linspace(-side / 2, side / 2, n) * 1e3
        mean = float(I.mean()) or 1.0
        fig = go.Figure(go.Heatmap(x=xs, y=ys, z=(I / mean).T, colorscale="Viridis", colorbar={"title": "I / ⟨I⟩"}))
        fig.update_layout(title=f"Speckle-Intensität bei z = {float(data['distance']) * 1e3:.3g} mm "
                                f"(Kontrast {float(data['contrast']):.3f})",
                          xaxis_title="x [mm]", yaxis_title="y [mm]", height=480, yaxis_scaleanchor="x")
        x = (I / mean).ravel()
        top = float(np.percentile(x, 99.5)) or 1.0
        hist, edges = np.histogram(x, bins=64, range=(0.0, top), density=True)
        c = 0.5 * (edges[1:] + edges[:-1])
        pdf = go.Figure()
        pdf.add_trace(go.Scatter(x=c, y=hist, mode="markers", name="Simulation"))
        pdf.add_trace(go.Scatter(x=c, y=np.exp(-c), mode="lines", name="exp(−x) (voll entwickelt)"))
        pdf.update_layout(title="Intensitätsverteilung, x = I/⟨I⟩", xaxis_title="x", yaxis_title="Dichte",
                          yaxis_type="log", height=380)
        return [fig, pdf]

    @staticmethod
    def summary(data) -> dict:
        s = {"Kontrast std(I)/⟨I⟩": float(data["contrast"])}
        if "ks_modified" in data:
            s["Stephens-D* (Grenze 1,094 bei 5 %)"] = float(data["ks_modified"])
            s["KS p (Kolmogorov, konservativ)"] = float(data["ks_p_value"])
            s["Speckle-Größe / (c·λ·z/D) − 1"] = float(data["speckle_size_rel_error"])
        if "coherent_fraction" in data and not math.isnan(float(data["coherent_fraction"])):
            s["kohärenter Anteil exp(−(2kσ)²)"] = float(data["coherent_fraction"])
        return s

    @staticmethod
    def notes(data) -> list[str]:
        out = []
        if "stats_error" in data:
            out.append(f"Statistik der Bibliothek nicht berechnet: {data['stats_error']}")
        elif "ks_rejects" in data:
            cf = float(data["coherent_fraction"]) if "coherent_fraction" in data else float("nan")
            developed = math.isnan(cf) or cf < SPECKLE_FULLY_DEVELOPED
            verdict = "wird verworfen" if bool(data["ks_rejects"]) else "wird nicht verworfen"
            out.append(f"Negative Exponentialverteilung (Stephens-KS, 5 %, n = {int(data['ks_n'])} unabhängige "
                       f"Stichproben): {verdict}." + ("" if developed else
                       " Nicht aussagekräftig: der Speckle ist nur teilweise entwickelt (kohärenter Anteil "
                       f"{cf:.2g})."))
        return out
