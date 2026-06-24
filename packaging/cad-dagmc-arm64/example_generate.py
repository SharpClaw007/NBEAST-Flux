"""CAD -> DAGMC .h5m (Phase 6, Stage D). Run in the cad-arm64 env.

Builds an HEU sphere (~Godiva critical radius) as a CadQuery solid, meshes it with
gmsh, and writes a watertight DAGMC geometry whose volume is tagged "fuel".
"""

import cadquery as cq
from cad_to_dagmc import CadToDagmc

RADIUS_CM = 8.7  # Godiva critical radius is 8.74 cm

sphere = cq.Workplane().sphere(RADIUS_CM)
c = CadToDagmc()
c.add_cadquery_object(sphere, material_tags=["fuel"])
c.export_dagmc_h5m_file(filename="sphere.h5m", max_mesh_size=3.0, min_mesh_size=0.5)
print("wrote sphere.h5m (material tag: fuel)")
