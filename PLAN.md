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

### Phase 4 — Content + export + polish  ✅ COMPLETE (2026-06-23)
- **Fuel assembly template** (N×N RectLattice) + **integer parameters** (pins-per-side).
- **Report export** (File ▸ Export…): one-page PDF/PNG report + spectrum CSV + reproducible deck.
- **In-app explanatory layer**: plain-language captions under every result view + tooltips on all controls.
- **Simple / Advanced mode**: Simple = one Quality preset (Quick/Standard/High); Advanced = raw batches/particles.
- **Example presets** (Examples menu): Godiva / pin cell / 7×7 assembly with good defaults + expected-k hints.
- Deferred: materials-library expansion — low value until there's a material-assignment UI (and it needs
  more bundled nuclides); revisit alongside a future material picker.
21 tests pass.

- Assembly template; materials library expansion; 3 validated examples as one-click tutorials
- Report export; simple/advanced settings toggle; smart defaults
- **Done when:** a new user goes launch → validated assembly result → exported report + deck, no docs.

### Phase 5 — Release engineering  ◐ IN PROGRESS (2026-06-23)
Done: **constructor installer pipeline** (`packaging/`) — bundles the env + nbeast wheel +
254 MB curated data (relative-path `cross_sections.xml`) via `extra_files` + `post_install`
(offline pip install, data unpack, launcher script). The osx-64 installer (755 MB,
`nodagmc_nompi`) builds, installs to a prefix, imports, and runs Godiva (k=1.003) from the
bundle — smoke test also caught/fixed conda defaulting to the DAGMC variant. MIT LICENSE added.
Also done: **native osx-arm64 OpenMC build** (`packaging/openmc-arm64/`) — built the
nodagmc/nompi variant from the feedstock recipe via rattler-build, patched to ignore
Homebrew's `/opt/homebrew` (which CMake otherwise links over conda's HDF5/fmt → undefined
symbols). Verified: native arm64 import + Godiva k≈1.0, **no Rosetta**, and no mpich/
FI_PROVIDER issue (it's nompi).
**macOS target is Apple Silicon only** — Intel/osx-64 was dropped (its CI runners
starved). The native **osx-arm64 installer (724 MB)** is built + validated: installs to a
prefix, imports, and runs Godiva from the bundle (`Mach-O arm64` end to end). **v0.0.1 is
published** with the Linux + arm64 installers. Version is single-sourced from
`nbeast.__version__`.
Docs done: README (end-user install + usage) and `packaging/RELEASE.md` (one-line
version bump → build → smoke-test → sign → publish).
**Public repo live with green CI** (github.com/SharpClaw007/NBEAST-Flux). A release
workflow (`.github/workflows/release.yml`) builds all three installers on a `v*` tag —
including a native arm64 OpenMC compile on an Apple Silicon runner — and attaches them to
a GitHub Release (unverified until the first tag; like ci.yml it may need a tuning pass).
**In-app selectable data download** done (`core/data.py` + `gui/data_manager.py`, via
File ▸ Cross-section data…): pick a library + elements/nuclides or a preset, download into
a user dir **seeded from the bundle** (so it stays a superset, never a replacement), and
activate it. The downloader (`openmc_data_downloader` + `retry`) is bundled into the
installer offline. 26 tests pass. **v0.0.1 released** (Linux + Apple Silicon).
Remaining: **macOS signing/notarization** (needs an Apple Developer ID); and validating
the arm64 release job on the next tag (restructured but unproven on a runner).

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

**Detailed implementation plan: [`docs/phase6-plan.md`](docs/phase6-plan.md)** (stages
A–F, effort/risk).

**Stage A — native arm64 MOAB + pymoab: ✅ DONE** (`packaging/moab-arm64/`). Recon
re-shaped the chain: the **MOAB library already ships for `osx-arm64`** (conda-forge), so
Stages B/C are pre-unblocked; the only gap was **pymoab**, whose release-tarball autotools
build is broken (no `paths.py`). Built it from the **git repo via scikit-build-core** (a
self-contained `MOAB` wheel) and validated natively: `import pymoab`, Mach-O arm64
binaries, `.h5m` round-trip.

**Stage B — native arm64 DAGMC: ✅ DONE** (`packaging/dagmc-arm64/`). Built `dagmc 3.2.4`
(nompi/nodoubledown) for `osx-arm64` via conda-build (feedstock is `meta.yaml`), against
the conda-forge arm64 MOAB lib. Fixes: carry the compiler pins (else `c_osx-arm64`
unsatisfiable) and pin **`eigen 3.*`** (Eigen 5.x breaks DAGMC 3.2.4) + Homebrew guard.
Validated: `libdagmc.dylib` + `make_watertight` are Mach-O arm64, links arm64 `libMOAB`.

**Stage C — dagmc-enabled OpenMC (arm64): ✅ DONE** (`packaging/openmc-arm64/`,
`build_openmc_dagmc_arm64.sh`). Rebuilt OpenMC's `dagmc` variant for arm64
(`-DOPENMC_USE_DAGMC=ON`) against the Stage B DAGMC + arm64 MOAB — the smallest stage, as
predicted. Validated: `openmc-0.15.3-dagmc_nompi_*.conda`; `import openmc` on arm64;
`libopenmc.dylib` links `libdagmc` + `libMOAB`; `openmc.lib` loads the full native chain;
`DAGMCUniverse` available. The end-to-end `.h5m` → k-eff run is the Stage C↔D handoff
(needs a real geometry). **Stages D–F remain parked** until otherwise directed.

So the entire native-arm64 build chain is complete: **MOAB → DAGMC → dagmc-OpenMC**, all
Mach-O arm64.

**Stage D — CAD → DAGMC pipeline: ✅ DONE** (`packaging/cad-dagmc-arm64/`). `cad_to_dagmc`
(CadQuery/OCP + gmsh) on conda-forge arm64 — writes `.h5m` via h5py, **no custom builds
needed**. Validated end to end: CadQuery HEU sphere (r=8.7 cm) → `.h5m` → dagmc-OpenMC →
**k-eff 0.984 ± 0.003** native arm64 (closes Stage C's functional run too).

**🎯 Phase 6 technical core is complete (Stages A–D): custom CAD geometry → criticality,
natively on Apple Silicon.**

**Stage E — CAD GUI integration: ✅ DONE (core).** `nbeast.core.cad` orchestrates the
three envs as subprocesses (gated on `is_available()`); `gui/cad_import.py` is a CAD
import dialog (STEP picker, **per-solid material assignment**, mesh + run controls)
wired into the File menu (shown only when the DAGMC envs exist). Validated end to end
from the GUI env: STEP → assign → mesh → run → **k-eff 0.984 ± 0.005**. 31 tests pass.
It also has a **3D CAD viewport** (`FluxViewport.show_cad`) — a "Preview 3D" button
renders the imported solids coloured by material (validated on a fuel+clad pin).

**Stage F — packaging/distribution: ✅ DONE (mechanism).** Because the feature needs two
numpy-incompatible envs, CAD ships as an **optional Apple-Silicon add-on** (gated on
`cad.is_available()`): `packaging/cad-support/assemble_channel.sh` builds a conda channel
of the two custom artifacts (dagmc + dagmc-OpenMC; everything else is conda-forge), and
`setup_cad_support.sh` creates the two envs from it. Validated: channel assembles + a
dry-run solve installs from it. Remaining execution: publish the channel + optional in-app
setup + notarization.

CAD runs also return a **flux spectrum** (shown in the Spectrum view), the channel is
**published** (`cad-channel-osx-arm64-1`), and **File ▸ Set up CAD geometry support…**
installs the add-on in-app (off-thread, live log) when the envs are absent.

CAD runs also return a **spatial flux map** (z-integrated mesh tally), rendered in the 3D
viewport (centre-peaked on a bare HEU sphere — textbook).

**Publication-style flux render** (`FluxViewport.show_field_volume`): a 3D **volume render**
of the flux field — log colour scale, a graded opacity transfer function (low flux
transparent → glowing core), clim clipped to the data, a log colorbar, and a
semi-transparent **geometry overlay**. Wired into both **CAD runs** (3D `flux_volume`
tally + the imported solids as overlay) and **template runs** (`Scalar flux (3D volume)`
in the Results list, via `add_flux_volume_mesh`). Produces the "science-paper" look.

**🏁 Phase 6 is complete (Stages A–F):** custom CAD geometry → mesh → criticality + flux
spectrum + spatial flux map, with a 3D preview, all native on Apple Silicon, published as a
one-command optional add-on with in-app setup. The **only** item left is **macOS
notarization** (needs an Apple Developer ID).

### Phase 7 (v3) — Research-grade: from demo to citable tool
The gap between *"a student can play with it"* and *"a researcher can publish with it."* NBEAST
currently nails the **simple-for-students** half of the v1 vision; this phase builds the
**trustworthy-enough-to-publish** half. **Rigor comes first** — it's a precondition for the rest,
and the citation work depends on it. Ordered by leverage:

**Tier 1 — Trust layer: ✅ DONE (2026-06-26).** The "results need error bars + a convergence
proof" layer landed end to end and is validated against a real Godiva run (54 tests pass).
- **Tally uncertainties everywhere** — `core/results.py` now reads `std_dev`/`rel_err`:
  `Spectrum` carries `flux_std` (+`rel_err`); the spectrum view and report draw a **±1σ band**;
  `field_to_vtk` writes a `<score>_rel_err` array and the Results panel gained a **"Flux relative
  error"** map; the spectrum CSV gained `flux_std`/`flux_rel_err` columns.
- **Source-convergence diagnostic** — `tallies.add_entropy_mesh` enables Shannon entropy; the
  worker computes it **live from the source bank** (`lib.source_bank()`, since `openmc.lib` doesn't
  expose it) and streams it; the monitor shows a stacked **entropy plot with a dashed inactive→active
  boundary**, and the report overlays entropy on the k-eff axis.
- **Convergence / quality warnings** — `results.diagnostics()` returns a `Diagnostics` record
  (k-eff in pcm, rel-err summary, entropy, warnings) from defensible heuristics: high k-eff σ,
  noisy flux, too-few inactive batches, and a Shannon-entropy plateau test. Surfaced in the status
  bar and the report.
- **Reproducibility & provenance** — a **seed control** (fixed by default → reproducible; verified:
  same seed ⇒ identical k, different seed ⇒ independent realization); `core/provenance.py` captures
  NBEAST/OpenMC versions, data library, parameters, seed, host + timestamp, written as
  `provenance.json` in the exported deck and summarised in the report.

**Tier 2 — Citable: ✅ DONE (2026-06-30).** In-repo citation infrastructure is in place:
- **`CITATION.cff`** (CFF 1.2.0) so GitHub renders a "Cite this repository" button; **`.zenodo.json`**
  so a GitHub release auto-archives with a DOI; a short **JOSS paper** (`paper/paper.md` + `paper.bib`)
  whose Statement of Need leads with the native Apple-Silicon CAD toolchain.
- **`CONTRIBUTING.md`** (dev setup, test workflow, the benchmark contract, PR process) plus README
  **Contributing** and **Citing** sections.
- **Remaining (account-gated, user-only):** enable Zenodo↔GitHub + cut a release to mint the DOI,
  then submit the paper to JOSS; add the DOI badge + `doi:`/`preferred-citation:` once minted.

**Tier 3 — Research workflow: ✅ DONE (2026-06-30).** The calculator became an instrument:
- **Project save / load** (`core/project.py`) — a directory-backed project (`project.json` +
  `runs/<id>/statepoint.h5`); **run history persists across launches**, and reopening restores the
  last template/parameters/settings. A default project under `~/.nbeast` makes this automatic.
- **Run-to-run comparison** (`core/compare.py` + comparison dialog) — Δk with its **combined
  uncertainty** (real effect vs MC noise), a changed-first parameter diff, and overlaid spectra.
- **Parameter sweeps / criticality search** (`core/sweep.py` + sweep dialog) — sweep one parameter
  over a range, or a robust **regula-falsi-with-bracket-expansion** search for the critical value
  (validated end-to-end: finds Godiva's critical radius to ~0.02 cm). Runs off-thread, cancellable.
- **Raw data export** (`results.export_mesh_data`) — mesh-tally mean/std/rel-err + geometry to
  NumPy / CSV / HDF5 (cell ordering verified against OpenMC centroids).
- 36 new tests (project, sweep, compare, raw export, GUI), full suite green.

**Tier 4 — Physics breadth: ✅ DONE (2026-06-30).** All four pillars landed:
- **Fixed-source / shielding mode** — a `run_mode` on `TemplateSpec`, a water shield-slab template
  with a monoenergetic beam, and run_mode threaded end-to-end (runner writes `run_meta.json`; the
  worker skips k-eff; the GUI handles the no-k-eff monitor/diagnostics/report). Validated: flux &
  dose attenuate ~40× through 30 cm of water.
- **Richer tallies** — reaction-rate maps (absorption, ν-fission), a **heating** map, and a
  flux-to-dose-rate mesh (ICRP coefficients), all surfaced in the Results picker; plus **multigroup
  XS generation** (`core/mgxs_gen.py` + dialog) producing CASMO-2/4/8/16 few-group constants
  (total/absorption/fission/ν-fission/χ) with CSV/HDF5 export.
- **Temperature / Doppler control** — a global temperature, exposed as an editable *and sweepable*
  parameter, threaded through every builder (nearest-temperature interpolation; capped at 1200 K by
  the single-temperature water S(α,β) kernel). Validated: Δk(294→900 K) ≈ −1842 pcm.
- **Depletion / burnup** — an **optional, data-gated** workflow (like CAD): `core/depletion.py` +
  `_depletion_run.py` subprocess + a setup guide and a k-vs-burnup dialog. `is_available()` gates on
  a configured chain. Validated end-to-end locally against a reduced CASL chain (k vs burnup over a
  toy Godiva history); the chain + depletion-capable library are user-downloaded, never bundled.
- Notes: depletion needs `normalization_mode='source-rate'` for reduced chains (no fission-Q);
  power normalization needs a full chain. A stale local data index (missing O18) that silently broke
  water templates through the `openmc.lib` worker was rebuilt via `data.build_index`.

**Done when:** a researcher can run a **converged, uncertainty-quantified, reproducible** case;
**save / compare / sweep** it; **export the raw tally data**; and **cite NBEAST by DOI**.

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

## Status (current)
Research-grade offline GUI, all working; **180 tests pass** (`pytest -q`). Commit + push to
`main` after each task. **No `Co-Authored-By: Claude` trailer** (author `juanq <jr101@rice.edu>`).
Never commit cross-section data (`data/` gitignored; downloads local-only). Test env:
`env -u DYLD_LIBRARY_PATH OPENMC_CROSS_SECTIONS=.../data/cross_sections.xml FI_PROVIDER=tcp QT_QPA_PLATFORM=offscreen`;
dev python `~/miniforge3/envs/nbeast/bin/python`. App = `NBEAST.app` (thin launcher → editable
`nbeast` console script, so `src/` edits flow in live). Bundle carries only H/O/U/Zr.

**Built this session (newest first):**
- **Data Library** (`gui/data_library.py`, `core/data.py`) — one window, replaces the scattered
  downloader/poison/depletion entry points (`data_manager.py` retired). Categories by material use +
  Poisons + Depletion + **All elements** (full 97-element / 556-nuclide periodic table, each
  element expands lazily → its isotopes + the materials that use it). Real **cached size table**
  (`core/data_sizes.json`, probed HEAD sizes; Everything ≈ 5 GB). Per-item/category/all download,
  import `.h5`/xml, per-element **delete** (downloaded items live in their category, not a top block).
- **Material dropdowns**: list every *installed* material cross-category (any material → any slot),
  no greyed "needs data" entries. Added **Plutonium metal (Jezebel)** fuel.
- **Results 2D/3D**: separate list entries per field; z-uniform templates extrude the slice to 3D,
  CAD renders volumetric on the geometry, Godiva uses its real 3D flux.
- **CAD**: off-screen colour-coded preview (Rosetta GL teardown crash fixed), box fission source
  (off-origin geometry), all fields volumetric.
- **Analysis tab** (was a menu); **moderation curve**; **reactor poisoning** (Xe/Sm, validated);
  **units** (SI/US + optional reactor-power/source-strength → absolute, validated to PWR scale).

**Deferred / open:**
- Account-gated: **Zenodo DOI + JOSS** submission (parked, needs user accounts).
- Depletion "download" in the Data Library **links to the setup dialog** (not fully inline).
- CAD: no report export yet (use raw-data export); CAD config not persisted across launches.
- Delete granularity is per-element (not per-isotope) — intentional.
