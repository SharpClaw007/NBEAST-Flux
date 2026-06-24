# Phase 6 — Native Apple Silicon CAD geometry (implementation plan)

**Goal:** let a user import a CAD model, assign materials, mesh it, and run/visualise
it **natively on Apple Silicon** — i.e., bring DAGMC (CAD-based) geometry to NBEAST.

**Status:** PARKED until v1 is finished. Not started. This is the largest single
track in the roadmap.

## Why it's hard: the dependency chain

CAD geometry in OpenMC = **DAGMC**, which sits on **MOAB**. Neither has a usable
`osx-arm64` conda-forge build (the same gap we hit for OpenMC, but deeper — see the
upstream `moab-feedstock`/`dagmc-feedstock` discussion). Our entire v1 is the
`nodagmc` build specifically to avoid this. So Phase 6 is a **ground-up native-arm64
build of the whole stack**, then a CAD pipeline and UI on top.

```
MOAB (mesh/geometry kernel)            ← Stage A  (first domino, biggest unknown)
 ├── DAGMC (CAD geometry on MOAB)      ← Stage B
 │    └── dagmc-enabled OpenMC         ← Stage C
 └── cad_to_dagmc (STEP → .h5m)        ← Stage D  (needs MOAB + gmsh + OCP)
        └── GUI: import/assign/mesh/view ← Stage E
              └── packaging             ← Stage F
```

We've proven the *method* for this kind of build in `packaging/openmc-arm64/`:
restrict a conda-forge feedstock recipe to one arm64 variant, build with rattler-build,
and fix the Homebrew/CMake prefix leak (`-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew`).
Each stage below reuses that playbook.

## Stages

### Stage A — Native arm64 MOAB  ✅ DONE
**Built + validated** — see [`../packaging/moab-arm64/`](../packaging/moab-arm64/).
Findings that re-shaped this stage and the ones after:
- The **MOAB C++ library already ships for `osx-arm64`** on conda-forge (5.6.0) — so
  Stages B/C (which link the library) are already unblocked; no library rebuild needed.
- The only true gap was **pymoab** (Python bindings; conda-forge builds it nowhere).
  The MOAB release tarball ships only a **deprecated, broken** autotools pymoab path
  (references `paths.py` but never generates it), and `moab` isn't on PyPI.
- The fix: build from the **git repo via scikit-build-core** — it has the root
  `pyproject.toml` + `paths.py` and yields a self-contained `MOAB` wheel that bundles
  `libMOAB` under `pymoab/core/`. Built natively with the OpenMC-style Homebrew guard
  (`CMAKE_IGNORE_PREFIX_PATH=/opt/homebrew`).
- **Validated:** native `arm64` `import pymoab`, Mach-O arm64 `core.so` + bundled
  `libMOAB.dylib`, and an `.h5m` write/read round-trip.

### Stage B — Native arm64 DAGMC  ✅ DONE
**Built + validated** — see [`../packaging/dagmc-arm64/`](../packaging/dagmc-arm64/).
- Built `dagmc 3.2.4` (nompi/nodoubledown) for `osx-arm64` via **conda-build** (the
  feedstock is the older `meta.yaml` format), retargeting the osx-64 variant to arm64,
  against the conda-forge arm64 MOAB library.
- Two gotchas fixed: the compiler pins had to be carried over (else `c_osx-arm64` was
  unsatisfiable), and **`eigen` pinned to `3.*`** (conda-forge's Eigen 5.x breaks DAGMC
  3.2.4's matrix `operator[]`). Plus the usual Homebrew/CMake guard.
- **Validated:** `libdagmc.dylib` + `make_watertight` are Mach-O arm64, `make_watertight`
  runs, and it links the conda-forge arm64 `libMOAB`. (DoubleDown/embree skipped — not
  needed for dagmc-OpenMC.)

### Stage C — dagmc-enabled OpenMC (arm64)  ✅ DONE (build) / functional run → Stage D
**Built + validated** — see [`../packaging/openmc-arm64/`](../packaging/openmc-arm64/)
(`build_openmc_dagmc_arm64.sh` + `variant-dagmc.yaml`).
- Rebuilt OpenMC's **`dagmc`** variant for `osx-arm64` via rattler-build (flip
  `dagmc: [dagmc]`, `-DOPENMC_USE_DAGMC=ON`), linked against the Stage B DAGMC (local
  channel) + conda-forge arm64 MOAB. As predicted, the smallest stage — the recipe was
  already ours; only fix was putting `rattler-build` on PATH.
- **Validated:** `openmc-0.15.3-dagmc_nompi_*.conda` for arm64; resolves the Stage B
  `dagmc 3.2.4` + conda-forge arm64 `moab`; `import openmc` on `arm64`; `libopenmc.dylib`
  is Mach-O arm64 and links `libdagmc` + `libMOAB`; `openmc.lib` loads the full native
  chain at runtime; `DAGMCUniverse` available.
- **The functional `.h5m` → k-eff run is the Stage C↔D handoff** — it needs a real DAGMC
  geometry, which is exactly Stage D's output (`cad_to_dagmc`: STEP → `.h5m` → run).

