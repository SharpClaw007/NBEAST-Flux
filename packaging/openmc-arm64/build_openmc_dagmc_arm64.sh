#!/usr/bin/env bash
# Build a NATIVE osx-arm64 OpenMC with DAGMC enabled (Phase 6, Stage C).
#
# Same feedstock recipe as the nodagmc build, but the dagmc variant: links the
# Stage B arm64 DAGMC (from a local channel) + conda-forge arm64 MOAB and compiles
# -DOPENMC_USE_DAGMC=ON, so OpenMC can run .h5m CAD geometry natively on Apple
# Silicon. Output is a local conda channel (separate from the nodagmc build).
#
# Requires: rattler-build, and the Stage B DAGMC channel. Run on Apple Silicon.
# Usage: ./build_openmc_dagmc_arm64.sh [dagmc_channel] [workdir] [outdir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAGMC_CHANNEL="${1:-/tmp/dagmc-arm64-build}"
WORK="${2:-/tmp/openmc-feedstock}"
OUT="${3:-/tmp/openmc-dagmc-arm64-build}"

echo ">>> [1/4] Fetch conda-forge openmc-feedstock recipe"
rm -rf "$WORK"
git clone --depth 1 https://github.com/conda-forge/openmc-feedstock "$WORK"

echo ">>> [2/4] Install our single arm64 dagmc/nompi variant"
cp "$HERE/variant-dagmc.yaml" "$WORK/.ci_support/osx_arm64_dagmc_nompi_py312.yaml"

echo ">>> [3/4] Patch build.sh: ignore Homebrew prefix (Apple Silicon CMake leak)"
if ! grep -q CMAKE_IGNORE_PREFIX_PATH "$WORK/recipe/build.sh"; then
  sed -i '' \
    's#export CONFIGURE_ARGS=""#export CONFIGURE_ARGS="-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew"#' \
    "$WORK/recipe/build.sh"
fi

echo ">>> [4/4] Build (native arm64, DAGMC enabled) using DAGMC channel: $DAGMC_CHANNEL"
# Scrub Homebrew + put the conda toolchain (incl. rattler-build) on PATH.
env -u HOMEBREW_PREFIX -u HOMEBREW_CELLAR -u HOMEBREW_REPOSITORY \
    -u LIBRARY_PATH -u LDFLAGS -u CPPFLAGS -u CFLAGS -u CXXFLAGS \
    -u CMAKE_PREFIX_PATH -u PKG_CONFIG_PATH -u CPATH \
    PATH="$HOME/miniforge3/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    rattler-build build \
      -r "$WORK/recipe/recipe.yaml" \
      -m "$WORK/.ci_support/osx_arm64_dagmc_nompi_py312.yaml" \
      --target-platform osx-arm64 \
      --ignore-recipe-variants \
      --test skip \
      -c "$DAGMC_CHANNEL" \
      -c conda-forge \
      --output-dir "$OUT"

echo ">>> Built channel at: $OUT"
find "$OUT" -name 'openmc-*dagmc*.conda'
