"""Phase 0 / Spike A: headless UO2-water pin cell, k-eff eigenvalue.

Canonical PWR-style pin cell with reflective boundaries (infinite lattice).
Built with explicit surfaces (no RectangularPrism helper) to stay robust across
OpenMC versions. Run from a scratch dir with OPENMC_CROSS_SECTIONS pointing at a
cross_sections.xml that includes: U235, U238, O16, H1, Zr90-96, plus the
c_H_in_H2O thermal-scattering table.

Usage:
    OPENMC_CROSS_SECTIONS=/path/to/cross_sections.xml \
        python /Users/juanq/dev/NBEAST-flux/spikes/pincell.py
"""

import os

import openmc


def build_model(enrichment: float = 3.2, use_sab: bool | None = None) -> openmc.model.Model:
    # S(a,b) is mandatory for accurate thermal results; allow skipping it for
    # toolchain validation when the c_H_in_H2O data isn't available yet.
    if use_sab is None:
        use_sab = os.environ.get("NBEAST_NO_SAB") != "1"
    # --- Materials ---------------------------------------------------------
    fuel = openmc.Material(name="UO2 fuel")
    fuel.add_element("U", 1.0, enrichment=enrichment)
    fuel.add_element("O", 2.0)
    fuel.set_density("g/cm3", 10.4)

    clad = openmc.Material(name="Zircaloy")
    clad.add_element("Zr", 1.0)
    clad.set_density("g/cm3", 6.55)

    water = openmc.Material(name="Water")
    water.add_element("H", 2.0)
    water.add_element("O", 1.0)
    water.set_density("g/cm3", 1.0)
    if use_sab:
        water.add_s_alpha_beta("c_H_in_H2O")

    materials = openmc.Materials([fuel, clad, water])

    # --- Geometry ----------------------------------------------------------
    fuel_or = openmc.ZCylinder(r=0.39)        # fuel pellet outer radius
    clad_ir = openmc.ZCylinder(r=0.40)        # clad inner (gap)
    clad_or = openmc.ZCylinder(r=0.46)        # clad outer

    pitch = 1.26
    h = pitch / 2.0
    left = openmc.XPlane(-h, boundary_type="reflective")
    right = openmc.XPlane(h, boundary_type="reflective")
    bottom = openmc.YPlane(-h, boundary_type="reflective")
    top = openmc.YPlane(h, boundary_type="reflective")

    fuel_cell = openmc.Cell(name="fuel", fill=fuel, region=-fuel_or)
    gap_cell = openmc.Cell(name="gap", region=+fuel_or & -clad_ir)  # void
    clad_cell = openmc.Cell(name="clad", fill=clad, region=+clad_ir & -clad_or)
    water_cell = openmc.Cell(
        name="moderator",
        fill=water,
        region=+clad_or & +left & -right & +bottom & -top,
    )

    root = openmc.Universe(cells=[fuel_cell, gap_cell, clad_cell, water_cell])
    geometry = openmc.Geometry(root)

    # --- Settings ----------------------------------------------------------
    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.batches = 100
    settings.inactive = 20
    settings.particles = 2000
    settings.source = openmc.IndependentSource(
        space=openmc.stats.Box((-h, -h, -1), (h, h, 1)),
        constraints={"fissionable": True},
    )

    return openmc.model.Model(geometry, materials, settings)


if __name__ == "__main__":
    import os
    import pathlib

    run_dir = pathlib.Path(__file__).parent / "run"
    run_dir.mkdir(exist_ok=True)
    os.chdir(run_dir)

    model = build_model()
    sp_path = model.run()
    with openmc.StatePoint(sp_path) as sp:
        print(f"KEFF {sp.keff}")
