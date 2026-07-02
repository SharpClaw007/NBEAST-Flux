"""Validated reference cases — they triple as starter examples, tutorials, and
regression tests. Each returns a runnable ``openmc.model.Model``.
"""

from __future__ import annotations

import openmc

from . import templates

# Godiva critical radius (ICSBEP HEU-MET-FAST-001), cm.
GODIVA_RADIUS = 8.7407
# Jezebel critical radius (ICSBEP PU-MET-FAST-001), cm.
JEZEBEL_RADIUS = 6.3849

# Nuclides a benchmark needs beyond the bundled H/O/U/Zr (for data-availability gating).
JEZEBEL_NUCLIDES = ("Pu239", "Pu240", "Pu241", "Ga69", "Ga71")

# Expected k-eff for the built-in benchmarks (for tests / UI "known-good" badges).
EXPECTED_KEFF = {
    "godiva": 1.0,
    "jezebel": 1.0,
}


def godiva(radius: float = GODIVA_RADIUS, material: str = "heu_metal_godiva",
           **kwargs) -> openmc.model.Model:
    """Bare HEU metal sphere; k_eff ~= 1.0 at the benchmark radius. The
    fast-criticality trust anchor (radius and material are adjustable for studies)."""
    return templates.bare_sphere(material, radius=radius, **kwargs)


def jezebel_material() -> openmc.Material:
    """Jezebel δ-phase Pu-Ga alloy — ICSBEP PU-MET-FAST-001 benchmark-model atom
    densities (atoms/b-cm). Distinct from the generic ``plutonium_metal`` (α-phase):
    this is the faithful benchmark composition, incl. ~1 wt% gallium stabilizer.
    """
    m = openmc.Material(name="Jezebel (Pu-Ga, δ-phase)")
    m.add_nuclide("Pu239", 3.7047e-2)
    m.add_nuclide("Pu240", 1.7512e-3)
    m.add_nuclide("Pu241", 1.1674e-4)
    m.add_nuclide("Ga69", 8.266052160e-4)
    m.add_nuclide("Ga71", 5.48594784e-4)
    total = 3.7047e-2 + 1.7512e-3 + 1.1674e-4 + 8.266052160e-4 + 5.48594784e-4
    m.set_density("atom/b-cm", total)
    return m


def jezebel(radius: float = JEZEBEL_RADIUS, **kwargs) -> openmc.model.Model:
    """Bare δ-phase Pu-Ga sphere — ICSBEP **PU-MET-FAST-001**, k_eff ~= 1.0 at
    r = 6.3849 cm. A second fast-criticality anchor (plutonium) alongside Godiva (HEU).
    Needs Pu + Ga cross sections (not in the bundled library)."""
    return templates.bare_sphere(jezebel_material(), radius=radius, **kwargs)


def pincell(**kwargs) -> openmc.model.Model:
    """PWR UO2/water pin cell; k_inf ~= 1.41 at 3.2% enrichment."""
    return templates.pin_cell(**kwargs)


# --- Mosteller Doppler-defect pin-cell benchmark (LA-UR-07-0922) --------------
# Benchmark-model atom densities (atoms/b-cm) for the requested enrichments, at the two
# temperature states. HZP = everything at 600 K; HFP = fuel at 900 K, rest at 600 K.
# 1400 ppm soluble boron in the moderator for all cases. Geometry is temperature-
# dependent (thermal expansion); the pellet/clad/pitch values below match the 600 K
# model (the pellet's 900 K radius differs by ~1e-4 cm — negligible vs Monte Carlo σ).
# Source: R.D. Mosteller, LA-UR-07-0922; geometry via mit-crpg/benchmarks doppler-defect.
_MOSTELLER_FUEL = {   # (enrichment wt%): {state: {nuclide: density}}
    0.711: {
        600: {"O16": 4.61171e-2, "U235": 1.66029e-4, "U238": 2.28925e-2},
        900: {"O16": 4.59967e-2, "U235": 1.65595e-4, "U238": 2.28328e-2},
    },
    2.4: {
        600: {"O16": 4.61260e-2, "U234": 4.50257e-6, "U235": 5.60420e-4, "U238": 2.24981e-2},
        900: {"O16": 4.60056e-2, "U234": 4.49081e-6, "U235": 5.58956e-4, "U238": 2.24393e-2},
    },
    3.9: {
        600: {"O16": 4.61339e-2, "U234": 7.31651e-6, "U235": 9.10661e-4, "U238": 2.21490e-2},
        900: {"O16": 4.60134e-2, "U234": 7.29740e-6, "U235": 9.08283e-4, "U238": 2.20911e-2},
    },
}
_MOSTELLER_GEOM = {"fuel_radius": 0.39398, "clad_inner_radius": 0.40226,
                   "clad_outer_radius": 0.45972, "pitch": 1.26678}