### Stage D — CAD → DAGMC pipeline  ✅ DONE
**Built + validated end to end** — see [`../packaging/cad-dagmc-arm64/`](../packaging/cad-dagmc-arm64/).
- **`cad_to_dagmc`** (CadQuery/OCP + gmsh) on conda-forge **osx-arm64**. Key finding: it
  writes the `.h5m` via **h5py — no MOAB/pymoab needed**, so the CAD pipeline needs *no
  custom builds*. (The Stage A pymoab isn't on this path; still valid for other MOAB work.)
- Runs in its own env (it pins `numpy<=1.26.4`; dagmc-OpenMC is numpy 2) — the `.h5m` is
  passed as a file between gen + run, which also matches NBEAST's subprocess design.
- **Validated:** CadQuery HEU sphere (r=8.7 cm) → `sphere.h5m` → **k-eff = 0.984 ± 0.003**
  native arm64 — the expected near-critical value (Godiva radius 8.74 cm). This also
  **closes Stage C's functional `.h5m` → k-eff run**.

> **Phase 6 technical core complete:** custom CAD geometry → criticality runs natively on
> Apple Silicon (Stages A–D). Stages E–F are application work (GUI + packaging), not builds.

### Stage E — GUI integration  ✅ DONE (core) / viewport = optional polish
**Functional CAD feature wired into the app + validated end to end.**
- **Engine** — `nbeast.core.cad` orchestrates the three envs as subprocesses (the GUI
  runs in the nbeast env): `inspect_step` (count solids), `generate_h5m` (STEP → `.h5m`,
  cad env), `run_model` (`.h5m` → k-eff, dagmc-OpenMC env). `is_available()` gates the
  feature; env pythons discovered by name or `NBEAST_CAD_PYTHON`/`NBEAST_DAGMC_PYTHON`.
  Material presets + `material_specs()` map per-solid tags to run-ready material dicts.
- **GUI** — `gui/cad_import.py`: STEP picker, **per-solid material assignment** table,
  mesh-size + batches/particles controls, off-thread generate+run, k-eff readout. Wired
  into the File menu (shown only when the DAGMC envs exist); k-eff lands in the status bar.
- **Validated:** STEP → assign → mesh → run → **k-eff 0.984 ± 0.005**, orchestrated from
  the nbeast env. 31 tests pass (+ an opt-in `NBEAST_CAD_E2E` end-to-end).
- **3D CAD viewport ✅** — `FluxViewport.show_cad()` renders the imported solids
  (per-solid STLs from `cad.tessellate`) coloured by assigned material; a "Preview 3D"
  button drives it. Validated on a 2-solid pin (fuel + clad).
- **Flux spectrum ✅ + spatial flux map ✅** — CAD runs add a log-energy flux tally and a
  z-integrated regular-mesh tally over the geometry bounding box; the worker returns both
  as arrays (no VTK needed in the dagmc env) and the GUI shows the spectrum in the Spectrum
  view and the flux map in the 3D viewport (`show_field_array`). Validated on a bare-HEU
  sphere: fast spectrum, and a centre-peaked flux map (~8× centre/edge) — textbook for a
  bare critical sphere.

### Stage F — Packaging  ✅ DONE (mechanism) / publish = execution step
**Distribution mechanism authored + validated** — see [`../packaging/cad-support/`](../packaging/cad-support/).
Because the feature needs two numpy-incompatible envs, a single bundled installer doesn't
fit; CAD is an **optional Apple-Silicon add-on** (the app gates on `cad.is_available()`):
- `assemble_channel.sh` gathers the two custom artifacts (dagmc, dagmc-OpenMC — everything
  else is conda-forge) into an indexed conda channel.
- `setup_cad_support.sh <channel>` creates the `cad-arm64` + `openmc-dagmc-arm64` envs;
  NBEAST then auto-detects them.
- **Validated:** the channel assembles and a dry-run solve installs `openmc(dagmc)` +
  `dagmc` from it, `moab` from conda-forge.
- **Published ✅** — the channel is a release asset
  ([cad-channel-osx-arm64-1](https://github.com/SharpClaw007/NBEAST-Flux/releases/tag/cad-channel-osx-arm64-1));
  `setup_cad_support.sh` defaults to fetching it.
- **In-app setup ✅** — File ▸ Set up CAD geometry support… (`gui/cad_setup.py`) runs the
  setup off-thread with a live log when the envs are absent.
- **Remaining:** macOS **notarization** of the CAD envs (needs an Apple Developer ID).

## Effort & risk (rough)

| Stage | Effort | Risk |
|-------|--------|------|
| A MOAB     | ~days–1 week | **High** (static libs, recipe migration) |
| B DAGMC    | ~days        | Medium (embree on arm64) |
| C dagmc-OpenMC | ~1–2 days | Low (known recipe) |
| D CAD pipeline | ~1 week  | Medium (OCP/gmsh integration, watertight meshing) |
| E GUI      | ~1–2 weeks   | Medium (material-assignment UX, viewport) |
| F packaging| ~days        | Medium (size, separate installer) |

**Total: ~5–8 weeks of focused work.** Strictly sequential through A→C; D can start
once A lands; E/F follow. Stage A is the make-or-break first domino.

## Recommended kickoff
Start with **Stage A** exactly as we did OpenMC: clone `moab-feedstock`, write a single
`osx-arm64` variant config, apply the Homebrew-prefix fix, `rattler-build`, iterate on
build errors. If MOAB compiles and `pymoab` imports natively, the rest of the chain is
"known-hard but tractable." If MOAB fights us, that's the signal to weigh upstreaming
vs. a vendored build before sinking effort into B–F.
