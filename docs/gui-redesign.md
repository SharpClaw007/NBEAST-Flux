# NBEAST GUI overhaul — master plan

> **Status: shipped (G0–G6).** All seven phases are on `main`, suite green (229
> passed, 5 data-gated skips). The app is now a COMSOL-style Model Builder:
> - **G0** Document + undo/redo (⌘Z) + project schema v2 (+v1 migration) + window-state persistence.
> - **G1** Three-pane shell — Model/Studies/Results tree, settings pane, messages strip; menus + shortcuts.
> - **G2** Live geometry preview (default tab; analytic slices, live on edit).
> - **G3** Persistent Studies framework (config + results saved in the project); k-eff fully in-pane.
> - **G4** All analysis tools persist their results onto their study (survive close/reopen).
> - **G5** Welcome screen (recents + template gallery + examples) and Report center (sectioned HTML/PDF).
> - **G6** Data Library search + disk-usage footer + non-blocking download progress; polish pass.
>
> Deferred-by-design (noted where relevant): full in-pane embedding of the analysis
> plots (tools remain their own windows but are now persistent + non-modal-in-effect);
> a dedicated Compare *study* kind (compare stays on the Saved-runs right-click); the
> CAD import stays its working off-screen-preview dialog rather than a sheet-wizard.

---


**Goal:** make NBEAST look and work like commercial scientific software (COMSOL /
ANSYS class), while keeping the two-layer architecture (`nbeast.core` Qt-free,
`nbeast.gui` PySide6) and the 200-test suite green at every step.

**Decided direction** (user-confirmed):

- **Paradigm:** COMSOL-style **Model Builder** — one authoritative tree (Model →
  Studies → Results), a settings pane driven by tree selection, a central viewport.
- **Analyses become persistent Studies** — configured, queued, re-runnable, saved in
  the project with their results. The eight one-shot modal dialogs are retired.
- **Look:** native macOS polish (platform-correct toolbar, icons, spacing, shortcuts,
  sheets), not a custom theme. Anything custom-drawn must be theme-independent
  (the periodic-table dark-mode lesson).
- **UX systems in scope:** live geometry preview · welcome screen · undo/redo ·
  report center · Data Library redesign.

---

## 1. Design principles

1. **The tree is the truth.** Every model object, study, and result is a tree node;
   selecting a node shows its settings; right-click adds/derives/deletes. No state
   lives only inside a dialog.
2. **Nothing is lost.** Every run, sweep, and analysis is a Study persisted in the
   project — closing a window never discards results. Reopening a project restores
   everything, including plots.
3. **See before you run.** The viewport always shows *something*: the colored model
   geometry before a run, live convergence during, fields after.
4. **Honesty is UI.** Uncertainties, "needs data" states, validation badges, and
   approximation notes (temperature snapping, relative-vs-absolute units) are shown
   where the number is shown, not buried in docs.
5. **Native, not novel.** macOS conventions: `⌘R` runs, `⌘Z` undoes, `⌘,` opens
   Settings, destructive confirmations are sheets, menus follow HIG naming.
6. **Small-lab pragmatism.** Single-window, no MDI; keyboard-friendly; fast startup;
   everything works offline with the bundled data.

---

## 2. Target architecture

### 2.1 Shell layout (replaces the 5-dock arrangement)

```
┌──────────────────────────── toolbar (native) ─────────────────────────────┐
│  New  Open │ ⏵ Run  ⏹ │ quality ▾ │ units ▾ │            search/status   │
├────────────┬──────────────────┬───────────────────────────────────────────┤
│ MODEL      │ SETTINGS         │  VIEWPORT TABS                            │
│ BUILDER    │ (of selected     │  [ Geometry | Convergence | Flux | Spec ] │
│ (tree)     │  tree node)      │                                           │
│            │                  │             3D / plot area                │
│ ▾ Model    │  contextual      │                                           │
│ ▾ Studies  │  form + Run      ├───────────────────────────────────────────┤
│ ▾ Results  │  button          │  MESSAGES / PROGRESS strip (collapsible)  │
└────────────┴──────────────────┴───────────────────────────────────────────┘
```

- **Model Builder tree** (left, always visible): three fixed roots.
  - **Model** — template node (Pin cell/Assembly/Godiva/Shield/CAD) with children:
    Geometry (params), Materials (one node per role), Physics/Settings (temperature,
    density coupling, power/source normalization, seed).
  - **Studies** — every configured analysis (see §3). Context menu: *Add Study ▸
    (k-eff, Sweep, Criticality search, Moderation curve, Poisoning, MGXS, Depletion,
    Compare)*, Duplicate, Rename, Delete, Run, Run All.
  - **Results** — one node per completed study run, children per view (Flux 2D/3D,
    Spectrum, Dose, tables, exports). Double-click opens in the viewport.
