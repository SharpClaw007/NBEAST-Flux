---
title: 'NBEAST: An offline desktop GUI for neutron-flux Monte Carlo on OpenMC'
tags:
  - Python
  - neutronics
  - Monte Carlo
  - reactor physics
  - criticality
  - OpenMC
authors:
  - name: J. Reyes
    affiliation: 1
affiliations:
  - name: Independent Researcher
    index: 1
date: 26 June 2026
bibliography: paper.bib
---

# Summary

`NBEAST` is an offline, open-source desktop application that puts a complete
graphical front end on the [OpenMC](https://openmc.org) Monte Carlo neutron
transport code [@Romano2015]. A user picks a reactor-physics template (a PWR pin
cell, an $N \times N$ fuel assembly, or a bare critical sphere), edits its physical
parameters in a model tree, and presses **Run**; the neutron multiplication factor
$k_\mathrm{eff}$ converges live on a plot, and the results — the spatial flux and
fission-rate maps, the energy spectrum, energy-coloured neutron tracks, and a
publication-style 3-D flux volume render — appear in tabbed viewports. Every run
can be exported as a one-page report together with the exact, reproducible OpenMC
input deck that produced it. The application ships fully offline: a single
installer bundles Python, OpenMC, the GUI, and a curated cross-section library
derived from ENDF/B-VIII.0 [@Brown2018], so a new user can install on a
disconnected machine and run a validated criticality calculation with no setup.

Every Monte Carlo result is reported with its statistical uncertainty and a
source-convergence diagnostic. NBEAST surfaces per-bin relative errors on the flux
spectrum and mesh tallies, streams the Shannon entropy of the fission source
alongside $k_\mathrm{eff}$ during the run [@Brown2006], and runs a set of
convergence heuristics that warn — in plain language — when a result should not yet
be trusted. Each run records its provenance (code and nuclear-data versions,
parameters, and random-number seed) so that results are reproducible and citable.

# Statement of need

OpenMC is a powerful, modern, open-source Monte Carlo transport code, but using it
means hand-writing Python or XML input decks and working from the command line.
That workflow is a barrier in two settings where neutron transport is taught and
explored: undergraduate and early-graduate reactor-physics education, where the
input-deck overhead obscures the physics, and rapid exploratory analysis, where a
researcher wants to vary a parameter and *see* the flux without writing a script
each time. Established graphical tools exist for commercial codes, but there has
not been a polished, end-to-end, open-source GUI for a mainstream Monte Carlo
transport engine.

NBEAST addresses this gap with a two-layer design: a Qt-free engine layer
(`nbeast.core`) that maps a small domain model to OpenMC objects, drives
batch-stepped execution in an isolated subprocess, reads results, and exports input
decks; and a thin PySide6 GUI layer over it. The engine is independently testable
and scriptable, and the validated benchmark cases double as the regression test
suite — if a model is built incorrectly, the benchmark $k_\mathrm{eff}$ fails the
test. Progressive disclosure (a Simple/Advanced toggle) keeps the tool approachable
for students while exposing batch, particle, and seed control to experts.

A distinguishing capability is **native Apple Silicon support, including CAD
geometry**. Importing CAD models into OpenMC requires DAGMC [@Wilson2010], which in
turn requires MOAB [@Tautges2004]; at the time of writing, neither has a usable
`osx-arm64` build in the conda-forge ecosystem. NBEAST builds the entire chain from
source — MOAB (with `pymoab`), DAGMC, and a DAGMC-enabled OpenMC — as native arm64
binaries, and integrates a CAD-to-DAGMC meshing pipeline [@cad_to_dagmc] so that a
user can import a STEP assembly, assign materials per solid, mesh it, and run
criticality on it at native speed on an Apple Silicon Mac with no emulation. To our
knowledge this is the first packaged toolchain to make CAD-based neutron transport
work natively on Apple Silicon.

# Features

- **Templated geometry** with live, editable parameters: pin cell, $N \times N$
  assembly, and bare sphere (e.g. the Godiva critical-mass benchmark).
- **Live criticality** monitoring: $k_\mathrm{eff}$ and Shannon entropy stream per
  batch, with a clean cancel.
- **Results with uncertainty**: flux and fission mesh maps, a flux relative-error
  map, the energy spectrum with a $\pm 1\sigma$ band, sampled neutron tracks
  coloured by energy, and a 3-D flux volume render.
- **Trust layer**: convergence diagnostics and warnings, and a per-run provenance
  record for reproducibility.
- **Reproducible export**: a PDF/PNG report, CSV data, and the OpenMC input deck.
- **Offline by default**: bundled cross-section data; optional in-app download of
  additional nuclear data.
- **CAD geometry** (optional Apple-Silicon add-on) via the native DAGMC/MOAB build.

The validated examples (Godiva $k_\mathrm{eff} \approx 1.0$; pin cell and assembly
$k_\infty \approx 1.41$) ship as one-click tutorials and as the automated
regression tests, anchoring correctness.

# Acknowledgements

NBEAST is built on OpenMC and the broader open-source scientific Python and
conda-forge ecosystems, and uses ENDF/B-VIII.0 nuclear data distributed by the
National Nuclear Data Center at Brookhaven National Laboratory.

# References
