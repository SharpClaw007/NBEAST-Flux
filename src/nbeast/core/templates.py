"""Parametric geometry templates -> ``openmc.model.Model``.

These are the "simple path" for v1: a handful of well-understood geometries the
user fills in with form fields. Each returns a complete, runnable Model with
sensible eigenvalue defaults. Built with explicit surfaces for version-robustness.
"""

from __future__ import annotations

import openmc

from . import materials


def _eigenvalue_settings(
    batches: int,
    inactive: int,
    particles: int,
    source: openmc.IndependentSource,
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.Settings:
    s = openmc.Settings()
    s.run_mode = "eigenvalue"
    s.batches = batches
    s.inactive = inactive
    s.particles = particles
    s.source = source
    if seed is not None:
        s.seed = int(seed)  # fix the RNG stream so the run is reproducible
    _apply_temperature(s, temperature)
    return s


def scale_density(mat: openmc.Material, fraction: float | None) -> openmc.Material:
    """Scale a material's density to ``fraction`` of nominal — the knob for void /
    moderation studies (fraction 0 ≈ voided, 1 = nominal). Floored to a trace so the
    cell stays runnable at zero moderation."""
    if fraction is None:
        return mat
    units = mat.density_units if mat.density_units not in (None, "sum") else "g/cm3"
    base = mat.density if mat.density else 1.0
    mat.set_density(units, max(base * float(fraction), 1.0e-6))
    return mat


def _apply_temperature(settings: openmc.Settings, temperature: float | None) -> None:
    """Run every cell at ``temperature`` (K) — the knob for Doppler-feedback studies.
    Left at the data's default when None.

    Uses the *nearest* available data temperature (within a wide tolerance) rather
    than interpolation: the curated thermal-scattering kernel (H in H2O) ships at a
    single temperature (294 K), so interpolation would reject any other value. With
    ``nearest`` the resonance (continuous-energy) data still snaps to the bundled
    250/294/600/900/1200 K grid — enough to show fuel Doppler feedback — while the
    thermal kernel stays at 294 K. The parameter range is capped so the request
    always stays within tolerance of an available temperature.
    """
    if temperature is None:
        return
    settings.temperature = {"method": "nearest", "tolerance": 1000.0,
                            "default": float(temperature)}


def pin_cell(
    fuel: str = "uo2",
    clad: str = "zircaloy",
    moderator: str = "water",
    enrichment: float = 3.2,
    pitch: float = 1.26,
    fuel_radius: float = 0.39,
    clad_inner_radius: float = 0.40,
    clad_outer_radius: float = 0.46,
    moderator_density: float | None = None,
    batches: int = 100,
    inactive: int = 20,
    particles: int = 2000,
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.model.Model:
    """PWR-style pin cell with reflective boundaries (infinite lattice). Fuel, clad,
    and moderator are chosen by material-catalog key; ``enrichment`` applies only to
    enrichment-parametric fuels. ``moderator_density`` (fraction of nominal) drives
    void / moderation studies."""
    fuel = materials.build(fuel, enrichment=enrichment)
    clad = materials.build(clad)
    mod = scale_density(materials.build(moderator), moderator_density)

    fuel_or = openmc.ZCylinder(r=fuel_radius)
    clad_ir = openmc.ZCylinder(r=clad_inner_radius)
    clad_or = openmc.ZCylinder(r=clad_outer_radius)

    h = pitch / 2.0
    left = openmc.XPlane(-h, boundary_type="reflective")
    right = openmc.XPlane(h, boundary_type="reflective")
    bottom = openmc.YPlane(-h, boundary_type="reflective")
    top = openmc.YPlane(h, boundary_type="reflective")

    fuel_cell = openmc.Cell(name="fuel", fill=fuel, region=-fuel_or)
    gap_cell = openmc.Cell(name="gap", region=+fuel_or & -clad_ir)
    clad_cell = openmc.Cell(name="clad", fill=clad, region=+clad_ir & -clad_or)
    mod_cell = openmc.Cell(
        name="moderator",
        fill=mod,
        region=+clad_or & +left & -right & +bottom & -top,
    )

    geometry = openmc.Geometry(
        openmc.Universe(cells=[fuel_cell, gap_cell, clad_cell, mod_cell])
    )
    source = openmc.IndependentSource(
        space=openmc.stats.Box((-h, -h, -1), (h, h, 1)),
        constraints={"fissionable": True},
    )
    settings = _eigenvalue_settings(batches, inactive, particles, source, seed, temperature)
    return openmc.model.Model(geometry, openmc.Materials([fuel, clad, mod]), settings)


def assembly(
    n_side: int = 5,
    fuel: str = "uo2",
    clad: str = "zircaloy",
    moderator: str = "water",
    enrichment: float = 3.2,
    pitch: float = 1.26,
    fuel_radius: float = 0.39,
    clad_inner_radius: float = 0.40,
    clad_outer_radius: float = 0.46,
    moderator_density: float | None = None,
    batches: int = 100,
    inactive: int = 20,
    particles: int = 5000,
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.model.Model:
    """An N×N square lattice of identical pins (materials chosen by catalog key).
    ``moderator_density`` (fraction of nominal) drives void / moderation studies."""
    n_side = int(n_side)
    fuel = materials.build(fuel, enrichment=enrichment)
    clad = materials.build(clad)
    mod = scale_density(materials.build(moderator), moderator_density)

    fuel_or = openmc.ZCylinder(r=fuel_radius)
    clad_ir = openmc.ZCylinder(r=clad_inner_radius)
    clad_or = openmc.ZCylinder(r=clad_outer_radius)
    pin = openmc.Universe(cells=[
        openmc.Cell(name="fuel", fill=fuel, region=-fuel_or),
        openmc.Cell(name="gap", region=+fuel_or & -clad_ir),
        openmc.Cell(name="clad", fill=clad, region=+clad_ir & -clad_or),
        openmc.Cell(name="moderator", fill=mod, region=+clad_or),
    ])
    outer = openmc.Universe(cells=[openmc.Cell(fill=mod)])

    half = n_side * pitch / 2.0
    lattice = openmc.RectLattice()
    lattice.lower_left = (-half, -half)
    lattice.pitch = (pitch, pitch)
    lattice.universes = [[pin] * n_side for _ in range(n_side)]
    lattice.outer = outer

    left = openmc.XPlane(-half, boundary_type="reflective")
    right = openmc.XPlane(half, boundary_type="reflective")
    bottom = openmc.YPlane(-half, boundary_type="reflective")
    top = openmc.YPlane(half, boundary_type="reflective")
    root = openmc.Cell(fill=lattice, region=+left & -right & +bottom & -top)

    geometry = openmc.Geometry([root])
    source = openmc.IndependentSource(
        space=openmc.stats.Box((-half, -half, -1), (half, half, 1)),
        constraints={"fissionable": True},
    )
    settings = _eigenvalue_settings(batches, inactive, particles, source, seed, temperature)
    return openmc.model.Model(geometry, openmc.Materials([fuel, clad, mod]), settings)


def bare_sphere(
    material: openmc.Material | str,
    radius: float,
    enrichment: float = 19.75,
    batches: int = 120,
    inactive: int = 20,
    particles: int = 5000,
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.model.Model:
    """A bare (vacuum-bounded) sphere of one material — the classic fast-metal
    criticality geometry (e.g. Godiva, Jezebel). ``material`` may be a catalog key
    or a ready-built ``openmc.Material``."""
    if isinstance(material, str):
        material = materials.build(material, enrichment=enrichment)
    sphere = openmc.Sphere(r=radius, boundary_type="vacuum")
    cell = openmc.Cell(name="core", fill=material, region=-sphere)
    geometry = openmc.Geometry([cell])
    source = openmc.IndependentSource(space=openmc.stats.Point((0.0, 0.0, 0.0)))
    settings = _eigenvalue_settings(batches, inactive, particles, source, seed, temperature)
    return openmc.model.Model(geometry, openmc.Materials([material]), settings)


def _fixed_source_settings(
    batches: int,
    particles: int,
    source: openmc.IndependentSource,
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.Settings:
    s = openmc.Settings()
    s.run_mode = "fixed source"  # external source, no k-eff / inactive batches
    s.batches = batches
    s.particles = particles
    s.source = source
    if seed is not None:
        s.seed = int(seed)
    _apply_temperature(s, temperature)
    return s


def shield_slab(
    shield: str = "water",
    thickness: float = 30.0,
    source_energy: float = 2.0,
    transverse_half: float = 5.0,
    batches: int = 25,
    particles: int = 5000,
    inactive: int = 0,        # accepted for a uniform build signature; unused
    seed: int | None = None,
    temperature: float | None = None,
) -> openmc.model.Model:
    """A shield slab with a monoenergetic neutron beam — the canonical fixed-source
    attenuation/shielding demo.

    A pencil beam of ``source_energy`` MeV neutrons enters a slab of the chosen
    ``shield`` material of the given ``thickness`` (cm); transverse boundaries are
    reflective so the slab is effectively infinite in y and z (a 1-D problem). Pair
    with the flux and dose-rate meshes to see exponential attenuation.
    """
    water = materials.build(shield)
    w = float(transverse_half)
    front = openmc.XPlane(0.0, boundary_type="vacuum")
    back = openmc.XPlane(thickness, boundary_type="vacuum")
    y0 = openmc.YPlane(-w, boundary_type="reflective")
    y1 = openmc.YPlane(w, boundary_type="reflective")
    z0 = openmc.ZPlane(-w, boundary_type="reflective")
    z1 = openmc.ZPlane(w, boundary_type="reflective")
    cell = openmc.Cell(name="shield", fill=water,
                       region=+front & -back & +y0 & -y1 & +z0 & -z1)
    geometry = openmc.Geometry([cell])

    # Plane source just inside the front face (a hair off the vacuum boundary so the
    # sites land in the cell), aimed straight through the slab.
    x_src = min(0.05, thickness * 0.01)
    source = openmc.IndependentSource(
        space=openmc.stats.Box((x_src, -w, -w), (x_src, w, w)),
        angle=openmc.stats.Monodirectional((1.0, 0.0, 0.0)),
        energy=openmc.stats.Discrete([float(source_energy) * 1.0e6], [1.0]),
    )
    settings = _fixed_source_settings(batches, particles, source, seed, temperature)
    return openmc.model.Model(geometry, openmc.Materials([water]), settings)
