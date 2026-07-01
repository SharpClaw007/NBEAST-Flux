"""Moderation-curve physics: reactivity, subcritical multiplication, density scaling."""

import math

from nbeast.core import reactivity


def test_reactivity_pcm():
    assert reactivity.reactivity_pcm(1.0) == 0.0
    assert math.isclose(reactivity.reactivity_pcm(1.05), (0.05 / 1.05) * 1e5)
    assert reactivity.reactivity_pcm(0.9) < 0
    assert reactivity.reactivity_pcm(0.0) is None
    assert reactivity.reactivity_pcm(None) is None


def test_subcritical_multiplication():
    assert math.isclose(reactivity.subcritical_multiplication(0.9), 10.0)
    assert math.isclose(reactivity.subcritical_multiplication(0.99), 100.0)
    # no steady-state power at or above critical
    assert reactivity.subcritical_multiplication(1.0) is None
    assert reactivity.subcritical_multiplication(1.2) is None
    assert reactivity.subcritical_multiplication(None) is None


def test_moderator_density_scaling():
    from nbeast.core import materials, templates

    water = materials.build("water")
    templates.scale_density(water, 0.5)
    assert math.isclose(water.density, 0.5)
    templates.scale_density(water, 0.0)      # voided -> floored, still runnable
    assert 0.0 < water.density < 1e-3
    # None leaves it untouched
    nominal = materials.build("water")
    templates.scale_density(nominal, None)
    assert math.isclose(nominal.density, 1.0)
