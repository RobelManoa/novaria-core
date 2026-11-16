"""Recalcul par lots des agrégats par fenêtre, à partir des mêmes messages que le flux (ADR-011, section 4.2).

C'est la « vérité de référence » du prototype : un calcul écrit à part, en Python, sans Flink, qui applique les mêmes règles que
`sql/agregats.sql` (fenêtres fixes alignées sur l'heure UTC, vitesse moyenne pondérée par les véhicules, un message compté une
seule fois par `id`). Le flux est correct quand ses documents MongoDB égalent ce recalcul pour toutes les fenêtres fermées.

Aucune dépendance : bibliothèque standard seulement.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

TAILLES_S = (60, 300)  # 1 minute (alertes) et 5 minutes (tendances), ADR-011
DESORDRE_S = 10  # filigrane : 10 s de désordre admis
RETARD_AUTORISE_S = 30  # un message en retard de moins de 30 s met la fenêtre à jour

# Clé d'une fenêtre : (tronçon, début de fenêtre en secondes UTC, taille en secondes, exécution du simulateur)
Cle = tuple[str, int, int, str]


@dataclass(frozen=True)
class Agregat:
    road_segment_id: str
    window_start: int  # secondes depuis 1970, UTC
    window_size_s: int
    run_id: str
    window_end: int
    intersection_id: str
    source_type: str
    sample_count: int
    vehicle_count: int
    flow_veh_per_min: float
    average_speed_kmh: float | None
    occupancy_rate: float | None
    max_queue_length_m: float | None
    non_valid_count: int

    @property
    def cle(self) -> Cle:
        return (self.road_segment_id, self.window_start, self.window_size_s, self.run_id)


def secondes(instant: str) -> int:
    """« 2026-10-20T08:00:10Z » → secondes depuis 1970 (UTC). Le fuseau est explicite dans le contrat (suffixe Z)."""
    if not instant.endswith("Z"):
        raise ValueError(f"instant sans fuseau UTC : {instant!r}")
    return int(datetime.fromisoformat(instant.removesuffix("Z") + "+00:00").astimezone(UTC).timestamp())


def iso(secondes_utc: int) -> str:
    return datetime.fromtimestamp(secondes_utc, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def arrondi(valeur: float | None, decimales: int = 3) -> float | None:
    """Arrondi « moitié vers le haut » sur la représentation décimale, comme le ROUND de Flink SQL (BigDecimal, HALF_UP)."""
    if valeur is None:
        return None
    pas = Decimal(1).scaleb(-decimales)
    return float(Decimal(repr(float(valeur))).quantize(pas, rounding=ROUND_HALF_UP))


def debut_de_fenetre(instant: int, taille_s: int) -> int:
    return instant - instant % taille_s


def dedoublonner(messages: list[dict]) -> list[dict]:
    """Un message par `id`, le premier arrivé (comme la déduplication de la collecte, règle DQ-03)."""
    vus: set[str] = set()
    uniques = []
    for message in messages:
        if message["id"] not in vus:
            vus.add(message["id"])
            uniques.append(message)
    return uniques


def agreger(messages: list[dict], tailles_s: tuple[int, ...] = TAILLES_S) -> dict[Cle, Agregat]:
    """Agrégats de TOUS les messages (aucun n'est écarté pour retard) : la vérité de référence."""
    groupes: dict[Cle, list[dict]] = defaultdict(list)
    for message in dedoublonner(messages):
        donnee = message["data"]
        instant = secondes(message["time"])
        run = donnee["provenance"]["run_id"]
        for taille in tailles_s:
            groupes[(donnee["road_segment_id"], debut_de_fenetre(instant, taille), taille, run)].append(message)
    return {cle: _agregat(cle, lot) for cle, lot in groupes.items()}


def _agregat(cle: Cle, lot: list[dict]) -> Agregat:
    troncon, debut, taille, run = cle
    donnees = [m["data"] for m in lot]
    vehicules = sum(d["vehicle_count"] for d in donnees)
    # Vitesse pondérée par les véhicules ; un message sans vitesse ne compte pas au dénominateur (NULL ignoré par SUM en SQL).
    avec_vitesse = [d for d in donnees if d["average_speed_kmh"] is not None]
    poids = sum(d["vehicle_count"] for d in avec_vitesse)
    vitesse = sum(d["average_speed_kmh"] * d["vehicle_count"] for d in avec_vitesse) / poids if poids else None
    occupations = [d["occupancy_rate"] for d in donnees if d["occupancy_rate"] is not None]
    files = [d["queue_length_m"] for d in donnees if d.get("queue_length_m") is not None]
    return Agregat(
        road_segment_id=troncon,
        window_start=debut,
        window_size_s=taille,
        run_id=run,
        window_end=debut + taille,
        intersection_id=max(d["intersection_id"] for d in donnees),
        source_type=max(d["provenance"]["source_type"] for d in donnees),
        sample_count=len(lot),
        vehicle_count=vehicules,
        flow_veh_per_min=arrondi(vehicules * 60.0 / taille),
        average_speed_kmh=arrondi(vitesse),
        occupancy_rate=arrondi(sum(occupations) / len(occupations)) if occupations else None,
        max_queue_length_m=max(files) if files else None,
        non_valid_count=sum(1 for d in donnees if d["quality"]["status"] != "VALID"),
    )


def instant_du_filigrane(messages: list[dict]) -> int:
    """Filigrane final du flux : le plus récent instant d'événement moins le désordre admis."""
    return max(secondes(m["time"]) for m in messages) - DESORDRE_S


def fenetres_fermees(agregats: dict[Cle, Agregat], filigrane: int) -> dict[Cle, Agregat]:
    """Les fenêtres que le flux a dû émettre : celles dont la fin est atteinte par le filigrane."""
    return {cle: agregat for cle, agregat in agregats.items() if agregat.window_end <= filigrane}
