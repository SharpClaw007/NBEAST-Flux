#!/usr/bin/env bash
# Build MOAB + pymoab natively for osx-arm64 (Phase 6, Stage A).
#
# conda-forge ships the MOAB *library* for arm64 but not pymoab (the Python
# bindings the CAD → .h5m pipeline needs). The MOAB release tarball ships only a
# deprecated, broken autotools pymoab path (no paths.py). The maintained build is
# scikit-build-core from the git repo: it produces a SELF-CONTAINED `MOAB` wheel
# that bundles libMOAB under pymoab/core (which pymoab/paths.py discovers at
# runtime). We build it into a dedicated native-arm64 conda env.
#
# Run on Apple Silicon. Usage: ./build_moab_arm64.sh
set -euo pipefail

CONDA="$HOME/miniforge3/bin/conda"
ENV="moab-arm64"
TAG="5.6.0"
SRC="/tmp/moab-src-${TAG}"

echo ">>> [1/3] native arm64 build env"
if ! "$CONDA" env list | grep -q "/envs/${ENV}$"; then
  "$CONDA" create -y -n "$ENV" -c conda-forge \
    python=3.12 numpy cython scikit-build-core cmake ninja pip pkg-config \
    c-compiler cxx-compiler fortran-compiler hdf5 eigen
else
  echo "    (env '$ENV' already exists — reusing)"
fi

echo ">>> [2/3] fetch MOAB ${TAG} from git (has the scikit-build pyproject + paths.py)"
rm -rf "$SRC"
git clone --depth 1 --branch "$TAG" https://bitbucket.org/fathomteam/moab.git "$SRC"

echo ">>> [3/3] build + install pymoab via scikit-build-core"
# shellcheck disable=SC1091
source "$HOME/miniforge3/etc/profile.d/conda.sh"
set +u                 # conda activation scripts reference unbound vars
conda activate "$ENV"
set -u
export CMAKE_PREFIX_PATH="$CONDA_PREFIX"
# CMAKE_IGNORE_PREFIX_PATH keeps CMake off Homebrew (the hazard that bit OpenMC).
pip install "$SRC" -v --no-build-isolation \
  --config-settings=cmake.define.ENABLE_HDF5=ON \
  --config-settings=cmake.define.ENABLE_PYMOAB=ON \
  --config-settings=cmake.define.CMAKE_IGNORE_PREFIX_PATH=/opt/homebrew

echo ">>> validate: native arm64 import + a basic mesh op (run from /tmp to avoid source shadowing)"
cd /tmp
python - <<'PY'
import platform
from pymoab import core, types
mb = core.Core()
verts = mb.create_vertices([0.,0.,0., 1.,0.,0., 0.,1.,0.])
print("machine          :", platform.machine())
print("pymoab Core      :", type(mb).__module__)
print("created vertices :", len(range(verts[0], verts[0] + 3)) if hasattr(verts, '__getitem__') else verts)
print("PYMOAB OK")
PY
