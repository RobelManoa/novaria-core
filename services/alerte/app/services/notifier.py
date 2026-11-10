"""Notification simulée : remettre chaque alerte CREATED au canal, puis la passer à NOTIFIED.

Le canal est un courriel ou un webhook simulé (`adapters/channels.py`) : aucune donnée personnelle
n'y circule en v1 (RG-23). La remise est **au moins une fois** : si le service s'arrête entre la
remise et l'écriture de NOTIFIED, l'alerte est remise une seconde fois au redémarrage ; un
destinataire retrouve le doublon à son `alert_id`.

Une remise qui échoue laisse l'alerte à CREATED : elle est retentée après `retry_after_s`, sans
bloquer les autres.
"""

import logging
import time
from collections.abc import Callable

from app.services.alerts import AlertService
from app.services.ports import AlertStore, NotificationChannel, NotificationFailed

logger = logging.getLogger("app.notifier")


class Notifier:
    def __init__(
        self,
        store: AlertStore,
        service: AlertService,
        channel: NotificationChannel,
        *,
        retry_after_s: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._service = service
        self._channel = channel
        self._retry_after_s = retry_after_s
        self._monotonic = monotonic
        self._not_before: dict[str, float] = {}

    def run_once(self, limit: int = 50) -> int:
        """Notifie les alertes en attente ; rend le nombre de celles qui sont passées à NOTIFIED."""
        now = self._monotonic()
        done = 0
        for alert in self._store.pending_notification(limit):
            if self._not_before.get(alert.alert_id, 0.0) > now:
                continue
            try:
                self._channel.send(alert)
            except NotificationFailed as error:
                self._not_before[alert.alert_id] = now + self._retry_after_s
                logger.warning(
                    "remise impossible, nouvel essai plus tard",
                    extra={"fields": {"alert_id": alert.alert_id, "error": type(error).__name__,
                                      "counter": "notification_failures"}},
                )  # fmt: skip
                continue
            self._not_before.pop(alert.alert_id, None)
            if self._service.mark_notified(alert.alert_id) is not None:
                done += 1
        return done
