"""Phase 0 / Spike B: consumer side — spawn the worker, read live JSON events.

Demonstrates the GUI's relationship to the engine: launch OpenMC in an isolated
subprocess, stream per-batch results, and (optionally) cancel mid-run cleanly.

Env:
    OPENMC_CROSS_SECTIONS  required (path to cross_sections.xml)
    CANCEL_AFTER           if set to N>0, send SIGTERM after N batches
"""

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent


def main() -> int:
    env = dict(os.environ)
    env["FI_PROVIDER"] = "tcp"

    cancel_after = int(os.environ.get("CANCEL_AFTER", "0"))
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "worker.py")],
        stdout=subprocess.DEVNULL,   # OpenMC's own logging — discarded here
        stderr=subprocess.PIPE,      # structured JSON event stream
        text=True,
        bufsize=1,
        env=env,
    )

    seen = 0
    last = None
    assert proc.stderr is not None
    for line in proc.stderr:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print("  [non-json]", line)
            continue

        if msg["type"] == "batch":
            seen += 1
            last = msg
            print(f"  batch {msg['batch']:>3}  k = {msg['keff']:.5f} +/- {msg['keff_std']:.5f}")
            if cancel_after and seen >= cancel_after:
                print(f">>> CANCEL: SIGTERM after {seen} batches")
                proc.terminate()
        else:
            print("  EVENT", msg if msg["type"] != "error" else msg["message"])

    rc = proc.wait()
    print(f">>> worker exit code: {rc}; batches streamed: {seen}; last: {last}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
