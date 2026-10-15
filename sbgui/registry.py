"""Plugin registries.

Extending the GUI = writing one class and decorating it, e.g.::

    @GEOMETRIES.register
    class MyShape(Geometry):
        id = "my_shape"; label = "Meine Form"; fields = (Field(...),)
        def build(self, p, h): ...

Modules in ``sbgui/plugins/`` are imported automatically; third-party packages can add
plugins through the ``sbgui.plugins`` entry-point group. Rule for plugin modules: only
stdlib and numpy at import time (gmsh, plotly, specklebem are imported inside methods), so
that the same module can be loaded by the GUI process and by the worker process, which have
different Python environments.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import ClassVar

from .params import Field, Schema


class Plugin:
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    fields: ClassVar[tuple[Field, ...]] = ()

    @classmethod
    def schema(cls) -> Schema:
        return Schema(cls.fields)


class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, type[Plugin]] = {}

    def register(self, cls):
        if not cls.id:
            raise ValueError(f"{cls.__name__}: plugin needs a non-empty `id`")
        if cls.id in self._items and self._items[cls.id] is not cls:
            raise ValueError(f"{self.kind} plugin id {cls.id!r} registered twice")
        self._items[cls.id] = cls
        return cls

    def get(self, plugin_id: str):
        try:
            return self._items[plugin_id]
        except KeyError:
            raise KeyError(
                f"unknown {self.kind} plugin {plugin_id!r}; available: {sorted(self._items)}"
            ) from None

    def ids(self) -> list[str]:
        return list(self._items)

    def all(self) -> list[type[Plugin]]:
        return list(self._items.values())


GEOMETRIES = Registry("geometry")
MATERIALS = Registry("material")
EXCITATIONS = Registry("excitation")
OBSERVABLES = Registry("observable")

_loaded = False


def load_plugins() -> None:
    """Import every module in ``sbgui.plugins`` and every ``sbgui.plugins`` entry point."""
    global _loaded
    if _loaded:
        return
    from . import plugins

    for m in pkgutil.iter_modules(plugins.__path__):
        importlib.import_module(f"{plugins.__name__}.{m.name}")
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="sbgui.plugins"):
            ep.load()
    except Exception:  # a broken third-party plugin must not take the GUI down
        import traceback

        traceback.print_exc()
    _loaded = True
