"""Run a DAGMC .h5m to k-eff (Phase 6, Stage D). Run in the dagmc-OpenMC arm64 env.

Set OPENMC_CROSS_SECTIONS first (e.g. NBEAST's curated data, which has the Godiva
nuclides). Expects sphere.h5m from example_generate.py in the cwd.
"""

import openmc

# HEU (Godiva-like); the material NAME must match the .h5m "fuel" tag.
fuel = openmc.Material(name="fuel")
fuel.add_nuclide("U235", 0.9371, "wo")
fuel.add_nuclide("U238", 0.0527, "wo")
fuel.add_nuclide("U234", 0.0102, "wo")
fuel.set_density("g/cm3", 18.74)
materials = openmc.Materials([fuel])

dag_univ = openmc.DAGMCUniverse("sphere.h5m")
geometry = openmc.Geometry(dag_univ.bounded_universe())  # vacuum-bounded bounding box

settings = openmc.Settings()
settings.run_mode = "eigenvalue"
settings.batches = 50
settings.inactive = 10
settings.particles = 2000
settings.source = openmc.IndependentSource(space=openmc.stats.Point((0, 0, 0)))

model = openmc.Model(geometry, materials, settings)
sp_path = model.run()
with openmc.StatePoint(sp_path) as sp:
    print("KEFF", sp.keff)
