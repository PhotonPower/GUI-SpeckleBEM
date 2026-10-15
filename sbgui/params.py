"""Declarative parameter schemas.

A plugin declares its inputs once as ``Field`` objects. The same declaration drives the
Streamlit widgets, the range validation and the conversion to SI. Config files store the
*display* values (nm, deg, ...) so that they stay human-readable; plugins only ever see SI.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

UNIT_SI = {"": 1.0, "-": 1.0, "nm": 1e-9, "µm": 1e-6, "mm": 1e-3, "deg": math.pi / 180.0}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "float"  # float | int | choice | bool | text
    default: Any = 0.0
    unit: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple = ()  # ((value, label), ...)
    help: str = ""
    visible_if: Callable[[dict], bool] | None = None  # evaluated on the *display* values


class Schema:
    def __init__(self, fields=()):
        self.fields = tuple(fields)
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate field keys in schema: {keys}")

    def defaults(self) -> dict:
        return {f.key: f.default for f in self.fields}

    def fill(self, values: dict | None) -> dict:
        """Defaults overlaid with the known keys of ``values`` (unknown keys are dropped)."""
        out = self.defaults()
        out.update({k: v for k, v in (values or {}).items() if k in out})
        return out

    def is_visible(self, f: Field, values: dict) -> bool:
        return f.visible_if is None or bool(f.visible_if(values))

    def to_si(self, values: dict) -> dict:
        v = self.fill(values)
        return {
            f.key: (float(v[f.key]) * UNIT_SI[f.unit] if f.kind == "float" else v[f.key])
            for f in self.fields
        }

    def errors(self, values: dict) -> list[str]:
        """Range errors of the visible fields (messages in German, they go to the UI)."""
        v = self.fill(values)
        out = []
        for f in self.fields:
            if not self.is_visible(f, v):
                continue
            x = v[f.key]
            if f.kind in ("float", "int"):
                if not isinstance(x, (int, float)) or not math.isfinite(x):
                    out.append(f"{f.label}: keine gültige Zahl")
                    continue
                if f.min is not None and x < f.min:
                    out.append(f"{f.label} = {x:g} {f.unit} liegt unter {f.min:g} {f.unit}")
                if f.max is not None and x > f.max:
                    out.append(f"{f.label} = {x:g} {f.unit} liegt über {f.max:g} {f.unit}")
            elif f.kind == "choice" and x not in [c[0] for c in f.choices]:
                out.append(f"{f.label}: unbekannte Auswahl {x!r}")
        return out
