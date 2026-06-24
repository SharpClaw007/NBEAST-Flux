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

    dag = openmc.DAGMCUniverse(job["h5m"]).bounded_universe()  # vacuum-bounded box
    geometry = openmc.Geometry(dag)

    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.batches = job["batches"]
    settings.inactive = job["inactive"]
    settings.particles = job["particles"]
    settings.source = openmc.IndependentSource(space=openmc.stats.Point((0.0, 0.0, 0.0)))

    rundir = os.path.join(os.path.expanduser("~"), ".nbeast", "cad_run")
    os.makedirs(rundir, exist_ok=True)
    os.chdir(rundir)

    model = openmc.Model(geometry, materials, settings)
    sp_path = model.run(output=False)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        print("RESULT:" + json.dumps({"keff": float(k.n), "keff_std": float(k.s)}))


if __name__ == "__main__":
    main()
