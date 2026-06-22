"""Export a model to a reproducible OpenMC input deck.

`model.xml` is the portable, runnable deck — anyone with OpenMC can run it. A
small `run.py` wrapper is emitted alongside so the export is self-explanatory.
(Richer, object-level Python codegen — the full student->code bridge — is a
later enhancement; the XML already guarantees reproducibility.)
"""

from __future__ import annotations

from pathlib import Path

import openmc

_RUN_SCRIPT = '''\
"""Reproducible OpenMC input exported by NBEAST.

Requires an OpenMC environment with a cross-section library configured
(set OPENMC_CROSS_SECTIONS), then:

    python run.py
"""
import openmc

model = openmc.Model.from_model_xml("{xml_name}")
model.run()
'''


def to_model_xml(model: openmc.model.Model, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.export_to_model_xml(str(path))
    return path


def to_runnable_script(path: str | Path, xml_name: str = "model.xml") -> Path:
    path = Path(path)
    path.write_text(_RUN_SCRIPT.format(xml_name=xml_name))
    return path


def export_deck(model: openmc.model.Model, out_dir: str | Path) -> tuple[Path, Path]:
    """Write ``model.xml`` + ``run.py`` into ``out_dir``; returns both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    xml = to_model_xml(model, out_dir / "model.xml")
    script = to_runnable_script(out_dir / "run.py", xml_name="model.xml")
    return xml, script
