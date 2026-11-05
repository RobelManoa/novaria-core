"""Entrée « MQTT simulé » et rejeu d'un fichier de mesures (MS-08)."""

import json

import pytest

from app.adapters.mqtt_sim import DEFAULT_FILTER, SimulatedMqttAdapter, topic_matches
from app.cli import build_parser, main, replay, topic_of
from app.services.ingestion import Outcome, PublishFailed
from tests.support import body, measurement, with_value

TOPIC = "novaria/iot/measurements/SENSOR_001"


@pytest.fixture(autouse=True)
def replay_dir(tmp_path, monkeypatch):
    """Le répertoire de rejeu de ces tests : celui où ils écrivent leurs fichiers."""
    monkeypatch.setenv("REPLAY_DIR", str(tmp_path))
    return tmp_path


# --- Filtre d'abonnement MQTT -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("topic_filter", "topic", "expected"),
    [
        (DEFAULT_FILTER, TOPIC, True),
        (DEFAULT_FILTER, "novaria/iot/measurements/inconnu", True),
        (DEFAULT_FILTER, "novaria/iot/measurements", False),
        (DEFAULT_FILTER, "novaria/iot/measurements/SENSOR_001/extra", False),
        (DEFAULT_FILTER, "novaria/iot/autre/SENSOR_001", False),
        (DEFAULT_FILTER, "autre/iot/measurements/SENSOR_001", False),
        ("novaria/#", TOPIC, True),
        ("novaria/#", "novaria", True),  # `a/#` correspond aussi au niveau parent `a` (MQTT 3.1.1)
        ("#", "n'importe/quoi", True),
        ("novaria/+/measurements/+", TOPIC, True),
        ("novaria/+/measurements/+", "novaria/iot/autre/S", False),
        ("novaria/+/measurements/+", "novaria/iot/measurements/S", True),
        ("novaria/#/x", TOPIC, False),  # `#` n'est permis qu'en dernier niveau
        (TOPIC, TOPIC, True),
        (TOPIC, "novaria/iot/measurements/SENSOR_002", False),
        ("", "", True),
    ],
)
def test_the_subscription_filter_follows_the_mqtt_rules(topic_filter, topic, expected):
    assert topic_matches(topic_filter, topic) is expected


# --- Adaptateur -------------------------------------------------------------------------------


def adapter(rig, **kwargs) -> SimulatedMqttAdapter:
    return SimulatedMqttAdapter(rig.service, **kwargs)


def test_a_message_delivered_to_the_subscriber_goes_through_the_same_service_as_http(rig):
    event = measurement(0)
    receipt = adapter(rig).on_message(TOPIC, body(event))
    assert receipt is not None
    assert receipt.outcome is Outcome.ACCEPTED
    assert [e["id"] for e in rig.publisher.events("iot.raw")] == [event["id"]]
    assert event["id"] in rig.raw.documents


def test_a_message_outside_the_subscription_is_not_received_at_all(rig):
    assert adapter(rig).on_message("autre/sujet", body(measurement(0))) is None
    assert rig.publisher.calls == []
    assert rig.raw.documents == {}


def test_qos1_redelivery_is_a_duplicate_ignored_not_a_second_publication(rig):
    event = measurement(0)
    mqtt = adapter(rig)
    first = mqtt.on_message(TOPIC, body(event))
    again = mqtt.on_message(TOPIC, body(event))
    assert (first.outcome, again.outcome) == (Outcome.ACCEPTED, Outcome.DUPLICATE)
    assert len(rig.publisher.events("iot.raw")) == 1


def test_an_invalid_message_over_mqtt_goes_to_the_error_topic_with_its_reason(rig):
    receipt = adapter(rig).on_message(
        TOPIC, body(with_value(measurement(0), ("data", "vehicle_count"), -3))
    )
    assert receipt.outcome is Outcome.REJECTED
    (dlq,) = rig.publisher.events("errors.dlq")
    assert dlq["data"]["reason_code"] == "CONTRACT_VIOLATION"
    assert rig.publisher.events("iot.raw") == []


