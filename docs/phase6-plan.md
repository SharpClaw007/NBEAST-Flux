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

### Stage C — dagmc-enabled OpenMC (arm64)
- Rebuild OpenMC's **`dagmc`** variant for `osx-arm64` (same recipe we already use,
  with `dagmc=dagmc`, against the Stage-B DAGMC). Smallest stage — we know this recipe.
- **Done when:** OpenMC runs a DAGMC `.h5m` model natively → sane k-eff.

### Stage D — CAD → DAGMC pipeline
- Use **`cad_to_dagmc`** (open-source: CadQuery/**OCP** + **gmsh** + pymoab) to turn a
  **STEP** file into a watertight DAGMC `.h5m`. All deps are on conda-forge arm64 once
  Stage A provides MOAB. (Avoids proprietary Cubit/Coreform.)
- **Done when:** STEP → `.h5m` → an OpenMC run, native arm64, end to end.

### Stage E — GUI integration
- **CAD import**: file picker (STEP/BREP), per-volume **material assignment** (a new
  UI — map CAD solids to the materials library), mesh-resolution controls → `cad_to_dagmc`.
- **Engine**: a `CADModel` in `nbeast.core` that builds an OpenMC DAGMC universe from
  the `.h5m`; the existing tally/results/runner pipeline works unchanged on it.
- **Viewport**: render the CAD surface mesh in the pyvista viewport (it reads the mesh).
- **Done when:** import a STEP file → assign materials → mesh → run → flux/spectrum/tracks.

### Stage F — Packaging
- Bundle the DAGMC stack + CAD pipeline (OCP, gmsh, cad_to_dagmc, dagmc-OpenMC, MOAB,
  DAGMC). This is **heavy** (OCP alone is hundreds of MB) → likely a separate
  **"NBEAST-CAD"** installer or an optional in-app download rather than the default.
- Extend the release workflow for the longer dagmc build chain.

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
