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
