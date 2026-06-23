# NBEAST — Plan

An offline-capable, open-source desktop GUI for neutron-flux Monte Carlo simulation,
built on **OpenMC**. The goal: the first polished, mainstream, end-to-end GUI for
neutron transport — simple enough for students, deep enough for experts.

Reference UX: Caedium-style — ribbon toolbar, dockable trees (model + results),
properties grid, tiled multi-viewport center (3D scene + live monitor plots), status bar.

---

## Roles
- **User (domain owner):** reactor-physics / OpenMC expertise. Owns correctness:
  benchmark specs, material compositions, sensible defaults, UX sign-off.
- **Claude (builder):** writes the application, architecture, packaging, tests.
- **Contract between us:** validated benchmark cases (below) are the regression tests.
  If a template is built wrong, the benchmark k-eff catches it. This is non-negotiable.

## Locked decisions (v1 spec)
| Dimension | Decision |
|---|---|
| Target user | Students & educators; experts served via progressive disclosure |
| Platforms | macOS + Linux at launch; Windows architected-for, deferred |
| Project model | Open source |
| Physics | Criticality / k-eff (eigenvalue mode) only |
| Geometry | Templates + primitives (pin cell, lattice/assembly, simple solids) + live preview |
| Nuclear data | Curated teaching subset bundled (offline day-one); optional in-app full ENDF/B-VIII download |
| Export | Report (PDF/PNG/CSV) + **reproducible OpenMC input deck** |
| Validation | Godiva + pin cell + small assembly ship as validated examples = tutorials = regression tests |
| Team / clock | Solo (user as domain reviewer, Claude as dev); no fixed deadline |

## Stack
- **Language:** Python end-to-end.
- **GUI shell:** PySide6 (Qt, LGPL) — ribbon, `QDockWidget` panels, `QTreeView`, properties grid.
- **3D viewport:** VTK via pyvista + pyvistaqt (embedded in Qt).
- **Live monitors:** pyqtgraph (real-time k-eff / Shannon entropy / tally-vs-batch).
- **Static report figures:** matplotlib.
- **Engine integration:** OpenMC Python API + `openmc.lib` (C/ctypes) for batch-level streaming.
- **Packaging:** conda + `constructor` → per-OS installers (.dmg/.pkg for macOS, .sh / AppImage for Linux).

---

## Architecture

Two clean layers so the engine is testable and scriptable without a GUI:

- **`nbeast.core` (no Qt):** domain model (materials, geometry templates, settings, tallies)
  that maps to OpenMC objects; a `Runner` for batch-stepped execution with a callback API;
  a `Results` reader (statepoints); the OpenMC input-deck exporter (it builds real `openmc`
  objects, so export is nearly free). Fully unit-tested and CI'd.
- **`nbeast.gui` (PySide6):** thin layer over `core`, talks via Qt signals/slots. The run
  executes off the UI thread; per-batch data streams to the monitors.

**Run isolation (DECIDED):** a **subprocess worker** runs the `openmc.lib` batch loop and
emits per-batch JSON lines over a pipe → crash isolation + clean stop/kill + live streaming.
The GUI never runs transport in-process. Phase 0 Spike B validates the mechanics.

## UI layout (Caedium → NBEAST)
- **Ribbon:** Project (New/Open/Save) · Model (Materials/Geometry/Source) · Tallies · Run (Run/Step/Stop) · Results · Help
- **Left dock (top):** Model tree — Materials, Geometry, Settings, Tallies
- **Left dock (bottom):** Properties grid for the selected item
- **Center (tiled/tabbed):** 3D geometry + flux view · convergence monitor (k-eff + entropy) · flux spectrum
- **Right dock:** Results tree — toggleable fields (flux, fission rate, by energy group, mesh)
- **Status bar:** run state, batch counter, ETA

---

## v1 scope

