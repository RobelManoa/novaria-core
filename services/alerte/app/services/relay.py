"""Relais de la boîte d'envoi : publier sur Kafka les événements écrits avec les changements d'état.

Motif « outbox » (ADR-009). L'événement a été écrit dans la même transaction que le changement
d'état ; le relais le publie ensuite, **dans l'ordre**, et ne le marque publié qu'après l'accusé du
broker. Si Kafka est en panne, les événements attendent dans la base : rien n'est perdu, et rien ne
bloque la création des alertes. Si le service s'arrête entre l'accusé et le marquage, l'événement
repart une seconde fois : son `id` est stable (`alerte-<alert_id>-<état>`), le consommateur
le reconnaît.

Un seul relais doit tourner (celui du travailleur) : deux relais se partageraient les lignes et
l'ordre de publication ne serait plus garanti.
"""

import logging

from app.services.events import dumps
from app.services.ports import AlertStore, EventPublisher, OutboxRow

logger = logging.getLogger("app.relay")


class OutboxRelay:
    def __init__(self, store: AlertStore, publisher: EventPublisher, *, batch: int = 100) -> None:
        self._store = store
        self._publisher = publisher
        self._batch = batch

    def _publish(self, row: OutboxRow) -> None:
        self._publisher.publish(row.topic, row.event_key, dumps(row.payload))
        self._publisher.flush()  # l'accusé du broker avant de marquer la ligne publiée

    def run_once(self) -> int:
        """Publie un lot ; rend le nombre d'événements publiés. Lève `PublishFailed`."""
        published = self._store.relay_outbox(self._publish, limit=self._batch)
        if published:
            logger.info(
                "événements publiés",
                extra={"fields": {"count": published, "counter": "events_published"}},
            )
        return published
