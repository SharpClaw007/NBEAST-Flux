"""Subprocess worker: run an OpenMC eigenvalue calc and stream per-batch results.

Invoked by the Runner as::

    python -m nbeast.core.worker <run_dir> <total_batches>

It runs the ``openmc.lib`` batch loop in <run_dir> (which must contain model.xml)
and emits one JSON object per line on **stderr** (stdout is left to OpenMC's own
logging). Responds to SIGTERM/SIGINT by finishing the current batch and shutting
down cleanly. Protocol:

    {"type": "start",     "batches": N|null}
    {"type": "batch",     "batch": i, "keff": k, "keff_std": s, "entropy": h|absent}
    {"type": "cancelled", "batch": i}
    {"type": "done",      "keff": k, "keff_std": s}
    {"type": "error",     "message": "...", "trace": "..."}

If ``entropy_mesh.json`` is present in <run_dir>, each batch also reports the live
Shannon entropy of the fission source (openmc.lib doesn't expose it, so we compute
it from the source bank). This is best-effort — any failure just omits the field.
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


def _make_entropy_fn():
    """Build a callable mapping the live source bank -> Shannon entropy (bits),
    using the entropy mesh dropped by the Runner. Returns None when unavailable."""
    try:
        with open("entropy_mesh.json") as handle:
            spec = json.load(handle)
        import numpy as np

        ll = np.asarray(spec["lower_left"], dtype=float)
        ur = np.asarray(spec["upper_right"], dtype=float)
        dim = np.asarray(spec["dimension"], dtype=int)
        extent = np.where(ur > ll, ur - ll, 1.0)
        nbins = int(dim.prod())
    except Exception:  # noqa: BLE001
        return None

    def compute(sites) -> float:
        import numpy as np

        r = sites["r"]
        if r.dtype.names:  # nested ('x','y','z')
            xyz = np.stack([r["x"], r["y"], r["z"]], axis=1)
        else:              # shape (N, 3)
            xyz = np.asarray(r, dtype=float).reshape(len(sites), 3)
        names = sites.dtype.names or ()
        wgt = np.asarray(sites["wgt"], dtype=float) if "wgt" in names else np.ones(len(sites))
        idx = np.clip(((xyz - ll) / extent * dim).astype(int), 0, dim - 1)
        flat = (idx[:, 0] * dim[1] + idx[:, 1]) * dim[2] + idx[:, 2]
        counts = np.bincount(flat, weights=wgt, minlength=nbins).astype(float)
        total = counts.sum()
        if total <= 0:
            return 0.0
        p = counts / total
        nz = p > 0
        return float(-(p[nz] * np.log2(p[nz])).sum())

    return compute


def _read_run_mode() -> str:
    """Run mode from run_meta.json in the cwd (default eigenvalue)."""
    try:
        with open("run_meta.json") as handle:
            return json.load(handle).get("run_mode", "eigenvalue")
    except Exception:  # noqa: BLE001
        return "eigenvalue"


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

    fixed_source = _read_run_mode() == "fixed source"

    try:
        lib.init()
        lib.simulation_init()
        entropy_fn = None if fixed_source else _make_entropy_fn()
        _emit({"type": "start", "batches": total_batches})
        for _ in lib.iter_batches():
            event = {"type": "batch", "batch": lib.current_batch()}
            if not fixed_source:  # k-eff is meaningless in fixed-source mode
                k = lib.keff()
                event["keff"], event["keff_std"] = k[0], k[1]
            if entropy_fn is not None:
                try:
                    event["entropy"] = entropy_fn(lib.source_bank())
                except Exception:  # noqa: BLE001 — disable after first failure
                    entropy_fn = None
            _emit(event)
            if stop["flag"]:
                _emit({"type": "cancelled", "batch": lib.current_batch()})
                break
        # Persist a statepoint (with any tallies) so results can be visualised.
        statepoint = os.path.abspath("statepoint.h5")
        try:
            lib.statepoint_write(statepoint)
        except Exception:  # noqa: BLE001
            statepoint = None
        done = {"type": "done", "statepoint": statepoint}
        if not fixed_source:
            k = lib.keff()
            done["keff"], done["keff_std"] = k[0], k[1]
        lib.simulation_finalize()
        lib.finalize()
        _emit(done)
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit({"type": "error", "message": str(exc), "trace": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
