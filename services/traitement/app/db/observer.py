"""Construit l'observateur d'audit à partir de la configuration (BE-05), un pour le service."""

import logging
from functools import lru_cache

from app.core.config import get_settings
from app.repositories.audit import open_collections
from app.services.audit import Observer, RecordingObserver

logger = logging.getLogger("app.audit")


def log_failure(message: str, fields: dict) -> None:
    logger.error(message, extra={"fields": fields})


@lru_cache
def get_observer() -> Observer | None:
    """`None` si `AUDIT_MONGO_URL` est absente : rien n'est journalisé (avertissement unique)."""
    settings = get_settings()
    if settings.audit_mongo_url is None:
        logger.warning("AUDIT_MONGO_URL absente : aucun audit ni compteur d'usage n'est écrit")
        return None
    audit, usage = open_collections(settings.audit_mongo_url.get_secret_value())
    return RecordingObserver(audit, usage, service=settings.service_name, log=log_failure)
