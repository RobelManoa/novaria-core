"""Les trois fils du service : phases, envoi des événements, lecture des recommandations (MS-12).

Ils tournent dans le **même processus** que l'API, parce que l'état des feux est en mémoire et
qu'une commande manuelle doit le modifier. Chacun a une seule tâche et ne dépend pas des autres :

| Fil | Tâche | Si Kafka tombe |
|---|---|---|
| `signal-ticker` | phases, perte des recommandations | continue : il ramène au plan fixe |
| `signal-dispatch` | publie la file d'envoi, attend l'accusé | retente ; les événements attendent |
| `signal-consumer` | lit, valide les offsets après l'envoi | se reconnecte |

Aucun des trois ne meurt sur une exception : elle est journalisée et le tour suivant reprend.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.services.ingestion import RecommendationHandler
from app.services.outbox import Outbox
from app.services.ports import AuditFailed, AuditLog, Publisher, PublishFailed
from app.services.signals import SignalService

logger = logging.getLogger("app.runtime")

AUDIT_PAUSE_S = 10.0  # après un échec d'écriture du journal, on n'insiste pas pendant ce délai
BATCH = 100


class Dispatcher:
    """Vide la file d'envoi vers le bus, puis écrit les entrées d'audit des décisions parties."""

    def __init__(
        self,
        outbox: Outbox,
        publisher: Publisher,
        audit: AuditLog,
        service: SignalService,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._audit = audit
        self._service = service
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._audit_paused_until = 0.0

    def drain(self) -> bool:
        """Vrai si tout ce qui attendait est parti et accusé ; faux si le bus ne répond pas."""
        with self._lock:
            while True:
                items = self._outbox.take(BATCH)
                if not items:
                    return True
                try:
                    for item in items:
                        self._publisher.publish(item.topic, item.key, item.value)
                    self._publisher.flush()
                except PublishFailed as error:
                    self._outbox.give_back(items)
                    logger.warning(
                        "événements en attente : le bus ne répond pas",
                        extra={"fields": {"error": str(error), "pending": len(self._outbox)}},
                    )
                    return False
                for item in items:
                    if item.audit is not None:
                        self._write_audit(item.audit)

    def _write_audit(self, entry: dict[str, Any]) -> None:
        if self._monotonic() < self._audit_paused_until:
            self._service.audit_lost += 1
            return
        try:
            self._audit.record(entry)
        except AuditFailed:
            self._audit_paused_until = self._monotonic() + AUDIT_PAUSE_S
            self._service.audit_lost += 1


class Runtime:
    def __init__(
        self,
        service: SignalService,
        dispatcher: Dispatcher,
        handler: RecommendationHandler | None,
        source_factory: Callable[[], Any] | None,
        *,
        tick_interval_s: float = 0.5,
        retry_s: float = 2.0,
        poll_ms: int = 500,
    ) -> None:
        self._service = service
        self._dispatcher = dispatcher
        self._handler = handler
        self._source_factory = source_factory
        self._tick_interval_s = tick_interval_s
        self._retry_s = retry_s
        self._poll_ms = poll_ms
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def alive(self) -> bool:
        return bool(self._threads) and all(t.is_alive() for t in self._threads)

    def start(self) -> None:
        self._service.start()
        targets = [("signal-ticker", self._tick_loop), ("signal-dispatch", self._dispatch_loop)]
        if self._handler is not None and self._source_factory is not None:
            targets.append(("signal-consumer", self._consume_loop))
        for name, target in targets:
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, *, final_drain_s: float = 5.0) -> None:
        """Arrêt volontaire : plan fixe pour tous, dit sur le bus avant de partir."""
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._service.stop()
        deadline = time.monotonic() + final_drain_s
        while not self._dispatcher.drain() and time.monotonic() < deadline:
            time.sleep(0.2)

    # ------------------------------------------------------------------ les fils
    def _tick_loop(self) -> None:
        while not self._stop.wait(self._tick_interval_s):
            try:
                self._service.tick()
            except Exception:
                logger.exception("tour du contrôleur interrompu, le suivant reprend")

    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                sent = self._dispatcher.drain()
            except Exception:
                logger.exception("envoi interrompu, le suivant reprend")
                sent = False
            self._stop.wait(0.05 if sent else self._retry_s)

    def _consume_loop(self) -> None:
        while not self._stop.is_set():
            try:
                source = self._source_factory()  # type: ignore[misc]
            except Exception as error:
                logger.error(
                    "lecture de traffic.recommendations impossible, nouvel essai",
                    extra={"fields": {"error": type(error).__name__}},
                )
                self._stop.wait(self._retry_s)
                continue
            try:
                self._read(source)
            except Exception as error:
                logger.error(
                    "lecture de traffic.recommendations interrompue, nouvel essai",
                    extra={"fields": {"error": type(error).__name__}},
                )
            finally:
                source.close()
            self._stop.wait(self._retry_s)

    def _read(self, source: Any) -> None:
        offsets: dict[int, int] = {}  # prochain offset à valider, par partition
        while not self._stop.is_set():
            for record in source.poll(self._poll_ms):
                self._handler.handle(record.value, record.key)  # type: ignore[union-attr]
                offsets[record.partition] = max(offsets.get(record.partition, 0), record.offset + 1)
            if offsets and self._dispatcher.drain():
                source.commit(offsets)  # tout ce qui a été décidé est parti et accusé
                offsets = {}
