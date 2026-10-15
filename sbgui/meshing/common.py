"""Pure-numpy mesh helpers: icosphere, consistent orientation, quality statistics."""

from __future__ import annotations

import numpy as np


def _icosahedron() -> tuple[np.ndarray, np.ndarray]:
    t = (1.0 + 5.0**0.5) / 2.0
    v = np.array(
        [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
         [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]],
        dtype=float,
    )
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    f = np.array(
        [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4],
         [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8],
         [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]],
        dtype=np.int64,
    )
    return v, f


def _subdivide(v: np.ndarray, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(f)
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    uniq, inv = np.unique(edges, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    mid = v[uniq].mean(axis=1)
    mid /= np.linalg.norm(mid, axis=1, keepdims=True)
    base = len(v)
    v2 = np.vstack([v, mid])
    m01, m12, m20 = inv[:n] + base, inv[n : 2 * n] + base, inv[2 * n :] + base
    a, b, c = f.T
    f2 = np.vstack(
        [np.c_[a, m01, m20], np.c_[b, m12, m01], np.c_[c, m20, m12], np.c_[m01, m12, m20]]
    )
    return v2, f2


def icosphere_subdivisions(radius: float, h: float, max_sub: int = 7) -> int:
    """Smallest n such that the longest edge of the unit icosphere times ``radius`` is <= h."""
    v, f = _icosahedron()
    for n in range(max_sub + 1):
        e = np.concatenate([v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 1]]])
        if np.linalg.norm(e, axis=1).max() * radius <= h or n == max_sub:
            return n
        v, f = _subdivide(v, f)
    return max_sub


def icosphere(radius: float, h: float, max_sub: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Outward-oriented icosphere with all edges <= h (until ``max_sub`` is reached)."""
    n = icosphere_subdivisions(radius, h, max_sub)
    v, f = _icosahedron()
    for _ in range(n):
        v, f = _subdivide(v, f)
    return v * radius, f


def signed_volume(v: np.ndarray, f: np.ndarray) -> float:
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def orient_consistently(f: np.ndarray) -> np.ndarray:
    """Flip triangles so that every shared edge is traversed in opposite directions.

    Requires a closed, edge-manifold mesh (each edge in exactly two triangles); raises
    ValueError otherwise. Each connected component is oriented independently from its first
    triangle; use ``orient_outward`` afterwards to fix the global sign.
    """
    f = np.asarray(f, dtype=np.int64).copy()
    n = len(f)
    he = np.stack([f, np.roll(f, -1, axis=1)], axis=-1).reshape(-1, 2)  # half-edge 3*i + k
    key = np.sort(he, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    ks = key[order]
    same = np.all(ks[1:] == ks[:-1], axis=1)
    idx = np.nonzero(same)[0]
    if 2 * len(idx) != 3 * n or (len(idx) > 1 and np.any(same[1:] & same[:-1])):
        raise ValueError("mesh is not closed and edge-manifold (every edge needs exactly two triangles)")
    a, b = order[idx], order[idx + 1]
    same_dir = np.all(he[a] == he[b], axis=1)  # True: neighbours disagree in orientation
    fa, fb = a // 3, b // 3
    nbr = [[] for _ in range(n)]
    for x, y, s in zip(fa.tolist(), fb.tolist(), same_dir.tolist()):
        nbr[x].append((y, s))
        nbr[y].append((x, s))
    flip = np.full(n, -1, dtype=np.int8)
    for start in range(n):
        if flip[start] != -1:
            continue
        flip[start] = 0
        stack = [start]
        while stack:
            x = stack.pop()
            for y, s in nbr[x]:
                want = flip[x] ^ int(s)
                if flip[y] == -1:
                    flip[y] = want
                    stack.append(y)
                elif flip[y] != want:
                    raise ValueError("mesh is not orientable")
    f[flip == 1] = f[flip == 1][:, [0, 2, 1]]
    return f


def orient_outward(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Consistent orientation with positive enclosed volume (normals point out of the body)."""
    f = orient_consistently(f)
    if signed_volume(v, f) < 0:
        f = f[:, [0, 2, 1]]
    return f


def is_closed(f: np.ndarray) -> bool:
    he = np.stack([f, np.roll(f, -1, axis=1)], axis=-1).reshape(-1, 2)
    key = np.sort(he, axis=1)
    _, counts = np.unique(key, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def mesh_stats(v: np.ndarray, f: np.ndarray) -> dict:
    """Edge-length and angle statistics for the quality gate in the GUI."""
    p0, p1, p2 = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    l01, l12, l20 = (np.linalg.norm(p1 - p0, axis=1), np.linalg.norm(p2 - p1, axis=1),
                     np.linalg.norm(p0 - p2, axis=1))
    el = np.concatenate([l01, l12, l20])

    def ang(a, b, c):  # angle opposite to side a
        return np.arccos(np.clip((b**2 + c**2 - a**2) / (2 * b * c), -1, 1))

    angles = np.degrees(np.stack([ang(l12, l01, l20), ang(l20, l01, l12), ang(l01, l12, l20)]))
    area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    return {
        "n_vertices": int(len(np.unique(f))),
        "n_triangles": int(len(f)),
        "edge_min": float(el.min()),
        "edge_mean": float(el.mean()),
        "edge_max": float(el.max()),
        "angle_min_deg": float(angles.min()),
        "angle_p01_deg": float(np.percentile(angles.min(axis=0), 1)),
        "area_total": float(area.sum()),
        "closed": is_closed(f),
        "volume": signed_volume(v, f),
    }
