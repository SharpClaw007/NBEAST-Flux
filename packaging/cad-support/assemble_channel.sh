#!/usr/bin/env bash
# Assemble a local conda channel of the custom arm64 CAD artifacts (Phase 6, Stage F).
#
# conda-forge provides everything EXCEPT the two packages we built ourselves:
# dagmc (Stage B) and dagmc-enabled OpenMC (Stage C). This gathers them into a
# channel that setup_cad_support.sh (or a published release) installs from. The
# moab library and the whole CAD env (cad_to_dagmc/OCP/gmsh) come from conda-forge.
#
# Usage: ./assemble_channel.sh [channel_dir] [dagmc_build] [openmc_dagmc_build]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANNEL="${1:-$HERE/channel}"
DAGMC_BUILD="${2:-/tmp/dagmc-arm64-build}"
OPENMC_BUILD="${3:-/tmp/openmc-dagmc-arm64-build}"
CONDA="$HOME/miniforge3/bin/conda"

mkdir -p "$CHANNEL/osx-arm64"
cp "$DAGMC_BUILD"/osx-arm64/dagmc-*.conda "$CHANNEL/osx-arm64/"
cp "$OPENMC_BUILD"/osx-arm64/openmc-*dagmc*.conda "$CHANNEL/osx-arm64/"
"$CONDA" index "$CHANNEL"

echo ">>> Channel assembled at: $CHANNEL"
ls "$CHANNEL/osx-arm64"/*.conda
echo ">>> Publish this directory (e.g. attach to a GitHub release) and point"
echo "    setup_cad_support.sh at it."
