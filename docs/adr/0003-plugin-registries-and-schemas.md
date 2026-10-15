# ADR 0003 — Plugin registries with declarative parameter schemas

Status: accepted (2026-10-15)

## Context
The library grows (PML route, near fields, speckle statistics, more geometries). Hard-coded forms would need a
page rewrite for every addition.

## Decision
Four registries (geometry, material, excitation, observable). A plugin declares `Field`s once; the schema
renders the widgets, checks ranges and converts to SI. Discovery by importing `sbgui/plugins/*` and the
`sbgui.plugins` entry-point group. Plugin methods are split by process (`build`/`compute` in the worker,
`figures` in the GUI).

## Consequences
+ a new geometry or observable is one file; forms, checks, cost panel, config and results page follow
− forms are generic (grid of fields); special layouts need a new widget kind
− plugin modules must stay free of heavy top-level imports (ADR 0001)
