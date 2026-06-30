"""Subprocess entry point for a depletion/burnup calculation.

Invoked by :class:`nbeast.core.depletion.DepletionRunner` as::

    python -m nbeast.core._depletion_run <run_dir>

``<run_dir>`` must contain ``model.xml`` and ``depletion_config.json``. The run
drives ``openmc.deplete`` and writes ``depletion_results.h5``; progress is emitted
as JSON lines on **stderr**:

    {"type": "start", "steps": N}
    {"type": "done",  "results": "/abs/path/depletion_results.h5"}
    {"type": "error", "message": "...", "trace": "..."}

Crash isolation: a depletion failure (or the MPI finalize quirk on macOS) kills this
process, not the GUI. SIGTERM cancels the run.
"""

from __future__ import annotations

import os

# Must precede openmc.lib (mpich) load — avoids the OFI finalize abort on macOS.
os.environ.setdefault("FI_PROVIDER", "tcp")

import json
import sys
import traceback


def _emit(obj: dict) -> None:
    sys.stderr.write(json.dumps(obj) + "\n")
    sys.stderr.flush()


def main(argv: list[str]) -> int:
    run_dir = argv[1]
    os.chdir(run_dir)
    cfg = json.loads((open("depletion_config.json").read()))

    import openmc
    import openmc.deplete as dep

    if cfg.get("chain"):
        openmc.config["chain_file"] = cfg["chain"]

    try:
        model = openmc.Model.from_model_xml("model.xml")
        for mat in model.materials:
            if mat.id == cfg["fuel_id"]:
                mat.volume = float(cfg["fuel_volume"])
                mat.depletable = True

        operator = dep.CoupledOperator(
            model, cfg["chain"], normalization_mode=cfg["norm_mode"]
        )
        integrator_cls = getattr(dep, cfg["integrator"])
        kwargs = {"timesteps": cfg["timesteps"], "timestep_units": "d"}
        if cfg["norm_mode"] == "source-rate":
            kwargs["source_rates"] = cfg["rates"]
        else:
            kwargs["power"] = cfg["power"]
        integrator = integrator_cls(operator, **kwargs)

        _emit({"type": "start", "steps": len(cfg["timesteps"])})
        integrator.integrate()
        _emit({"type": "done", "results": os.path.abspath("depletion_results.h5")})
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "message": str(exc), "trace": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
