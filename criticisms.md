# NBEAST — criticisms and fixes

> **Resolution status (all 12 addressed).** Suite: 200 passed, 5 skipped (data-gated
> benchmarks that need downloads). Highlights:
> - **#8** dose filters → log-log at all 3 sites (+ lock-in tests). ✅
> - **#10** FLiBe → Li-7 enriched; MOX → reactor-grade Pu vector (WNA); `plutonium_metal`
>   relabelled α-phase; faithful `benchmarks.jezebel()` added — **validated k = 0.99893**. ✅
> - **#9** few-group set completed (transport + diffusion coeff + P0 ν-scatter matrix);
>   claim softened; **two-group solve reproduces MC k∞ to ~450 pcm**. ✅
> - **#7** criticality search made σ-aware (significance-gated brackets, Illinois FP,
>   variance-aware refinement, x ± σₓ) — **validated on Godiva, 8.732 ± 0.010 cm**. ✅
> - **#1** Mosteller Doppler pin-cell benchmark added (coefficients within ~1σ of VII.0);
>   **LEU-COMP-THERM-001** thermal critical experiment added — **validated k = 1.00206**. ✅
> - **#11** regression windows tightened (±10000 → ±~1200 pcm) + assembly==pincell +
>   Doppler magnitude band. ✅
> - **#5** energy-conservation test (KERMA/κ ≈ 0.91, local-deposition bound) + dose
>   hand-calc (**dose/flux = 301.0 = ICRP-116 @ 1 MeV, exact**). ✅
> - **#3** poisons spectrum-averaged (fold clean spectrum); saturated default —
>   **Xe −2831 pcm, now in the −2600..−3000 reference range** (was −3230). ✅
> - **#4** isothermal `couple_density` path (NIST water ρ(T)) + temperature "data note";
>   true interpolation documented as a multi-temp-download path. ✅
> - **#12** test skips (not silent PASS), generations-per-batch entropy indexing,
>   source-rate σ exposed + documented. ✅
> - **#2** depletion "workflow validated; numbers not benchmarked" banner (VERA deferred
>   per request). ✅
> - **#6** Standard data tier (one-click ~90%-of-catalog set). ✅
>
> Also fixed en route: stale auto-material selections no longer crash the tree, and
> synthetic-element downloads (Pu/Am/Tc) now fetch by nuclide (`-e` matched nothing).
> See `docs/validation.md` for the numbers and git history for per-item commits.

---


An honest assessment of where NBEAST's academic rigor is strong, where it is thin,
and the concrete fixes for each gap. The summary judgment: the tool is usable for
real work **within a bounded scope** (reactor-physics teaching, criticality, and
rapid exploratory flux/spectrum studies), with **no glaring errors in the core
pipeline** — the Godiva model build, the absolute-normalization chain, the Δk
uncertainty math, the per-lethargy spectrum conversion, and the poison equilibrium
algebra have all been independently verified against the specs and formulas.

Items **1–6** are about validation breadth and unvalidated advanced features.
Items **7–12** come from a follow-up code audit and are **genuine correctness
issues in specific features** — the criticality search's statistics, dose
interpolation, the few-group export's claim, and three catalog materials. All are
bounded and cheap to fix; none sit in the core criticality path.

Each item lists the concern and concrete, code-level fixes tied to the files they
touch, ordered within each section from cheapest to heaviest.

---

## 1. Validation breadth is thin (the thermal-lattice path is not benchmarked)

**Concern.** One external benchmark (Godiva, a bare fast-metal sphere) carries the
entire criticality claim. The thermal-lattice path (pin cell / assembly k∞ ≈ 1.41)
is checked only against a soft textbook expectation ("≈ 1.40") and an internal
consistency check (assembly == pin cell to ~1 pcm) — **not** against a thermal
criticality benchmark. Thermal correctness currently rests on the inference
"OpenMC is validated + our fast-sphere model-build is faithful ⟹ our thermal
model-build is faithful," which is reasonable but not airtight.

**Fixes.**

- **Cheapest interim** — in `docs/validation.md`, stop comparing pin-cell k∞ to a
  soft "≈ 1.40" and instead cite a specific published pin-cell k∞ (e.g. an OECD/NEA
  or VERA 2D pin value) with its enrichment/temperature, so the number has a real
  referent.
