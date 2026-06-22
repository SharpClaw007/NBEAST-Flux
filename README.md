# NBEAST

An offline-capable, open-source **desktop GUI for neutron-flux Monte Carlo simulation**,
built on [OpenMC](https://openmc.org). The goal: the first polished, mainstream, end-to-end
GUI for neutron transport — simple enough for students, deep enough for experts.

- **Status:** early development. Phase 0 (de-risk) complete; Phase 1 (headless core) in progress.
- **Scope (v1):** criticality / k-eff; templated geometry (pin cell, assembly, primitives);
  curated bundled cross-section data (offline); report + reproducible OpenMC-input export.
- **Platforms (v1):** macOS + Linux. **License:** MIT.

See [`PLAN.md`](PLAN.md) for the full plan and [`docs/phase0-notes.md`](docs/phase0-notes.md)
for the foundation findings.

## Development

OpenMC has no conda-forge build for Apple Silicon, so on macOS the env runs as `osx-64`
under Rosetta 2 (Linux x86-64 is native). See `environment.yml`.

```sh
# Apple Silicon: CONDA_SUBDIR=osx-64 conda env create -f environment.yml
conda env create -f environment.yml
conda activate nbeast
pip install -e .

# Curated cross-section data (offline bundle prototype):
python spikes/fetch_data.py data
export OPENMC_CROSS_SECTIONS="$PWD/data/cross_sections.xml"

# Run the benchmark regression tests:
pytest
```
