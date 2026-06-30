"""Tier-3 run-to-run comparison numerics (data-free)."""

import math

import pytest

from nbeast.core import compare
from nbeast.core.project import RunRecord


def test_keff_delta_significant():
    d = compare.keff_delta(1.0000, 0.0005, 1.0100, 0.0005)
    assert d.delta == pytest.approx(0.01)
    assert d.delta_pcm == pytest.approx(1000.0)
    assert d.sigma_pcm == pytest.approx(math.hypot(50, 50), rel=1e-6)
    assert d.significant and d.n_sigma > 2


def test_keff_delta_within_noise():
    d = compare.keff_delta(1.0000, 0.0010, 1.0008, 0.0010)
    assert not d.significant  # 0.0008 < 2 * sqrt(2)*0.001
    assert "within noise" in d.summary()


def test_keff_delta_zero_uncertainty():
    d = compare.keff_delta(1.0, 0.0, 1.1, 0.0)
    assert d.sigma == 0.0 and math.isinf(d.n_sigma) and d.significant


def test_param_diff_changed_first_and_union():
    rows = compare.param_diff({"radius": 8.7, "pitch": 1.26}, {"radius": 9.0, "n": 7})
    keys = [r.key for r in rows]
    assert keys[0] == "n" or rows[0].changed  # changed rows sort first
    by_key = {r.key: r for r in rows}
    assert by_key["radius"].changed is True
    assert by_key["pitch"].changed is True   # present in A, missing in B => changed
    assert by_key["pitch"].b is None
    assert set(keys) == {"radius", "pitch", "n"}


def test_param_diff_unchanged_floats():
    rows = compare.param_diff({"pitch": 1.26}, {"pitch": 1.2600000001})
    assert rows[0].changed is False  # isclose tolerance


def test_compare_uses_record_titles():
    a = RunRecord(id="run-0001", template="Godiva", parameters={"radius": 8.5},
                  keff=0.97, keff_std=0.001)
    b = RunRecord(id="run-0002", template="Godiva", parameters={"radius": 9.0},
                  keff=1.03, keff_std=0.001)
    data = compare.compare(a, b)
    assert data["keff_a"] == 0.97 and data["keff_b"] == 1.03
    assert "Godiva" in data["label_a"]
    assert data["delta"].delta == pytest.approx(0.06)
    assert any(r.key == "radius" and r.changed for r in data["params"])
