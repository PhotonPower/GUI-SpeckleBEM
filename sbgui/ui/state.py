"""Session state, cached bridge calls and the generic widgets that render any plugin schema."""

from __future__ import annotations

import copy
import json

import streamlit as st

from .. import bridge
from ..config import default_config
from ..registry import load_plugins

WKEY = "w:"  # prefix of every schema widget key (so they can be cleared in one go)


def bootstrap() -> dict:
    load_plugins()
    if "cfg" not in st.session_state:
        st.session_state.cfg = default_config()
    return st.session_state.cfg


def load_into_session(cfg: dict) -> None:
    """Replace the working config (e.g. 'use as template') and drop stale widget state."""
    cfg = copy.deepcopy(cfg)
    cfg["resolved"] = {}
    st.session_state.cfg = cfg
    for k in [k for k in st.session_state if str(k).startswith(WKEY)]:
        del st.session_state[k]


# ---- cached calls into the worker environment --------------------------------------------------
@st.cache_data(show_spinner="Bibliothek wird abgefragt …", ttl=300)
def lib_capabilities():
    return bridge.capabilities()


@st.cache_data(show_spinner="Regeln der Bibliothek werden abgefragt …", ttl=300)
def _lib_rules(key: str):
    return bridge.rules(json.loads(key))


def lib_rules(cfg: dict) -> dict | None:
    """Library rule values (box depth, waist fraction, ...) for the current optics/materials."""
    base = default_config()
    for k in ("optics", "mesh", "object", "background"):
        base[k] = cfg[k]
    return _lib_rules(json.dumps({k: base[k] for k in base if k != "resolved"}, sort_keys=True))


# ---- generic widgets ---------------------------------------------------------------------------
def _widget(f, values: dict, key: str):
    cur = values.get(f.key, f.default)
    if key not in st.session_state:
        st.session_state[key] = cur
    label = f"{f.label} [{f.unit}]" if f.unit not in ("", "-") else f.label
    if f.kind == "float":
        if not isinstance(st.session_state[key], float):
            st.session_state[key] = float(st.session_state[key])
        return st.number_input(label, min_value=f.min, max_value=f.max, step=f.step, key=key,
                               help=f.help or None, format="%g")
    if f.kind == "int":
        return st.number_input(label, min_value=int(f.min) if f.min is not None else None,
                               max_value=int(f.max) if f.max is not None else None,
                               step=int(f.step or 1), key=key, help=f.help or None)
    if f.kind == "choice":
        opts = [c[0] for c in f.choices]
        if st.session_state[key] not in opts:
            st.session_state[key] = f.default
        names = dict(f.choices)
        return st.selectbox(label, opts, format_func=lambda v: names[v], key=key, help=f.help or None)
    if f.kind == "bool":
        return st.checkbox(label, key=key, help=f.help or None)
    if f.kind == "text":
        return st.text_area(label, key=key, help=f.help or None, height=140)
    raise ValueError(f"unknown field kind {f.kind!r}")


def render_schema(schema, values: dict, prefix: str, columns: int = 2) -> None:
    """Render all visible fields of ``schema`` and write the entered values back into ``values``."""
    values.update(schema.fill(values))
    cols = st.columns(columns)
    i = 0
    for f in schema.fields:
        if not schema.is_visible(f, values):
            continue
        with cols[i % columns]:
            values[f.key] = _widget(f, values, f"{WKEY}{prefix}.{f.key}")
        i += 1


def plugin_picker(registry, spec: dict, prefix: str, label: str, only=None) -> type:
    """Selectbox for a plugin type plus the form of its parameters. Returns the chosen class."""
    ids = [i for i in registry.ids() if only is None or only(registry.get(i))]
    if spec["type"] not in ids:
        spec["type"], spec["params"] = ids[0], registry.get(ids[0]).schema().defaults()
    key = f"{WKEY}{prefix}.type"
    if key not in st.session_state:
        st.session_state[key] = spec["type"]
    chosen = st.selectbox(label, ids, format_func=lambda i: registry.get(i).label, key=key)
    if chosen != spec["type"]:
        for k in [k for k in st.session_state if str(k).startswith(f"{WKEY}{prefix}.p.")]:
            del st.session_state[k]
        spec["type"], spec["params"] = chosen, registry.get(chosen).schema().defaults()
    cls = registry.get(chosen)
    if cls.description:
        st.caption(cls.description)
    render_schema(cls.schema(), spec["params"], f"{prefix}.p")
    return cls


def show_issues(issues) -> bool:
    """Render issues; returns True if there is at least one blocking error."""
    blocking = False
    for i in issues:
        if i.level == "error":
            st.error(i.msg, icon="⛔")
            blocking = True
        elif i.level == "warning":
            st.warning(i.msg, icon="⚠️")
        else:
            st.info(i.msg, icon="ℹ️")
    return blocking


def show_library_messages(status: dict) -> None:
    """Warnings/errors the library logged during a run (parsed from run.log by the worker)."""
    for note in status.get("notes") or []:
        st.warning(note, icon="⚠️")
    msgs = status.get("library_messages") or []
    if not msgs:
        return
    with st.expander(f"Meldungen der Bibliothek ({len(msgs)})", expanded=True):
        for m in msgs:
            (st.error if m.get("level") == "error" else st.warning)(m.get("msg", ""), icon="📚")
