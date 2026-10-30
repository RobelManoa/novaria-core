"""Contrôle des fenêtres de trafic avant leur chargement dans `dwh.fact_traffic_window` (DAT-06).

Fonctions pures, bibliothèque standard seulement. Une ligne d'un fichier de fenêtres (CSV, textes) ressort typée
(`Fenetre`) ou refusée (`Rejet`, même forme que le nettoyage de Paris) avec la règle et le motif. Ces règles reprennent
les contraintes de la table : le chargement refuse la ligne avec son motif au lieu de laisser PostgreSQL faire échouer
tout le lot. La première règle violée l'emporte, dans l'ordre de `REGLES`.

Le grain est celui de la table : un tronçon, un début de fenêtre, une taille de fenêtre (le `run_id` est celui du
chargement, pas d'une colonne). Deux lignes du même grain dans un fichier : la première est retenue, la suivante est
refusée (DUPLICATE_KEY). Règles et justification : docs/03-donnees/etl-planifie-local.md.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from transforms.paris_qualite import DUPLICATE_KEY, MISSING_REQUIRED, OUT_OF_RANGE, TYPE_INVALID, Rejet

UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
NOT_ALIGNED = "NOT_ALIGNED"
SPEED_WITHOUT_VEHICLE = "SPEED_WITHOUT_VEHICLE"
REGLES = (MISSING_REQUIRED, TYPE_INVALID, OUT_OF_RANGE, NOT_ALIGNED, SPEED_WITHOUT_VEHICLE, UNKNOWN_REFERENCE, DUPLICATE_KEY)

COLONNES = (
    "road_segment_id", "window_start", "window_size_s", "source_type", "vehicle_count", "flow_veh_per_min",
    "average_speed_kmh", "occupancy_rate", "max_queue_length_m", "speed_ratio", "sample_count",
    "expected_sample_count", "congestion_state", "classifier_version",
)
OBLIGATOIRES = (
    "road_segment_id", "window_start", "window_size_s", "source_type", "vehicle_count", "flow_veh_per_min",
    "sample_count", "expected_sample_count", "congestion_state", "classifier_version",
)
TAILLES_DE_FENETRE = (60, 300)  # secondes : CHECK de la table
SMALLINT_MAX = 32_767
# Bornes de la table : (minimum, maximum) de chaque colonne numérique facultative ou non.
BORNES = {
    "flow_veh_per_min": (Decimal(0), Decimal("999999.99")),  # numeric(8, 2)
    "average_speed_kmh": (Decimal(0), Decimal(200)),
    "occupancy_rate": (Decimal(0), Decimal(1)),
    "max_queue_length_m": (Decimal(0), Decimal("999999.9")),  # numeric(7, 1)
    "speed_ratio": (Decimal(0), Decimal("9.999")),  # numeric(4, 3)
}
ENTIERS = {"vehicle_count": (0, 2_147_483_647), "sample_count": (0, SMALLINT_MAX), "expected_sample_count": (1, SMALLINT_MAX)}
SEGMENT = re.compile(r"ROAD_\d{3,}", re.ASCII)
NOMBRE = re.compile(r"[+-]?\d+(\.\d+)?", re.ASCII)
ENTIER = re.compile(r"[+-]?\d{1,12}", re.ASCII)


class ErreurFenetre(Exception):
    """Fichier de fenêtres inutilisable (en-tête) : rien n'est chargé."""


@dataclass(frozen=True)
class Referentiels:
    """Valeurs que l'entrepôt connaît : tronçons (dim_road_segment), états (dim_congestion_state), sources (dim_source)."""

    segments: Collection[str]
    etats: Collection[str]
    sources: Collection[str]


@dataclass(frozen=True)
class Fenetre:
    ligne: int
    road_segment_id: str
    window_start: datetime  # UTC
    window_size_s: int
    source_type: str
    vehicle_count: int
    flow_veh_per_min: Decimal
    average_speed_kmh: Decimal | None
    occupancy_rate: Decimal | None
    max_queue_length_m: Decimal | None
    speed_ratio: Decimal | None
    sample_count: int
    expected_sample_count: int
    congestion_state: str
    classifier_version: str

    @property
    def grain(self) -> tuple[str, datetime, int]:
        return (self.road_segment_id, self.window_start, self.window_size_s)


class _Refus(Exception):
    def __init__(self, regle: str, motif: str) -> None:
        super().__init__(motif)
        self.regle, self.motif = regle, motif


def verifier_entete(entete: list[str]) -> None:
    manquantes = [colonne for colonne in COLONNES if colonne not in entete]
    if manquantes:
        raise ErreurFenetre(f"Colonnes absentes du fichier : {', '.join(manquantes)} (attendues : {', '.join(COLONNES)}).")


