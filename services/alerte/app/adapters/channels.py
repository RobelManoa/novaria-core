"""Canaux de notification simulés : le journal, ou un webhook (MS-11).

Aucune donnée personnelle en v1 (RG-23) : le message dit quelle alerte, où, depuis quand, jamais
« qui » doit la recevoir. Le canal « courriel » est ce même message écrit dans le journal, avec le
nom de canal en champ : il n'y a pas de serveur de messagerie à joindre.

Le webhook est un `POST` JSON vers une adresse configurée (`WEBHOOK_URL`). L'adresse peut porter un
secret (jeton dans le chemin) : elle n'est jamais journalisée, seul le type de l'échec l'est.
"""

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from app.domain.model import Alert, utc_stamp
from app.services.ports import NotificationFailed

logger = logging.getLogger("app.notification")


def message_of(alert: Alert) -> dict:
    """Ce qui est remis : de quoi retrouver l'alerte, aucun nom ni adresse de personne."""
    return {
        "alert_id": alert.alert_id,
        "kind": alert.kind.value,
        "severity": alert.severity.value,
        "state": alert.state.value,
        "road_segment_id": alert.road_segment_id,
        "intersection_id": alert.intersection_id,
        "opened_at": utc_stamp(alert.opened_at),
        "cause": alert.cause,
        "source_type": alert.provenance.source_type,
    }


class LogChannel:
    name = "log"

    def send(self, alert: Alert) -> None:
        logger.info(
            "notification simulée",
            extra={"fields": {"channel": self.name, "counter": "notifications",
                              **message_of(alert)}},
        )  # fmt: skip


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, *, timeout_s: float = 3.0) -> None:
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("WEBHOOK_URL doit commencer par http:// ou https://")
        self._url = url
        self._timeout_s = timeout_s

    def send(self, alert: Alert) -> None:
        request = urllib.request.Request(  # noqa: S310 - schéma contrôlé dans `__init__`
            self._url,
            data=json.dumps(message_of(alert)).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "novaria-alerte"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:  # noqa: S310
                status = response.status
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise NotificationFailed(type(error).__name__) from error
        if not 200 <= status < 300:
            raise NotificationFailed(f"HTTP {status}")
        logger.info(
            "notification remise",
            extra={"fields": {"channel": self.name, "alert_id": alert.alert_id,
                              "counter": "notifications"}},
        )  # fmt: skip
