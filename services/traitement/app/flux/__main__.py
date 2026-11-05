"""Point d'entrée du service de flux : `python -m app.flux`."""

import logging
import signal
import sys
import threading

from app.core.logs import configure_logging

from .adapters.kafka_io import KafkaPublisher, KafkaSource
from .adapters.mongo_store import MongoStore
from .adapters.warehouse import Warehouse
from .processor import Processor
from .runner import run
from .settings import FluxSettings

logger = logging.getLogger("app.flux")


def main() -> int:
    settings = FluxSettings()
    configure_logging("traitement-flux", settings.log_level)
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())

    warehouse = Warehouse(settings.postgres_url.get_secret_value())
    mongo = MongoStore(settings.mongo_url.get_secret_value())
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers)
    source = None
    try:
        referential = warehouse.load_referential()
        if not referential.sensors:
            logger.error("référentiel vide : aucun capteur dans dwh.dim_sensor")
            return 1
        logger.info(
            "référentiel chargé",
            extra={
                "fields": {
                    "sensors": len(referential.sensors),
                    "segments": len(referential.segments),
                    "replay": settings.flux_replay,
                }
            },
        )
        processor = Processor(
            referential, publisher, mongo, warehouse, mongo, replay=settings.flux_replay
        )
        source = KafkaSource(
            settings.kafka_bootstrap_servers,
            settings.topic_raw,
            settings.consumer_group,
            max_records=settings.poll_max_records,
        )
        handled = run(
            processor,
            source,
            stop,
            poll_timeout_ms=settings.poll_timeout_ms,
            heartbeat_file=settings.heartbeat_file,
        )
        logger.info("arrêt demandé", extra={"fields": {"handled": handled}})
        return 0
    except Exception as error:  # noqa: BLE001 - toute panne arrête le service sans valider d'offset
        logger.error("arrêt sur panne", extra={"fields": {"error": type(error).__name__}})
        return 1
    finally:
        if source is not None:
            source.close()
        publisher.close()
        mongo.close()
        warehouse.close()


if __name__ == "__main__":
    sys.exit(main())
