# NBEAST — criticisms and fixes

An honest assessment of where NBEAST's academic rigor is strong, where it is thin,
and the concrete fixes for each gap. The summary judgment: the tool is usable for
real work **within a bounded scope** (reactor-physics teaching, criticality, and
rapid exploratory flux/spectrum studies), with **no glaring physics or numerical
errors** in what is implemented. The weaknesses below are about **validation
breadth** and a few **unvalidated advanced features**, not about the correctness of
the core pipeline.

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

## Priority order (most rigor per hour)

1. **#1** — Mosteller pin-cell benchmark + regression test.
2. **#5** — energy-conservation test for absolute units.
3. **#3** — two-pass, spectrum-averaged poison concentrations.
4. **#4** — temperature interpolation (remove nearest-snapping).
5. **#2** — VERA depletion validation.
6. **#6** — "Standard" cross-section bundle.
7. Heavier lifts: **#4** density-coupled isothermal coefficient, **#1** ICSBEP
   `LEU-COMP-THERM` geometry.

The top three are small, high-credibility wins that mostly reuse existing code.
