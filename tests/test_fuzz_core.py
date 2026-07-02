"""Adversarial fuzz + property tests for the pure core (Qt-free, OpenMC-free where
possible). Every test is deterministic (seeded RNG) so a failure reproduces exactly.

The goal is near-certainty: exhaustive small combinations + randomized invariants over
the numerics that back the whole app — reactivity, units, sweep/search, studies
serialization, materials, geometry previews, comparison, data helpers, and poisons.
"""

from __future__ import annotations

import itertools
import math
import random

import pytest

from nbeast.core import (
    compare,
    data,
    materials,
    reactivity,
    render_geometry,
    specs,
    studies,
    units,
)
from nbeast.core.sweep import CriticalitySearch, sweep_values

SEEDS = range(40)


# ---- reactivity -------------------------------------------------------------
def test_reactivity_domain_and_monotonicity():
    assert reactivity.reactivity_pcm(1.0) == pytest.approx(0.0)
    # both functions reject non-physical k ≤ 0 (and None); M also rejects k ≥ 1
    for bad in (None, 0.0, -1.0, -1e-9):
        assert reactivity.reactivity_pcm(bad) is None
        assert reactivity.subcritical_multiplication(bad) is None
    for supercrit in (1.0, 1.5, 3.0):
        assert reactivity.subcritical_multiplication(supercrit) is None
    rng = random.Random(1)
    ks = sorted(rng.uniform(0.2, 3.0) for _ in range(200))
    rhos = [reactivity.reactivity_pcm(k) for k in ks]
    assert all(b >= a - 1e-6 for a, b in zip(rhos, rhos[1:]))     # ρ increases with k
    # subcritical multiplication: defined + positive below 1, diverges approaching 1
    assert reactivity.subcritical_multiplication(0.5) == pytest.approx(2.0)
    assert reactivity.subcritical_multiplication(1.0) is None
    assert reactivity.subcritical_multiplication(1.5) is None
    assert reactivity.subcritical_multiplication(0.999) > 100


# ---- units ------------------------------------------------------------------
def test_length_conversion_round_trips_and_labels():
    rng = random.Random(2)
    for _ in range(500):
        v = rng.uniform(-1e6, 1e6)
        for system in ("SI", "US", "nonsense"):
            back = units.display_to_cm(units.cm_to_display(v, system), system)
            assert back == pytest.approx(v, rel=1e-9, abs=1e-9)
    assert units.length_unit("US") == "in" and units.length_unit("SI") == "cm"
    assert units.is_length("cm") and not units.is_length(None) and not units.is_length("wt%")


def test_field_labels_and_factors_never_raise():
    scores = ["flux", "fission", "absorption", "nu-fission", "heating", "dose", "volume",
              "flux_rel_err", "dose_rel_err", "", "garbage", "x__3d", "flux_rel_err_rel_err"]
    for score, system, absolute in itertools.product(scores, ("SI", "US"), (True, False)):
        title = units.colorbar_title(score, system, absolute)   # must never raise
        factor = units.field_factor(score, system, absolute)
        assert isinstance(title, str)
        assert isinstance(factor, float) and factor > 0 and math.isfinite(factor)
    # known scores always produce a non-empty, informative title
    for score in ("flux", "dose", "heating", "flux_rel_err"):
        assert units.colorbar_title(score, "SI", False).strip()
    # a relative-error field is never unit-scaled; SI is always factor 1
    assert units.field_factor("flux_rel_err", "US", True) == 1.0
    assert units.field_factor("dose", "SI", True) == 1.0


# ---- sweep value lists ------------------------------------------------------
def test_sweep_values_invariants():
    rng = random.Random(3)
    for _ in range(300):
        lo, hi, n = rng.uniform(-50, 50), rng.uniform(-50, 50), rng.randint(1, 40)
        vals = sweep_values(lo, hi, n)
        assert len(vals) == n
        assert vals[0] == pytest.approx(lo)
        if n > 1:
            assert vals[-1] == pytest.approx(hi)
            diffs = [b - a for a, b in zip(vals, vals[1:])]
            assert all(math.isclose(d, diffs[0], rel_tol=1e-6, abs_tol=1e-9) for d in diffs)
    for _ in range(200):
        lo, hi, n = rng.uniform(1e-3, 10), rng.uniform(1e-3, 10), rng.randint(2, 20)
        vlog = sweep_values(lo, hi, n, log=True)
        assert vlog[0] == pytest.approx(lo) and vlog[-1] == pytest.approx(hi)
        ratios = [b / a for a, b in zip(vlog, vlog[1:])]
        assert all(math.isclose(r, ratios[0], rel_tol=1e-6) for r in ratios)   # geometric
    with pytest.raises(ValueError):
        sweep_values(1, 2, 0)
    with pytest.raises(ValueError):
        sweep_values(-1, 5, 4, log=True)


