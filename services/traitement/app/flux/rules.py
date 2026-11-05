"""Règles du flux, chacune une valeur nommée (ADR-011 : délais ; ADR-028 : seuils d'état).

Les valeurs sont des hypothèses de départ : l'ADR-011 les dit « à régler par mesure sur MS-15 »
et l'ADR-028 « à fixer dans le cadrage ML ». Les nommer permet de les changer sans toucher au
code de calcul.
"""

from dataclasses import dataclass

CLASSIFIER_VERSION = "regles-v0"
WINDOW_SIZES_S = (60, 300)  # 1 minute (état, alertes) et 5 minutes (tendances)
STATE_WINDOW_S = 60  # seules les fenêtres d'une minute alimentent l'hystérésis (ADR-028)

# --- Temps d'événement (ADR-011, section 4.1) ---------------------------------------------------
OUT_OF_ORDERNESS_S = 10  # désordre admis : le filigrane retarde de 10 s sur le plus grand temps vu
ALLOWED_LATENESS_S = (
    30  # retard autorisé : une fenêtre déjà publiée reste modifiable 30 s après son filigrane
)
FUTURE_TOLERANCE_S = 5  # DQ-10 : un horodatage plus de 5 s après l'horloge est refusé (hors rejeu)

# --- Fermeture sans nouveau message (horloge, pas temps d'événement) ----------------------------
# Sans message depuis 15 s, les fenêtres terminées sont publiées (sinon elles resteraient ouvertes).
IDLE_FLUSH_S = 15.0
IDLE_RETIRE_S = 600.0  # sans message depuis 10 min, l'état du run est libéré

MIN_COMPLETENESS = 0.5  # DQ-07 : en dessous, l'état est UNKNOWN


@dataclass(frozen=True)
class Thresholds:
    """Seuils d'hystérésis de l'ADR-028 (ratio de vitesse) et nombres de fenêtres consécutives."""

    slow_below: float = 0.60  # FREE_FLOW -> SLOW : ratio < 0,60 ...
    congested_below: float = 0.35  # ... -> CONGESTED : ratio < 0,35 ...
    degrade_windows: int = 2  # ... pendant 2 fenêtres
    recover_to_slow_above: float = 0.45  # CONGESTED -> SLOW : ratio > 0,45 ...
    free_above: float = 0.70  # -> FREE_FLOW : ratio > 0,70 ...
    recover_windows: int = 3  # ... pendant 3 fenêtres
    min_completeness: float = MIN_COMPLETENESS


DEFAULT_THRESHOLDS = Thresholds()
