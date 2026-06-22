# Phase 0 — De-risk findings & architecture decisions

Status: **COMPLETE** (2026-06-22). All three spikes passed. Spike code lives in `spikes/`.

## Environment (pinned)

- **macOS Apple Silicon has no native OpenMC**: conda-forge ships `openmc 0.15.3` for
  `osx-64` and `linux-64` only — **not `osx-arm64`**. Dev therefore runs an **osx-64 env
  under Rosetta 2**. Linux x86-64 is native. Full pin set in `environment.yml`.
- Key versions: openmc 0.15.3, python 3.12, PySide6 6.11.1, pyvista 0.48.4, pyvistaqt
  0.11.4, pyqtgraph 0.14.0, vtk 9.6.2, openmc_data_downloader 0.6.1.

## Spike A — headless pin cell + curated data ✅

- UO₂/water PWR pin cell (3.2% enr., reflective BCs) runs headless: **k∞ = 1.4115 ± 0.0025**
  (physically sane; zero leakage as expected). ~4 s on this machine under Rosetta, 8 threads.
- **Curated data = 387 MB** for the full pin-cell nuclide set — well under the <1 GB budget.
- Data recipe (`spikes/fetch_data.py`), with workarounds discovered:
  - Neutron data from **ENDF/B-VIII.0**, fetched per-nuclide (the curated mechanism we want).
  - **S(α,β) `c_H_in_H2O` must come from ENDF/B-7.1** — the 8.0 thermal-scattering asset
    URLs in `openmc_data_downloader` 0.6.1 return **404**. (Mixing 7.1 S(α,β) with 8.0
    neutron data is acceptable for teaching.)
  - Enrichment expansion needs **U234/235/236/238** — enumerate nuclides explicitly; don't
    rely on whole-element (`-e`) expansion.
  - The downloader rewrites `cross_sections.xml` per call, so build one unified library from
    all `.h5` files via `openmc.data.DataLibrary`.

## Spike B — subprocess streaming worker ✅

The chosen run-isolation architecture is validated (`spikes/worker.py` + `run_worker.py`):

- Worker runs the `openmc.lib` batch loop (`simulation_init` → `iter_batches` → `keff` →
  `simulation_finalize`) and emits **one JSON event per batch**.
- **Channel separation**: structured JSON on **stderr**, OpenMC's own log on **stdout**
  (discarded by the parent, but available for a future console pane). Clean and robust.
- **Live streaming** of k-eff per batch confirmed; final value matches Spike A exactly.
- **Clean cancellation**: SIGTERM → worker finishes the in-flight batch and exits **0**.
- **`FI_PROVIDER=tcp` is required** in the worker env, or conda's mpich OFI provider aborts
  at finalize on macOS (`nic=bridge101`) and returns a spurious non-zero exit.
- **Shannon entropy is NOT exposed by `openmc.lib`.** Options for the live monitor: parse
  OpenMC stdout (it prints entropy per generation when an entropy mesh is set) or read
  `StatePoint.entropy` post-run. **Decision deferred to Phase 2** when we build the monitor.

## Spike C — embedded 3D viz ✅ (core)

- Flux **mesh tally → OpenMC VTK writer → pyvista render → PNG** works
  (`spikes/flux_mesh.py`). Mesh-cell ordering handled by OpenMC's writer.
- OpenMC's VTK writer outputs **volume-normalized** flux (flux density). Decide deliberately
  in Phase 3 whether the UI shows raw flux or flux density.
- The embedded **`pyvistaqt.QtInteractor` segfaults under headless `QT_QPA_PLATFORM=offscreen`**
  (no GL context) — an automation-environment artifact, not a code issue. The in-window
  widget will be verified in Phase 2/3 on a real display.

## Confirmed decisions

- **Subprocess worker** architecture is sound — proceed with it for Phase 1+.
- **Curated bundled data** is viable within the size budget.
- Stack (PySide6 + pyvista/pyvistaqt + pyqtgraph + `openmc.lib`) imports and runs together.

## Open risks carried forward

1. **macOS arm64 distribution** (task #5): decide before Phase 5 — Rosetta osx-64 vs native
   source build vs contributing an `osx-arm64` conda-forge feedstock build.
2. **Data-source reliability**: `openmc_data_downloader` is flaky (dead S(α,β) URLs). For v1,
   evaluate downloading the official ENDF/B-VIII.0 library once and curating the subset
   ourselves for a controlled, reproducible bundle.
3. **Live entropy** streaming approach — settle in Phase 2.

## macOS arm64 — investigated & decided (2026-06-22)

Read the conda-forge `openmc-feedstock` (`recipe/recipe.yaml`, rattler-build) and its arm64
PRs/issues. Conclusions:

- The recipe's only `skip:` entries are **`win`** and **`python <3.11`** — arm64 is *not*
  excluded for any technical reason. The OpenMC compile is portable C++17 (vendored
  pugixml/xtensor/fmt/Catch2).
- The real blocker is **DAGMC**: conda-forge's openmc matrix builds dagmc variants, and
  `dagmc` → `moab` lack full arm64 support. Fixing it "properly" is a stalled multi-feedstock
  chain (issue #87, PR #81, draft #86; open since 2025).
- **We don't use DAGMC.** Our target is `nodagmc`/`nompi`. PR #81 (by OpenMC maintainer
  kkiesling) already produced a *working* nodagmc arm64 build by dropping the dagmc variants.
- All our run-deps have osx-arm64 builds: njoy2016, ncrystal, mcpl, endf, uncertainties,
  hdf5, h5py.

**Decision:** before Phase 5, build our own **nodagmc/nompi osx-arm64** OpenMC conda package
(current `recipe.yaml` minus the dagmc variant axis) on free GitHub Actions arm64 macOS
runners → our own channel → consumed by constructor. Small, controllable packaging delta;
no dependence on the stalled upstream DAGMC chain. Optional parallel: revive PR #81 scoped to
nodagmc-arm64 as an upstream contribution (not on the critical path). Dev stays on Rosetta
osx-64 until then. See task #5.