- **Settings pane** (replaces the Properties table): a real form per node type —
  grouped fields, unit suffixes, inline "needs data → open Data Library" chips,
  per-field reset-to-default, and the node's primary action button (e.g. *Run study*).
- **Viewport** (center): tabbed; tabs are created/closed by Results interaction, with
  Geometry and Convergence always available.
- **Messages strip** (bottom, collapsible): run log, progress bar per queued study,
  warnings (replaces most `statusBar().showMessage` traffic; status bar keeps only
  transient hints). Errors appear here as dismissible banners, not just fading text.
- **Retired:** Properties dock, Results dock, Run history dock, Analysis dock (all
  absorbed by the tree); the free-floating dialogs (become studies or panes).

### 2.2 The document object (foundation for everything)

Today model state lives in `MainWindow` dicts (`_param_values`,
`_material_values`, spins). Extract a **`Document`** (Qt-free where possible,
`gui/document.py` + `core/project.py` v2 schema):

- holds template, params, materials, physics settings, study list, result refs;
- emits change signals; the tree/settings/viewport are views over it;
- **all mutations go through `QUndoCommand`s** (SetParam, SetMaterial,
  SwitchTemplate, AddStudy, EditStudy, DeleteStudy, RenameNode) on a `QUndoStack`
  → native Edit ▸ Undo/Redo, ⌘Z/⇧⌘Z, dirty-state tracking, and the window's
  `setWindowModified` dot for free;
- project schema v2 (JSON): `{model, studies[], results[]}` with a migrator for
  v1 projects (current format) — old projects open cleanly.

---

## 3. Studies system (the workflow core)

A **Study** = config + runner + persisted results.

```python
# core/studies.py (Qt-free)
@dataclass
class StudyConfig:            # serializable; one subclass per study type
    kind: str                 # "keff" | "sweep" | "search" | "moderation" |
                              # "poisoning" | "mgxs" | "depletion" | "compare"
    name: str
    quality: RunQuality       # batches/particles/inactive/seed
    params: dict              # kind-specific

class StudyRun:               # a completed execution
    config_snapshot, timestamps, statepoint/artifact paths,
    diagnostics, scalar results (k, worths, x±σ…), provenance
```

- **Queue:** studies run sequentially on the existing worker/Runner machinery
  (one subprocess at a time — Rosetta + MPI make parallel runs risky). Queue UI in
  the messages strip: pending / running (with live batch progress) / done / failed.
- **Persistence:** each StudyRun's artifacts live under the project dir
  (`runs/<study>/<timestamp>/`); plots are re-derived from artifacts on load (no
  pickled figures). Run history dock is retired — its content *is* the Results tree.
- **Migration map (dialog → study type):**

