"""Ports : ce dont le service de réponse a besoin du monde extérieur (ADR-010).

Le domaine et les services ne connaissent ni Kafka ni MongoDB : ils parlent à ces interfaces.
"""

from typing import Any, Protocol


class PublishFailed(Exception):
    """Le bus n'a pas accusé réception : l'événement reste en attente et sera retenté."""


class AuditFailed(Exception):
    """Le journal d'audit n'a pas pu écrire (base indisponible ou entrée refusée)."""


class CommandNotRecorded(Exception):
    """Commande non appliquée faute d'avoir pu la journaliser : le journal passe avant l'effet."""


class RateLimited(Exception):
    """Trop de commandes d'un même opérateur sur la dernière minute."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(retry_after_s)
        self.retry_after_s = retry_after_s


class UnknownIntersection(Exception):
    """Ce carrefour n'a pas de feux dans ce service."""


class Publisher(Protocol):
    def publish(self, topic: str, key: str | None, value: bytes) -> None: ...

    def flush(self) -> None: ...


class AuditLog(Protocol):
    def record(self, entry: dict[str, Any]) -> None:
        """Écrit une entrée ; lève `AuditFailed` si elle n'est pas écrite."""

    def history(
        self, intersection_id: str, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Les commandes d'un carrefour, la plus récente d'abord ; lève `AuditFailed`."""