- **High-leverage** — add the **Mosteller Doppler pin-cell benchmark**. It *is* the
  `templates.pin_cell` geometry (≈1.26 cm pitch, ≈0.39 cm pellet, Zr clad, water)
  with a published cross-code reference k∞ *and* Doppler defect, so it also closes
  concern #4.
  - Add `benchmarks.mosteller_pincell(enrichment, fuel_temp, mod_temp)` in
    `core/benchmarks.py`, driving `pin_cell` with the benchmark's exact
    dimensions/compositions.
  - Add a `test_mosteller` in `tests/test_benchmarks.py` asserting k∞ at
    0.71 / 2.4 / 3.9 wt% within the published band.
- **Strongest (higher effort)** — add one ICSBEP `LEU-COMP-THERM-001` case as its
  own 3-D rod-lattice geometry (a new function, not the template — it needs finite
  rods + water reflector). This upgrades the thermal claim from "textbook + internal
  consistency" to "published critical experiment, k = 1.0," and is the single
  biggest credibility win.

---

## 2. Depletion / burnup is plumbing-only, not physics-validated

**Concern.** The bundled library is criticality-only; the depletion workflow was
exercised with a reduced actinide-only chain. Burnup *numbers* are not trustworthy
for real work until a user supplies a full chain + depletion library — and even then
nothing in-tool validates them.

**Fixes.**

- **Label it in-UI now** — in `gui/depletion_dialog.py` / `gui/depletion_setup.py`,
  add a "workflow validated; burnup numbers not benchmarked" banner so a user cannot
  mistake plumbing for physics.
- **Validate against the VERA depletion benchmark (Problem 1 — single fuel pin).**
  It publishes pin-cell k∞ vs burnup from multiple codes, the tractable target for a
  template tool.
  - Bundle/download a full chain (`chain_endfb80.xml`) + a depletion-capable
    library, then run `core/_depletion_run.py` on the pin cell to ~60 GWd/tHM.
  - Add a depletion section to `docs/validation.md` comparing the k∞(burnup) curve
    and key inventories (U-235, Pu-239, and Nd-148 as the burnup monitor) against
    the published range.

---

## 3. Poison worths are a saturation / infinite-lattice estimate (Xe reads high)

**Concern.** Equilibrium Xe-135 / Sm-149 worths come from closed-form chain
constants using 2200 m/s one-group cross sections, evaluated at the saturation
(maximum) xenon level in an infinite pin lattice. Xe comes out slightly high
(≈ −3230 pcm vs a typical −2600 to −3000).

**Fixes.**

- **Cheap, big accuracy gain — make the concentrations spectrum-consistent.** The
  overprediction comes from the hard-coded 2200 m/s constants in `core/poisons.py`
  (`SIGMA_F_U235 = 585`, `SIGMA_A_XE = 2.65e6`). Do a **two-pass** calculation:
  1. Run the clean pin cell and tally spectrum-averaged σ_f(U235) and
     σ_a(Xe135) / σ_a(Sm149) over the actual thermal flux.
  2. Feed those into `equilibrium_ratios()` instead of the 2200 m/s values.
- **Already half-built — default to a finite operating flux, not saturation.**
  `equilibrium_ratios(flux=...)` supports it; in `gui/poisoning_dialog.py` default
  to a realistic thermal flux (~3×10¹³ n·cm⁻²·s⁻¹) rather than `None` (saturation),
  and present saturation as the conservative upper bound.
- **Rigorous** — once concern #2's chain is available, compute Xe/Sm from a short
  depletion-to-equilibrium solve, replacing the closed form entirely.

---

## 4. Doppler is constant-density and uses nearest-temperature snapping

**Concern.** Temperatures snap to the nearest data grid point
(250 / 294 / 600 / 900 / 1200 K) with the thermal S(α,β) kernel pinned at 294 K, so
the reported coefficient is a fuel-temperature/spectral (Doppler) coefficient, not a
full isothermal coefficient, and intermediate temperatures are not truly
interpolated.

**Fixes.**

- **Enable true temperature interpolation.** The blocker is the thermal kernel
  (only 294 K bundled). Download `c_H_in_H2O` at multiple temperatures (ENDF/B
  provides 294 / 350 / … / 600 K), then switch `_apply_temperature` in
  `core/templates.py` from `{"method": "nearest"}` to `{"method":
  "interpolation"}`. This removes grid-snapping for both continuous-energy and
  thermal-scattering data.