**IN**
- Pin cell + simple assembly templates; primitives incl. bare sphere (Godiva)
- Preset materials library (UO₂ at enrichments, water, zircaloy, etc.) — no hand-entered densities
- Eigenvalue settings (batches, inactive, particles) with smart defaults + simple/advanced toggle
- Run with live k-eff + Shannon-entropy monitor; step / stop
- Results: k-eff ± σ, flux spectrum, flux/fission mesh-tally 3D map
- Particle-track visualization (sampled neutron histories) — signature teaching feature
- Export: report + OpenMC input deck
- 3 validated built-in examples (Godiva, pin cell, assembly)
- Curated bundled data + optional full-library download
- macOS + Linux installers

**OUT (explicitly deferred)**
- Shielding / fixed-source; general CSG editor; CAD/DAGMC import (CAD → **Phase 6**)
- Depletion/burnup; variance reduction; multiphysics coupling
- Windows; raw HDF5/VTK data export
- Parameter sweeps / criticality search — strong **post-v1** candidate (the simple↔expert bridge)

---

## Phased build plan (milestone-based; risk front-loaded)

### Phase 0 — De-risk spikes  ✅ COMPLETE (2026-06-22)
All three spikes passed. Findings & pinned env: `docs/phase0-notes.md`, `environment.yml`.
Key results: pin cell **k∞ = 1.4115 ± 0.0025**; subprocess streaming + clean cancel proven;
flux mesh → VTK → render works. Surprises: **no conda-forge OpenMC for osx-arm64** (dev runs
osx-64 under Rosetta, task #5); **`FI_PROVIDER=tcp`** required; **S(α,β) from ENDF/B-7.1**;
entropy not in `openmc.lib`.

Prove the scary parts before building UI on top of them.
- **Spike A (packaging):** bundle conda-forge `openmc` + curated data via `constructor` on
  macOS + Linux. **Done when:** a no-internet machine runs a pin cell from the installed bundle.
- **Spike B (live streaming):** settle in-process vs subprocess; worker runs the `openmc.lib`
  batch loop and emits per-batch k-eff (+ entropy, or parsed if not exposed) as JSON lines;
  consumer prints live. **Done when:** live k-eff streams and the run stops cleanly mid-flight.
- **Spike C (viz):** pyvistaqt renders an OpenMC geometry slice, a flux mesh tally, and sampled
  tracks in an embedded Qt widget. **Done when:** a flux mesh tally renders in-app.
- **Output:** short architecture-decision note + a pinned, known-good dependency set.

### Phase 1 — Headless core (no GUI)  ✅ COMPLETE (2026-06-22)
`src/nbeast/core/` built and tested: materials presets, geometry templates,
benchmarks (Godiva k≈1.0, pin cell), subprocess `Runner` (live stream + cancel),
`Results` reader (spectrum + mesh→VTK), deck `export` (model.xml + run.py). 6
pytest regression tests pass locally; CI workflow added (`.github/workflows/ci.yml`,
runs on first push). Done-criterion met: builds Godiva → runs → k≈1.0 → exports deck.

- Domain model + OpenMC adapter (pin cell template + materials library)
- `Runner` (architecture chosen in Phase 0) with clean callback API
- `Results` reader (k-eff, spectrum, mesh tally)
- OpenMC input-deck export
- Godiva + pin-cell as **automated regression tests** in CI
- **Done when:** `nbeast.core` builds Godiva, runs it, returns k≈1.0 ± stat, exports the deck — all in CI.

### Phase 2 — Application shell  ✅ COMPLETE (2026-06-22)
`src/nbeast/gui/`: MainWindow (toolbar with template/batches/particles + Run/Stop,
dockable Model tree + Properties, Convergence monitor tab + 3D placeholder, status
bar), RunController (QThread → core Runner, queued signals), pyqtgraph monitor.
2 headless smoke tests pass (offscreen): window constructs without data, and a
short Godiva run streams to the live monitor and yields k≈1.0. Full suite: 8 passed.
NOTE: the 3D viewport is a placeholder (real pyvistaqt widget lands in Phase 3, needs
a display). CI updated to install GUI deps + headless-Qt libs.

### Phase 2.5 — Editable parameters  ✅ COMPLETE (2026-06-22)
The Model tree + Properties panel are now a real editor (closing the "what am I
simulating?" gap). Per-template parameter schemas live in `core/specs.py`
(enrichment/pitch/radii for pin cell; radius for Godiva). The tree shows current
values; selecting a group renders editable fields in Properties; edits drive
`_build_model`. 11 tests pass (incl. edit-enrichment→composition-changes).

- PySide6 ribbon + docking layout, model tree, properties grid, viewport tabs, status bar
- Run control wired to the core `Runner` off-thread; live k-eff/entropy via pyqtgraph
- **Done when:** open app → pick pin-cell template → Run → watch convergence live → see k-eff.

### Phase 3 — Visualization  ✅ COMPLETE (2026-06-22)
First increment done: GUI runs attach flux spectrum + flux slice-mesh tallies and
write a statepoint (worker reports its path); **Spectrum** tab (pyqtgraph,
flux-per-lethargy vs log-E) and **Flux map** tab (`FluxViewport`: pyvistaqt,
created lazily + headless-guarded) added; off-screen flux→PNG render (`gui/render.py`)
for headless tests and future report export. 13 tests pass; the pin-cell spectrum
shows the correct thermal/epithermal/fast shape and the flux z-slice renders.
Now complete: live 3D `QtInteractor` verified on a real display (flux renders as a
flat 2D slice); **fission-rate map** + **Results field toggle** (right dock);
**neutron-track visualization** ("Show tracks" — energy-coloured polylines, born
fast and slowing down). 16 tests pass. Known quirk: pin-cell tracks stream far in
z (the lattice is axially unbounded) — bounded templates like Godiva render cleanly;
a future tweak could add axial viz bounds.

- 3D geometry render; flux/fission mesh-tally overlay with toggleable results tree; spectrum; particle tracks
- **Done when:** results viewports deliver the Caedium-style multi-pane experience.

### Phase 4 — Content + export + polish
- Assembly template; materials library expansion; 3 validated examples as one-click tutorials
- Report export; simple/advanced settings toggle; smart defaults
- **Done when:** a new user goes launch → validated assembly result → exported report + deck, no docs.

### Phase 5 — Release engineering
- Polished installers (macOS signing/notarization decision; Linux AppImage); in-app full-data download
- Docs/tutorials; public repo + license; build CI
- **Done when:** a stranger downloads, installs offline, and runs Godiva on macOS and Linux.

### Phase 6 (v2) — Native arm64 DAGMC/MOAB + CAD geometry
The CAD / custom-geometry track, out of v1 scope. CAD geometry in OpenMC needs
**DAGMC**, which needs **MOAB** — and neither has a usable macOS-arm64 conda-forge
build (the stalled upstream chain; this is the same dependency we deliberately
dropped via the `nodagmc` build). So this is a ground-up effort, not a bolt-on:
- Build **MOAB** from source for `osx-arm64` (and linux), bottom-up — our own
  feedstock/CI, independent of the stalled upstream PRs.
- Build **DAGMC** on that MOAB; produce a **dagmc-enabled OpenMC** build.
- Add a **CAD import + meshing pipeline** (MOAB) and a **CAD geometry viewport**;
  extend the engine/templates to a DAGMC geometry path.
- **Done when:** a user can import a CAD model, mesh it, and run/visualise it
  **natively on Apple Silicon**.

---

## Decisions
**Locked:**
- **License:** MIT.
- **Run isolation:** subprocess worker + per-batch JSON-lines streaming (see Architecture).
- **Materials library:** Claude curates the most-used presets for v1; total bundled data kept
  **under ~1 GB** to keep rebuild/iteration fast.

**Open (deferred):**
- **App name / branding / aesthetic** — later.
- **macOS signing** — Apple Developer ID vs unsigned-with-instructions (defer to Phase 5).

## Immediate next step
Install OpenMC locally (conda-forge), `git init` the repo, and run Phase 0 Spike A:
prove a pin cell runs headless from a bundled environment on this Mac.
