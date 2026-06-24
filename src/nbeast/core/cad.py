"""CAD (DAGMC) geometry support — Phase 6, Stage E.

The GUI runs in the nbeast env, which has neither cad_to_dagmc nor dagmc-OpenMC.
The CAD pipeline spans two native-arm64 envs built under packaging/:

  - the CAD env (cad_to_dagmc): STEP -> watertight DAGMC .h5m
  - the dagmc-OpenMC env:       run a .h5m to k-eff

This module orchestrates both as subprocesses. DAGMC support is OPTIONAL —
``is_available()`` gates the UI so the rest of the app is unaffected when the envs
aren't present (e.g. the v1 nodagmc install). Env pythons are discovered by name
(``cad-arm64`` / ``openmc-dagmc-arm64``) or via the ``NBEAST_CAD_PYTHON`` /
``NBEAST_DAGMC_PYTHON`` overrides.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_GEN = _HERE / "_cad_gen.py"
_RUN = _HERE / "_cad_run.py"

# CAD material presets, keyed by a clean tag (used as the DAGMC group + OpenMC
# material name). Compositions use nuclides present in the curated bundled data.
MATERIAL_PRESETS: dict[str, dict] = {
    "heu": {
        "label": "HEU metal (Godiva)", "density": 18.74, "color": "#c9a227",
        "nuclides": [
            {"nuclide": "U235", "fraction": 0.9371},
            {"nuclide": "U238", "fraction": 0.0527},
            {"nuclide": "U234", "fraction": 0.0102},
        ],
    },
    "uo2": {
        "label": "UO₂ (3% enriched)", "density": 10.5, "color": "#6b8e23",
        "nuclides": [
            {"nuclide": "U235", "fraction": 0.0264},
            {"nuclide": "U238", "fraction": 0.8549},
            {"nuclide": "O16", "fraction": 0.1187},
        ],
    },
    "water": {
        "label": "Water", "density": 1.0, "color": "#7fb8d8",
        "nuclides": [
            {"nuclide": "H1", "fraction": 0.1119},
            {"nuclide": "O16", "fraction": 0.8881},
        ],
    },
    "zirc": {
        "label": "Zircaloy", "density": 6.55, "color": "#9aa0a6",
        "nuclides": [
            {"nuclide": "Zr90", "fraction": 0.5},
            {"nuclide": "Zr92", "fraction": 0.5},
        ],
    },
}


def material_specs(tags) -> list[dict]:
    """Map a list of material-preset tags to unique run-ready material dicts."""
    specs = []
    for tag in dict.fromkeys(tags):  # unique, order-preserving
        preset = MATERIAL_PRESETS[tag]
        specs.append({"name": tag, "density": preset["density"], "nuclides": preset["nuclides"]})
    return specs


def _conda_root() -> pathlib.Path:
    p = pathlib.Path(sys.executable).resolve()
    for parent in p.parents:
        if parent.name == "envs":
            return parent.parent
    return pathlib.Path(os.path.expanduser("~/miniforge3"))


def _env_python(override_var: str, env_name: str) -> pathlib.Path | None:
    override = os.environ.get(override_var)
    if override and pathlib.Path(override).exists():
        return pathlib.Path(override)
    candidate = _conda_root() / "envs" / env_name / "bin" / "python"
    return candidate if candidate.exists() else None


def cad_python() -> pathlib.Path | None:
    return _env_python("NBEAST_CAD_PYTHON", "cad-arm64")


def dagmc_python() -> pathlib.Path | None:
    return _env_python("NBEAST_DAGMC_PYTHON", "openmc-dagmc-arm64")


def is_available() -> bool:
    """True when both the CAD and dagmc-OpenMC envs are present."""
    return cad_python() is not None and dagmc_python() is not None


DEFAULT_CHANNEL_URL = (
    "https://github.com/SharpClaw007/NBEAST-Flux/releases/download/"
    "cad-channel-osx-arm64-1/nbeast-cad-channel-osx-arm64.tar.gz"
)


def conda_exe() -> pathlib.Path | None:
    candidate = _conda_root() / "bin" / "conda"
    return candidate if candidate.exists() else None


def setup_support(channel: str | None = None, on_line=None) -> None:
    """Create the two CAD envs (downloading the published channel if needed).

    Mirrors packaging/cad-support/setup_cad_support.sh, in Python, so the app can
    run it. `on_line` (if given) receives each output line for live progress.
    """
    import shutil
    import tarfile
    import tempfile
    import urllib.request

    def emit(msg):
        if on_line:
            on_line(msg)

    conda = conda_exe()
    if conda is None:
        raise RuntimeError("conda/Miniforge not found — run setup_cad_support.sh manually.")

    channel = channel or DEFAULT_CHANNEL_URL
    if str(channel).endswith(".tar.gz"):
        tmp = tempfile.mkdtemp(prefix="nbeast_cad_ch_")
        tgz = os.path.join(tmp, "channel.tar.gz")
        if str(channel).startswith("http"):
            emit(f"Downloading channel: {channel}")
            urllib.request.urlretrieve(channel, tgz)
        else:
            shutil.copy(channel, tgz)
        with tarfile.open(tgz) as tar:
            tar.extractall(tmp, filter="data")
        channel_dir = os.path.join(tmp, "channel")
    else:
        channel_dir = str(channel)

    commands = [
        [str(conda), "create", "-y", "-n", "cad-arm64", "-c", "conda-forge",
         "cad_to_dagmc", "cadquery", "gmsh", "python-gmsh", "ocp", "numpy<=1.26.4", "python=3.12"],
        [str(conda), "create", "-y", "-n", "openmc-dagmc-arm64", "-c", channel_dir, "-c", "conda-forge",
         "openmc=0.15.3=dagmc_nompi_*", "dagmc=3.2.4=nompi_nodoubledown_*", "python=3.12"],
    ]
    for cmd in commands:
        emit("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            emit(line.rstrip())
        if proc.wait() != 0:
            raise RuntimeError("conda env creation failed (see log above).")
    emit("Done — CAD support is installed. Reopen NBEAST to use it.")


def _run_json(python: pathlib.Path, script: pathlib.Path, payload: dict, timeout=1800) -> dict:
    proc = subprocess.run(
        [str(python), str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr.strip() or proc.stdout.strip())[-2000:] or "subprocess failed")
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    raise RuntimeError("no result from worker:\n" + proc.stdout[-2000:])


def inspect_step(step_path) -> int:
    """Return the number of solids in a STEP file (for per-volume material assignment)."""
    if cad_python() is None:
        raise RuntimeError("CAD env not available")
    return _run_json(cad_python(), _GEN, {"mode": "inspect", "step": str(step_path)})["n_solids"]


def tessellate(step_path, out_dir) -> list[str]:
    """Export each solid of a STEP file to an STL for 3D preview. Returns the paths."""
    if cad_python() is None:
        raise RuntimeError("CAD env not available")
    os.makedirs(out_dir, exist_ok=True)
    payload = {"mode": "tessellate", "step": str(step_path), "out_dir": str(out_dir)}
    return _run_json(cad_python(), _GEN, payload)["stls"]


def generate_h5m(step_path, material_tags, out_path,
                 max_mesh_size: float = 10.0, min_mesh_size: float = 1.0) -> str:
    """STEP -> DAGMC .h5m, one material tag per solid. Returns the .h5m path."""
    if cad_python() is None:
        raise RuntimeError("CAD env not available")
    payload = {
        "mode": "generate", "step": str(step_path),
        "material_tags": list(material_tags), "out": str(out_path),
        "max_mesh_size": max_mesh_size, "min_mesh_size": min_mesh_size,
    }
    return _run_json(cad_python(), _GEN, payload)["h5m"]


def run_model(h5m_path, materials, batches: int = 50, inactive: int = 10,
              particles: int = 2000, cross_sections: str | None = None) -> dict:
    """Run a DAGMC .h5m to k-eff in the dagmc-OpenMC env.

    `materials` is a list of dicts: {name, density, density_units?, nuclides:
    [{nuclide, fraction, percent_type?}]}. Returns {keff, keff_std}.
    """
    if dagmc_python() is None:
        raise RuntimeError("dagmc-OpenMC env not available")
    payload = {
        "h5m": str(h5m_path), "materials": materials,
        "batches": batches, "inactive": inactive, "particles": particles,
        "cross_sections": cross_sections or os.environ.get("OPENMC_CROSS_SECTIONS"),
    }
    return _run_json(dagmc_python(), _RUN, payload)
