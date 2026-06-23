#!/usr/bin/env bash
# Build a NATIVE osx-arm64 OpenMC (nodagmc/nompi) conda package with rattler-build.
#
# conda-forge has no osx-arm64 OpenMC (its build matrix includes DAGMC, which lacks
# an arm64 build). We reuse the feedstock recipe but build only the nodagmc/nompi
# variant for arm64 — which compiles cleanly. Output is a local conda channel that
# the constructor installer can consume for a native Apple Silicon build.
#
# Requires: rattler-build  (conda install -n base -c conda-forge rattler-build)
# Run on an Apple Silicon machine. Usage: ./build_openmc_arm64.sh [workdir] [outdir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:-/tmp/openmc-feedstock}"
OUT="${2:-/tmp/openmc-arm64-build}"

echo ">>> [1/4] Fetch conda-forge openmc-feedstock recipe"
rm -rf "$WORK"
git clone --depth 1 https://github.com/conda-forge/openmc-feedstock "$WORK"

echo ">>> [2/4] Install our single arm64 nodagmc/nompi variant"
cp "$HERE/variant.yaml" "$WORK/.ci_support/osx_arm64_nodagmc_nompi_py312.yaml"

echo ">>> [3/4] Patch build.sh: ignore Homebrew prefix"
# On Apple Silicon, CMake auto-searches /opt/homebrew (it exists on dev machines and
# GitHub runners) and would link Homebrew's fmt/HDF5 instead of the conda env's,
# leaving HDF5 symbols undefined. Make CMake ignore that prefix.
if ! grep -q CMAKE_IGNORE_PREFIX_PATH "$WORK/recipe/build.sh"; then
  sed -i '' \
    's#export CONFIGURE_ARGS=""#export CONFIGURE_ARGS="-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew"#' \
    "$WORK/recipe/build.sh"
fi

echo ">>> [4/4] Build (native arm64)"
rattler-build build \
  -r "$WORK/recipe/recipe.yaml" \
  -m "$WORK/.ci_support/osx_arm64_nodagmc_nompi_py312.yaml" \
  --target-platform osx-arm64 \
  --ignore-recipe-variants \
  --test skip \
  -c conda-forge \
  --output-dir "$OUT"

echo ">>> Built channel at: $OUT"
find "$OUT" -name 'openmc-*.conda'