# ---- criticality search: the highest-risk numerics -------------------------
def _drive_search(kfun, lo, hi, *, noise=0.0, seed=0, **kw):
    """Run a search against a synthetic k(x); returns the search + eval count. Hard
    cap guards against a runaway (a real bug); asserted below."""
    s = CriticalitySearch(lo, hi, **kw)
    rng = random.Random(seed)
    n = 0
    while True:
        x = s.propose()
        if x is None:
            break
        std = noise
        k = kfun(x) + (rng.gauss(0, noise) if noise else 0.0)
        s.submit(x, k, std)
        n += 1
        assert n <= 60, "search failed to terminate — likely a propose() bug"
    return s, n


def test_search_never_escapes_bounds_or_raises():
    rng = random.Random(4)
    for seed in SEEDS:
        slope = rng.choice([-1, 1]) * rng.uniform(0.02, 0.5)
        root = rng.uniform(3, 25)
        lo, hi = rng.uniform(1, 5), rng.uniform(6, 12)
        xmin, xmax = 0.5, 60.0
        s, _ = _drive_search(lambda x: 1.0 + slope * (x - root), lo, hi,
                             noise=rng.choice([0.0, 0.0, 0.001]), seed=seed,
                             x_min=xmin, x_max=xmax)
        for p in s.points:
            assert xmin - 1e-9 <= p.x <= xmax + 1e-9        # clamp respected always
        est = s.estimate()
        assert est is None or math.isfinite(est)
        std = s.estimate_std()
        assert std is None or (math.isfinite(std) and std >= 0)
        sol = s.solution
        assert {"x", "x_std", "converged", "bracketed", "n_evals", "points"} <= sol.keys()


def test_search_finds_clean_roots():
    """Noise-free monotonic curves with the root inside a generous bracket must
    converge to it (both increasing and decreasing)."""
    rng = random.Random(5)
    for _ in range(30):
        root = rng.uniform(6, 20)
        slope = rng.choice([-1, 1]) * rng.uniform(0.05, 0.3)
        s, _ = _drive_search(lambda x: 1.0 + slope * (x - root), root - 4, root + 4,
                             x_min=0.1, x_max=100)
        assert s.converged
        assert s.estimate() == pytest.approx(root, abs=0.05)


def test_search_degenerate_inputs_are_graceful():
    # flat curve (no root) — must not raise, must not claim a bracket
    s, _ = _drive_search(lambda x: 0.5, 1, 5, x_min=0, x_max=10)
    assert not s.bracketed
    # target unreachable within bounds — reports best effort, converged False
    s2, _ = _drive_search(lambda x: 0.05 * x, 1, 5, x_min=1, x_max=6)
    assert not s2.converged and s2.solution["x"] is not None
    with pytest.raises(ValueError):
        CriticalitySearch(5.0, 5.0)


def test_particles_factor_bounded():
    rng = random.Random(6)
    s = CriticalitySearch(1, 2)
    assert s.particles_factor() == 1
    s.submit(1.0, 0.9, 0.004)
    s.submit(2.0, 1.1, 0.004)
    for _ in range(50):
        s.submit(rng.uniform(1, 2), rng.uniform(0.9, 1.1), rng.uniform(1e-4, 1e-2))
        f = s.particles_factor()
        assert 1 <= f <= s.max_particles_factor and isinstance(f, int)


# ---- studies serialization + registry --------------------------------------
def test_study_config_and_result_round_trip_fuzz():
    rng = random.Random(7)
    kinds = list(studies.STUDY_KINDS)
    for _ in range(300):
        cfg = studies.StudyConfig(
            kind=rng.choice(kinds), name="".join(rng.choice("abc ") for _ in range(5)),
            params={f"k{i}": rng.choice([rng.random(), rng.randint(0, 9), "x", None])
                    for i in range(rng.randint(0, 4))},
            quality={"batches": rng.randint(10, 500)}, study_id=f"study-{rng.randint(0,999):03d}")
        assert studies.StudyConfig.from_dict(cfg.to_dict()) == cfg
        res = studies.StudyResult(
            ok=rng.random() > 0.5, summary="s", scalars={"keff": rng.random()},
            points=[(rng.random(), rng.random(), rng.random()) for _ in range(rng.randint(0, 5))],
            warnings=["w"] * rng.randint(0, 3))
        rt = studies.StudyResult.from_dict(res.to_dict())
        assert rt.ok == res.ok and rt.scalars == res.scalars and len(rt.points) == len(res.points)


