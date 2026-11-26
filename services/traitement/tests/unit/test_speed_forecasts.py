"""Le service de prévision d'un réseau de vitesses (IA-16) : lit, remplit, prévoit, compare, et
refuse sans inventer."""

from datetime import timedelta

import pytest

from app.services import speed_forecasts as sf
from tests.speed_data import META, NETWORK, SENSORS, T0, FakeSpeedRepository, model_bytes, speed

KMH = sf.MPH_EN_KMH


@pytest.fixture
def models_dir(tmp_path):
    (tmp_path / "prevision-metr-la-reseau.json").write_bytes(model_bytes())
    return tmp_path


def service(models_dir, repository=None):
    return sf.SpeedForecastService(repository or FakeSpeedRepository(), models_dir)


def forecast(models_dir, **changes):
    arguments = {"as_of": T0, "horizon_min": 15, "sensor_ids": None} | changes
    return service(models_dir).forecast("metr-la", **arguments)


def test_one_forecast_per_sensor_with_the_persistence_and_the_measured_speed(models_dir):
    result = forecast(models_dir)
    assert result.as_of == T0 and result.horizon_min == 15
    assert [i.sensor_id for i in result.items] == SENSORS
    assert {i.target_time for i in result.items} == {T0 + timedelta(minutes=15)}
    first = result.items[0]
    assert first.persistence_speed_kmh == round(
        speed(0, 0) * KMH, 1
    )  # la dernière vitesse connue, en km/h
    assert first.observed_speed_kmh == round(
        speed(0, 3) * KMH, 1
    )  # ce qui a vraiment été mesuré 15 minutes plus tard
    assert all(isinstance(i.predicted_speed_kmh, float) for i in result.items)


def test_an_absent_measure_is_filled_with_the_last_known_one_for_the_persistence(models_dir):
    third = forecast(models_dir).items[2]  # aucune mesure au pas T0 pour ce capteur
    assert third.persistence_speed_kmh == round(speed(2, -1) * KMH, 1)


def test_the_model_is_really_used_and_depends_on_the_data(models_dir):
    a = forecast(models_dir).items[0].predicted_speed_kmh
    changed = FakeSpeedRepository()
    original = changed.readings
    changed.readings = lambda n, s, e: [
        r.__class__(r.observed_at, r.sensor_id, r.speed + 20) for r in original(n, s, e)
    ]
    b = (
        service(models_dir, changed)
        .forecast("metr-la", as_of=T0, horizon_min=15, sensor_ids=None)
        .items[0]
        .predicted_speed_kmh
    )
    assert a != b


def test_the_horizon_picks_the_matching_output_and_target_time(models_dir):
    five, thirty = forecast(models_dir, horizon_min=5), forecast(models_dir, horizon_min=30)
    assert five.items[0].target_time == T0 + timedelta(minutes=5)
    assert thirty.items[0].target_time == T0 + timedelta(minutes=30)
    assert five.items[0].predicted_speed_kmh != thirty.items[0].predicted_speed_kmh


def test_no_measure_at_the_target_means_no_observed_speed(models_dir):
    result = forecast(
        models_dir, as_of=T0 + timedelta(minutes=60), horizon_min=15
    )  # le réseau s'arrête à T0 + 1 h
    assert all(i.observed_speed_kmh is None for i in result.items)


def test_as_of_is_rounded_down_to_the_last_measured_instant(models_dir):
    assert forecast(models_dir, as_of=T0 + timedelta(minutes=3)).as_of == T0
    assert forecast(models_dir, as_of=None).as_of == T0 + timedelta(minutes=60)


def test_a_date_before_any_measure_is_refused(models_dir):
    with pytest.raises(sf.NoDataBefore):
        forecast(models_dir, as_of=T0 - timedelta(days=30))


def test_the_sensor_filter(models_dir):
    result = forecast(models_dir, sensor_ids=["767541", "inconnu"])
    assert [i.sensor_id for i in result.items] == ["767541"]


