"""Core data-manager logic: presets, seeding, and indexing (non-network)."""

import os
import pathlib

import pytest


def test_default_data_dir():
    from nbeast.core import data

    d = data.default_data_dir()
    assert isinstance(d, pathlib.Path) and d.name == "data"


def test_presets_structure():
    from nbeast.core import data

    assert len(data.PRESETS) >= 4
    assert any("Thermal" in name for name in data.PRESETS)
    for preset in data.PRESETS.values():
        assert "elements" in preset and "sab" in preset


_XS = os.environ.get("OPENMC_CROSS_SECTIONS")
requires_data = pytest.mark.skipif(
    not (_XS and pathlib.Path(_XS).exists()),
    reason="OPENMC_CROSS_SECTIONS not set or missing",
)


@requires_data
def test_seed_and_index(tmp_path):
    """Seeding from an existing library copies the h5 and rebuilds the index."""
    from nbeast.core import data

    data.seed_from(_XS, tmp_path)
    assert list(tmp_path.glob("*.h5")), "no h5 seeded"

    xml = data.build_index(tmp_path)
    assert xml.exists() and xml.name == "cross_sections.xml"
