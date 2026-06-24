# CAD → DAGMC → OpenMC, native arm64 (Phase 6, Stage D)

The end of the CAD-geometry chain: turn a CAD model into a DAGMC `.h5m` and run it
through the native-arm64 dagmc-OpenMC (Stage C) — entirely on Apple Silicon.

## Key finding: no MOAB/pymoab needed here

`cad_to_dagmc` writes the DAGMC `.h5m` directly via **h5py** — its deps are
`cadquery, gmsh, h5py, networkx, numpy, ocp, python-gmsh, trimesh`, all on conda-forge
**osx-arm64**. So the CAD pipeline needs **no custom builds at all** (the Stage A pymoab
is not on this path; it remains available for other MOAB Python work).

## Two envs (numpy ABI)

`cad_to_dagmc` pins `numpy<=1.26.4`; the dagmc-OpenMC we built is numpy 2. So:

- **`cad-arm64`** (this dir's `setup_env.sh`) — generates the `.h5m`.
- **dagmc-OpenMC env** (Stage C) — runs the `.h5m`.

The `.h5m` is just a file passed between them — which also mirrors NBEAST's
subprocess-worker design (build geometry in one process, run in the worker).

## Validated end to end

```sh
./setup_env.sh                                   # create cad-arm64
conda run -n cad-arm64 python example_generate.py    # CadQuery HEU sphere -> sphere.h5m
# in the dagmc-OpenMC env, with OPENMC_CROSS_SECTIONS set:
python example_run.py                            # sphere.h5m -> k-eff
```

A CadQuery HEU sphere at r = 8.7 cm → `sphere.h5m` (50 KB) → **k-eff = 0.984 ± 0.003**,
native arm64. That's the expected near-critical value (Godiva's critical radius is
8.74 cm), so the whole chain — CAD meshing, DAGMC geometry, and transport — is correct.

This **closes Stage C's functional `.h5m` → k-eff run** and completes the Phase 6
*technical core*: **custom CAD geometry → criticality, natively on Apple Silicon.** What
remains is GUI integration (Stage E) and packaging (Stage F). See
[`../../docs/phase6-plan.md`](../../docs/phase6-plan.md).