def test_unknown_network(models_dir):
    with pytest.raises(sf.NetworkNotFound):
        service(models_dir).forecast("nulle-part", as_of=None, horizon_min=15, sensor_ids=None)


def test_no_model_file_means_unavailable_never_a_persistence_dressed_as_a_model(tmp_path):
    with pytest.raises(sf.ModelUnavailable, match="Aucun modèle"):
        service(tmp_path).forecast("metr-la", as_of=None, horizon_min=15, sensor_ids=None)
    with pytest.raises(sf.ModelUnavailable, match="MODELS_DIR"):
        sf.SpeedForecastService(FakeSpeedRepository(), None).forecast(
            "metr-la", as_of=None, horizon_min=15, sensor_ids=None
        )


def test_a_corrupt_model_file_is_refused_with_a_clear_message(tmp_path):
    (tmp_path / "prevision-metr-la-reseau.json").write_bytes(b"{pas du json")
    with pytest.raises(sf.ModelUnavailable, match="refusé"):
        service(tmp_path).forecast("metr-la", as_of=None, horizon_min=15, sensor_ids=None)


def test_a_model_that_does_not_match_the_loaded_network_is_refused(models_dir):
    other = FakeSpeedRepository(sensors=["a", "b", "c", "d"])
    with pytest.raises(sf.ModelUnavailable, match="ne correspond plus"):
        service(models_dir, other).forecast("metr-la", as_of=None, horizon_min=15, sensor_ids=None)


def test_new_sensors_in_the_network_are_counted_not_invented(models_dir):
    bigger = FakeSpeedRepository(sensors=[*SENSORS, "nouveau-1", "nouveau-2"])
    result = service(models_dir, bigger).forecast(
        "metr-la", as_of=T0, horizon_min=15, sensor_ids=None
    )
    assert result.sensors_without_model == 2
    assert [i.sensor_id for i in result.items] == SENSORS


def test_a_network_that_is_not_in_five_minute_steps_has_no_model(models_dir):
    minute = FakeSpeedRepository(
        network=NETWORK.__class__("metr-la", "x", "", "REAL_HISTORICAL", 60, "mph")
    )
    with pytest.raises(sf.ModelUnavailable, match="5 minutes"):
        service(models_dir, minute).forecast("metr-la", as_of=None, horizon_min=15, sensor_ids=None)


def test_a_kmh_network_gives_the_same_speeds_in_kmh(models_dir):
    kmh = FakeSpeedRepository(
        network=NETWORK.__class__("metr-la", "x", "", "REAL_HISTORICAL", 300, "kmh")
    )
    original = kmh.readings
    kmh.readings = lambda n, s, e: [
        r.__class__(r.observed_at, r.sensor_id, round(r.speed * KMH, 2)) for r in original(n, s, e)
    ]
    a = forecast(models_dir).items[0]
    b = (
        service(models_dir, kmh)
        .forecast("metr-la", as_of=T0, horizon_min=15, sensor_ids=None)
        .items[0]
    )
    assert abs(a.persistence_speed_kmh - b.persistence_speed_kmh) <= 0.1
    assert abs(a.predicted_speed_kmh - b.predicted_speed_kmh) <= 0.5


def test_the_networks_listing_carries_the_coverage_and_the_card_or_the_reason(models_dir, tmp_path):
    [with_model] = service(models_dir).networks()
    assert with_model.model is not None and with_model.model_problem is None
    assert with_model.coverage.sensors == 4 and with_model.coverage.steps == 73
    vide = tmp_path / "vide"
    vide.mkdir()
    [without] = service(vide).networks()
    assert without.model is None and "Aucun modèle" in without.model_problem


def test_the_card_is_the_one_written_by_the_training(models_dir):
    loaded = sf.load_model(models_dir, "metr-la")
    assert sf.card(loaded)["jeu"] == META["jeu"]
    assert len(loaded.file_sha256) == 64
    assert (
        sf.load_model(models_dir, "metr-la") is loaded
    )  # gardé en mémoire tant que le fichier ne change pas
