"""Generate and read a small set of particle tracks for visualization.

Tracks come from a tiny dedicated run (a single batch of a handful of source
particles) with OpenMC's track output enabled — not the main eigenvalue run,
which has far too many particles to track. Each particle's polyline carries its
energy at every state, so the viewer can colour by energy (watch neutrons slow
down).
"""

from __future__ import annotations

import os
import pathlib
import sys

import numpy as np
import openmc


def generate(model: openmc.model.Model, n_particles: int = 15, run_dir="."):
    """Run a short tracked simulation; return the path to tracks.h5."""
    os.environ.setdefault("FI_PROVIDER", "tcp")
    run_dir = pathlib.Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    model.settings.particles = n_particles
    model.settings.batches = 1
    model.settings.inactive = 0

    # Resolve the openmc executable next to this Python so we don't depend on PATH.
    openmc_exec = str(pathlib.Path(sys.executable).with_name("openmc"))
    model.run(tracks=True, output=False, cwd=str(run_dir), openmc_exec=openmc_exec)
    return run_dir / "tracks.h5"


def read_polylines(tracks_path, max_polylines: int = 60) -> list[dict]:
    """Return [{points:(M,3), energy:(M,), particle:str}, ...] — one per track segment."""
    tracks = openmc.Tracks(str(tracks_path))
    polylines: list[dict] = []
    for track in tracks:
        for particle_track in track.particle_tracks:
            # states["r"] is a structured (x, y, z) array — stack into (M, 3).
            r = particle_track.states["r"]
            points = np.column_stack([r["x"], r["y"], r["z"]]).astype(float)
            if points.shape[0] < 2:
                continue  # need at least two points to draw a segment
            energy = np.asarray(particle_track.states["E"], dtype=float)
            polylines.append(
                {"points": points, "energy": energy, "particle": str(particle_track.particle)}
            )
            if len(polylines) >= max_polylines:
                return polylines
    return polylines
