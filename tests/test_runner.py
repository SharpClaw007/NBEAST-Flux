"""Runner tests: live streaming and clean cancellation via the subprocess worker."""

import os
import pathlib

import pytest

_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@requires_data
def test_runner_streams_and_finishes(tmp_path):
    from nbeast.core import benchmarks
    from nbeast.core.runner import Runner

    model = benchmarks.godiva(particles=2000, batches=40, inactive=10)
    seen = []
    runner = Runner(cross_sections=_XS)
    result = runner.run(model, tmp_path / "run", on_batch=seen.append)

    assert len(seen) == 40, f"expected 40 batch events, got {len(seen)}"
    assert result.error is None and not result.cancelled
    assert result.keff is not None and abs(result.keff - 1.0) < 0.02


@requires_data
def test_runner_cancels_cleanly(tmp_path):
    from nbeast.core import benchmarks
    from nbeast.core.runner import Runner

    # Long run; cancel deterministically once batch 10 has streamed.
    model = benchmarks.godiva(particles=4000, batches=500, inactive=10)
    runner = Runner(cross_sections=_XS)

    def on_batch(update):
        if update.batch >= 10:
            runner.cancel()

    result = runner.run(model, tmp_path / "run", on_batch=on_batch)

    assert result.cancelled, "run should report cancellation"
    assert result.error is None
    assert len(result.batches) < 500, "should stop well before all batches complete"
