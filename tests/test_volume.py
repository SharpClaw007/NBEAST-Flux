"""3D flux volume mesh tally (for the publication volume render)."""

import openmc

from nbeast.core import tallies


def test_add_flux_volume_mesh():
    sphere = openmc.Sphere(r=5.0, boundary_type="vacuum")
    cell = openmc.Cell(region=-sphere)
    model = openmc.Model(geometry=openmc.Geometry([cell]))

    mesh = tallies.add_flux_volume_mesh(model, n=12)
    assert tuple(mesh.dimension) == (12, 12, 12)

    vol = [t for t in model.tallies if t.name == "flux_volume"]
    assert len(vol) == 1
    assert vol[0].scores == ["flux"]