- **Offer a true isothermal coefficient.** Add a `couple_density=True` path that
  scales moderator density with temperature via the saturated-water density curve
  (IAPWS or a fitted ρ(T) at PWR pressure), reusing the existing
  `templates.scale_density`. Report the constant-density Doppler and the full
  moderator/isothermal coefficient separately — which is also more instructive.
- **Validate** the resulting Doppler defect against the Mosteller benchmark from
  concern #1.

---

## 5. Absolute units are an order-of-magnitude fission-power normalization

**Concern.** The normalization math is correct (flux = tally·S/V; heating eV→J;
dose via ICRP-116 pSv·cm² → Sv/h; source rate from a whole-geometry `kappa-fission`
tally). But "order of magnitude" is the current *confidence* level — it is not
calibrated against an absolute flux/dose standard, and dose/heating maps are
validated for shape/trend, not absolute magnitude.

**Fixes.**

- **Make the energy-conservation check a test.** The heating map already integrates
  to ~the input power (κ-fission vs the heating score agree to ~200 MeV/fission).
  Formalize it: a `tests/test_units.py` case that sets a pin power, then asserts
  Σ(heating · cell volume) equals the input power within a few percent. This turns
  "lands on the right scale" into "energy conservation verified."
- **Document / enable local-vs-transported deposition.** `kappa-fission` assumes all
  recoverable energy deposits locally. If photon transport is off, the *spatial*
  heating map deposits gamma energy at the fission site. Either enable
  `settings.photon_transport` for accurate heating maps, or state the
  local-deposition assumption explicitly in `core/units.py` / `docs/validation.md`.
- **Anchor dose.** Add one flux-to-dose check against a hand calculation
  (monoenergetic beam × the ICRP-116 coefficient at that energy) so `dose_mesh` has
  an absolute referent, not just a shape.

---

## 6. The offline library is tiny (H / O / U / Zr)

**Concern.** The bundled offline library carries only H/O/U/Zr, so most of the
material catalog needs a download before it will run.

**Fixes.**

- **Ship a "Standard" bundle tier.** `core/data.py` already defines download
  presets — extend the *bundled* set to cover the catalog's common materials (add
  B, Gd, Fe, Cr, Ni, C, Na, Al, Si, N, He, Pb). That makes ~90% of the material
  dropdown runnable offline at the cost of a larger installer. Keep the current
  minimal bundle as a "Lite" installer and offer "Standard" as the default.
- **Auto-fetch on first launch when online.** Wire the first-run flow
  (`gui/data_manager.py`) to fetch the "Thermal reactor + Common absorbers +
  structural" presets already defined in `data.PRESETS`, keeping the offline
  installer minimal while giving online users a complete catalog immediately.

---

## 7. The criticality search ignores Monte Carlo noise in k

**Concern.** The most scientifically dangerous feature as shipped. The sweep worker
computes `(k, σ)` per point but calls `search.submit(x, k)` — the uncertainty is
discarded (`CriticalitySearch.submit` in `core/sweep.py` has no std parameter at
all). Convergence gates on a fixed `tol_k = 1.5e-3` (150 pcm), while the default
search run quality (60 batches × 1500 particles, `gui/sweep_dialog.py`) yields
σ(k) of roughly 100–300 pcm — the tolerance sits **at or below the noise floor**.
Bracketing keys off the sign of `(a.k − t)(b.k − t)` on raw noisy k, so two
near-critical points can produce a spurious sign flip and a regula-falsi "root"
driven by noise. The result is reported with no uncertainty band. It is also
internally inconsistent: the diagnostics flag any run with σ(k) > 200 pcm as
"statistically weak" (`_KEFF_PCM_WARN` in `core/results.py`), yet the search
claims convergence at 150 pcm.

**Fixes.**

- **Cheapest interim** — raise `tol_k` above the default-quality noise floor and
  reconcile it with `_KEFF_PCM_WARN` (one number, one comment explaining why).
- **The real fix** — thread σ through: `submit(x, k, std)`, store per-point σ, and
  gate convergence on `|k − target| ≤ max(tol_k, m·σ)` with m ≈ 2. Only accept a
  bracket when the endpoints differ from the target by more than their combined σ.