| Today (modal dialog) | Becomes |
|---|---|
| Run button / run history | **k-eff study** (the default study every project starts with) |
| SweepDialog (sweep + criticality search) | **Sweep study**, **Criticality-search study** (report x ± σₓ in the result node) |
| ModerationDialog | **Moderation-curve study** |
| PoisoningDialog | **Poisoning study** (two-pass; stores σ̄ used) |
| MgxsDialog | **MGXS study** (group constants table + export artifacts) |
| DepletionDialog | **Depletion study** (keeps the "not benchmarked" banner in its settings pane) |
| CompareDialog | **Compare study** (references two other studies' runs) |
| CAD import | stays a **wizard/sheet** (it's setup, not analysis) but its result lands as a normal k-eff study |

- Each study's settings pane reuses one shared frame: name/notes row → config form →
  quality group → *Run* / *Duplicate* buttons → last-run summary line with badge
  (✅ converged / ⚠ cautions from diagnostics).

---

## 4. Live geometry preview

- New `core/render_geometry.py`: build the template model → color-by-material
  geometry render **without transport**. Two paths:
  - templates: matplotlib/`openmc.Universe.plot` slice (xy + xz) — cheap, data-free;
  - 3D: off-screen PyVista render of template solids (cylinders/lattice/sphere/slab
    built analytically; CAD already has tessellated STLs) → QPixmap. **Off-screen
    only** — live VTK widgets segfault on teardown under Rosetta (known issue; the
    CAD importer already uses this pattern successfully).
- Debounced (~300 ms) refresh on any Document change; material legend chips reuse
  the CAD legend component.
- The Geometry viewport tab is the app's **default view on open** — the app never
  starts empty.

## 5. Welcome screen

- Shown at launch (and via File ▸ Welcome): recent projects (path, template badge,
  last-run k), **template gallery** with geometry thumbnails (from §4 renderer),
  example cases (current Examples menu), and a "validation status" footer linking
  docs/validation.md. Opening anything lands in the Model Builder.

## 6. Report center

- One dialog/pane assembling a report from checkable sections: model description +
  geometry render, per-study sections (config, k ± σ, plots, field renders,
  diagnostics + cautions), data provenance (library, temperatures, seed, versions),
  validation appendix. Output: HTML (always) + PDF (Qt print). Replaces/absorbs the
  current export_report path. Per-study "Include in report" checkboxes in the tree.

## 7. Data Library redesign

Keep the two concepts (Materials view, Elements periodic table) but restructure as a
**package-manager window**:

- Left sidebar: Installed · Materials (by category) · Elements · Poisons ·
  Depletion · Import. Top: search box filtering across everything ("Gd", "steel",
  "c_Graphite").
- Rows get status **chips** (Installed / Needs data / Downloading 42%) with inline
  per-row progress bars (downloads currently freeze the whole window's tree —
  switch to per-row async progress with a cancel button).
- Footer: disk-usage bar (bundle + downloads), Standard-set and Everything buttons,
  Reset. Downloads queue like studies (visible in the messages strip too).
- Periodic table stays (it's good) — gains the search highlight + a hover card
  (full element name, isotope count, size).

## 8. Native macOS polish pass

- **Toolbar:** icon+text native `QToolBar`, SF-Symbols-style template icons
  (monochrome, auto light/dark), unified title-toolbar look.
- **Shortcuts:** ⌘R run · ⌘. stop · ⌘Z/⇧⌘Z undo/redo · ⌘S save · ⌘, settings ·
  ⌘1/2/3/4 viewport tabs · ⌘F search tree · Space quick-look a result.
- **Menus:** HIG-conformant (File/Edit/View/Study/Window/Help); Edit exists (undo
  needs it); View toggles panes; Help ▸ searchable actions.
- **Sheets & dialogs:** destructive confirmations (delete study, reset data) as
  window-modal sheets; CAD import as a sheet-wizard.
- **Details:** remember window geometry + layout; default 1440×900; empty-state
  hints in every pane ("No studies yet — right-click Studies to add one"); tooltips
  on every field (with units + typical range); HiDPI pixmaps everywhere;
  theme-independent custom drawing (audit: periodic table done, flux colorbars,
  legend chips, plots' pens).

---

## 9. Phasing (each phase ships on `main`, suite green, app usable)

| Phase | Contents | Size | Exit criteria |
|---|---|---|---|
| **G0 Foundation** | `Document` extraction, undo stack + commands, project schema v2 + v1 migrator, style/icon kit, window-state persistence | L | all edits undoable; old projects open; tests for commands/migrator |
| **G1 Shell** | Model Builder tree + settings pane replace Properties/Results/History/Analysis docks; messages strip; menu/toolbar/shortcut overhaul | L | feature parity with today's docks; GUI tests updated |
| **G2 Geometry preview** | `render_geometry` + Geometry tab + welcome-screen thumbnails infra | M | pin cell/assembly/godiva/slab/CAD all preview pre-run, live on edit |
| **G3 Studies** | Study framework + queue; migrate k-eff, sweep, search, moderation | L | studies persist + reload with plots; run-history dock retired |
| **G4 Studies II** | poisoning, MGXS, depletion, compare as studies; CAD wizard-sheet | M | all 8 dialogs retired |
| **G5 Welcome + Report** | welcome screen; report center absorbing export_report | M | cold launch → welcome; one-click HTML/PDF report with study sections |
| **G6 Data Library + polish** | package-manager redesign, per-row download progress, search; final macOS pass (sheets, empty states, tooltips, icons); screenshots for README | M | download UX non-blocking; HIG audit checklist done |

Ordering rationale: G0 unblocks everything (undo + document are load-bearing);
the shell must exist before studies have a home; geometry preview early because it
transforms perceived quality for small cost; Data Library last because it was
recently rebuilt and is functional today.

## 10. Risks & mitigations

- **VTK under Rosetta:** never embed live GL widgets in transient windows;
  off-screen render → pixmap everywhere except the (already-stable) main viewport.
- **QThread footguns:** keep the bound-method-signal pattern (the lambda/direct-
  connection crash from the CAD work); one shared `StudyQueue` controller instead
  of per-dialog thread plumbing — fewer places to get it wrong.
- **Scope creep in G1:** the shell lands with *parity*, not new features; every
  pane keeps its current capability list as the acceptance checklist.
- **Schema migration:** v1 projects and old run dirs must load (test fixtures with
  a captured v1 project file).
- **Test churn:** GUI tests are rewritten per phase alongside the code they cover;
  the core (physics) tests are untouched by all of this.

## Out of scope (explicitly)

Multi-window/MDI, collaborative features, in-app scripting console, Windows/Linux
theming passes (revisit after G6), parallel study execution.
