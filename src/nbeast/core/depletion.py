"""Optional depletion / burnup workflow — gated on downloadable data.

Depletion tracks how a fuel's composition (and reactivity) evolve as it burns:
U-235 fissions away, actinides and fission products build in, k-effective drifts.
It is the headline reactor-analysis capability — and the most data-hungry. It needs
two things NBEAST does **not** bundle (its curated offline library is a *criticality*
library, kept under ~1 GB):

* a **depletion chain** file (decay + transmutation data, hundreds of nuclides), and
* a **depletion-capable cross-section library** (cross sections for the fission
  products and actinides the chain produces).

So depletion is an opt-in feature, mirroring the CAD support: :func:`is_available`
reports whether the data is present, and the GUI offers a setup guide when it isn't.
Once a chain is configured (``openmc.config['chain_file']`` or the
``OPENMC_DEPLETION_CHAIN`` environment variable) and an adequate library is active,
the workflow runs a real burnup calculation in an isolated subprocess.

Power can be normalised either by **fission energy** (specify thermal power, the
usual input) or by **source rate** (specify neutrons/s) — the latter does not need
fission-Q data in the chain, which is useful for reduced chains.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import openmc

INTEGRATORS = ("PredictorIntegrator", "CECMIntegrator")
NORMALIZATIONS = ("power", "source-rate")


# ---- availability gate -----------------------------------------------------
def chain_path() -> str | None:
    """The configured depletion chain file, or None."""
    try:
        configured = openmc.config.get("chain_file")
    except Exception:  # noqa: BLE001
        configured = None
    candidate = configured or os.environ.get("OPENMC_DEPLETION_CHAIN")
    return str(candidate) if candidate else None


def is_available() -> bool:
    """True when depletion can actually run: the ``openmc.deplete`` module imports
    and a depletion chain file is configured and present on disk."""
    try:
        import openmc.deplete  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    cp = chain_path()
    return bool(cp and Path(cp).exists())


# ---- fuel identification ---------------------------------------------------
def fuel_material(model: openmc.model.Model):
    """The depletable (fissionable) material in a model — the one that burns."""
    for mat in model.materials:
        names = {n[0] if isinstance(n, tuple) else n for n in mat.get_nuclides()}
        if any(n.startswith("U23") or n.startswith("Pu") for n in names):
            return mat
    return model.materials[0] if model.materials else None


def fuel_volume(template_key: str, params: dict) -> float:
    """Analytic fuel volume (cm³) per template, for the depletion atom inventory.

    2-D lattices (pin cell, assembly) are infinite in z, so a unit (1 cm) height is
    used — absolute inventory scales with it, but k and relative burnup do not.
    """
    if template_key in ("godiva", "bare_sphere"):
        r = float(params.get("radius", 8.7407))
        return (4.0 / 3.0) * math.pi * r ** 3
    if template_key == "pin_cell":
        r = float(params.get("fuel_radius", 0.39))
        return math.pi * r ** 2 * 1.0
    if template_key == "assembly":
        r = float(params.get("fuel_radius", 0.39))
        n = int(params.get("n_side", 5))
        return math.pi * r ** 2 * 1.0 * n * n
    raise ValueError(f"No fuel-volume rule for template {template_key!r}")


# ---- run configuration + driver -------------------------------------------
@dataclass
class DepletionConfig:
    timesteps_days: list[float]
    normalization: str = "power"      # "power" | "source-rate"
    power_watts: float = 1.0e6        # used when normalization == "power"
    source_rate: float = 1.0e16       # used when normalization == "source-rate"
    integrator: str = "PredictorIntegrator"

    def values(self) -> list[float]:
        n = len(self.timesteps_days)
        v = self.power_watts if self.normalization == "power" else self.source_rate
        return [float(v)] * n


@dataclass
class DepletionResult:
    days: list[float] = field(default_factory=list)
    keff: list[float] = field(default_factory=list)
    keff_std: list[float] = field(default_factory=list)
    results_path: str | None = None
    error: str | None = None
    cancelled: bool = False


class DepletionRunner:
    """Run a burnup calculation in an isolated subprocess and stream progress."""

    def __init__(self, cross_sections: str | None = None, chain: str | None = None):
        self._cross_sections = cross_sections
        self._chain = chain or chain_path()
        self._proc: subprocess.Popen | None = None

    def run(
        self,
        model: openmc.model.Model,
        config: DepletionConfig,
        run_dir: str | Path,
        fuel_id: int,
        fuel_vol: float,
        *,
        on_start: Callable[[int], None] | None = None,
    ) -> DepletionResult:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        model.export_to_model_xml(str(run_dir / "model.xml"))
        (run_dir / "depletion_config.json").write_text(json.dumps({
            "chain": self._chain,
            "fuel_id": int(fuel_id),
            "fuel_volume": float(fuel_vol),
            "timesteps": list(config.timesteps_days),
            "norm_mode": "fission-q" if config.normalization == "power" else "source-rate",
            "power": config.power_watts,
            "rates": config.values(),
            "integrator": config.integrator,
        }))

        env = dict(os.environ)
        env["FI_PROVIDER"] = "tcp"
        if self._cross_sections:
            env["OPENMC_CROSS_SECTIONS"] = self._cross_sections

        self._proc = subprocess.Popen(
            [sys.executable, "-m", "nbeast.core._depletion_run", str(run_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
        )
        result = DepletionResult()
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "start" and on_start:
                on_start(int(msg.get("steps", 0)))
            elif kind == "done":
                result.results_path = msg.get("results")
            elif kind == "error":
                result.error = msg.get("message")
        self._proc.wait()
        if self._proc.returncode and result.error is None and result.results_path is None:
            result.cancelled = True
        self._proc = None

        if result.results_path and Path(result.results_path).exists():
            parsed = read_results(result.results_path)
            result.days, result.keff, result.keff_std = (
                parsed["days"], parsed["keff"], parsed["keff_std"]
            )
        return result

    def cancel(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()


# ---- results reader --------------------------------------------------------
def read_results(path: str | Path) -> dict:
    """Read an OpenMC ``depletion_results.h5`` into plain lists.

    Returns ``{days, keff, keff_std, materials: {id: {nuclide: [atoms...]}}}``.
    """
    import openmc.deplete as dep

    results = dep.Results(str(path))
    times, keff = results.get_keff()
    days = [float(t) / 86400.0 for t in times]
    k = [float(v) for v in keff[:, 0]]
    kstd = [float(v) for v in keff[:, 1]]
    return {"days": days, "keff": k, "keff_std": kstd, "_results": results}


def nuclide_trajectory(results, material_id: int | str, nuclide: str):
    """(days, atoms) trajectory for one nuclide in one material, from a Results object."""
    times, atoms = results.get_atoms(str(material_id), nuclide)
    return [float(t) / 86400.0 for t in times], [float(a) for a in atoms]