- **Report the answer as an interval** — propagate endpoint σ through the
  regula-falsi slope (or bootstrap over the stored points) and display the critical
  parameter as `x ± σₓ`, not a bare number.
- **Heavier** — variance-aware refinement: auto-increase particles as the bracket
  narrows so σ(k) shrinks in step with the interval (and switch regula falsi to the
  Illinois variant, which doesn't retain a stale endpoint on monotone curves).

---

## 8. Dose maps interpolate ICRP-116 coefficients linear–linear

**Concern.** The `openmc.EnergyFunctionFilter(energies, coeffs)` for the dose tally
is constructed without setting `.interpolation`, so it defaults to
`"linear-linear"` — in `core/tallies.py` (dose mesh) and twice in
`core/_cad_run.py`. ICRP-116 fluence-to-dose coefficients are tabulated on a
coarse, decade-spanning energy grid and are conventionally interpolated log–log;
lin–lin between sparse points over log energy measurably distorts the dose
response, worst in the thermal/epithermal range.

**Fixes.**

- **One line, three sites** — set `filt.interpolation = "log-log"` on every
  `EnergyFunctionFilter` (`core/tallies.py`, both sites in `core/_cad_run.py`).
- **Lock it in** — a unit test asserting the dose filter's interpolation scheme, so
  a future refactor can't silently regress to the default.
- This pairs with concern #5's dose anchor: do the hand-calculation check *after*
  switching to log–log, so the anchor validates the corrected behaviour.

---

## 9. The few-group export cannot actually drive a diffusion code

**Concern.** `SCALAR_TYPES` in `core/mgxs_gen.py` is
`("total", "absorption", "fission", "nu-fission", "chi")`, but the module docstring
(and README) say these are the group constants "deterministic diffusion/transport
codes consume." A diffusion solve needs a **transport-corrected cross section /
diffusion coefficient** (OpenMC exposes `"transport"`; only `"total"` is provided)
and a **scattering matrix** (acknowledged in-code as future work). What *is*
produced is correctly flux-weighted via `openmc.mgxs` — this is an overstated
claim, not a math error.

**Fixes.**

- **Cheapest** — soften the claim in the `mgxs_gen.py` docstring, README, and
  `docs/validation.md`: "few-group reaction constants" until the set is complete.
- **The real fix** — add `"transport"` to `SCALAR_TYPES` and a P0
  `openmc.mgxs.ScatterMatrixXS` to the library build; export both alongside the
  existing constants. Then the diffusion claim becomes true, and a two-group
  hand-solve of the pin cell (k∞ from the four-factor form of the exported
  constants vs the Monte Carlo k∞) becomes a strong new validation row.

---

## 10. Three catalog materials are physically mislabeled

**Concern.** Spot-checking `core/materials.py` against standard references found
three entries whose composition contradicts their label:

- **`flibe`** uses natural lithium (`add_element("Li", 2.0)` → 7.5 % Li-6). Real
  FLiBe is Li-7-enriched to ~99.99 % precisely because Li-6 is a strong (n,α)
  absorber — natural-Li FLiBe is drastically over-absorbing, wrong for any
  reactivity study.
- **`mox`** docstring says "reactor-grade Pu vector" but ships Pu-239/240/241 =
  93/6/1 — a weapons-grade vector. Reactor-grade is ~55–60 % Pu-239 with ~24 %
  Pu-240.
- **`plutonium_metal`** references Jezebel (PU-MET-FAST-001) but is α-phase Pu at
  19.84 g/cc with no gallium; real Jezebel is δ-phase Pu–Ga at 15.61 g/cc with
  ~4.5 % Pu-240 and ~1 wt% Ga. Built at Jezebel's critical radius it would give
  the wrong k.

**Fixes.**

- **`flibe`** — default to Li-7 enrichment (~99.995 at%) with a `li7_enrichment`
  parameter; keep natural Li reachable but not the default.
- **`mox`** — either relabel the docstring honestly ("low-burnup / weapons-grade
  vector") or switch to a genuine reactor-grade vector (≈ 52/24/15/6/3 for
  239/240/241/242/238) and cite it.
- **`plutonium_metal`** — drop the Jezebel reference from the docstring (it is a
  generic α-Pu building block), **or** promote it properly: add a faithful
  `benchmarks.jezebel()` (δ-phase Pu–Ga, 15.61 g/cc, r = 6.3849 cm, published
  k = 1.0000) — which would also add a second ICSBEP benchmark to the validation
  table, compounding concern #1's fix.

---

## 11. The thermal-lattice regression windows are smoke-width

**Concern.** `tests/test_benchmarks.py` asserts `1.30 < k∞ < 1.50` for both the pin
cell and the assembly — a ±10 000 pcm window around the expected 1.41. A
few-percent moderator/fuel density error or an enrichment slip (3.2 % → ~2.5 %)
passes. The Doppler test (`tests/test_tier4.py`) asserts sign only. The test suite
reliably catches "pipeline broken," not quantitative physics drift — the benchmark
contract in CONTRIBUTING.md promises more than the tolerances deliver.

**Fixes.**

- **Cheapest** — tighten the windows to the current values ± a few hundred pcm
  (e.g. `1.405 < k∞ < 1.42`), with a comment stating these are *regression* pins to
  NBEAST's own validated output, not external truth. Statistical spread at the CI
  run quality is far smaller than the window.
- **Add the missing internal check as a test** — assembly k∞ == pin-cell k∞ within
  combined σ (validation.md already demonstrates ~1 pcm agreement; no test asserts
  it).
- **Give Doppler a magnitude band** — assert the 294→900 K coefficient lands in
  −2 to −4.5 pcm/K, not just `k(900) < k(294)`.
- **After concern #1's Mosteller case lands** — replace the regression pins with
  the published benchmark band, upgrading these from self-referential to
  externally anchored.

---

## 12. Small hygiene items (grouped)

**Concern + fix, one line each.**

- **Green-but-empty tests** — `tests/test_data_library.py` early-`return`s when
  data is absent, reporting PASS while asserting nothing. Use the suite's own
  `requires_data` skip marker (or `pytest.skip`) so absence shows as SKIP.
- **Entropy slice conflates generations and batches** — the convergence check in
  `core/results.py` indexes the per-generation entropy array with batch counts;
  correct only while `generations_per_batch == 1`. Index via generations-per-batch
  (or assert it is 1 where the settings are built).
- **Absolute-map error bars are formally incomplete** — `field_to_vtk` scales means
  by `source_rate` but leaves relative errors untouched; the source rate is itself
  a tally estimate correlated with the flux. The κ-fission tally is well converged
  so the effect is small — state the omission in `core/units.py` /
  `docs/validation.md`, or fold the source-rate σ in quadrature.
- **Temperature snapping is silent in the UI** — `settings.temperature` uses
  `method="nearest"` with `tolerance=1000.0` (`core/templates.py`), so a request
  can snap hundreds of K with no visible notice (docstring-only). Surface "data
  evaluated at X K (snapped from Y K)" in the run summary / diagnostics panel;
  subsumed once concern #4's true interpolation lands.

---

## Priority order (most rigor per hour)

1. **#8** — log–log dose interpolation (one line at three sites + a lock-in test).
2. **#10** — fix/relabel `flibe`, `mox`, `plutonium_metal` (small, prevents wrong
   results today).
3. **#9 (cheap half)** — soften the "diffusion codes consume this" claim to match
   what is exported.
4. **#7** — σ(k)-aware criticality search. The one fix that is *required* before
   search results can be quoted in real work.
5. **#1** — Mosteller pin-cell benchmark + regression test.
6. **#5** — energy-conservation test for absolute units.
7. **#11** — tighten the k∞ regression windows + assembly==pin-cell test + Doppler
   magnitude band (re-anchor to Mosteller once #1 lands).
8. **#3** — two-pass, spectrum-averaged poison concentrations.
9. **#4** — temperature interpolation (remove nearest-snapping).
10. **#12** — hygiene items, as the files are touched anyway.
11. **#2** — VERA depletion validation; **#6** — "Standard" cross-section bundle.
12. Heavier lifts: **#9** transport-corrected XS + scattering matrix, **#4**
    density-coupled isothermal coefficient, **#10** faithful `jezebel()` benchmark,
    **#1** ICSBEP `LEU-COMP-THERM` geometry.

Items 1–3 are an afternoon combined; item 4 is the single credibility-critical
fix; items 5–7 are the validation-breadth wins that mostly reuse existing code.
