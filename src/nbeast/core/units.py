"""Display unit systems (SI / US-Imperial) + conversions — Qt-free.

Field maps come straight from OpenMC tallies: they are *per source neutron* and
**not power-normalized**, so by default they are relative spatial distributions,
not absolute rates. When a reactor power is supplied the physics normalization
(see :mod:`nbeast.core.results`) converts them to absolute units; this module
owns only the display labels + the SI↔US conversions.

Deposition assumption: the source rate comes from a whole-geometry ``kappa-fission``
tally (recoverable fission energy), and photon transport is off by default, so the
spatial ``heating`` (KERMA) map deposits photon energy at the fission site rather than
where gammas actually stop. Energy is conserved to ~10% (KERMA integrates to ~0.91 of
kappa-fission on an all-actinide system — the un-transported photon fraction; validated
in ``tests/test_units.py``). For an accurate *spatial* heating map, enable
``settings.photon_transport``; the integral normalization is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

CM_PER_INCH = 2.54

SI = "SI"
US = "US"
SYSTEMS = (SI, US)


# ---- length (the geometry is stored in cm, OpenMC's native unit) -------------
def length_unit(system: str) -> str:
    return "in" if system == US else "cm"


def cm_to_display(value_cm: float, system: str) -> float:
    return value_cm / CM_PER_INCH if system == US else value_cm


def display_to_cm(value: float, system: str) -> float:
    return value * CM_PER_INCH if system == US else value


def is_length(unit: str | None) -> bool:
    return unit == "cm"


# ---- field colorbar labels + (absolute) unit conversion ----------------------
@dataclass(frozen=True)
class _Abs:
    si: str
    us: str
    us_factor: float   # multiply an SI (per-cm) value to get the US (per-inch) value


# Absolute units, only meaningful once power-normalized. The US factor converts
# the length dimension (per cm^n -> per in^n) or the dose (Sv -> rem).
_ABS = {
    "flux":       _Abs("n·cm⁻²·s⁻¹", "n·in⁻²·s⁻¹", CM_PER_INCH ** 2),
    "fission":    _Abs("cm⁻³·s⁻¹",   "in⁻³·s⁻¹",   CM_PER_INCH ** 3),
    "absorption": _Abs("cm⁻³·s⁻¹",   "in⁻³·s⁻¹",   CM_PER_INCH ** 3),
    "nu-fission": _Abs("cm⁻³·s⁻¹",   "in⁻³·s⁻¹",   CM_PER_INCH ** 3),
    "heating":    _Abs("W·cm⁻³",     "W·in⁻³",     CM_PER_INCH ** 3),
    "dose":       _Abs("Sv·h⁻¹",     "rem·h⁻¹",    100.0),
}

_QUANTITY = {
    "flux": "Scalar flux",
    "fission": "Fission rate",
    "absorption": "Absorption rate",
    "nu-fission": "Neutron production",
    "heating": "Heating",
    "dose": "Neutron dose rate",
    "volume": "Scalar flux",
}


def _base(score: str) -> str:
    return score[:-8] if score.endswith("_rel_err") else score


def quantity(score: str) -> str:
    return _QUANTITY.get(score, _QUANTITY.get(_base(score), _base(score).title()))


def colorbar_title(score: str, system: str, absolute: bool) -> str:
    """Two-line colorbar title: quantity on top, unit/relative note below."""
    if score.endswith("_rel_err"):
        return f"{quantity(score)}\n(relative error)"
    q = quantity(score)
    if not absolute:
        return f"{q}\n(relative · per source n)"
    unit = _ABS.get(_base(score))
    if unit is None:
        return q
    return f"{q}\n({unit.us if system == US else unit.si})"


def field_factor(score: str, system: str, absolute: bool) -> float:
    """Multiplier applied to an absolute SI field value to display it in `system`."""
    if not absolute or score.endswith("_rel_err"):
        return 1.0
    unit = _ABS.get(_base(score))
    if unit is None or system != US:
        return 1.0
    return unit.us_factor
