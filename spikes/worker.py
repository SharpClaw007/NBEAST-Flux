"""Phase 0 / Spike B: OpenMC batch-stepping worker (the subprocess side).

Runs an eigenvalue calc via openmc.lib, emitting one JSON line per batch to
stdout so a parent process can drive a live convergence monitor. Responds to
SIGTERM by finishing the current batch and shutting down cleanly (the basis for
a responsive "Stop" button). This is the streaming mechanism the GUI will use.

Protocol (one JSON object per line on stdout):
    {"type": "start",     "batches": N}
    {"type": "batch",     "batch": i, "keff": k, "keff_std": s}
    {"type": "cancelled", "batch": i}        # if SIGTERM received
    {"type": "done",      "keff": k, "keff_std": s}
    {"type": "error",     "message": "..."}
"""

import os

# Must be set before openmc.lib loads the C library, or mpich's OFI provider
# aborts at finalize on macOS (nic=bridge101). See Phase 0 notes.
os.environ.setdefault("FI_PROVIDER", "tcp")

import json
import pathlib
import signal
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pincell import build_model


def emit(obj: dict) -> None:
    # Structured events go on stderr so OpenMC's own logging (fd 1 / stdout)
    # never pollutes the data channel. The GUI can show stdout in a console pane.
    sys.stderr.write(json.dumps(obj) + "\n")
    sys.stderr.flush()


def main() -> int:
    run_dir = pathlib.Path(__file__).parent / "run_worker"
    run_dir.mkdir(exist_ok=True)
    os.chdir(run_dir)

    model = build_model()
    n_batches = model.settings.batches
    model.export_to_model_xml()

    import openmc.lib as lib

    stop = {"flag": False}

    def on_term(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    try:
        lib.init()
        lib.simulation_init()
        emit({"type": "start", "batches": n_batches})
        for _ in lib.iter_batches():
            k = lib.keff()
            emit({
                "type": "batch",
                "batch": lib.current_batch(),
                "keff": k[0],
                "keff_std": k[1],
            })
            if stop["flag"]:
                emit({"type": "cancelled", "batch": lib.current_batch()})
                break
        k = lib.keff()
        lib.simulation_finalize()
        lib.finalize()
        emit({"type": "done", "keff": k[0], "keff_std": k[1]})
        return 0
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": f"{exc}", "trace": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
