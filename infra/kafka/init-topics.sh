#!/bin/sh
# Crée les 6 sujets du bus (ADR-009) s'ils manquent. Lancé une fois par le service « kafka-init » de
# docker-compose.yml, avant les services : la création automatique est désactivée côté broker.
# Même liste que KAFKA_TOPICS de scripts/dev/dev.py (3 partitions, réplication 1 en local) ;
# scripts/dev/test_compose.py vérifie que les deux restent identiques.
set -eu

KAFKA="/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092"

creer() {
  nom="$1"
  shift
  $KAFKA --create --if-not-exists --topic "$nom" --partitions 3 --replication-factor 1 "$@"
  echo "sujet $nom : prêt"
}

creer iot.raw --config retention.ms=604800000
creer traffic.indicators
creer traffic.recommendations
creer alerts.events
creer signal.status
creer errors.dlq
