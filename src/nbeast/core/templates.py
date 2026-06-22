"""Parametric geometry templates -> ``openmc.model.Model``.

These are the "simple path" for v1: a handful of well-understood geometries the
user fills in with form fields. Each returns a complete, runnable Model with
sensible eigenvalue defaults. Built with explicit surfaces for version-robustness.
"""

from __future__ import annotations

import openmc

from . import materials


def _eigenvalue_settings(
    batches: int, inactive: int, particles: int, source: openmc.IndependentSource
) -> openmc.Settings:
    s = openmc.Settings()
    s.run_mode = "eigenvalue"
    s.batches = batches
    s.inactive = inactive
    s.particles = particles
    s.source = source
    return s


def pin_cell(
    enrichment: float = 3.2,
    pitch: float = 1.26,
    fuel_radius: float = 0.39,
    clad_inner_radius: float = 0.40,
    clad_outer_radius: float = 0.46,
    with_sab: bool = True,
    batches: int = 100,
    inactive: int = 20,
    particles: int = 2000,
) -> openmc.model.Model:
    """PWR-style UO2/water pin cell with reflective boundaries (infinite lattice)."""
    fuel = materials.uo2(enrichment)
    clad = materials.zircaloy()
    mod = materials.water(with_sab=with_sab)

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
    settings = _eigenvalue_settings(batches, inactive, particles, source)
    return openmc.model.Model(geometry, openmc.Materials([fuel, clad, mod]), settings)


def bare_sphere(
    material: openmc.Material,
    radius: float,
    batches: int = 120,
    inactive: int = 20,
    particles: int = 5000,
) -> openmc.model.Model:
    """A bare (vacuum-bounded) sphere of one material — the classic fast-metal
    criticality geometry (e.g. Godiva, Jezebel)."""
    sphere = openmc.Sphere(r=radius, boundary_type="vacuum")
    cell = openmc.Cell(name="core", fill=material, region=-sphere)
    geometry = openmc.Geometry([cell])
    source = openmc.IndependentSource(space=openmc.stats.Point((0.0, 0.0, 0.0)))
    settings = _eigenvalue_settings(batches, inactive, particles, source)
    return openmc.model.Model(geometry, openmc.Materials([material]), settings)
