"""Point d'entrée du travailleur : `python -m app.worker` (MS-11).

Lit `traffic.indicators`, évalue les règles, écrit les alertes, publie `alerts.events` (boîte
d'envoi) et remet les notifications simulées. L'API (`uvicorn app.main:app`) est un autre processus
de la même image.
"""

import logging
import signal
import sys
import threading

from app.adapters.channels import LogChannel, WebhookChannel
from app.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.adapters.postgres_store import PostgresAlertStore
from app.core.config import TOPIC_INDICATORS, Settings, get_settings
from app.core.logs import configure_logging
from app.core.redaction import install_redaction
from app.domain.rules import RuleEngine
from app.services.alerts import AlertService
from app.services.ingestion import IndicatorHandler
from app.services.notifier import Notifier
from app.services.ports import NotificationChannel, PublishFailed, StoreFailed
from app.services.relay import OutboxRelay
from app.worker.runner import RulesCache, run

logger = logging.getLogger("app.worker")


def build_channel(settings: Settings) -> NotificationChannel:
    if settings.notification_channel == "webhook":
        if settings.webhook_url is None:
            raise ValueError("NOTIFICATION_CHANNEL=webhook demande WEBHOOK_URL")
        return WebhookChannel(
            settings.webhook_url.get_secret_value(), timeout_s=settings.notification_timeout_s
        )
    return LogChannel()


def main() -> int:
    settings = get_settings()
    configure_logging("alerte-worker", settings.log_level)
    install_redaction()
    if settings.dsn is None or not settings.kafka_bootstrap_servers:
        logger.error("POSTGRES_URL et KAFKA_BOOTSTRAP_SERVERS sont obligatoires")
        return 1
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())

    store = PostgresAlertStore(
        settings.dsn, max_size=settings.postgres_pool_max, timeout_s=settings.postgres_timeout_s
    )
    publisher = KafkaPublisher(
        settings.kafka_bootstrap_servers,
        timeout_s=settings.kafka_publish_timeout_s,
        client_id="novaria-alerte",
    )
    source = None
    try:
        service = AlertService(store)
        rules = RulesCache(store, settings.rules_ttl_s)
        handler = IndicatorHandler(service, RuleEngine(), rules.get, publisher)
        notifier = Notifier(store, service, build_channel(settings))
        relay = OutboxRelay(store, publisher, batch=settings.outbox_batch)
        source = KafkaSource(
            settings.kafka_bootstrap_servers,
            TOPIC_INDICATORS,
            settings.kafka_group_id,
            client_id="novaria-alerte",
        )
        logger.info("travailleur prêt", extra={"fields": {"topic": TOPIC_INDICATORS}})
        handled = run(
            handler,
            source,
            relay,
            notifier,
            stop,
            poll_timeout_ms=settings.worker_poll_ms,
            heartbeat_file=settings.heartbeat_file or None,
        )
        logger.info("arrêt demandé", extra={"fields": {"handled": handled}})
        return 0
    except Exception as error:  # noqa: BLE001 - toute panne arrête le service, offset non validé
        # Détail dit pour nos seules exceptions (nom de l'erreur de la base ou du bus), jamais
        # pour un message extérieur : il pourrait reprendre une adresse de connexion.
        detail = str(error) if isinstance(error, StoreFailed | PublishFailed) else ""
        fields = {"error": type(error).__name__, "detail": detail}
        logger.error("arrêt sur panne", extra={"fields": fields})
        return 1
    finally:
        if source is not None:
            source.close()
        publisher.close()
        store.close()


if __name__ == "__main__":
    sys.exit(main())
