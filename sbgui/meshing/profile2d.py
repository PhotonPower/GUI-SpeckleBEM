"""2-D cross-section of an isolated line (ridge) or trench with sidewall angle and rounded corners.

Physical frame of this module: x across the line, z up (into the air), substrate surface at z = 0.
The library frame has the object on the +z side and light travelling in +z (docs/06); the
mapping z_lib = -z_phys is applied in ``extrude.py``, so users never see it.

Parametrisation (the usual metrology one):
  * ``cd``      width at half height (CD_mid) - independent of the sidewall angle,
  * ``height``  ridge height / trench depth,
  * ``swa``     sidewall angle against the substrate plane, 90 deg = vertical. For swa < 90 the
                feature is wider at the substrate plane (ridge foot / trench opening) than at its
                far end (ridge top / trench floor),
  * ``r_top``   radius of the corners at the higher z (ridge top corners / trench opening edges),
  * ``r_bottom`` radius of the corners at the lower z (ridge feet / trench floor corners).
"""

from __future__ import annotations

import math

import numpy as np


def _corner(p0, p1, p2, r):
    """Tangent points, centre and tangent length of a fillet of radius r at p1."""
    u1, u2 = p0 - p1, p2 - p1
    l1, l2 = np.linalg.norm(u1), np.linalg.norm(u2)
    u1, u2 = u1 / l1, u2 / l2
    phi = math.acos(max(-1.0, min(1.0, float(u1 @ u2))))  # interior angle
    if phi < 1e-9 or abs(phi - math.pi) < 1e-9:
        raise ValueError("degenerate corner (collinear or folded edges)")
    t = r / math.tan(phi / 2.0)
    bis = u1 + u2
    bis /= np.linalg.norm(bis)
    return {"t": t, "c": p1 + bis * (r / math.sin(phi / 2.0)), "t1": p1 + u1 * t,
            "t2": p1 + u2 * t, "l1": l1, "l2": l2}


def fillet_polyline(points: np.ndarray, radii, seg: float, min_arc_points: int = 1) -> np.ndarray:
    """Round the interior vertices of an open polyline.

    ``radii[i]`` is the fillet radius at ``points[i + 1]`` (0 = keep sharp). Arcs are sampled
    with chord length <= ``seg`` and at least ``min_arc_points`` segments (1 = a corner whose arc
    is shorter than ``seg`` becomes a chamfer). Raises ValueError if
    neighbouring fillets overlap or do not fit on their edges.
    """
    pts = np.asarray(points, dtype=float)
    radii = list(radii)
    if len(radii) != len(pts) - 2:
        raise ValueError("need one radius per interior vertex")
    corners = [None if r <= 0 else _corner(pts[i], pts[i + 1], pts[i + 2], r)
               for i, r in enumerate(radii)]
    for i, c in enumerate(corners):  # edge i+1 lies between vertex i+1 and i+2
        if c is None:
            continue
        nxt = corners[i + 1] if i + 1 < len(corners) else None
        if c["t"] > c["l2"] * (1 - 1e-9) or (nxt is not None and c["t"] + nxt["t"] > c["l2"] * (1 - 1e-9)):
            raise ValueError(
                f"Rundung zu groß für die Kante: Tangentenlänge {c['t'] * 1e9:.1f} nm, "
                f"Kante {c['l2'] * 1e9:.1f} nm"
            )
        if i == 0 and c["t"] > c["l1"] * (1 - 1e-9):
            raise ValueError("Rundung zu groß für die erste Kante")
    out = [pts[0]]
    for i, c in enumerate(corners):
        if c is None:
            out.append(pts[i + 1])
            continue
        r = radii[i]
        a1 = math.atan2(*(c["t1"] - c["c"])[::-1])
        a2 = math.atan2(*(c["t2"] - c["c"])[::-1])
        d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        n = max(min_arc_points, math.ceil(abs(d) * r / seg))
        ang = a1 + d * np.linspace(0.0, 1.0, n + 1)
        out.extend(c["c"] + r * np.stack([np.cos(ang), np.sin(ang)], axis=1))
    out.append(pts[-1])
    return np.asarray(out)


def line_widths(cd: float, height: float, swa: float) -> tuple[float, float]:
    """(half-width at the substrate plane, half-width at the far end) for sidewall angle ``swa`` [rad]."""
    c = 1.0 / math.tan(swa) if swa < math.pi / 2 - 1e-12 else 0.0
    return cd / 2 + height / 2 * c, cd / 2 - height / 2 * c


def line_profile(kind: str, cd: float, height: float, swa: float, r_top: float,
                 r_bottom: float, Lx: float, seg: float, min_arc_points: int = 1) -> np.ndarray:
    """Polyline (n, 2) of (x, z_phys) from x = -Lx/2 to +Lx/2. kind: "ridge" | "trench"."""
    if kind not in ("ridge", "trench"):
        raise ValueError(f"kind must be 'ridge' or 'trench', got {kind!r}")
    if not (0 < swa <= math.pi / 2):
        raise ValueError("Seitenwandwinkel muss in (0°, 90°] liegen")
    if cd <= 0 or height <= 0:
        raise ValueError("CD und Höhe müssen positiv sein")
    hw_near, hw_far = line_widths(cd, height, swa)
    if hw_far <= 0:
        raise ValueError(
            "Profil läuft spitz zu: Breite am freien Ende ≤ 0. Seitenwandwinkel erhöhen, "
            "CD vergrößern oder Höhe verringern."
        )
    if hw_near >= Lx / 2:
        raise ValueError("Struktur ist breiter als das Rechengebiet (Lx zu klein)")
    s = 1.0 if kind == "ridge" else -1.0
    pts = np.array([[-Lx / 2, 0.0], [-hw_near, 0.0], [-hw_far, s * height],
                    [hw_far, s * height], [hw_near, 0.0], [Lx / 2, 0.0]])
    r_far, r_near = (r_top, r_bottom) if kind == "ridge" else (r_bottom, r_top)
    return fillet_polyline(pts, [r_near, r_far, r_far, r_near], seg, min_arc_points)


def polygon_area(poly_xz: np.ndarray, z0: float = 0.0) -> float:
    """Signed area between the profile and the plane z = z0 (positive = material above z0)."""
    x, z = poly_xz[:, 0], poly_xz[:, 1] - z0
    return float(np.sum(0.5 * (z[1:] + z[:-1]) * np.diff(x)))
