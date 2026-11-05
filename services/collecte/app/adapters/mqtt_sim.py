"""Réception « MQTT simulé » des mesures (MS-08, ADR-008 : « HTTP ou MQTT simulé »).

MQTT (Message Queuing Telemetry Transport) est le protocole habituel des capteurs. Le projet n'a pas
de courtier MQTT (aucun conteneur, aucun paquet) : l'entrée est **simulée**. Cet adaptateur reçoit
ce qu'un abonné MQTT recevrait, un *sujet* (`topic`) et une *charge* (`payload`, des octets), et le
confie au même `IngestionService` que le point d'entrée HTTP. Il prouve que la logique de collecte
ne dépend pas du transport : mêmes règles de validation, mêmes issues, même idempotence.

- Abonnement à `novaria/iot/measurements/+` : `topic_matches` : `+` remplace exactement un niveau,
  `#` termine le filtre
- Un message livré hors abonnement n'est pas reçu : `on_message` rend `None` : rien n'est lu, rien
  n'est écrit
- QoS 1 : au moins une livraison, donc des doublons possibles : la redélivrance d'un message est un
  doublon, ignoré (idempotence par `id`)
- Pas d'accusé tant que le traitement n'a pas réussi : `PublishFailed` et `StoreFailed` remontent à
  l'appelant, qui ne doit pas acquitter

Le sujet ne sert qu'à l'abonnement : l'identité du capteur est celle du message, validée comme pour
HTTP.
"""

from app.services.ingestion import IngestionService, Receipt

DEFAULT_FILTER = "novaria/iot/measurements/+"
TOPIC_PREFIX = "novaria/iot/measurements/"


def topic_matches(topic_filter: str, topic: str) -> bool:
    """Filtre d'abonnement MQTT : `+` pour un niveau exactement, `#` pour le reste (en dernier)."""
    wanted = topic_filter.split("/")
    actual = topic.split("/")
    for index, level in enumerate(wanted):
        if level == "#":
            return index == len(wanted) - 1
        if index >= len(actual) or (level != "+" and level != actual[index]):
            return False
    return len(actual) == len(wanted)


class SimulatedMqttAdapter:
    def __init__(self, service: IngestionService, topic_filter: str = DEFAULT_FILTER) -> None:
        self._service = service
        self._filter = topic_filter

    def on_message(
        self, topic: str, payload: bytes, *, correlation_id: str | None = None
    ) -> Receipt | None:
        """Traite un message livré à l'abonné ; `None` si le sujet n'est pas abonné."""
        if not topic_matches(self._filter, topic):
            return None
        return self._service.receive(payload, correlation_id=correlation_id)
