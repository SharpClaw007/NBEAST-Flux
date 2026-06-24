# Native arm64 DAGMC (Phase 6, Stage B)

DAGMC (Direct Accelerated Geometry Monte Carlo) is the CAD-geometry engine OpenMC
links for `.h5m` models. conda-forge ships it for `linux-64` / `osx-64` but **not
`osx-arm64`**. This builds it natively for Apple Silicon, on top of the conda-forge
arm64 MOAB library (the lib already exists for arm64 — see `../moab-arm64/`).

## Approach

The `dagmc-feedstock` uses the older **conda-build (`meta.yaml`)** format with no arm64
variant, so we build it with **conda-build** on Apple Silicon (native osx-arm64),
restricted to the minimal **nompi / nodoubledown** variant (no MPI, no DoubleDown/embree
— exactly what dagmc-OpenMC needs). `build_dagmc_arm64.sh` runs the build; `recipe/` is
the vendored feedstock recipe with three arm64 adaptations:

1. **`conda_build_config.yaml`** — the feedstock's osx-64 nodoubledown/nompi config
   retargeted to arm64 (deployment target 11.0, `arm64-apple-darwin20.0.0`). Without the
   compiler pins, `{{ compiler('c') }}` resolved to an unsatisfiable `c_osx-arm64`.
2. **`meta.yaml`** — pin **`eigen 3.*`**. conda-forge moved to Eigen 5.x, whose stricter
   `operator[]` checks break DAGMC 3.2.4 (`THE_BRACKET_OPERATOR_IS_ONLY_FOR_VECTORS` on a
   3×3 matrix). DAGMC 3.2.4 predates Eigen 5.
3. **`build.sh`** — add `-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew` (the Homebrew/CMake
   leak guard from the OpenMC + MOAB builds); in-build tests made non-fatal for the port.

## Result (validated)

`dagmc-3.2.4-nompi_nodoubledown_*.conda` for **osx-arm64**. Installed into a fresh env it
pulls the conda-forge arm64 `moab` (`nompi_notempest`) and:
`libdagmc.dylib` + `make_watertight` are **Mach-O arm64**, `make_watertight --help` runs,
and it links the arm64 `libMOAB`. Run on Apple Silicon: `./build_dagmc_arm64.sh`.

## Next (Stage C)

Rebuild OpenMC's **`dagmc`** variant for `osx-arm64` against this DAGMC + the arm64 MOAB,
so OpenMC can run `.h5m` CAD geometry natively. See
[`../../docs/phase6-plan.md`](../../docs/phase6-plan.md).
