"""Le travailleur, l'API et un client SSE réels, chronométrés (tests d'intégration, MS-11).

Le travailleur et l'API sont ceux du service, branchés sur le vrai Kafka et le vrai PostgreSQL ;
seuls quelques crochets de mesure (instants du traitement d'un indicateur et de la publication d'un
événement) sont ajoutés par héritage. Tous les instants viennent de la même horloge monotone
(`time.perf_counter`) : les écarts sont des durées réelles, sans dérive entre machines.
"""

import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field

import httpx
import jwt
import uvicorn

from app.adapters.channels import LogChannel
from app.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.adapters.postgres_store import PostgresAlertStore
from app.core.config import TOPIC_INDICATORS
from app.domain.rules import RuleEngine
from app.services.alerts import AlertService
from app.services.ingestion import IndicatorHandler
from app.services.notifier import Notifier
from app.services.ports import NotificationChannel
from app.services.relay import OutboxRelay
from app.worker.runner import RulesCache, run
from tests.integration import stack


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Timeline:
    """Instants (secondes monotones) des étapes d'un indicateur ou d'un événement."""

    consumed: dict[str, float] = field(default_factory=dict)  # indicateur reçu par le travailleur
    handled: dict[str, float] = field(default_factory=dict)  # alertes écrites en base (validées)
    published: dict[str, float] = field(default_factory=dict)  # événement accusé par Kafka


class TimedHandler(IndicatorHandler):
    def __init__(self, *args, timeline: Timeline, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeline = timeline

    def handle(self, raw: bytes, key: bytes | None = None):
        identifier = json.loads(raw).get("id", "?")
        self._timeline.consumed[identifier] = time.perf_counter()
        result = super().handle(raw, key)
        self._timeline.handled[identifier] = time.perf_counter()
        return result


class TimedRelay(OutboxRelay):
    def __init__(self, *args, timeline: Timeline, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._timeline = timeline

    def _publish(self, row) -> None:
        super()._publish(row)  # accusé du broker obtenu
        self._timeline.published[row.event_id] = time.perf_counter()


class TimedSource(KafkaSource):
    """Dit quand le groupe a ses partitions : avant, un message publié pourrait être manqué
    (un groupe neuf lit depuis la fin, et la fin n'est fixée qu'à l'affectation)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.assigned = threading.Event()

    def poll(self, timeout_ms: int = 1000):
        records = super().poll(timeout_ms)
        partitions = self._consumer.assignment()
        if partitions and not self.assigned.is_set():
            for partition in partitions:
                self._consumer.position(partition)  # « latest » est résolu ici : la fin est fixée
            self.assigned.set()
        return records


class Worker:
    """`python -m app.worker` dans un fil : mêmes pièces, mêmes réglages de boucle.

    `from_start` : un groupe neuf relit tout le sujet (rejeu) ; sinon il part de la fin, et les
    indicateurs des essais précédents ne sont pas retraités.
    """

    def __init__(
        self,
        group_id: str,
        *,
        channel: NotificationChannel | None = None,
        rules_ttl_s: float = 0.2,
        from_start: bool = False,
    ) -> None:
        self.timeline = Timeline()
        self.store = PostgresAlertStore(stack.PG_URL)
        self.publisher = KafkaPublisher(stack.BOOTSTRAP, timeout_s=15)
        service = AlertService(self.store)
        rules = RulesCache(self.store, rules_ttl_s)
        self.handler = TimedHandler(
            service, RuleEngine(), rules.get, self.publisher, timeline=self.timeline
        )
        self.notifier = Notifier(self.store, service, channel or LogChannel())
        self.relay = TimedRelay(self.store, self.publisher, timeline=self.timeline)
        self.source = TimedSource(
            stack.BOOTSTRAP, TOPIC_INDICATORS, group_id,
            auto_offset_reset="earliest" if from_start else "latest",
        )  # fmt: skip
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.closed = False
        self._thread = threading.Thread(target=self._run, name="worker", daemon=True)

    def _run(self) -> None:
        try:
            run(
                self.handler, self.source, self.relay, self.notifier, self.stop, poll_timeout_ms=100
            )
        except BaseException as error:  # noqa: BLE001 - remonté par `close`
            self.error = error

    def diagnose(self) -> str:
        return (
            f"fil vivant : {self._thread.is_alive()} ; erreur : {self.error!r} ; "
            f"indicateurs reçus : {len(self.timeline.consumed)} ; événements publiés : "
            f"{sorted(self.timeline.published)}"
        )

    def start(self) -> "Worker":
        self._thread.start()
        stack.wait_until(
            self.source.assigned.is_set, 90, why=self.diagnose
        )  # affectation : 1 à 5 s
        return self

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        self._thread.join(timeout=30)
        self.source.close()
        self.publisher.close()
        self.store.close()
        if self.error is not None:
            raise self.error


class Api:
    """L'API du service sur un vrai port, avec son lecteur de `alerts.events` (flux SSE)."""

    def __init__(self, monkeypatch, *, heartbeat_s: float = 30.0) -> None:
        from app.api import deps
        from app.core.config import get_settings

        self.secret = secrets.token_urlsafe(48)  # généré à l'exécution
        self.bus_seen: list[str] = []
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        monkeypatch.setenv("POSTGRES_URL", stack.PG_URL)
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", stack.BOOTSTRAP)
        monkeypatch.setenv("JWT_SECRET", self.secret)
        monkeypatch.setenv("SSE_HEARTBEAT_S", str(heartbeat_s))
        get_settings.cache_clear()
        deps.close_components()
        from app.main import app

        self._deps = deps
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self.server.run, name="api", daemon=True)

    def start(self) -> "Api":
        self._thread.start()
        stack.wait_until(lambda: self.server.started, 30)
        components = self._deps.get_components()
        assert components.reader is not None
        stack.wait_until(components.reader.ready.is_set, 60)  # lecteur positionné sur la fin
        forward = components.reader._on_message

        def spy(raw: bytes) -> None:
            self.bus_seen.append(json.loads(raw)["id"])  # ce que le lecteur de alerts.events a lu
            forward(raw)

        components.reader._on_message = spy
        return self

    def reader_alive(self) -> bool:
        reader = self._deps.get_components().reader
        return bool(reader and reader._thread and reader._thread.is_alive())

    def close(self) -> None:
        # `force_exit` : un flux SSE ouvert retiendrait l'arrêt, qui s'achèverait trop tard et
        # fermerait les composants (globaux au processus) du serveur suivant. En exploitation, un
        # serveur par processus : ce cas n'existe pas.
        self.server.should_exit = True
        self.server.force_exit = True
        self._thread.join(timeout=30)
        assert not self._thread.is_alive(), "le serveur d'essai ne s'est pas arrêté"
        self._deps.close_components()

    def token(self, role: str = "viewer", sub: str = "user-it") -> str:
        now = int(time.time())
        payload = {"sub": sub, "role": role, "iat": now, "exp": now + 900}
        return jwt.encode(payload, self.secret, algorithm="HS256")

    def headers(self, role: str = "viewer", sub: str = "user-it") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(role, sub)}"}

    def get(self, path: str, role: str = "viewer", **params):
        return httpx.get(self.url + path, headers=self.headers(role), params=params, timeout=15)

    def post(self, path: str, role: str = "operator", sub: str = "user-it", **kwargs):
        return httpx.post(self.url + path, headers=self.headers(role, sub), timeout=15, **kwargs)


