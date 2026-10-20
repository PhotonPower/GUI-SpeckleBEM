# 05 Library interface

Calls into SpeckleBem, where they are made, and what was verified. Verified against SpeckleBem 0.1.0
(main fa856af), Linux build with OpenMP and BLAS (1 core, 3 GB), 2026-10-20; first verified at 62ece8b
(2026-10-15). The library reports 0.1.0 for every commit, so the worker probes features (`cmd_info`).

| Call | Used in | Verified |
|---|---|---|
| `sb.__version__`, `has_openmp`, `has_blas_lapack`, `has_cuda`; feature probes `AngularSpectrumBeam`, `RoughSurface` + `rough_surface_box_params`, `Simulation.with_pml` + `make_open_surface_mesh`, `"mlfmm" in Simulation.with_pml.__doc__` (WP-PML5a/5b), `plane_grid` + `Simulation.field`, `Simulation.incident_power` + `reflectance`, h5py + `Simulation.save` | `worker.cmd_info` / `library_features` | yes (fa856af: all true except hdf5 without h5py) |
| spdlog default logger on stdout (`[time] [warning] msg`, flushed per line) | `liblog.py` parses `run.log` → `status.library_messages` | format checked against fa856af log output |
| `default_box_depth`, `beam_waist_fraction`, `is_plasmonic`, `is_weakly_absorbing`, `exterior_wavelength`, `field_decay_length` | `worker.cmd_rules` | yes; `default_box_depth` raises for lossless objects (reported as `box_depth_error`) |
| `sb.vacuum`, `silicon_500nm`, `silver_500nm`, `sb.Material(eps_r=)`, `sb.DispersiveMaterial(λ, n−jk).at(λ)` | `plugins/materials.py` | vacuum, `Material`; Si/Ag tables by name; `DispersiveMaterial` path not run yet |
| `sb.PlaneWave(wavelength, direction, polarization=[vector], background)` | `excitations.py` | yes |
| `sb.AngularSpectrumBeam(..., region_radius=)`, `sb.GaussianBeam`, `sb.check_beam_waist(L, w0, incidence_angle=, max_fraction=)` | `excitations.py` | `AngularSpectrumBeam` yes (needs `region_radius` ≥ mesh extent, set from `meta.max_radius`); paraxial `GaussianBeam` and `check_beam_waist` not run separately |
| `sb.TriangleMesh(vertices, triangles)`, `.is_closed()` | `worker.cmd_run` | yes |
| `sb.Simulation(mesh, exc, object=, exterior=, solver=, compression=, formulation=, preconditioner=, mlfmm={"accuracy_digits"})`, `.solve(tol=, callback=)`, `.report()`, `.num_unknowns`, `.formulation`, `.save()` | `worker.cmd_run` | dense direct and dense GMRES yes; **MLFMM path not run in the GUI** (sandbox memory), `.save()` not run |
| `res.iterations`, `.converged`, `.true_relative_residual`, `.residual_history` | `worker.cmd_run` | yes |
| `sb.rough_surface_box_params(obj, bg, λ, σ, h, grading=)` → `.kwargs()`, `.beam_waist_fraction`, `.uniform_fallback`; `sb.RoughSurface(L, σ, Lc, h, seed, **kwargs)` → `.mesh`, heights | `plugins/geometry_rough.py` (`build_lib`) | yes (fa856af): L = 4.5 µm, h = 50 nm Si → 113 760 triangles, box 5.65 µm, fine band 3.54 µm; **docs/10 swaps `height_map` / `heights`** (the build returns the array as `height_map`, a `HeightMap` as `heights`; the GUI accepts both); a manual `box_depth` above which the automatic fine band ends raises `ValueError` (the GUI drops the band like the library's automatic rule) |
| `sim.incident_power()` (RuntimeError for a plane wave), `sim.reflectance(90, 180)` | `observables.DrcHemisphere` (G22) | names and behaviour from docs/10 (WP25), feature probe true on fa856af; not yet compared on a real solve |
| `sb.plane_grid(origin, u, v, nu, nv)` (full extents), `sim.field(points, kind=)` (R2 returns the total field; ValueError closer than 1e-3 h), `mie.scattered_E`, `mie.internal_E`, `exc.electric_field` | `observables.NearField` (G13) | yes (fa856af): sphere r = 300 nm, n = 1.5, h = 80 nm, tol 1e-4: max e = 0.026 outside beyond h/2 |
| `material.n` (complex, n − jk) | `observables.DrcHemisphere` (Fresnel reference for σ = 0) | yes (Si 500 nm: R₀ = 0.38772) |
| `sim.bistatic_rcs(theta, plane=)`, `sim.scattered_power(n_theta, n_phi)`, `sb.Mie(radius=, wavelength=, material=, exterior=)` `.bistatic_rcs(theta, phi)`, `.scattering_cross_section()` | `observables.BistaticRCS` | yes (σ(θ) 0.5 % vs Mie; C_sca matches); yz plane uses φ = π/2 for Mie, not independently verified |
| `sb.hemisphere_grid(-1, n_theta, n_phi)`, `.directions`, `.weights`, `sim.drc(dirs)`, `sim.drc(dirs, co_pol=)` | `observables.DrcHemisphere` | yes on a small dielectric trench (weights sum 2π; co/cross present); **no physical validation** |

Conventions of the contract that the GUI relies on: `Simulation` rejects meshes outside the controlled
region of an angular-spectrum beam (message names the required radius); `sim.report()` returns `str`;
`str(sim.formulation)` is `Formulation.ICTF` (the GUI strips the prefix).

Not connected yet: `io.save_hdf5`/`load_hdf5` beyond `Simulation.save`, `Simulation.with_pml` / `PmlTermination` / `make_open_surface_mesh` (PML route), `has_cuda` backends.
`sim.field` / `plane_grid` (near field), `io.save_hdf5`/`load_hdf5` beyond `Simulation.save`, `has_cuda` backends.
`sim.reflectance`, `io.save_hdf5`/`load_hdf5` beyond `Simulation.save`, `has_cuda` backends.