def test_http_and_mqtt_give_the_same_outcome_for_the_same_bytes(rig, client):
    valid, invalid = (
        body(measurement(0)),
        body(with_value(measurement(1), ("data", "occupancy_rate"), 2)),
    )
    mqtt = adapter(rig)
    assert mqtt.on_message(TOPIC, valid).outcome is Outcome.ACCEPTED
    assert client.post("/api/v1/measurements", content=valid).json()["status"] == "DUPLICATE"
    assert mqtt.on_message(TOPIC, invalid).outcome is Outcome.REJECTED
    assert client.post("/api/v1/measurements", content=invalid).status_code == 422
    assert len(rig.publisher.events("errors.dlq")) == 2


def test_a_failure_goes_back_to_the_subscriber_so_it_does_not_acknowledge(rig):
    rig.publisher.fail_on = {"iot.raw"}
    with pytest.raises(PublishFailed):
        adapter(rig).on_message(TOPIC, body(measurement(0)))


def test_a_custom_subscription_filter_is_honoured(rig):
    mqtt = adapter(rig, topic_filter="capteurs/#")
    assert mqtt.on_message(TOPIC, body(measurement(0))) is None
    assert mqtt.on_message("capteurs/a/b", body(measurement(0))).outcome is Outcome.ACCEPTED


# --- Rejeu d'un fichier -----------------------------------------------------------------------


def write_jsonl(path, events: list) -> None:
    path.write_bytes(b"\n".join(e if isinstance(e, bytes) else body(e) for e in events) + b"\n")


def test_the_topic_of_a_line_is_its_sensor_or_unknown():
    assert topic_of(body(measurement(0, sensor=7))) == "novaria/iot/measurements/SENSOR_007"
    assert topic_of(b"pas du json") == "novaria/iot/measurements/inconnu"
    assert topic_of(b'{"data": 3}') == "novaria/iot/measurements/inconnu"
    assert topic_of(body(with_value(measurement(0), ("data", "sensor_id"), "a/b"))).endswith(
        "inconnu"
    )
    assert topic_of(body(with_value(measurement(0), ("data", "sensor_id"), ""))).endswith("inconnu")


def test_replay_counts_each_outcome(tmp_path, rig):
    file = tmp_path / "mesures.jsonl"
    good = [measurement(n) for n in range(4)]
    write_jsonl(
        file, [*good, good[0], with_value(measurement(9), ("data", "vehicle_count"), -1), b"{"]
    )
    counts = replay(file, redeliver=False, limit=0, adapter=adapter(rig))
    assert dict(counts) == {"ACCEPTED": 4, "DUPLICATE": 1, "REJECTED": 2}


def test_redeliver_sends_every_line_twice_and_the_second_is_a_duplicate(tmp_path, rig):
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(n) for n in range(5)])
    counts = replay(file, redeliver=True, limit=0, adapter=adapter(rig))
    assert dict(counts) == {"ACCEPTED": 5, "DUPLICATE": 5}
    assert len(rig.publisher.events("iot.raw")) == 5


def test_limit_stops_after_the_first_lines_and_blank_lines_are_skipped(tmp_path, rig):
    file = tmp_path / "mesures.jsonl"
    file.write_bytes(
        b"\n".join([body(measurement(0)), b"", body(measurement(1)), body(measurement(2))])
    )
    counts = replay(file, redeliver=False, limit=3, adapter=adapter(rig))
    assert dict(counts) == {"ACCEPTED": 2}


def test_replay_counts_a_broker_failure_without_stopping(tmp_path, rig):
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(n) for n in range(3)])
    rig.publisher.fail_on = {"iot.raw"}
    assert dict(replay(file, redeliver=False, limit=0, adapter=adapter(rig))) == {"FAILED": 3}


def test_replay_ignores_nothing_the_subscription_accepts(tmp_path, rig):
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(0)])
    counts = replay(file, redeliver=False, limit=0, adapter=adapter(rig, topic_filter="autre/+"))
    assert dict(counts) == {"IGNORED": 1}


def test_main_prints_the_summary_and_exits_0_when_every_message_has_an_outcome(
    tmp_path, rig, capsys
):
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(0), b"{"])
    code = main(["replay-mqtt", str(file), "--redeliver"], adapter=adapter(rig))
    assert code == 0
    assert "ACCEPTED=1, DUPLICATE=1, REJECTED=2, FAILED=0" in capsys.readouterr().out


