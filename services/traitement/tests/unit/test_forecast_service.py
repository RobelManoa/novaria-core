"""Prévision de référence par persistance (IA-06) : ce que la logique calcule, sans HTTP."""

from datetime import timedelta

import pytest

from app.services.forecasts import ForecastService, ForecastUnavailable
from tests.fakes import START, FakeIndicatorRepository, make_row


def service(*rows) -> ForecastService:
    return ForecastService(FakeIndicatorRepository(list(rows)))


def test_the_forecast_repeats_the_last_known_minute_of_each_segment():
    older = make_row(road_segment_id="ROAD_001", speed_ratio=0.9, window_start=START)
    last = make_row(
        road_segment_id="ROAD_001",
        speed_ratio=0.228,
        congestion_state="CONGESTED",
        window_start=START + timedelta(minutes=3),
    )
    (forecast,) = service(older, last).persistence(horizon_min=15)
    assert forecast.predicted_speed_ratio == 0.228
    assert forecast.row is last
    assert forecast.row.congestion_state == "CONGESTED"


def test_the_forecast_is_issued_when_the_last_window_ends_and_targets_the_horizon():
    row = make_row(window_start=START)
    (forecast,) = service(row).persistence(horizon_min=30)
    assert forecast.issued_at == START + timedelta(seconds=60)
    assert forecast.target_time == forecast.issued_at + timedelta(minutes=30)
    assert forecast.horizon_min == 30


def test_the_value_does_not_depend_on_the_horizon_but_the_target_does():
    rows = [make_row(window_start=START)]
    near = service(*rows).persistence(horizon_min=5)[0]
    far = service(*rows).persistence(horizon_min=60)[0]
    assert near.predicted_speed_ratio == far.predicted_speed_ratio
    assert far.target_time - near.target_time == timedelta(minutes=55)
    assert near.issued_at == far.issued_at


def test_segments_come_out_in_identifier_order_and_only_those_asked_for_are_kept():
    rows = [make_row(road_segment_id=f"ROAD_{n:03d}") for n in (3, 1, 2)]
    every = service(*rows).persistence(horizon_min=15)
    assert [f.row.road_segment_id for f in every] == ["ROAD_001", "ROAD_002", "ROAD_003"]
    two = service(*rows).persistence(horizon_min=15, road_segment_ids=["ROAD_003", "ROAD_001"])
    assert [f.row.road_segment_id for f in two] == ["ROAD_001", "ROAD_003"]


def test_an_unknown_segment_has_no_forecast_instead_of_an_invented_one():
    rows = [make_row(road_segment_id="ROAD_001")]
    assert service(*rows).persistence(horizon_min=15, road_segment_ids=["ROAD_999"]) == []


def test_a_segment_whose_last_window_has_no_speed_ratio_has_no_forecast():
    """Route vide : l'indicateur n'a pas de ratio (flux.md) ; la valeur n'est pas devinée."""
    rows = [
        make_row(road_segment_id="ROAD_001", speed_ratio=None, average_speed_kmh=None),
        make_row(road_segment_id="ROAD_002", speed_ratio=0.8),
    ]
    items = service(*rows).persistence(horizon_min=15)
    assert [f.row.road_segment_id for f in items] == ["ROAD_002"]


def test_only_the_most_recent_run_is_read():
    old = make_row(run_id="run-ancien", window_start=START, speed_ratio=0.1)
    new = make_row(run_id="run-recent", window_start=START + timedelta(hours=1), speed_ratio=0.7)
    (forecast,) = service(old, new).persistence(horizon_min=15)
    assert (forecast.row.run_id, forecast.predicted_speed_ratio) == ("run-recent", 0.7)


def test_five_minute_windows_are_never_used():
    five = make_row(window_size_s=300, window_start=START + timedelta(minutes=10), speed_ratio=0.1)
    minute = make_row(window_size_s=60, window_start=START, speed_ratio=0.6)
    (forecast,) = service(five, minute).persistence(horizon_min=15)
    assert forecast.predicted_speed_ratio == 0.6


def test_an_empty_warehouse_makes_every_forecast_unavailable():
    with pytest.raises(ForecastUnavailable):
        service().persistence(horizon_min=15)