def test_available_kinds_gating_matrix():
    for eig, mod in itertools.product((True, False), (True, False)):
        kinds = studies.available_kinds(eigenvalue=eig, moderated=mod)
        assert "keff" in kinds                              # a plain run always applies
        if not eig:
            assert kinds == ["keff"]
        if mod and eig:
            assert {"moderation", "poisoning", "sweep", "mgxs"} <= set(kinds)
        if eig and not mod:
            assert "moderation" not in kinds and "sweep" in kinds


def test_default_name_uniqueness_under_collisions():
    existing = []
    for _ in range(20):
        name = studies.default_name("sweep", existing)
        assert name not in existing
        existing.append(name)


# ---- materials: every entry is sound ---------------------------------------
def test_every_material_builds_and_reports_data():
    import openmc

    # Clear any active library so add_element expands to all natural isotopes without
    # validating against the (restrictive) bundle — the data-free "can it be built?"
    # check. (The GUI only ever builds *installed* materials; this checks all 29.)
    saved = openmc.config.get("cross_sections")
    if saved is not None:
        del openmc.config["cross_sections"]
    try:
        for key, spec in materials.LIBRARY.items():
            mat = spec.build()
            assert mat.get_nuclides(), f"{key} has no nuclides"
            need = spec.required_names()
            assert isinstance(need, set) and need
            els, sab = spec.missing_data(set())             # nothing available → all missing
            assert isinstance(els, list) and isinstance(sab, list)
            assert spec.missing_data(need) == ([], [])      # available == required → none missing
    finally:
        if saved is not None:
            openmc.config["cross_sections"] = saved


def test_by_category_is_consistent_with_membership():
    for cat in ("fuel", "moderator", "coolant", "cladding", "structural", "absorber", "reflector"):
        members = materials.by_category(cat)
        assert all(cat in m.categories for m in members)
        assert set(m.key for m in members) == {k for k, m in materials.LIBRARY.items()
                                               if cat in m.categories}


def test_auto_element_materials_build_for_synthetic_and_natural(tmp_path):
    active = tmp_path / "cross_sections.xml"
    active.write_text('<?xml version="1.0"?><cross_sections>'
                      '<library materials="Pu239" path="a" type="neutron"/>'
                      '<library materials="Pu240" path="b" type="neutron"/>'
                      '<library materials="W182" path="c" type="neutron"/>'
                      "</cross_sections>")
    starter = tmp_path / "s.xml"
    starter.write_text('<?xml version="1.0"?><cross_sections></cross_sections>')
    materials.refresh_auto_materials(str(active), str(starter))
    try:
        for key in ("element_Pu", "element_W"):
            assert key in materials.LIBRARY
            assert materials.LIBRARY[key].build().get_nuclides()
    finally:
        materials.refresh_auto_materials(None, None)


# ---- geometry previews over random parameters ------------------------------
def test_geometry_previews_are_finite_over_random_params():
    rng = random.Random(8)
    for name, spec in specs.SPECS.items():
        for _ in range(30):
            params = {}
            for p in spec.parameters:
                lo, hi = p.minimum, p.maximum
                params[p.key] = rng.randint(int(lo), int(hi)) if p.kind == "int" \
                    else rng.uniform(lo, hi)
            preview = render_geometry.preview(name, params, spec.material_defaults())
            if preview is None:
                continue
            for plot in (preview.xy, preview.xz):
                assert plot.width > 0 and plot.height > 0
                assert plot.shapes
                for s in plot.shapes:
                    assert all(math.isfinite(v) for v in (s.x, s.y, s.w, s.h))
                    assert s.w >= 0 and s.h >= 0


