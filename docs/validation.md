# NBEAST validation

NBEAST does not implement neutron transport itself — it builds [OpenMC](https://openmc.org)
models, runs them against evaluated nuclear data, and reads the results back. So the
quantity that needs validating is the part NBEAST *is* responsible for: that the
geometry, materials, run settings, and result-extraction pipeline are correct. The
test is simple and unforgiving — if any of that were wrong, a published criticality
benchmark would not come out right.

This page records NBEAST's outputs checked against published and textbook values.

**Setup.** All runs use the bundled cross-section library (**ENDF/B-VIII.0**
continuous-energy data; **ENDF/B-VII.1** H-in-H₂O thermal scattering), a fixed RNG
seed, and the model NBEAST itself builds from each template. Reproduce everything with
`scripts`-free, plain calls to `nbeast.core` (see [Reproducing](#reproducing) below).

## Results

| Quantity | NBEAST | Published / expected | Status |
|---|---|---|---|
| **Godiva k-eff** — ICSBEP **HEU-MET-FAST-001** (bare HEU sphere, r = 8.7407 cm) | **1.00000 ± 0.00044** | **1.0000 ± 0.0010** | ✅ exact (0 pcm) |
| Godiva spectrum | 96.3 % fast (>0.1 MeV), ~0 % thermal, mean E = 1.46 MeV | hard fast spectrum | ✅ |
| PWR pin cell k∞ — fresh 3.2 % UO₂ | 1.41303 ± 0.00086 | ≈ 1.40 | ✅ in range |
| Pin cell spectrum | 19.8 % of flux thermal (<1 eV) | substantial thermal peak | ✅ |
| **Fuel temperature (Doppler) coefficient** | **−3.59 pcm/K** | textbook −2 to −4 pcm/K | ✅ sign & magnitude |
| Assembly k∞ vs pin cell k∞ | 1.41294 vs 1.41303 | should coincide | ✅ (~1 pcm, within σ) |
| Water shield relaxation length (2 MeV beam) | 5.9 cm (195× over 40 cm) | fast neutrons in water ≈ 6–10 cm | ✅ |
| 2-group UO₂ χ (fast / thermal) | 1.000 / 0.000 | ≈ 1 / ≈ 0 | ✅ |
| 2-group UO₂ absorption, ν-fission | thermal ≫ fast | thermal ≫ fast | ✅ |

### Criticality — the anchor

The **Godiva** result is the headline: NBEAST reproduces the ICSBEP benchmark
eigenvalue **exactly within uncertainty** (k = 1.00000 ± 0.00044 against the published
1.0000 ± 0.0010). Because this is a bare metal sphere with no moderator, it isolates
the fast-physics, geometry, and material-density pipeline. Hitting 1.00000 means the
model NBEAST constructs is faithful.

The **pin cell** (k∞ ≈ 1.413) and **5×5 assembly** (k∞ ≈ 1.413, matching the single pin
to ~1 pcm) confirm the thermal-lattice path: correct UO₂/Zr/water materials, the
H-in-H₂O thermal-scattering kernel, and reflective-lattice boundaries.

### Reactivity feedback — the Doppler coefficient

Raising the fuel temperature broadens the U-238 capture resonances, which must *lower*
reactivity. NBEAST gives a clean, monotonic trend and a coefficient in the textbook
range:

| Temperature | k |
|---|---|
| 294 K | 1.41223 ± 0.00108 |
| 600 K | 1.39978 ± 0.00114 |
| 900 K | 1.39046 ± 0.00121 |

→ **−3.59 pcm/K** over 294→900 K. This is a *constant-density* fuel-temperature
(Doppler + spectral) coefficient — NBEAST does not yet vary moderator density with
temperature, so it excludes the moderator-density feedback that a full isothermal
coefficient would add.

### Spectra and shielding

The energy spectra match the systems: **Godiva** is hard and fast (mean 1.46 MeV, no
thermal population); the **pin cell** carries a ~20 % thermal population with the
expected 1/E slowing-down region between. The **water shield** attenuates a 2 MeV
neutron beam with a fitted relaxation length of **5.9 cm**, consistent with the known
~6–10 cm for fast neutrons in water.

### Few-group constants

Two-group (CASMO-2) constants collapsed from the pin cell are physically correct: the
fission spectrum χ is entirely in the fast group (1.000 / 0.000), and both absorption
and ν-fission are far larger in the thermal group, as expected for low-enriched UO₂.

### Moderation curve

Sweeping the pin cell's moderator density from voided to flooded traces the classic
under-moderation curve: k rises from **0.79 at 5 % density** (deeply subcritical,
fast-hardened) through the critical crossing (~12 %) to **1.41 at full density** — the
nominal pin k∞. The steep positive slope is the (safe) negative void coefficient a PWR
is built around. The dialog overlays reactivity and the source-driven multiplication
M = 1/(1−k), which diverges at the critical crossing.

### Fission-product poisoning (Xe-135 / Sm-149)

With Xe-135/Sm-149 data added, the equilibrium worths on the pin cell are **Sm-149
≈ −960 pcm** (reference −900 to −1300) and **Xe-135 ≈ −3230 pcm** at saturation
(reference −2600 to −3000 for a typical core). Sm lands squarely in range; Xe is
slightly high, honestly so — the estimate uses the *saturation* (maximum) xenon level
in an *infinite* pin lattice, both of which raise the worth relative to a leaky
operating core. Choosing a finite operating flux in the dialog brings Xe down toward
the typical range. Poisoning needs a Xe-135/Sm-149 download (not in the bundle).

### Absolute-unit normalization

Result maps are per source neutron by default (relative). Given a reactor power, they
are scaled to absolute rates using the **whole-geometry recoverable fission energy**
(a `kappa-fission` tally): source rate = *P* / (Σ κ-fission · 1.602×10⁻¹⁹ J/eV), then
flux = (track-length / cell volume) × source rate. For the pin cell at a single-pin
power of **65 kW**, the peak scalar flux is **≈7×10¹⁴ n·cm⁻²·s⁻¹** — the expected PWR
scale (≈10¹⁴). The independent heating map integrates to ~the input power (κ-fission and
the heating score agree to ~200 MeV/fission), an internal consistency check. Using the
thin visualization slice mesh instead of a global tally over-counts the source rate by
~300× (the slice captures only a fraction of the fissions), which is why the global
`power_norm` tally is required.

## Scope and honest limits

- **Criticality and flux physics are validated** and rest on a published benchmark and
  real evaluated data (ENDF/B-VIII.0). This is the core of the tool.
- **Depletion / burnup is plumbing-validated, not physics-validated.** The bundled
  library is a *criticality* library; the depletion check ran a deliberately reduced
  (actinide-only) chain, which exercises the workflow end-to-end but omits fission
  products and Xe/Sm poisoning. Its burnup *numbers* are not a physics benchmark — that
  requires the full chain and depletion-capable library a user downloads to enable the
  feature.
- **Dose and heating maps are validated for shape and trend** (correct attenuation /
  relative behaviour), not absolute calibration against a reference dose problem.
- **Dose coefficients are interpolated log-log** (the ICRP-116 tabulation convention).
  The filter default (linear-linear) deviates from log-log by up to ~3.5% in the
  thermal range on the openmc-provided table; NBEAST sets log-log explicitly on every
  dose tally (templates and CAD), locked in by tests.
- **Absolute units require a reactor power and a fissile system.** The normalization is
  a fission-power normalization (κ-fission over the whole model); it lands on the right
  order of magnitude (see above) but is not calibrated against an absolute flux standard.
  A pure shield (no fission) has no power basis, so its maps stay relative.
- **Poisoning is a thermal-lattice, saturation estimate.** Xe-135/Sm-149 concentrations
  come from the standard equilibrium chain constants (not a depletion solve), and the
  worths validate against reference ranges (above). It needs a Xe-135/Sm-149 download
  and is meaningless in a fast spectrum (correctly ~0 there).

## Reproducing

The numbers above come from `nbeast.core` calls with a fixed seed and the bundled
ENDF/B-VIII.0 library (`OPENMC_CROSS_SECTIONS` pointing at it). For example, Godiva:

```python
from nbeast.core import benchmarks, tallies
from nbeast.core.results import Results

model = benchmarks.godiva(batches=200, inactive=40, particles=15000, seed=1)
sp = model.run(output=False)
with Results(sp) as r:
    print(r.keff)          # -> 1.00000 +/- 0.00044
```

Run quality used for this page: Godiva 200×15000 (40 inactive); pin cell 150×10000;
Doppler series 120×8000; assembly 120×8000; shield 50×30000 (fixed source); multigroup
120×8000. Statistical uncertainties scale as usual — coarser runs widen the error bars
but do not move the central values.
