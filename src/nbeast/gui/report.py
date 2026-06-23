"""Compose a one-page run report (PDF + PNG) and a spectrum CSV.

Uses matplotlib (Agg) so it works headlessly. The flux panel embeds the
off-screen pyvista render (correct orientation) rather than re-deriving the
array here. The reproducible OpenMC deck is written separately by the caller
(nbeast.core.export).
"""

from __future__ import annotations

import csv
from pathlib import Path


def write_report(out_dir, title: str, summary_lines: list[str], result, statepoint) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from nbeast.core.results import Results

    from . import render

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(11, 8.5))
    grid = fig.add_gridspec(2, 2)

    # --- summary text ---
    ax_text = fig.add_subplot(grid[0, 0])
    ax_text.axis("off")
    ax_text.text(
        0.0, 1.0, title + "\n\n" + "\n".join(summary_lines),
        va="top", ha="left", fontsize=11, family="monospace",
    )

    # --- k-eff convergence ---
    ax_conv = fig.add_subplot(grid[0, 1])
    if result and result.batches:
        ax_conv.plot([u.batch for u in result.batches], [u.keff for u in result.batches], lw=1.2)
    ax_conv.set_title("k-effective convergence")
    ax_conv.set_xlabel("batch")
    ax_conv.set_ylabel("k-effective")

    # --- spectrum (+ CSV) and flux map ---
    ax_spec = fig.add_subplot(grid[1, 0])
    ax_flux = fig.add_subplot(grid[1, 1])
    ax_flux.axis("off")
    if statepoint:
        with Results(statepoint) as results:
            spectrum = results.flux_spectrum()
            edges = np.asarray(spectrum.energy_edges, dtype=float)
            flux = np.asarray(spectrum.flux, dtype=float)
            mids = np.sqrt(edges[:-1] * edges[1:])
            lethargy = np.log(edges[1:] / edges[:-1])
            per_lethargy = np.divide(flux, lethargy, out=np.zeros_like(flux), where=lethargy > 0)
            ax_spec.semilogx(mids, per_lethargy, lw=1.2)

            with open(out_dir / "spectrum.csv", "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["e_low_eV", "e_high_eV", "flux"])
                for lo, hi, value in zip(edges[:-1], edges[1:], flux):
                    writer.writerow([lo, hi, value])

            vtk = results.field_to_vtk(out_dir / "flux.vtk", "flux")
            panel = render.flux_to_png(vtk, out_dir / "flux_panel.png", title="")
            ax_flux.imshow(plt.imread(str(panel)))
    ax_spec.set_title("Flux energy spectrum")
    ax_spec.set_xlabel("energy (eV)")
    ax_spec.set_ylabel("flux per lethargy (a.u.)")
    ax_flux.set_title("Scalar flux")

    fig.suptitle("NBEAST run report")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    pdf_path = out_dir / "report.pdf"
    fig.savefig(pdf_path)
    fig.savefig(out_dir / "report.png", dpi=120)
    plt.close(fig)
    return pdf_path
