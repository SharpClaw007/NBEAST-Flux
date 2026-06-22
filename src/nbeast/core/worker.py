"""Subprocess worker: run an OpenMC eigenvalue calc and stream per-batch results.

Invoked by the Runner as::

    python -m nbeast.core.worker <run_dir> <total_batches>

It runs the ``openmc.lib`` batch loop in <run_dir> (which must contain model.xml)
and emits one JSON object per line on **stderr** (stdout is left to OpenMC's own
logging). Responds to SIGTERM/SIGINT by finishing the current batch and shutting
down cleanly. Protocol:

    {"type": "start",     "batches": N|null}
    {"type": "batch",     "batch": i, "keff": k, "keff_std": s}
    {"type": "cancelled", "batch": i}
    {"type": "done",      "keff": k, "keff_std": s}
    {"type": "error",     "message": "...", "trace": "..."}
"""

from __future__ import annotations

import os

# Must precede the openmc.lib (mpich) load or the OFI provider aborts at finalize
# on macOS (nic=bridge101).
os.environ.setdefault("FI_PROVIDER", "tcp")

import json
import signal
import sys
import traceback


def _emit(obj: dict) -> None:
    sys.stderr.write(json.dumps(obj) + "\n")
    sys.stderr.flush()


def main(argv: list[str]) -> int:
    run_dir = argv[1]
    total_batches = int(argv[2]) if len(argv) > 2 and argv[2] != "None" else None
    os.chdir(run_dir)

    import openmc.lib as lib

    stop = {"flag": False}

    def _on_term(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    try:
        lib.init()
        lib.simulation_init()
        _emit({"type": "start", "batches": total_batches})
        for _ in lib.iter_batches():
            k = lib.keff()
            _emit({
                "type": "batch",
                "batch": lib.current_batch(),
                "keff": k[0],
                "keff_std": k[1],
            })
            if stop["flag"]:
                _emit({"type": "cancelled", "batch": lib.current_batch()})
                break
        k = lib.keff()
        lib.simulation_finalize()
        lib.finalize()
        _emit({"type": "done", "keff": k[0], "keff_std": k[1]})
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "message": str(exc), "trace": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
