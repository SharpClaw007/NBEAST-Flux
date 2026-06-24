#!/usr/bin/env bash
# Build DAGMC natively for osx-arm64 (Phase 6, Stage B).
#
# conda-forge has no arm64 DAGMC (only linux-64 / osx-64). The feedstock is the
# older conda-build (meta.yaml) format with no arm64 variant, so we build it with
# conda-build on Apple Silicon (native osx-arm64), restricted to the minimal
# nompi/nodoubledown variant, against the conda-forge arm64 MOAB library.
#
# Requires conda-build (installed in base). Run on Apple Silicon.
# Usage: ./build_dagmc_arm64.sh [outdir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-/tmp/dagmc-arm64-build}"
CONDA="$HOME/miniforge3/bin/conda"

# Scrub Homebrew so the conda toolchain/CMake isn't shadowed (belt-and-suspenders
# with the -DCMAKE_IGNORE_PREFIX_PATH guard in recipe/build.sh).
env -u HOMEBREW_PREFIX -u HOMEBREW_CELLAR -u HOMEBREW_REPOSITORY \
    -u LIBRARY_PATH -u LDFLAGS -u CPPFLAGS -u CFLAGS -u CXXFLAGS \
    -u CMAKE_PREFIX_PATH -u PKG_CONFIG_PATH -u CPATH \
    PATH="$HOME/miniforge3/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    "$CONDA" build "$HERE/recipe" \
      -c conda-forge \
      --output-folder "$OUT" \
      --no-anaconda-upload

echo ">>> Built channel: $OUT"
find "$OUT" -name 'dagmc-*.conda' -o -name 'dagmc-*.tar.bz2'
