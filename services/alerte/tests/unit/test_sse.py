"""Diffusion en direct : concentrateur, format SSE, coupure d'un client lent, route (MS-11)."""

import asyncio
import json
import secrets
import threading

import pytest
from starlette.responses import StreamingResponse

from app.api.v1.stream import stream_events
from app.core.auth import Claims, Role
from app.core.config import Settings
from app.core.errors import ProblemError
from app.sse import ALERT_EVENT, EventHub, Message, stream


def run(coroutine):
    return asyncio.run(coroutine)


def lines(chunk: bytes) -> list[str]:
    return chunk.decode("utf-8").rstrip("\n").split("\n")


def bus_message(state: str = "CREATED", event_id: str = "alerte-x-created") -> bytes:
    return json.dumps(
        {"id": event_id, "data": {"alert_id": "abc", "state": state, "road_segment_id": "ROAD_001"}}
    ).encode()


# -------------------------------------------------------------------------------------- format
def test_a_message_is_encoded_as_event_id_and_data():
    chunk = Message(ALERT_EVENT, {"state": "CREATED", "texte": "é"}, "id-1").encode()
    assert lines(chunk) == [
        "event: alert.state_changed",
        "id: id-1",
        'data: {"state":"CREATED","texte":"é"}',
    ]
    assert chunk.endswith(b"\n\n")  # la ligne vide termine le message


def test_a_message_without_id_has_no_id_line():
    assert "id:" not in Message("heartbeat", {"time": "t"}).encode().decode()


# ---------------------------------------------------------------------------------------- flux
def test_the_stream_greets_then_delivers_published_events_in_order():
    async def scenario():
        hub = EventHub()
        reader = stream(hub, None, heartbeat_s=5)
        greeting = await anext(reader)
        assert hub.clients == 1  # inscrit avant le premier octet : rien ne peut lui échapper
        hub.on_bus_message(bus_message("CREATED", "e1"))
        hub.on_bus_message(bus_message("NOTIFIED", "e2"))
        first, second = await anext(reader), await anext(reader)
        await reader.aclose()
        return greeting, first, second, hub.clients

    greeting, first, second, clients = run(scenario())
    assert b"retry: 3000" in greeting and ": connecté".encode() in greeting
    assert lines(first)[:2] == ["event: alert.state_changed", "id: e1"]
    assert json.loads(lines(second)[2][len("data: ") :])["state"] == "NOTIFIED"
    assert clients == 0  # la déconnexion désinscrit le client


def test_every_client_receives_every_event():
    async def scenario():
        hub = EventHub()
        a, b = stream(hub, None, 5), stream(hub, None, 5)
        await anext(a), await anext(b)
        assert hub.publish(Message(ALERT_EVENT, {"n": 1})) == 2
        got = (await anext(a)), (await anext(b))
        await a.aclose(), await b.aclose()
        return got

    one, two = run(scenario())
    assert one == two


def test_events_published_from_another_thread_reach_the_client():
    """Le lecteur Kafka tourne dans un fil, les clients dans la boucle d'événements."""

    async def scenario():
        hub = EventHub()
        reader = stream(hub, None, 5)
        await anext(reader)
        thread = threading.Thread(target=hub.on_bus_message, args=(bus_message(),))
        thread.start()
        chunk = await asyncio.wait_for(anext(reader), 5)
        thread.join()
        await reader.aclose()
        return chunk

    assert b"alert.state_changed" in run(scenario())


def test_the_type_filter_only_lets_the_wanted_events_through():
    async def scenario():
        hub = EventHub()
        reader = stream(hub, frozenset({"signal.status"}), heartbeat_s=0.05)
        await anext(reader)
        hub.on_bus_message(bus_message())  # alert.state_changed : filtré
        chunk = await anext(reader)  # donc le prochain message est un battement de cœur
        await reader.aclose()
        return chunk

    assert lines(run(scenario()))[0] == "event: heartbeat"


def test_a_heartbeat_is_sent_when_nothing_happens():
    async def scenario():
        reader = stream(EventHub(), None, heartbeat_s=0.05)
        await anext(reader)
        chunk = await anext(reader)
        await reader.aclose()
        return chunk

    chunk = run(scenario())
    assert lines(chunk)[0] == "event: heartbeat"
    assert json.loads(lines(chunk)[1][len("data: ") :])["time"].endswith("Z")


def test_a_client_too_slow_is_cut_instead_of_growing_memory_without_bound():
    async def scenario():
        hub = EventHub(queue_size=2)
        reader = stream(hub, None, 5)
        await anext(reader)
        for index in range(5):  # le client ne lit pas
            hub.publish(Message(ALERT_EVENT, {"n": index}))
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        registered_after_cut = hub.clients  # avant que le flux ne soit lu jusqu'au bout
        remaining = [chunk async for chunk in reader]  # le flux se termine de lui-même
        return remaining, registered_after_cut, hub.clients

    remaining, registered_after_cut, clients = run(scenario())
    assert remaining == [] and registered_after_cut == 0 and clients == 0


def test_a_closed_loop_does_not_break_publication():
    hub = EventHub()

    async def subscribe():
        return hub.subscribe(None)

    subscription = run(subscribe())  # la boucle est fermée une fois `run` terminé
    assert hub.publish(Message(ALERT_EVENT, {})) == 1
    assert hub.clients == 0 and subscription.queue.empty()


def test_unsubscribing_twice_is_harmless():
    async def scenario():
        hub = EventHub()
        subscription = hub.subscribe(None)
        subscription.close()
        subscription.close()
        return hub.clients

    assert run(scenario()) == 0


@pytest.mark.parametrize("raw", [b"pas du json", b'{"id": "x"}', b'{"data": {}}', b"[1]", b"null"])
def test_a_garbled_bus_message_is_ignored(raw, caplog):
    hub = EventHub()
    caplog.set_level("WARNING")
    assert hub.on_bus_message(raw) is None
    assert "illisible" in caplog.text


# ------------------------------------------------------------------------------------- la route
SETTINGS = Settings(sse_heartbeat_s=5, jwt_secret=secrets.token_urlsafe(32))
VIEWER = Claims("user-1", Role.VIEWER)


def test_the_route_answers_an_event_stream_that_must_not_be_buffered():
    async def scenario():
        hub = EventHub()
        response = await stream_events(VIEWER, hub, SETTINGS, None)
        first = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return response, first

    response, first = run(scenario())
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert ": connecté".encode() in first


def test_the_route_accepts_known_types_separated_by_commas():
    async def scenario():
        hub = EventHub()
        response = await stream_events(VIEWER, hub, SETTINGS, "alert.state_changed, signal.status")
        await anext(response.body_iterator)
        hub.on_bus_message(bus_message())
        chunk = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return chunk

    assert b"alert.state_changed" in run(scenario())


def test_the_route_refuses_an_unknown_type():
    with pytest.raises(ProblemError) as error:
        run(stream_events(VIEWER, EventHub(), SETTINGS, "alert.state_changed,inconnu"))
    assert error.value.errors == [{"field": "query.types", "message": "Type inconnu : inconnu."}]


def test_empty_types_mean_every_type():
    async def scenario():
        hub = EventHub()
        response = await stream_events(VIEWER, hub, SETTINGS, " , ")
        await anext(response.body_iterator)
        hub.on_bus_message(bus_message())
        chunk = await anext(response.body_iterator)
        await response.body_iterator.aclose()
        return chunk

    assert b"alert.state_changed" in run(scenario())
