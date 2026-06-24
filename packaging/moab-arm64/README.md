# Native arm64 MOAB + pymoab (Phase 6, Stage A)

CAD geometry in OpenMC needs **DAGMC**, which needs **MOAB**. This builds MOAB with
its Python bindings (**pymoab**) natively for Apple Silicon — the first domino of
Phase 6.

## What was actually missing (and what wasn't)

- The **MOAB C++ library already ships for `osx-arm64`** on conda-forge (5.6.0). That
  already unblocks **DAGMC and dagmc-OpenMC** (Stages B/C), which link the library.
- The real gap is **pymoab** (the Python bindings the CAD → `.h5m` pipeline needs).
  conda-forge builds it **nowhere** — `moab-feedstock` produces only the library.
- The MOAB **release tarball** ships only a **deprecated, broken autotools** pymoab
  path: `pymoab/__init__.py` does `from .paths import *`, but the tarball contains no
  `paths.py` and no rule that generates it, so it can't import. `moab` is not on PyPI.
- The **maintained build is scikit-build-core, and it lives in the git repo** (the
  tarball strips the root `pyproject.toml` and `paths.py`). It produces a
  **self-contained `MOAB` wheel** that bundles `libMOAB` under `pymoab/core/`
  (discovered at runtime by `pymoab/paths.py`).

## What `build_moab_arm64.sh` does

1. Creates a native-arm64 conda env (`moab-arm64`) with the toolchain + `hdf5`/`eigen`.
2. Clones MOAB **5.6.0 from git** (which has the scikit-build `pyproject.toml` + `paths.py`).
3. `pip install` via **scikit-build-core**, with `CMAKE_IGNORE_PREFIX_PATH=/opt/homebrew`
   (the same Homebrew-leak guard the OpenMC arm64 build needed) and HDF5 found via
   `CMAKE_PREFIX_PATH`.
4. Validates natively: `import pymoab`, create a tet, and **write + read an `.h5m`**.

## Result (validated)

`import pymoab` works on `arm64`; `core.cpython-312-darwin.so` and the bundled
`libMOAB.dylib` are both **Mach-O arm64**; an `.h5m` mesh round-trips. Run on Apple
Silicon: `./build_moab_arm64.sh`.

## Next (Stage B onward)

The arm64 MOAB library (conda-forge) feeds a native **DAGMC** build (Stage B), then a
**dagmc-enabled OpenMC** (Stage C). This pymoab build feeds the **CAD → `.h5m`** pipeline
(`cad_to_dagmc`, Stage D). See [`../../docs/phase6-plan.md`](../../docs/phase6-plan.md).
