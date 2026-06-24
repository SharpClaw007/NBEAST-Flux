"""dagmc-OpenMC-env worker (Phase 6, Stage E). Executed by the openmc-dagmc-arm64
env's Python, NOT imported in the nbeast env. Reads a JSON job on stdin, runs a
DAGMC .h5m eigenvalue problem, prints a RESULT: line with k-eff.
"""

import json
import os
import sys


def main() -> None:
    job = json.load(sys.stdin)
    if job.get("cross_sections"):
        os.environ["OPENMC_CROSS_SECTIONS"] = job["cross_sections"]
    # model.run() invokes the `openmc` executable, which lives next to this Python.
    os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")

    import openmc

    mats = []
    for m in job["materials"]:
        mat = openmc.Material(name=m["name"])
        for nuc in m["nuclides"]:
            mat.add_nuclide(nuc["nuclide"], nuc["fraction"], nuc.get("percent_type", "wo"))
        mat.set_density(m.get("density_units", "g/cm3"), m["density"])
        mats.append(mat)
    materials = openmc.Materials(mats)

    dag_univ = openmc.DAGMCUniverse(job["h5m"])
    bbox = dag_univ.bounding_box
    geometry = openmc.Geometry(dag_univ.bounded_universe())  # vacuum-bounded box

    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.batches = job["batches"]
    settings.inactive = job["inactive"]
    settings.particles = job["particles"]
    settings.source = openmc.IndependentSource(space=openmc.stats.Point((0.0, 0.0, 0.0)))

    import numpy as np

    # Log-energy flux spectrum (same grid as the templated runs: 1e-5 eV -> 20 MeV).
    energies = np.logspace(np.log10(1e-5), np.log10(2.0e7), 101)
    spectrum = openmc.Tally(name="flux_spectrum")
    spectrum.filters = [openmc.EnergyFilter(energies)]
    spectrum.scores = ["flux"]

    # z-integrated flux map over the geometry bounding box.
    n = 50
    ll = [float(v) for v in bbox.lower_left]
    ur = [float(v) for v in bbox.upper_right]
    mesh = openmc.RegularMesh()
    mesh.dimension = (n, n, 1)
    mesh.lower_left = ll
    mesh.upper_right = ur
    flux_mesh = openmc.Tally(name="flux_mesh")
    flux_mesh.filters = [openmc.MeshFilter(mesh)]
    flux_mesh.scores = ["flux"]

    tallies = openmc.Tallies([spectrum, flux_mesh])

    rundir = os.path.join(os.path.expanduser("~"), ".nbeast", "cad_run")
    os.makedirs(rundir, exist_ok=True)
    os.chdir(rundir)

    model = openmc.Model(geometry, materials, settings, tallies)
    sp_path = model.run(output=False)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        spec = sp.get_tally(name="flux_spectrum")
        edges = spec.find_filter(openmc.EnergyFilter).values
        flux = spec.get_values(scores=["flux"]).ravel()
        fmap = sp.get_tally(name="flux_mesh").get_values(scores=["flux"]).reshape((n, n))
        print("RESULT:" + json.dumps({
            "keff": float(k.n), "keff_std": float(k.s),
            "energy_edges": [float(x) for x in edges],
            "flux": [float(x) for x in flux],
            "flux_map": [[float(v) for v in row] for row in fmap],
            "map_bounds": [ll[0], ll[1], ur[0], ur[1]],
        }))


if __name__ == "__main__":
    main()