def test_main_exits_1_when_the_bus_failed_a_message_so_it_can_be_replayed(tmp_path, rig, capsys):
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(0)])
    rig.publisher.fail_on = {"iot.raw"}
    assert main(["replay-mqtt", str(file)], adapter=adapter(rig)) == 1
    assert "FAILED=1" in capsys.readouterr().out


def test_main_exits_2_for_a_missing_file(tmp_path, rig, capsys):
    assert main(["replay-mqtt", str(tmp_path / "absent.jsonl")], adapter=adapter(rig)) == 2
    assert "n'est pas un fichier du répertoire de rejeu" in capsys.readouterr().err


# --- Le fichier rejoué reste dans le répertoire de rejeu --------------------------------------


def test_a_file_outside_the_replay_directory_is_refused_and_nothing_is_sent(
    tmp_path, rig, capsys, monkeypatch
):
    elsewhere = tmp_path / "ailleurs"
    elsewhere.mkdir()
    write_jsonl(elsewhere / "secret.jsonl", [measurement(0)])
    allowed = tmp_path / "permis"
    allowed.mkdir()
    monkeypatch.setenv("REPLAY_DIR", str(allowed))
    for argument in (
        str(elsewhere / "secret.jsonl"),  # chemin absolu
        "../ailleurs/secret.jsonl",  # remontée
    ):
        assert main(["replay-mqtt", argument], adapter=adapter(rig)) == 2
        assert "répertoire de rejeu" in capsys.readouterr().err
    assert rig.publisher.calls == []


def test_a_symbolic_link_out_of_the_replay_directory_is_refused(tmp_path, rig, monkeypatch):
    elsewhere = tmp_path / "ailleurs"
    elsewhere.mkdir()
    write_jsonl(elsewhere / "secret.jsonl", [measurement(0)])
    allowed = tmp_path / "permis"
    allowed.mkdir()
    link = allowed / "lien.jsonl"
    try:
        link.symlink_to(elsewhere / "secret.jsonl")
    except OSError:  # Windows sans droit de créer des liens symboliques
        pytest.skip("liens symboliques non disponibles")
    monkeypatch.setenv("REPLAY_DIR", str(allowed))
    assert main(["replay-mqtt", "lien.jsonl"], adapter=adapter(rig)) == 2
    assert rig.publisher.calls == []


def test_a_relative_name_and_a_subdirectory_are_replayed(tmp_path, rig, capsys):
    (tmp_path / "sous").mkdir()
    write_jsonl(tmp_path / "sous" / "mesures.jsonl", [measurement(0)])
    assert main(["replay-mqtt", "sous/mesures.jsonl"], adapter=adapter(rig)) == 0
    assert "ACCEPTED=1" in capsys.readouterr().out


def test_without_replay_dir_the_current_directory_is_the_limit(tmp_path, rig, capsys, monkeypatch):
    monkeypatch.delenv("REPLAY_DIR")
    inside = tmp_path / "ici"
    inside.mkdir()
    write_jsonl(inside / "mesures.jsonl", [measurement(0)])
    write_jsonl(tmp_path / "dehors.jsonl", [measurement(1)])
    monkeypatch.chdir(inside)
    assert main(["replay-mqtt", "mesures.jsonl"], adapter=adapter(rig)) == 0
    assert main(["replay-mqtt", "../dehors.jsonl"], adapter=adapter(rig)) == 2
    assert len(rig.publisher.events("iot.raw")) == 1


def test_the_parser_requires_a_command_and_a_file():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["replay-mqtt"])
    arguments = build_parser().parse_args(["replay-mqtt", "f.jsonl", "--limit", "5"])
    assert (arguments.limit, arguments.redeliver) == (5, False)


def test_main_builds_the_real_service_when_no_adapter_is_given_and_closes_it(
    tmp_path, monkeypatch, rig
):
    import app.cli as cli

    closed = []
    monkeypatch.setattr(cli, "get_ingestion_service", lambda: rig.service)
    monkeypatch.setattr(cli, "close_components", lambda: closed.append(True))
    file = tmp_path / "mesures.jsonl"
    write_jsonl(file, [measurement(0)])
    assert main(["replay-mqtt", str(file)]) == 0
    assert closed == [True]
    assert json.loads(rig.publisher.calls[0][2])["id"] == measurement(0)["id"]