# MCNP5 / ENDF/B-VII.0 reference k (Mosteller, LA-UR-07-0922, Table): (k_HFP, k_HZP).
MOSTELLER_KEFF = {
    0.711: {"HFP": (0.66108, 0.00018), "HZP": (0.66661, 0.00019)},
    2.4:   {"HFP": (1.09077, 0.00028), "HZP": (1.09955, 0.00027)},
    3.9:   {"HFP": (1.23048, 0.00029), "HZP": (1.24054, 0.00032)},
}


def mosteller_pincell(enrichment: float = 2.4, fuel_temp: float = 900.0,
                      **kwargs) -> openmc.model.Model:
    """The Mosteller Doppler-defect benchmark pin cell (LA-UR-07-0922) at one of the
    tabulated enrichments (0.711 / 2.4 / 3.9 wt%). ``fuel_temp`` = 900 K is the HFP
    state, 600 K the HZP state (moderator + clad stay at 600 K); the HFP−HZP pair gives
    the Doppler defect against a published cross-code reference. A validated thermal
    pin-cell benchmark, unlike the illustrative ``pincell``."""
    if enrichment not in _MOSTELLER_FUEL:
        raise ValueError(f"Mosteller enrichments are {sorted(_MOSTELLER_FUEL)}")
    state = 900 if fuel_temp >= 750 else 600

    fuel = openmc.Material(name=f"Mosteller UO2 {enrichment:g}% @ {state}K")
    for nuclide, dens in _MOSTELLER_FUEL[enrichment][state].items():
        fuel.add_nuclide(nuclide, dens)
    fuel.set_density("atom/b-cm", sum(_MOSTELLER_FUEL[enrichment][state].values()))
    fuel.temperature = float(fuel_temp)

    clad = openmc.Material(name="Mosteller Zr clad")
    clad.add_element("Zr", 1.0)
    clad.set_density("atom/b-cm", 4.21838e-2)
    clad.temperature = 600.0

    water = openmc.Material(name="Mosteller borated water (1400 ppm)")
    for nuclide, dens in (("H1", 4.42326e-2), ("B10", 1.02133e-5),
                          ("B11", 4.11098e-5), ("O16", 2.21163e-2)):
        water.add_nuclide(nuclide, dens)
    water.add_s_alpha_beta("c_H_in_H2O")
    water.set_density("atom/b-cm", 4.42326e-2 + 1.02133e-5 + 4.11098e-5 + 2.21163e-2)
    water.temperature = 600.0

    # Per-material temperatures (fuel 900/600 K, rest 600 K) carry the Doppler state.
    # Enable nearest-temperature snapping (temperature=600 sets the method + a default
    # for any untemperatured cell) so the 294 K-only bundled H-in-H2O kernel resolves at
    # 600 K — identical in HZP and HFP, so the Doppler *defect* is unaffected.
    return templates.pin_cell(
        fuel=fuel, clad=clad, moderator=water, temperature=600.0, **_MOSTELLER_GEOM, **kwargs)


def assembly(**kwargs) -> openmc.model.Model:
    """N×N PWR fuel assembly (reflective); k_inf ~= the pin-cell value."""
    return templates.assembly(**kwargs)


# --- ICSBEP LEU-COMP-THERM-001 (water-moderated 2.35 wt% UO2 rod cluster) ------
# Case 1: a single critical cluster (20×18 rods) in a large water reflector. This is a
# published *thermal* critical experiment (k = 1.00000 ± 0.00310) — the thermal-lattice
# credibility anchor, complementing the fast Godiva/Jezebel spheres. Atom densities and
# dimensions are the ICSBEP benchmark-model values (via the public Serpent/PNL-2438
# translation). Needs Al + 6061-trace + O/U/H data (a download beyond the bundle).
# Simplification (documented): the Al end plugs and the acrylic base plate are omitted;
# they are small reflector perturbations on a water-flooded cluster.
LCT001_KEFF = (1.00000, 0.00310)
LCT001_ELEMENTS = ("Al", "Cr", "Fe", "Mn", "Cu", "Mg", "Ti", "Zn", "Si")  # 6061 clad


