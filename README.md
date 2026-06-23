# NBEAST

An offline-capable, open-source **desktop GUI for neutron-flux Monte Carlo simulation**,
built on [OpenMC](https://openmc.org). The goal: the first polished, mainstream, end-to-end
GUI for neutron transport — simple enough for students, deep enough for experts.

- **Scope (v1):** criticality / k-eff; templated geometry (pin cell, fuel assembly, bare
  sphere) with editable parameters; live convergence; flux & fission maps; flux spectrum;
  neutron-track visualization; report + reproducible OpenMC-deck export. Bundled offline data.
- **Platforms (v1):** macOS (native Apple Silicon **and** Intel) + Linux. **License:** MIT.

See [`PLAN.md`](PLAN.md) for the full roadmap.

## What it does

Pick a template (pin cell / fuel assembly / Godiva), edit parameters in the Model tree, hit
**Run**, and watch k-effective converge live. Then explore results — scalar flux and fission
maps in 3D, the energy spectrum, and energy-colored neutron tracks — and export a report
(PDF/PNG/CSV) plus the exact OpenMC input deck. Simple mode picks run settings for you;
Advanced exposes batches/particles.

## Install (end users)

Download the installer for your platform from the releases page, then run it — it bundles
everything (Python, OpenMC, the GUI, and a curated cross-section library) for fully offline use.

```sh
# macOS (Apple Silicon: -arm64; Intel: -x86_64)
bash NBEAST-<version>-MacOSX-arm64.sh -b -p ~/nbeast
~/nbeast/bin/nbeast      # launch
```

No Python or conda required; the launcher points OpenMC at the bundled data automatically.

## Development

OpenMC has no conda-forge build for Apple Silicon, so the dev env runs as `osx-64` under
Rosetta 2 on macOS (Linux x86-64 is native). For a *native* arm64 OpenMC, see
[`packaging/openmc-arm64/`](packaging/openmc-arm64/).

```sh
# Apple Silicon: prefix with CONDA_SUBDIR=osx-64
conda env create -f environment.yml
conda activate nbeast
pip install -e .

# Curated cross-section data (offline bundle):
python spikes/fetch_data.py data
export OPENMC_CROSS_SECTIONS="$PWD/data/cross_sections.xml"

pytest          # benchmark + GUI regression tests
./launch.sh     # run the app from source
```

## Building installers

```sh
conda install -n base -c conda-forge constructor
packaging/build_installer.sh osx-arm64   # or osx-64 / linux-64
```

The version is single-sourced from `src/nbeast/__init__.py`. See
[`packaging/RELEASE.md`](packaging/RELEASE.md) for the full release process.
