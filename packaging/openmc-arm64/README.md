# Native Apple Silicon OpenMC build

conda-forge ships **no `osx-arm64` OpenMC** — its build matrix includes DAGMC, and
DAGMC→MOAB have no arm64 build (the stalled upstream chain). We don't need DAGMC for
v1, and the **`nodagmc`/`nompi`** variant compiles cleanly natively. This directory
builds it ourselves so the macOS app runs **natively on Apple Silicon (no Rosetta)**.

## Build

```sh
conda install -n base -c conda-forge rattler-build
./build_openmc_arm64.sh            # → /tmp/openmc-arm64-build/osx-arm64/openmc-*.conda
```

This produces a local conda channel containing
`openmc-0.15.3-nodagmc_nompi_*.conda` for `osx-arm64`.

## Verified

Installed into a native arm64 env and ran Godiva:
`python arch = arm64`, `openmc executable = Mach-O arm64`, Godiva k ≈ 1.0.
Being `nompi`, it also avoids the mpich/OFI finalize abort the osx-64 (Rosetta)
build needed `FI_PROVIDER=tcp` to suppress.

## Gotcha: Homebrew leakage

On Apple Silicon, CMake auto-searches `/opt/homebrew` whenever that prefix exists
(true on dev machines *and* GitHub macOS runners). It would link Homebrew's `fmt`
and HDF5 instead of the conda build env's, leaving HDF5 symbols undefined at link.
`build_openmc_arm64.sh` patches the recipe `build.sh` to pass
`-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew`, which fixes both.

## Consuming in the installer

Point `construct.yaml` at this channel ahead of conda-forge to build a native arm64
installer:

```yaml
channels:
  - file:///tmp/openmc-arm64-build   # our native arm64 openmc
  - conda-forge
```

(Then `constructor packaging/ --platform osx-arm64`.) Upstreaming this as an
`osx-arm64` addition to the conda-forge openmc feedstock is the long-term fix.

## Phase 6 Stage C — DAGMC-enabled OpenMC (arm64)

v1 ships the `nodagmc` build above. For the CAD-geometry track we also build the
**`dagmc`** variant, linked against the native arm64 DAGMC (`../dagmc-arm64/`) and the
conda-forge arm64 MOAB:

```sh
./build_openmc_dagmc_arm64.sh /tmp/dagmc-arm64-build   # needs the Stage B channel
# → /tmp/openmc-dagmc-arm64-build/osx-arm64/openmc-0.15.3-dagmc_nompi_*.conda
```

Same recipe + Homebrew guard; `variant-dagmc.yaml` flips `dagmc: [dagmc]`, the local
DAGMC channel is added ahead of conda-forge, and the build compiles
`-DOPENMC_USE_DAGMC=ON`.

**Verified:** installs with the Stage B `dagmc 3.2.4` + conda-forge arm64 `moab`;
`import openmc` on `arm64`; `libopenmc.dylib` is Mach-O arm64 and links
`@rpath/libdagmc.dylib` + `@rpath/libMOAB.5.dylib`; `openmc.lib` loads the full native
chain at runtime and `openmc.DAGMCUniverse` is available. An end-to-end `.h5m` → k-eff
run is exercised in **Stage D** (once `cad_to_dagmc` produces a real geometry).
