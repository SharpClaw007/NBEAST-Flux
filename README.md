<div align="center">

<img src="public/brand/nbeast-logo.svg" alt="NBEAST logo" width="76" height="76" />

# NBEAST

### Neutron-flux Monte Carlo simulation, made approachable.

An offline, open-source desktop GUI for neutron-transport Monte Carlo, built on
[OpenMC](https://openmc.org). Build a reactor model with a few clicks, watch criticality
converge live, and explore flux, fission, spectra, and neutron tracks — simple enough for
students, deep enough for experts.

[![CI](https://github.com/SharpClaw007/NBEAST-Flux/actions/workflows/ci.yml/badge.svg)](https://github.com/SharpClaw007/NBEAST-Flux/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![OpenMC](https://img.shields.io/badge/OpenMC-0.15-1f6feb)](https://openmc.org/)
[![PySide6](https://img.shields.io/badge/PySide6-Qt-41CD52?logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![PyVista](https://img.shields.io/badge/3D-PyVista%20%2F%20VTK-e8772e)](https://pyvista.org/)
[![Platforms](https://img.shields.io/badge/macOS%20%7C%20Linux-native-555555)](#getting-started)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<br />

<img src="docs/screenshots/app-spectrum.png" alt="NBEAST main window: model tree with editable parameters, result tabs, the flux energy spectrum, and the results panel" width="100%" />

</div>

---

## Overview

Neutron-transport Monte Carlo is powerful but usually means hand-writing input decks and
running a CLI. NBEAST puts a real desktop GUI on top of OpenMC: pick a template, edit its
parameters in a tree, press **Run**, and see k-effective converge in real time. Results —
spatial flux and fission maps, the energy spectrum, and energy-colored neutron tracks — show
up in tabbed viewports, and a one-click export produces a report plus the exact, reproducible
OpenMC input deck.

It ships fully offline: the installer bundles Python, OpenMC, the GUI, and a curated
cross-section library, so there's nothing to set up and no internet needed to run a simulation.

## Features

- **Templated geometry** — pin cell, N×N fuel assembly, and bare sphere (Godiva), each
  defined by a handful of editable parameters with live values in the model tree.
- **Live criticality** — k-effective streams in per batch on a convergence plot as the
  simulation runs; **Stop** cancels cleanly.
- **Flux & fission maps** — 2-D slices of **scalar flux** and **fission rate**, rendered in
  an interactive 3-D viewport; switch fields in the Results panel.
- **Energy spectrum** — flux per unit lethargy vs energy, showing the thermal, slowing-down,
  and fast regions at a glance.
- **Neutron tracks** — sampled particle paths in 3-D, **colored by energy** so you can watch
  neutrons born fast and slow down.
- **Editable parameters** — enrichment, pitch, radii, pins-per-side; what the tree shows is
  exactly what runs.
- **Report & deck export** — a PDF/PNG report (k-eff, parameters, plots) plus CSV and the
  reproducible **OpenMC input deck** that produced it.
- **Simple ↔ Advanced** — Simple mode picks run quality for you; Advanced exposes batches and
  particles. **Validated examples** (Godiva ≈ 1.0, pin cell, assembly) are one click away.
- **Fully offline** — bundled cross-section data; no Python, conda, or network required.

## Screenshots

<table>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/app-convergence.png" alt="Live k-effective convergence plot" /><br />
      <sub><b>Live convergence</b> — k-effective per batch, settling to a steady value.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/app-params.png" alt="Editable model tree and properties panel" /><br />
      <sub><b>Editable model</b> — select a group in the tree, edit parameters in Properties.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fission-pincell.png" alt="Pin-cell fission-rate map" /><br />
      <sub><b>Fission map (pin cell)</b> — fission confined to the fuel pellet, with the rim peak.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fission-assembly.png" alt="7x7 assembly fission-rate map" /><br />
      <sub><b>Fission map (7×7 assembly)</b> — the mesh resolves every pin.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/neutron-tracks.png" alt="Neutron tracks colored by energy" /><br />
      <sub><b>Neutron tracks</b> — sampled paths radiating from the source, colored by energy.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/report.png" alt="Exported one-page run report" /><br />
      <sub><b>Report export</b> — k-eff, parameters, convergence, spectrum, and flux on one page.</sub>
    </td>
  </tr>
</table>

> Screenshots use the built-in benchmark models (Godiva, a PWR pin cell, a 7×7 assembly)
> with ENDF/B-VIII.0 cross-section data.

## Tech stack

| Layer        | Technology                                                                 |
|--------------|----------------------------------------------------------------------------|
| Engine       | [OpenMC](https://openmc.org) — continuous-energy neutron Monte Carlo       |
| Language     | [Python](https://www.python.org/)                                          |
| GUI          | [PySide6](https://doc.qt.io/qtforpython/) (Qt)                             |
| 3-D viewport | [PyVista](https://pyvista.org/) / [VTK](https://vtk.org/)                  |
| Plots        | [pyqtgraph](https://www.pyqtgraph.org/) (live) + [matplotlib](https://matplotlib.org/) (report) |
| Packaging    | [conda](https://conda.org/) + [constructor](https://github.com/conda/constructor) (offline installer) |
| Nuclear data | [ENDF/B-VIII.0](https://www.nndc.bnl.gov/endf/) (+ ENDF/B-7.1 S(α,β))       |

## Project structure

```
NBEAST-Flux/
├── src/nbeast/
│   ├── core/            # Qt-free engine: materials, templates, runner, results, tallies, export, tracks
│   └── gui/             # PySide6 app: main window, 3-D viewport, monitor, spectrum, report
├── tests/               # benchmark (Godiva/pin/assembly) + headless GUI regression tests
├── packaging/           # constructor installer pipeline + native arm64 OpenMC build
├── spikes/              # Phase-0 prototypes and the curated-data fetch script
├── docs/                # screenshots and notes
├── environment.yml      # pinned dev environment
└── PLAN.md              # roadmap and decisions
```

## Getting started

### Install (end users)

Download the installer for your platform, run it, and launch — everything is bundled.

| Platform           | Installer                          |
|--------------------|------------------------------------|
| macOS (Apple Silicon) | `NBEAST-<version>-MacOSX-arm64.sh`  |
| macOS (Intel)      | `NBEAST-<version>-MacOSX-x86_64.sh` |
| Linux (x86-64)     | `NBEAST-<version>-Linux-x86_64.sh`  |

```sh
bash NBEAST-<version>-MacOSX-arm64.sh -b -p ~/nbeast
~/nbeast/bin/nbeast
```

### From source (development)

| Requirement | Version | Notes                                                |
|-------------|---------|------------------------------------------------------|
| conda       | any     | Miniforge recommended                                |
| OpenMC      | 0.15.3  | from conda-forge; Apple Silicon uses `osx-64`/Rosetta or the native build in `packaging/openmc-arm64/` |

```sh
# Apple Silicon: prefix with CONDA_SUBDIR=osx-64
conda env create -f environment.yml
conda activate nbeast
pip install -e .

python spikes/fetch_data.py data
export OPENMC_CROSS_SECTIONS="$PWD/data/cross_sections.xml"

pytest          # regression tests
./launch.sh     # run the app from source
```

Building installers and cutting releases: see [`packaging/RELEASE.md`](packaging/RELEASE.md).

## Acknowledgements

- [**OpenMC**](https://openmc.org) — the Monte Carlo transport engine NBEAST is built on.
- [**ENDF/B**](https://www.nndc.bnl.gov/endf/) nuclear data (NNDC, Brookhaven National Laboratory).
- [**conda-forge**](https://conda-forge.org/) — the packages and toolchain behind the offline installer.

## License

**MIT.** Copyright © 2026. Free to use, modify, and distribute — see [LICENSE](LICENSE) for the full text.
