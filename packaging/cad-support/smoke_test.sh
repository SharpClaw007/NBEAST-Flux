#!/usr/bin/env bash
# Phase 6 smoke test — Stages A-F. Exercises the native-arm64 CAD stack end to end.
# Expects the envs created by packaging/{moab,dagmc,openmc}-arm64 + cad-support
# (moab-arm64, openmc-dagmc-arm64, cad-arm64) and the nbeast dev env, under
# $HOME/miniforge3. Run on Apple Silicon.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
ENVS="$HOME/miniforge3/envs"
DATA="$REPO/data/cross_sections.xml"
PASS=0; FAIL=0
ok(){ echo "  PASS — $1"; PASS=$((PASS+1)); }
no(){ echo "  FAIL — $1"; FAIL=$((FAIL+1)); }

echo "=== Stage A: native arm64 MOAB + pymoab ==="
cd /tmp && "$ENVS/moab-arm64/bin/python" - <<'PY'
import platform
from pymoab import core, types
assert platform.machine() == "arm64", platform.machine()
mb = core.Core()
v = mb.create_vertices([0.,0.,0., 1.,0.,0., 0.,1.,0., 0.,0.,1.])
mb.create_element(types.MBTET, v)
mb.write_file("/tmp/sm_a.h5m")
core.Core().load_file("/tmp/sm_a.h5m")
PY
[ $? -eq 0 ] && ok "pymoab import + .h5m round-trip (arm64)" || no "pymoab"

echo "=== Stage B: native arm64 DAGMC ==="
DENV="$ENVS/openmc-dagmc-arm64"
file "$DENV/lib/libdagmc.dylib" 2>/dev/null | grep -q arm64 && ok "libdagmc.dylib is Mach-O arm64" || no "libdagmc arm64"
file "$DENV/bin/make_watertight" 2>/dev/null | grep -q arm64 && ok "make_watertight present + arm64" || no "make_watertight"
"$DENV/bin/make_watertight" --help >/dev/null 2>&1; [ $? -le 1 ] && ok "make_watertight executes" || no "make_watertight run"

echo "=== Stage C: dagmc-enabled OpenMC (arm64) ==="
cd /tmp && "$DENV/bin/python" - <<'PY'
import platform, openmc, openmc.lib
assert platform.machine() == "arm64"
openmc.lib._dll                 # dlopens libopenmc -> libdagmc -> libMOAB
assert hasattr(openmc, "DAGMCUniverse")
PY
[ $? -eq 0 ] && ok "openmc imports + openmc.lib loads + DAGMCUniverse" || no "dagmc-openmc import"
L="$DENV/lib/libopenmc.dylib"
{ otool -L "$L" 2>/dev/null | grep -q libdagmc && otool -L "$L" 2>/dev/null | grep -q libMOAB; } \
  && ok "libopenmc links libdagmc + libMOAB" || no "libopenmc linkage"

echo "=== regen test STEP (cad env) ==="
"$ENVS/cad-arm64/bin/python" -c "import cadquery as cq; cq.exporters.export(cq.Workplane().sphere(8.7), '/tmp/sphere.step')" \
  && ok "STEP export (cadquery, cad env)" || no "STEP export"

echo "=== Stage D + engine: CAD -> .h5m -> run (from the nbeast env) ==="
cd /tmp && OPENMC_CROSS_SECTIONS="$DATA" "$ENVS/nbeast/bin/python" - <<'PY'
from nbeast.core import cad
assert cad.is_available()
assert cad.inspect_step("/tmp/sphere.step") == 1
h5m = cad.generate_h5m("/tmp/sphere.step", ["fuel"], "/tmp/sm_d.h5m", max_mesh_size=4.0, min_mesh_size=1.0)
mats = [{"name": "fuel", "density": 18.74, "nuclides": [
    {"nuclide": "U235", "fraction": 0.9371},
    {"nuclide": "U238", "fraction": 0.0527},
    {"nuclide": "U234", "fraction": 0.0102}]}]
res = cad.run_model(h5m, mats, batches=25, inactive=8, particles=1200)
assert 0.7 < res["keff"] < 1.2, res["keff"]
assert len(res["flux"]) == 100
assert len(res["flux_map"]) == 50 and len(res["flux_map"][0]) == 50
print("    keff=%.4f  spectrum=100 groups  flux_map=50x50" % res["keff"])
PY
[ $? -eq 0 ] && ok "end-to-end keff + spectrum + flux map (arm64)" || no "end-to-end run"

echo "=== Stage E: GUI (headless) ==="
QT_QPA_PLATFORM=offscreen "$ENVS/nbeast/bin/python" - <<'PY'
from PySide6.QtWidgets import QApplication
app = QApplication([])
from nbeast.gui.cad_import import CadImportDialog
from nbeast.gui.cad_setup import CadSetupDialog
from nbeast.gui.viewport3d import FluxViewport
d = CadImportDialog(); d._on_inspected(2)
assert d.table.rowCount() == 2 and d.run_btn.isEnabled() and d.preview_btn.isEnabled()
s = CadSetupDialog(); assert s.install_btn.isEnabled()
v = FluxViewport()
v.show_field_array([[1., 2.], [3., 4.]], (0, 0), (1, 1))   # flux map
v.show_cad([], [])                                          # geometry preview
PY
[ $? -eq 0 ] && ok "CAD import + setup dialogs + viewport (headless)" || no "GUI headless"

echo "=== Stage F: packaging / distribution ==="
CONDA="$HOME/miniforge3/bin/conda"
CH=/Users/juanq/dev/NBEAST-flux/packaging/cad-support/channel
out=$("$CONDA" create -n _smoke_f --dry-run -c "$CH" -c conda-forge \
  'openmc=0.15.3=dagmc_nompi_*' 'dagmc=3.2.4=nompi_nodoubledown_*' python=3.12 2>&1)
{ echo "$out" | grep -q 'dagmc-3.2.4' && echo "$out" | grep -q 'openmc-0.15.3'; } \
  && ok "channel resolves openmc(dagmc) + dagmc" || no "channel resolve"
"$ENVS/nbeast/bin/python" -c "from nbeast.core import cad; assert cad.conda_exe(); assert cad.DEFAULT_CHANNEL_URL.endswith('.tar.gz')" \
  && ok "in-app setup helpers (conda_exe + channel URL)" || no "setup helpers"

echo
echo "================ Phase 6 smoke: $PASS passed, $FAIL failed ================"
[ "$FAIL" -eq 0 ]
