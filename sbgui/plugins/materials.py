"""Materials. Optics-style input (n + ik, k >= 0) is converted to the library convention exp(+jwt),
i.e. n - jk and eps_r = (n - jk)^2 with Im(eps_r) <= 0 for passive media (docs/06)."""

from __future__ import annotations

import numpy as np

from ..base import Issue, Material
from ..params import Field
from ..registry import MATERIALS

_LIBRARY_WAVELENGTH = 500e-9
_LIBRARY = {"vacuum": "Vakuum", "silicon_500nm": "Silizium (500 nm)", "silver_500nm": "Silber (500 nm)"}


@MATERIALS.register
class LibraryMaterial(Material):
    id = "library"
    label = "Bibliotheks-Material"
    description = "Tabellierte Werte der Bibliothek (Silizium und Silber nur bei 500 nm)."
    fields = (Field("name", "Material", "choice", "silicon_500nm", choices=tuple(_LIBRARY.items())),)

    def validate(self, p, wavelength):
        if p["name"] != "vacuum" and abs(wavelength - _LIBRARY_WAVELENGTH) > 1e-12:
            return [Issue("error", f"{_LIBRARY[p['name']]} ist nur bei 500 nm tabelliert "
                          f"(eingestellt: {wavelength * 1e9:g} nm). 'Konstanter Index' oder "
                          "'Tabelle' verwenden.")]
        return []

    def build(self, sb, p, wavelength):
        return {"vacuum": sb.vacuum, "silicon_500nm": sb.silicon_500nm,
                "silver_500nm": sb.silver_500nm}[p["name"]]()

    def refractive_index(self, p, wavelength):
        return {"vacuum": 1.0 + 0j}.get(p["name"])


@MATERIALS.register
class ConstantIndex(Material):
    id = "constant"
    label = "Konstanter Index n + ik"
    fields = (
        Field("n", "n", "float", 1.5, "-", min=0.01, max=100.0, step=0.01),
        Field("k", "k (≥ 0, Absorption)", "float", 0.0, "-", min=0.0, max=100.0, step=0.01),
    )

    def build(self, sb, p, wavelength):
        return sb.Material(eps_r=complex(p["n"], -p["k"]) ** 2)

    def refractive_index(self, p, wavelength):
        return complex(p["n"], -p["k"])


@MATERIALS.register
class TableMaterial(Material):
    id = "table"
    label = "Tabelle (λ, n, k)"
    description = "Eine Zeile pro Wellenlänge: 'λ[nm]  n  k' (Komma, Semikolon oder Leerraum)."
    fields = (Field("data", "Daten", "text",
                    "# lambda_nm  n  k\n400 5.57 0.39\n500 4.29 0.07\n600 3.94 0.02"),)

    @staticmethod
    def parse(text: str) -> np.ndarray:
        rows = []
        for line in text.splitlines():
            line = line.split("#")[0].replace(",", " ").replace(";", " ").strip()
            if line:
                rows.append([float(x) for x in line.split()[:3]])
        a = np.array(rows, dtype=float)
        if a.ndim != 2 or a.shape[1] != 3 or len(a) < 2:
            raise ValueError("mindestens zwei Zeilen mit je drei Zahlen nötig")
        if np.any(np.diff(a[:, 0]) <= 0):
            raise ValueError("Wellenlängen müssen streng aufsteigend sein")
        if np.any(a[:, 2] < 0):
            raise ValueError("k muss ≥ 0 sein")
        return a

    def validate(self, p, wavelength):
        try:
            a = self.parse(p["data"])
        except ValueError as e:
            return [Issue("error", f"Materialtabelle: {e}")]
        if not (a[0, 0] * 1e-9 <= wavelength <= a[-1, 0] * 1e-9):
            return [Issue("error", "Wellenlänge liegt außerhalb der Tabelle.")]
        return []

    def build(self, sb, p, wavelength):
        a = self.parse(p["data"])
        return sb.DispersiveMaterial(a[:, 0] * 1e-9, a[:, 1] - 1j * a[:, 2]).at(wavelength)

    def refractive_index(self, p, wavelength):
        a = self.parse(p["data"])
        lam = a[:, 0] * 1e-9
        return complex(np.interp(wavelength, lam, a[:, 1]), -np.interp(wavelength, lam, a[:, 2]))
