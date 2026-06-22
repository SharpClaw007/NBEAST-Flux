"""Deck export: model.xml round-trips and a runnable script is emitted.

Data-free (uses Godiva, whose materials are explicit nuclides), so it runs even
without a cross-section library configured.
"""

import openmc

from nbeast.core import benchmarks, export


def test_export_deck_roundtrips(tmp_path):
    model = benchmarks.godiva()
    xml, script = export.export_deck(model, tmp_path / "deck")

    assert xml.exists() and xml.stat().st_size > 0
    assert script.exists()
    assert "openmc" in script.read_text()

    # The XML is a valid, reloadable OpenMC model.
    reloaded = openmc.Model.from_model_xml(str(xml))
    assert len(reloaded.materials) >= 1
    assert reloaded.geometry is not None
    assert reloaded.settings.batches == model.settings.batches
