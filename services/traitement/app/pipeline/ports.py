"""Ce que le pipeline demande à la base : écrire des indicateurs dans l'entrepôt."""

from dataclasses import dataclass
from typing import Protocol

from .facts import IndicatorFact


@dataclass(frozen=True)
class FactFailure:
    """Un indicateur que l'entrepôt n'a pas pu écrire, avec un motif du contrat des rejets."""

    fact: IndicatorFact
    reason_code: str  # SEMANTIC_VIOLATION ou PROCESSING_FAILED
    reason: str


class FactStore(Protocol):
    def load(self, facts: list[IndicatorFact]) -> list[FactFailure]:
        """Écrit les faits (et leur exécution) en une transaction ; rend ceux refusés.

        Idempotent : un fait déjà présent est mis à jour, jamais dupliqué. Lève `StoreFailed` si la
        base elle-même est indisponible (aucun fait n'est alors écrit).
        """
