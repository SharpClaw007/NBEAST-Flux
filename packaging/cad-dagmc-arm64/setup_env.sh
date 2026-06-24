#!/usr/bin/env bash
# Create the native arm64 CAD → DAGMC env (Phase 6, Stage D).
#
# cad_to_dagmc writes the DAGMC .h5m via h5py (no MOAB/pymoab dependency), so the
# whole CAD pipeline is pure conda-forge arm64 — no custom builds. It pins
# numpy<=1.26.4, so geometry GENERATION lives in this env and the OpenMC RUN lives
# in the dagmc-OpenMC env (numpy 2); the .h5m file is passed between them.
set -euo pipefail
CONDA="$HOME/miniforge3/bin/conda"
"$CONDA" create -y -n cad-arm64 -c conda-forge \
  cad_to_dagmc cadquery gmsh python-gmsh ocp 'numpy<=1.26.4' python=3.12
echo ">>> cad-arm64 ready. Generate a geometry:  python example_generate.py"