def _texte(brut: Mapping[str, str], colonne: str) -> str:
    return (brut.get(colonne) or "").strip()


def _instant(texte: str) -> datetime:
    try:
        instant = datetime.fromisoformat(texte)
    except ValueError:
        raise _Refus(TYPE_INVALID, f"window_start « {texte} » n'est pas un instant ISO 8601") from None
    if instant.tzinfo is None:
        raise _Refus(TYPE_INVALID, f"window_start « {texte} » n'a pas de fuseau : l'entrepôt exige UTC")
    return instant.astimezone(UTC)


def _entier(brut: Mapping[str, str], colonne: str, minimum: int, maximum: int) -> int:
    texte = _texte(brut, colonne)
    if not ENTIER.fullmatch(texte):
        raise _Refus(TYPE_INVALID, f"{colonne} « {texte} » n'est pas un entier")
    valeur = int(texte)
    if not minimum <= valeur <= maximum:
        raise _Refus(OUT_OF_RANGE, f"{colonne} {valeur} hors de {minimum} à {maximum}")
    return valeur


def _decimal(brut: Mapping[str, str], colonne: str) -> Decimal | None:
    texte = _texte(brut, colonne)
    if not texte:
        return None
    if not NOMBRE.fullmatch(texte):
        raise _Refus(TYPE_INVALID, f"{colonne} « {texte} » n'est pas un nombre décimal")
    valeur = Decimal(texte)
    minimum, maximum = BORNES[colonne]
    if not minimum <= valeur <= maximum:
        raise _Refus(OUT_OF_RANGE, f"{colonne} {valeur} hors de {minimum} à {maximum}")
    return valeur


def _controler(numero: int, brut: Mapping[str, str], references: Referentiels) -> Fenetre:
    for colonne in OBLIGATOIRES:
        if not _texte(brut, colonne):
            raise _Refus(MISSING_REQUIRED, f"{colonne} est vide ou absent")
    segment = _texte(brut, "road_segment_id")
    if not SEGMENT.fullmatch(segment):
        raise _Refus(TYPE_INVALID, f"road_segment_id « {segment} » ne suit pas ROAD_nnn")
    debut = _instant(_texte(brut, "window_start"))
    taille = _entier(brut, "window_size_s", 0, SMALLINT_MAX)
    if taille not in TAILLES_DE_FENETRE:
        raise _Refus(OUT_OF_RANGE, f"window_size_s {taille} : seules {TAILLES_DE_FENETRE} sont admises")
    entiers = {colonne: _entier(brut, colonne, *bornes) for colonne, bornes in ENTIERS.items()}
    nombres = {colonne: _decimal(brut, colonne) for colonne in BORNES}
    if debut.timestamp() % taille:
        raise _Refus(NOT_ALIGNED, f"window_start {debut:%Y-%m-%dT%H:%M:%SZ} n'est pas un multiple de {taille} s")
    if nombres["average_speed_kmh"] is not None and entiers["vehicle_count"] == 0:
        raise _Refus(SPEED_WITHOUT_VEHICLE, "une vitesse n'existe que si au moins un véhicule a été observé")
    for colonne, valeurs in (("road_segment_id", references.segments), ("congestion_state", references.etats), ("source_type", references.sources)):
        if _texte(brut, colonne) not in valeurs:
            raise _Refus(UNKNOWN_REFERENCE, f"{colonne} « {_texte(brut, colonne)} » est inconnu de l'entrepôt")
    return Fenetre(
        ligne=numero, road_segment_id=segment, window_start=debut, window_size_s=taille, source_type=_texte(brut, "source_type"),
        flow_veh_per_min=nombres["flow_veh_per_min"], average_speed_kmh=nombres["average_speed_kmh"],
        occupancy_rate=nombres["occupancy_rate"], max_queue_length_m=nombres["max_queue_length_m"], speed_ratio=nombres["speed_ratio"],
        congestion_state=_texte(brut, "congestion_state"), classifier_version=_texte(brut, "classifier_version"), **entiers,
    )


class Controleur:
    """Contrôle les lignes d'un fichier dans l'ordre, en gardant les grains déjà vus pour repérer les doublons."""

    def __init__(self, references: Referentiels) -> None:
        self._references = references
        self._vus: dict[tuple, int] = {}

    def traiter(self, numero: int, brut: Mapping[str, str]) -> Fenetre | Rejet:
        try:
            fenetre = _controler(numero, brut, self._references)
        except _Refus as refus:
            return Rejet(numero, refus.regle, refus.motif, dict(brut))
        premiere = self._vus.setdefault(fenetre.grain, numero)
        if premiere != numero:
            return Rejet(numero, DUPLICATE_KEY, f"même tronçon, même fenêtre que la ligne {premiere} (la première est retenue)", dict(brut))
        return fenetre
