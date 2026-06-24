#!/usr/bin/env bash
# Set up CAD geometry support for NBEAST on Apple Silicon (Phase 6, Stage F).
#
# Creates the two native-arm64 conda envs the CAD feature needs. They can't be one
# env: cad_to_dagmc pins numpy<=1.26.4 while dagmc-OpenMC is numpy 2. NBEAST runs
# in its own env and orchestrates these two as subprocesses; once they exist it
# auto-enables File > Import CAD geometry (nbeast.core.cad.is_available()).
#
# With no argument it fetches the published channel; or pass a tarball URL, a local
# tarball, or a local channel dir.
#   ./setup_cad_support.sh
#   ./setup_cad_support.sh https://.../nbeast-cad-channel-osx-arm64.tar.gz
#   ./setup_cad_support.sh ./channel
set -euo pipefail

CONDA="$HOME/miniforge3/bin/conda"
DEFAULT_URL="https://github.com/SharpClaw007/NBEAST-Flux/releases/download/cad-channel-osx-arm64-1/nbeast-cad-channel-osx-arm64.tar.gz"
SOURCE="${1:-$DEFAULT_URL}"

# Resolve SOURCE to a local channel directory.
if [[ "$SOURCE" == *.tar.gz ]]; then
  tmp="$(mktemp -d)"
  if [[ "$SOURCE" == http* ]]; then
    echo ">>> downloading channel: $SOURCE"
    curl -fL --retry 3 -o "$tmp/channel.tar.gz" "$SOURCE"
  else
    cp "$SOURCE" "$tmp/channel.tar.gz"
  fi
  tar -xzf "$tmp/channel.tar.gz" -C "$tmp"
  CHANNEL="$tmp/channel"
else
  CHANNEL="$SOURCE"
fi

echo ">>> [1/2] CAD env (cad-arm64): STEP -> .h5m   (pure conda-forge)"
"$CONDA" create -y -n cad-arm64 -c conda-forge \
  cad_to_dagmc cadquery gmsh python-gmsh ocp 'numpy<=1.26.4' python=3.12

echo ">>> [2/2] dagmc-OpenMC env (openmc-dagmc-arm64): run .h5m   (custom channel + conda-forge)"
"$CONDA" create -y -n openmc-dagmc-arm64 -c "$CHANNEL" -c conda-forge \
  'openmc=0.15.3=dagmc_nompi_*' 'dagmc=3.2.4=nompi_nodoubledown_*' python=3.12

echo ">>> CAD support ready. NBEAST will detect it on next launch"
echo "    (File > Import CAD geometry). Override env locations with"
echo "    NBEAST_CAD_PYTHON / NBEAST_DAGMC_PYTHON if you used different names."
