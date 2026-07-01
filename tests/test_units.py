"""Display unit system: SI/US conversions + honest colorbar labels."""

import math

from nbeast.core import units


def test_length_conversions_roundtrip():
    assert units.length_unit("SI") == "cm"
    assert units.length_unit("US") == "in"
    assert math.isclose(units.cm_to_display(2.54, "US"), 1.0)
    assert math.isclose(units.cm_to_display(1.26, "SI"), 1.26)
    assert math.isclose(units.display_to_cm(1.0, "US"), 2.54)
    # round-trip
    assert math.isclose(units.display_to_cm(units.cm_to_display(3.7, "US"), "US"), 3.7)
    assert units.is_length("cm") and not units.is_length("wt%") and not units.is_length("K")


def test_colorbar_titles_are_honest():
    # relative by default — never claim absolute units
    assert units.colorbar_title("flux", "SI", absolute=False) == "Scalar flux\n(relative · per source n)"
    assert units.colorbar_title("flux", "US", absolute=False) == "Scalar flux\n(relative · per source n)"
    # absolute units convert with the system
    assert units.colorbar_title("flux", "SI", absolute=True) == "Scalar flux\n(n·cm⁻²·s⁻¹)"
    assert units.colorbar_title("flux", "US", absolute=True) == "Scalar flux\n(n·in⁻²·s⁻¹)"
    assert units.colorbar_title("dose", "US", absolute=True) == "Neutron dose rate\n(rem·h⁻¹)"
    # relative error is dimensionless in both systems
    assert units.colorbar_title("flux_rel_err", "US", absolute=True) == "Scalar flux\n(relative error)"


def test_field_factors():
    # no conversion unless absolute AND US
    assert units.field_factor("flux", "SI", absolute=True) == 1.0
    assert units.field_factor("flux", "US", absolute=False) == 1.0
    # area/volume scale by inch powers; dose Sv->rem is ×100
    assert math.isclose(units.field_factor("flux", "US", absolute=True), units.CM_PER_INCH ** 2)
    assert math.isclose(units.field_factor("fission", "US", absolute=True), units.CM_PER_INCH ** 3)
    assert math.isclose(units.field_factor("dose", "US", absolute=True), 100.0)
    assert units.field_factor("flux_rel_err", "US", absolute=True) == 1.0
