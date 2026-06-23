#!/usr/bin/env bash
# Build a self-contained NBEAST installer with conda `constructor`.
#
#   ./build_installer.sh [platform]      # platform defaults to osx-64
#
# Requires `constructor` on PATH (e.g. `conda install -n base constructor`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENVBIN="${NBEAST_ENVBIN:-$HOME/miniforge3/envs/nbeast/bin}"
PLATFORM="${1:-osx-64}"

mkdir -p "$HERE/dist"

echo ">>> [1/3] Building nbeast wheel"
"$ENVBIN/python" -m pip wheel "$REPO" --no-deps -w "$HERE/dist"

echo ">>> [2/3] Building curated data bundle (relative-path cross_sections.xml)"
"$ENVBIN/python" "$HERE/make_data_bundle.py" "$REPO/data" "$HERE/dist/nbeast_data.tar.gz"

echo ">>> [3/3] Running constructor for $PLATFORM"
CONDA_SUBDIR="$PLATFORM" constructor "$HERE" --platform "$PLATFORM" --output-dir "$HERE/dist"

echo ">>> Done. Installer(s):"
ls -la "$HERE/dist"/NBEAST-*.sh 2>/dev/null || true
