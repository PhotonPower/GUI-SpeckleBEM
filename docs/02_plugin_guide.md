# 02 Plugin guide

A plugin is one class with an `id`, a `label`, `fields` and the methods of its kind. Put the module into
`sbgui/plugins/`; it is imported automatically (`registry.load_plugins`). Third-party packages can register
through the `sbgui.plugins` entry-point group.

Rules: module-level imports are stdlib and numpy only (gmsh, plotly, specklebem inside methods); the same
module is loaded by the GUI and by the worker, whose environments differ. Methods receive SI dictionaries.

## Fields

```python
Field(key, label, kind="float|int|choice|bool|text", default, unit="nm|µm|mm|deg|-|",
      min=None, max=None, step=None, choices=((value, label), ...), help="", visible_if=lambda v: ...)
```

The schema renders the form, checks the ranges (`Schema.errors`) and converts floats with a unit to SI
(`Schema.to_si`). Config files hold the display values.

## Geometry (`base.Geometry`, runs in the GUI/job process)

| Member | Purpose |
|---|---|
| `kind` | `"object"` (isolated body, plane wave, bistatic RCS) or `"substrate"` (patch with closing box, beam, DRC) |
| `meta_hint(p)` | `{"kind", "lateral_size"}` without meshing (used by excitation checks) |
| `resolve(p, rules)` | fill values that depend on library rules (e.g. automatic box depth) |
| `validate(p, ctx)` | list of `Issue("error"/"warning"/"info", text)`; `ctx` has wavelength, h, meta, rules |
| `estimate_triangles(p, h)` | cost panel before meshing |
| `build(p, h)` | `MeshResult(vertices[m], triangles, meta)`; closed, normals out of the object, library frame |
| `outline(p)` | optional 2-D preview `{"x", "z", "title"}` |

`meta` may carry `mie_sphere: {"radius": r}`; the bistatic observable then compares with Mie automatically.

### Library-made meshes (`mesher = "library"`, G21)

Some meshes are made by the library itself (rough surfaces, open surfaces for the PML route). Such a
geometry sets `mesher = "library"` and implements `build_lib(sb, p, h, ctx)` instead of `build`; it runs in
the worker, `ctx` has `wavelength`, `h`, `rules` and the library materials `object` / `background`. It
returns a `base.LibraryMesh(result, handle, route)`: `result` is a `MeshResult` (vertices/triangles in the
library frame, JSON meta incl. `kind` and `lateral_size`; `open_surface: True` for open meshes),
`handle` the library object handed to the `Simulation`, `route` `"closed"` (`sb.Simulation`) or `"pml"`
(`sb.Simulation.with_pml`). `meta_hint`, `estimate_triangles` and `validate` stay pure Python (GUI side).
The job runner skips meshing for these geometries; the worker writes `mesh.npz` itself and runs the
pre-flight checks on the real mesh. The model page previews through `bridge.preview_mesh` (worker
command `mesh`), so the preview needs a reachable library.

## Material / Excitation (worker side `build`)

`Material.build(sb, p, wavelength)` returns a library material (`sb.Material`, ...). Optics-style input
n + ik is converted to the library convention n - jk. `Excitation.build(sb, p, ctx, background)` returns a
library excitation; `ctx` has wavelength, meta (incl. `max_radius`), rules. Both can add `validate`.

## Observable

`compute(sb, sim, p, ctx)` runs in the worker and returns numpy arrays/floats/strings (stored as
`obs<i>__<key>`). `figures(data, ctx)` runs in the GUI and returns Plotly figures from those arrays (it must
not need the library). Optional static `summary(data)` returns metrics for the header. `applies_to` selects
the geometry kinds it is offered for.

## Example: cylinder (object)

```python
@GEOMETRIES.register
class Cylinder(Geometry):
    id = "cylinder"; label = "Zylinder"; kind = "object"
    fields = (Field("radius", "Radius", "float", 200.0, "nm", min=10, max=5000),
              Field("height", "Höhe", "float", 300.0, "nm", min=10, max=5000))
    def meta_hint(self, p): return {"kind": "object", "lateral_size": 2 * p["radius"]}
    def estimate_triangles(self, p, h): ...
    def build(self, p, h): ...   # vertices, triangles, meta
```

## Test checklist for a new plugin

1. Schema defaults pass `Schema.errors`.
2. `validate` returns an error for an impossible parameter set and nothing for the defaults.
3. Build test: `mesh_stats(...)["closed"]`, positive volume, volume equals the analytic value (see
   `tests/test_geometry.py`), `estimate_triangles` within a factor ~1.6 of the real count.
4. If the plugin needs new library calls: add them to `docs/05_library_interface.md` with the version they
   were verified against.