def _lct001_materials():
    fuel = openmc.Material(name="LCT-001 UO2 2.35%")
    for nuc, dens in (("U234", 2.8563e-6), ("U235", 4.8785e-4), ("U236", 3.5348e-6),
                      ("U238", 2.0009e-2), ("O16", 4.1202e-2)):
        fuel.add_nuclide(nuc, dens)
    fuel.set_density("atom/b-cm", 2.0009e-2 + 4.8785e-4 + 2.8563e-6 + 3.5348e-6 + 4.1202e-2)

    clad = openmc.Material(name="LCT-001 6061 Al clad")
    # Al-27 and Mn-55 are mono-isotopic (nuclides); the rest are elemental atom
    # densities → add_element so OpenMC expands them to natural isotopes.
    clad.add_nuclide("Al27", 5.8433e-2)
    clad.add_nuclide("Mn55", 2.2115e-5)
    for element, dens in (("Cr", 6.2310e-5), ("Cu", 6.3731e-5), ("Mg", 6.6651e-4),
                          ("Ti", 2.5375e-5), ("Zn", 3.0967e-5), ("Si", 3.4607e-4),
                          ("Fe", 1.0152e-4)):
        clad.add_element(element, dens)
    clad.set_density("atom/b-cm", sum(
        (5.8433e-2, 6.2310e-5, 6.3731e-5, 6.6651e-4, 2.2115e-5, 2.5375e-5,
         3.0967e-5, 3.4607e-4, 1.0152e-4)))

    water = openmc.Material(name="LCT-001 water")
    water.add_nuclide("H1", 6.6706e-2)
    water.add_nuclide("O16", 3.3353e-2)
    water.add_s_alpha_beta("c_H_in_H2O")
    water.set_density("atom/b-cm", 6.6706e-2 + 3.3353e-2)
    return fuel, clad, water


def leu_comp_therm_001(nx: int = 20, ny: int = 18, batches: int = 150,
                       inactive: int = 40, particles: int = 5000,
                       seed: int | None = None) -> openmc.model.Model:
    """ICSBEP LEU-COMP-THERM-001 Case 1 — a water-moderated 2.35 wt% UO2 rod cluster,
    k ~= 1.0. Faithful benchmark-model compositions/dimensions; a 3-D finite rod lattice
    in a water reflector (vacuum outer). The published critical cluster is 20×18 rods
    plus one edge rod (18.08 columns) — the extra fractional rod is omitted (~a few
    hundred pcm), so expect k slightly below 1.0."""
    fuel_mat, clad_mat, water_mat = _lct001_materials()
    pitch, r_fuel, r_clad = 2.032, 0.5588, 0.635
    z_bot, z_top = -44.665, 47.775          # active fuel column (92.44 cm)

    fuel_or = openmc.ZCylinder(r=r_fuel)
    clad_or = openmc.ZCylinder(r=r_clad)
    bot = openmc.ZPlane(z_bot)
    top = openmc.ZPlane(z_top)
    fuel_cell = openmc.Cell(name="fuel", fill=fuel_mat, region=-fuel_or & +bot & -top)
    clad_cell = openmc.Cell(name="clad", fill=clad_mat, region=+fuel_or & -clad_or & +bot & -top)
    # water fills the rest of the pin cell (radially + the plena above/below the column)
    water_pin = openmc.Cell(name="pin_water", fill=water_mat,
                            region=~(-clad_or & +bot & -top))
    pin = openmc.Universe(cells=[fuel_cell, clad_cell, water_pin])
    water_u = openmc.Universe(cells=[openmc.Cell(fill=water_mat)])

    lattice = openmc.RectLattice()
    lattice.lower_left = (-nx * pitch / 2.0, -ny * pitch / 2.0)
    lattice.pitch = (pitch, pitch)
    lattice.universes = [[pin] * nx for _ in range(ny)]
    lattice.outer = water_u

    hx, hy = nx * pitch / 2.0, ny * pitch / 2.0
    x0, x1 = openmc.XPlane(-hx), openmc.XPlane(hx)
    y0, y1 = openmc.YPlane(-hy), openmc.YPlane(hy)
    # Water reflector box: ~30 cm radially, ~10 above / ~15.3 below the fuel column;
    # vacuum outer. Everything (lattice column + surrounding water) lives inside it.
    rx0 = openmc.XPlane(-hx - 30.0, boundary_type="vacuum")
    rx1 = openmc.XPlane(hx + 30.0, boundary_type="vacuum")
    ry0 = openmc.YPlane(-hy - 30.0, boundary_type="vacuum")
    ry1 = openmc.YPlane(hy + 30.0, boundary_type="vacuum")
    rz0 = openmc.ZPlane(z_bot - 15.3, boundary_type="vacuum")
    rz1 = openmc.ZPlane(z_top + 10.0, boundary_type="vacuum")

    # The lattice column is bounded in z by the reflector box (else particles leak out
    # the unbounded top/bottom of the column → "lost particles").
    column = +x0 & -x1 & +y0 & -y1 & +rz0 & -rz1
    lat_cell = openmc.Cell(fill=lattice, region=column)
    refl = openmc.Cell(fill=water_mat,
                       region=(+rx0 & -rx1 & +ry0 & -ry1 & +rz0 & -rz1) & ~column)
    geometry = openmc.Geometry([lat_cell, refl])

    source = openmc.IndependentSource(
        space=openmc.stats.Box((-hx, -hy, z_bot), (hx, hy, z_top)),
        constraints={"fissionable": True})
    settings = templates._eigenvalue_settings(batches, inactive, particles, source, seed)
    return openmc.model.Model(geometry, openmc.Materials([fuel_mat, clad_mat, water_mat]),
                              settings)
