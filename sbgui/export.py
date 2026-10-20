"""Exports of a run's results that need no library: CSV per observable. stdlib + numpy only."""

from __future__ import annotations

import io

import numpy as np


def observable_csv(data: dict) -> str | None:
    """CSV of one observable: every 1-D numeric array of the most common length >= 2 becomes a column,
    (n, 3) arrays become three columns (key_x, key_y, key_z), complex arrays real/imag columns; scalars
    go into ``# key = value`` header lines. None if there is no tabular data."""
    cols: dict[str, np.ndarray] = {}
    scalars: dict[str, str] = {}
    for k, v in data.items():
        a = np.asarray(v)
        if a.dtype.kind not in "biufc":
            if a.ndim == 0:
                scalars[k] = str(a)
            continue
        if a.ndim == 0:
            scalars[k] = f"{a.item():.12g}" if a.dtype.kind != "c" else str(a.item())
        elif a.ndim == 1:
            cols[k] = a
        elif a.ndim == 2 and a.shape[1] == 3:
            for i, c in enumerate("xyz"):
                cols[f"{k}_{c}"] = a[:, i]
    lengths = [len(a) for a in cols.values() if len(a) >= 2]
    if not lengths:
        return None
    n = max(set(lengths), key=lengths.count)
    table = {}
    for k, a in cols.items():
        if len(a) != n:
            continue
        if a.dtype.kind == "c":
            table[f"{k}_re"], table[f"{k}_im"] = a.real, a.imag
        else:
            table[k] = a
    out = io.StringIO()
    for k, v in scalars.items():
        out.write(f"# {k} = {v}\n")
    out.write(",".join(table) + "\n")
    np.savetxt(out, np.column_stack([np.asarray(a, dtype=float) for a in table.values()]), delimiter=",",
               fmt="%.12g")
    return out.getvalue()
