"""PSI (IA-06) : propriétés de l'indice, et un calcul refait à la main."""

import math
import random

import pytest

from app.drift.stats import FLOOR, population_stability_index, quantile_edges, shares


def sample(mean: float, sd: float = 0.05, n: int = 500, seed: int = 1) -> list[float]:
    rng = random.Random(seed)  # noqa: S311 : données de test, aucun usage cryptographique
    return [rng.gauss(mean, sd) for _ in range(n)]


def test_the_same_series_has_a_null_index():
    values = sample(0.9)
    assert population_stability_index(values, values) == pytest.approx(0.0, abs=1e-9)


def test_two_draws_of_the_same_law_are_stable():
    assert population_stability_index(sample(0.9, seed=1), sample(0.9, seed=2)) < 0.10


def test_a_shifted_series_goes_past_the_alert_threshold_and_a_bigger_shift_goes_further():
    reference = sample(0.9)
    small = population_stability_index(reference, sample(0.9 + 0.05, seed=3))
    large = population_stability_index(reference, sample(0.9 - 0.3, seed=3))
    assert 0.0 < small < large
    assert large > 0.25


def test_the_index_is_never_negative():
    for seed in range(5):
        assert population_stability_index(sample(0.5, seed=seed), sample(0.6, seed=seed + 9)) >= 0.0


def test_hand_computed_example_on_two_bins():
    reference = [1, 1, 1, 1, 2, 2, 2, 2]  # médiane 1,5 : deux tranches à parts égales
    current = [1, 1, 2, 2, 2, 2, 2, 2]  # 25 % puis 75 %
    edges = quantile_edges(reference, bins=2)
    assert edges == [1.5]
    assert shares(current, edges) == [0.25, 0.75]
    expected = (0.25 - 0.5) * math.log(0.25 / 0.5) + (0.75 - 0.5) * math.log(0.75 / 0.5)
    assert population_stability_index(reference, current, bins=2) == pytest.approx(expected)


def test_a_constant_reference_still_detects_a_drop():
    reference = [1.0] * 200
    assert population_stability_index(reference, [1.0] * 200) == pytest.approx(0.0, abs=1e-9)
    assert population_stability_index(reference, [0.5] * 200) > 0.25


def test_an_empty_tranche_does_not_make_the_logarithm_diverge():
    value = population_stability_index(sample(0.9), [5.0] * 100)  # toutes hors de la référence
    assert math.isfinite(value)
    assert value < 100 * math.log(1 / FLOOR)


def test_edges_have_no_duplicate_and_stay_sorted():
    edges = quantile_edges([0.0] * 50 + [1.0] * 50)
    assert edges == sorted(set(edges))


def test_empty_series_are_refused():
    with pytest.raises(ValueError):
        population_stability_index([], [1.0])
    with pytest.raises(ValueError):
        population_stability_index([1.0], [])