@dataclass(frozen=True)
class Received:
    at: float
    event: str
    event_id: str | None
    data: dict


class SseClient:
    """Un client du flux : lit les messages dans un fil et note l'instant de chacun."""

    def __init__(self, api: Api, role: str = "viewer", types: str | None = None) -> None:
        self.received: list[Received] = []
        self.connected = threading.Event()
        self.status: int | None = None
        self._api = api
        self._stop = threading.Event()
        self._params = {"types": types} if types else {}
        self._role = role
        self._thread = threading.Thread(target=self._run, name="sse-client", daemon=True)

    def start(self) -> "SseClient":
        self._thread.start()
        stack.wait_until(self.connected.is_set, 30)
        return self

    def _run(self) -> None:
        headers = self._api.headers(self._role)
        try:
            with httpx.stream(
                "GET", self._api.url + "/api/v1/events/stream", headers=headers,
                params=self._params, timeout=httpx.Timeout(30, read=None),
            ) as response:  # fmt: skip
                self.status = response.status_code
                event = event_id = None
                for line in response.iter_lines():
                    if self._stop.is_set():
                        return
                    if line.startswith(": connecté"):
                        self.connected.set()
                    elif line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("id: "):
                        event_id = line[4:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        self.received.append(
                            Received(time.perf_counter(), event or "", event_id, data)
                        )
                        event = event_id = None
        except httpx.HTTPError:
            pass
        finally:
            self.connected.set()  # un refus (401) ne doit pas bloquer l'attente

    def close(self) -> None:
        self._stop.set()

    def states_of(self, alert_id: str) -> list[str]:
        return [r.data["state"] for r in self.received if r.data.get("alert_id") == alert_id]

    def first(self, alert_id: str, state: str) -> Received | None:
        return next(
            (
                r
                for r in self.received
                if r.data.get("alert_id") == alert_id and r.data["state"] == state
            ),
            None,
        )
