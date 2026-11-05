"""Point d'entrée du pipeline d'écriture : `python -m app.pipeline`."""

import logging
import signal
import sys
import threading

from app.core.logs import configure_logging
from app.flux.adapters.kafka_io import KafkaPublisher, KafkaSource
from app.flux.adapters.mongo_store import MongoStore
from app.flux.runner import run

from .adapters.postgres import WarehouseWriter
from .processor import Pipeline
from .recommender import Recommender
from .settings import PipelineSettings

logger = logging.getLogger("app.pipeline")


def main() -> int:
    settings = PipelineSettings()
    configure_logging("traitement-pipeline", settings.log_level)
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())

    writer = WarehouseWriter(settings.postgres_url.get_secret_value())
    mongo = MongoStore(settings.mongo_url.get_secret_value())
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers)
    source = None
    try:
        reference = writer.load_plan_reference()
        if not reference.segments:
            logger.error("réseau vide : aucun tronçon dans dwh.dim_road_segment")
            return 1
        logger.info("réseau chargé", extra={"fields": {"segments": len(reference.segments)}})
        pipeline = Pipeline(writer, Recommender(reference), publisher, mongo, mongo)
        source = KafkaSource(
            settings.kafka_bootstrap_servers,
            settings.topic_indicators,
            settings.consumer_group,
            max_records=settings.poll_max_records,
        )
        handled = run(
            pipeline,
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
        writer.close()


if __name__ == "__main__":
    sys.exit(main())