# ---- compare ----------------------------------------------------------------
def test_keff_delta_symmetry_and_quadrature():
    rng = random.Random(9)
    for _ in range(300):
        ka, kb = rng.uniform(0.5, 1.5), rng.uniform(0.5, 1.5)
        sa, sb = rng.uniform(0, 0.01), rng.uniform(0, 0.01)
        d = compare.keff_delta(ka, sa, kb, sb)
        assert d.delta == pytest.approx(kb - ka)
        assert d.sigma == pytest.approx(math.hypot(sa, sb))
        rev = compare.keff_delta(kb, sb, ka, sa)
        assert rev.delta == pytest.approx(-d.delta) and rev.sigma == pytest.approx(d.sigma)
        assert d.significant == (d.n_sigma > 2.0)
    # zero uncertainty → infinite significance, never a ZeroDivisionError
    assert math.isinf(compare.keff_delta(1.0, 0.0, 1.1, 0.0).n_sigma)


def test_param_diff_over_random_dicts():
    rng = random.Random(10)
    for _ in range(200):
        a = {f"p{i}": rng.random() for i in range(rng.randint(0, 5))}
        b = {f"p{i}": rng.random() for i in range(rng.randint(0, 5))}
        rows = compare.param_diff(a, b)
        assert {r.key for r in rows} == set(a) | set(b)
        # changed-first ordering
        changed = [r.changed for r in rows]
        assert changed == sorted(changed, reverse=True)


# ---- data helpers -----------------------------------------------------------
def test_size_helpers_additive_and_bucketed():
    els = data.all_elements()
    assert data.size_for(elements=els[:3]) == sum(data.element_size(e) for e in els[:3])
    assert data.format_size(0) == "size unknown"
    for n, suffix in [(500, "KB"), (5_000_000, "MB"), (5_000_000_000, "GB")]:
        assert data.format_size(n).endswith(suffix)
    # monotonic across buckets
    assert data.everything_size() > data.standard_size() > 0


def test_element_of_and_nuclides_of_fuzz():
    rng = random.Random(11)
    assert data.element_of("c_H_in_H2O") is None
    for el in rng.sample(data.all_elements(), k=min(20, len(data.all_elements()))):
        nucs = data.nuclides_of(el)
        assert all(data.element_of(n) == el for n in nucs)
    # arbitrary junk never raises
    for junk in ("", "123", "c_", "Xx999", "U", "U235m1"):
        data.element_of(junk)


def test_downloaded_set_algebra(tmp_path):
    def write(path, names):
        libs = "".join(f'<library materials="{n}" path="x" type="neutron"/>' for n in names)
        path.write_text(f'<?xml version="1.0"?><cross_sections>{libs}</cross_sections>')

    starter = tmp_path / "s.xml"
    active = tmp_path / "a.xml"
    write(starter, ["U235", "O16"])
    write(active, ["U235", "O16", "Pu239", "Gd157", "c_D_in_D2O"])
    assert data.downloaded_elements(str(active), str(starter)) == ["Gd", "Pu"]
    assert data.downloaded_sab(str(active), str(starter)) == ["c_D_in_D2O"]
    # active == starter → nothing downloaded
    assert data.downloaded_elements(str(starter), str(starter)) == []


# ---- poisons ----------------------------------------------------------------
def test_equilibrium_ratios_scaling_laws():
    rng = random.Random(12)
    base_xe, base_sm = __import__("nbeast.core.poisons", fromlist=["x"]).equilibrium_ratios()
    from nbeast.core import poisons

    assert base_xe > 0 and base_sm > 0
    for _ in range(100):
        f = rng.uniform(0.5, 2.0)
        xe, _ = poisons.equilibrium_ratios(sigma_a_xe=poisons.SIGMA_A_XE * f)
        assert xe == pytest.approx(base_xe / f, rel=1e-6)     # saturation Xe ∝ 1/σ_a
        _, sm = poisons.equilibrium_ratios(sigma_f_u235=poisons.SIGMA_F_U235 * f)
        assert sm == pytest.approx(base_sm * f, rel=1e-6)     # ∝ σ_f
    # finite flux is below saturation and grows monotonically toward it
    fluxes = [1e11, 1e12, 1e13, 1e14, 1e15]
    xes = [poisons.equilibrium_ratios(flux=phi)[0] for phi in fluxes]
    assert all(b >= a for a, b in zip(xes, xes[1:]))
    assert xes[-1] <= base_xe + 1e-12
    assert poisons.spectrum_averaged_xs([], [], None) == {}   # junk → empty, no raise
