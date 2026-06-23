#!/usr/bin/env bash
# Build a self-contained NBEAST installer with conda `constructor`.
#
#   ./build_installer.sh [platform]      # osx-arm64 (default) | linux-64
#
# The version comes from nbeast.__version__ (single source of truth); this script
# generates construct.yaml from construct.yaml.in. For osx-arm64 it uses a local
# native OpenMC channel (built via openmc-arm64/, or $NBEAST_ARM64_CHANNEL).
#
# Requires `constructor` on PATH (conda install -n base constructor).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENVBIN="${NBEAST_ENVBIN:-$HOME/miniforge3/envs/nbeast/bin}"
PLATFORM="${1:-osx-arm64}"
mkdir -p "$HERE/dist"

VERSION="$("$ENVBIN/python" -c 'import nbeast; print(nbeast.__version__)')"
echo ">>> NBEAST $VERSION  ($PLATFORM)"

echo ">>> [1/4] wheel"
rm -f "$HERE/dist"/nbeast-*.whl
"$ENVBIN/python" -m pip wheel "$REPO" --no-deps -w "$HERE/dist"

echo ">>> [2/4] curated data bundle"
"$ENVBIN/python" "$HERE/make_data_bundle.py" "$REPO/data" "$HERE/dist/nbeast_data.tar.gz"

EXTRA_CHANNEL=""
if [ "$PLATFORM" = "osx-arm64" ]; then
  CHANNEL="${NBEAST_ARM64_CHANNEL:-$HERE/dist/arm64-channel}"
  if [ ! -d "$CHANNEL/osx-arm64" ]; then
    echo ">>> [3/4] building native arm64 OpenMC channel"
    bash "$HERE/openmc-arm64/build_openmc_arm64.sh" /tmp/openmc-feedstock "$CHANNEL"
  else
    echo ">>> [3/4] reusing arm64 OpenMC channel: $CHANNEL"
  fi
  EXTRA_CHANNEL="  - file://$CHANNEL"
else
  echo ">>> [3/4] OpenMC from conda-forge ($PLATFORM)"
fi

echo ">>> [4/4] render construct.yaml + run constructor"
sed -e "s|@VERSION@|$VERSION|g" -e "s|@EXTRA_CHANNEL@|$EXTRA_CHANNEL|" \
    "$HERE/construct.yaml.in" > "$HERE/construct.yaml"
CONDA_SUBDIR="$PLATFORM" constructor "$HERE" --platform "$PLATFORM" --output-dir "$HERE/dist"

echo ">>> Done:"
ls -la "$HERE/dist"/NBEAST-*.sh 2>/dev/null || true
