"""CAD-env worker (Phase 6, Stage E). Executed by the cad-arm64 env's Python, NOT
imported in the nbeast env. Reads a JSON job on stdin, prints a RESULT: line.

  inspect : count the solids in a STEP file
  generate: STEP -> watertight DAGMC .h5m with per-solid material tags
"""

import json
import os
import sys


def main() -> None:
    job = json.load(sys.stdin)
    mode = job["mode"]

    if mode == "inspect":
        import cadquery as cq

        result = cq.importers.importStep(job["step"])
        n = len(result.solids().vals())
        print("RESULT:" + json.dumps({"n_solids": n}))

    elif mode == "tessellate":
        import cadquery as cq

        result = cq.importers.importStep(job["step"])
        stls = []
        for i, solid in enumerate(result.solids().vals()):
            path = os.path.join(job["out_dir"], f"solid_{i}.stl")
            cq.exporters.export(cq.Workplane(obj=solid), path, exportType="STL")
            stls.append(path)
        print("RESULT:" + json.dumps({"stls": stls}))

    elif mode == "generate":
        from cad_to_dagmc import CadToDagmc

        c = CadToDagmc()
        c.add_stp_file(job["step"], material_tags=job["material_tags"])
        c.export_dagmc_h5m_file(
            filename=job["out"],
            max_mesh_size=job["max_mesh_size"],
            min_mesh_size=job["min_mesh_size"],
        )
        print("RESULT:" + json.dumps({"h5m": job["out"]}))

    else:
        raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()
