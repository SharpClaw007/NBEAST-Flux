# Contributing to NBEAST

Thanks for your interest in NBEAST — an offline desktop GUI for neutron-flux Monte
Carlo on [OpenMC](https://openmc.org). Bug reports, feature ideas, validated
benchmark cases, documentation, and code are all welcome.

## Ways to contribute

- **Report a bug** — open an issue with what you did, what you expected, and what
  happened (include OS, NBEAST version, and the run parameters or the exported
  `model.xml` when relevant).
- **Suggest a feature** — open an issue describing the use case. The roadmap lives
  in [`PLAN.md`](PLAN.md); check it first to see if it's already planned.
- **Contribute a validated case** — a benchmark with a known k-eff (e.g. from
  [ICSBEP](https://www.oecd-nea.org/jcms/pl_24498/)) is especially valuable: it
  becomes a regression test *and* a built-in example.
- **Improve docs** — the README, in-app captions/tooltips, and tutorials.
- **Write code** — see below.

## Development setup

NBEAST's scientific + GUI dependencies (OpenMC, NumPy, h5py, PySide6, PyVista, …)
come from **conda**, not pip — only the `nbeast` package itself is pip-installed.

```sh
# 1. Create the pinned environment (Miniforge recommended).
#    Apple Silicon: prefix env creation with CONDA_SUBDIR=osx-64, or use the
#    native arm64 OpenMC build under packaging/openmc-arm64/.
conda env create -f environment.yml
conda activate nbeast
pip install -e .

# 2. Fetch a curated cross-section library for runs/tests.
python spikes/fetch_data.py data
export OPENMC_CROSS_SECTIONS="$PWD/data/cross_sections.xml"
export FI_PROVIDER=tcp        # avoids the mpich/OFI finalize abort on macOS

# 3. Run the app from source.
./launch.sh
```

## Running the tests

```sh
pytest                        # full suite
pytest tests/test_benchmarks.py   # just the physics regression tests
QT_QPA_PLATFORM=offscreen pytest  # force-headless (CI uses this)
```

Tests that need transport data **skip** (not fail) when `OPENMC_CROSS_SECTIONS`
isn't set, so the data-free unit tests run anywhere. Headless GUI tests use Qt's
`offscreen` platform. Please make sure the suite is green before opening a PR, and
**add a test** for any behavior you change.

### The benchmark contract

Validated cases (Godiva, pin cell, assembly) are the regression tests: if a model
is built wrong, the benchmark k-eff catches it. Keep this property intact —
changes to geometry, materials, or settings must keep `tests/test_benchmarks.py`
passing (Godiva ≈ 1.0, pin cell / assembly k∞ ≈ 1.41).

## Architecture & code style

- **Two layers.** `nbeast.core` is Qt-free (domain model, OpenMC adapter, runner,
  results, export) and fully unit-tested; `nbeast.gui` is a thin PySide6 layer over
  it. Keep physics/IO in `core`; keep `gui` about widgets and signals.
- **Match the surrounding code.** PEP 8, type hints on public functions, a concise
  module docstring, and the comment density of neighboring files. No formatter is
  enforced, but keep lines reasonable (~100 cols) and imports sorted.
- **Never let visualization crash the app** — viewport code guards rendering in
  `try/except` and degrades to a placeholder.
- **Transport runs in a subprocess** (`core/worker.py`) for crash isolation and
  clean cancellation; the GUI never runs transport in-process.

Adding a geometry template or material? Templates live in `core/templates.py` with
an editable-parameter spec in `core/specs.py`; material presets live in
`core/materials.py`. The native arm64 DAGMC/MOAB build chain (for CAD) is under
`packaging/` — see [`docs/phase6-plan.md`](docs/phase6-plan.md).

## Pull requests

1. Fork and branch from `main`.
2. Make the change with a test; keep `pytest` green.
3. Write a clear PR description (what, why, and how you validated it).
4. Keep PRs focused — one logical change per PR.

By contributing, you agree your contributions are licensed under the project's
[MIT License](LICENSE).
