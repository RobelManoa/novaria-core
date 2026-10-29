"""Règles de qualité du comptage routier de Paris (DAT-04) : valeurs manquantes, types, bornes, cohérence, doublons.

Fonctions pures, bibliothèque standard uniquement. Une ligne brute (dictionnaire de textes, telle que lue dans le CSV
rangé par DAT-03) ressort typée (`LignePropre`) ou refusée (`Rejet`) avec la règle et le motif. Rien n'est corrigé en
silence : une valeur absente mais tolérée porte un drapeau, tout le reste est un rejet ou un décompte.

Une ligne refusée l'est pour la **première** règle violée, dans l'ordre de `REGLES`. Les doublons se détectent sur le lot
(un fichier), pas entre fichiers : l'idempotence entre fichiers est celle du chargement (DAT-05).
Règles, seuils et justification : docs/03-donnees/nettoyage-paris.md.
"""

from __future__ import annotations

import bisect
import functools
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

# --- Codes des règles (colonne `rule` de dwh.etl_reject) ---------------------------------------------------------
MISSING_REQUIRED = "MISSING_REQUIRED"
TYPE_INVALID = "TYPE_INVALID"
OUT_OF_RANGE = "OUT_OF_RANGE"
NOT_ON_THE_HOUR = "NOT_ON_THE_HOUR"
FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
STATE_MISMATCH = "STATE_MISMATCH"
DUPLICATE_KEY = "DUPLICATE_KEY"

# Drapeau d'une ligne retenue (jamais un rejet) : le taux d'occupation est vide, le débit est présent.
MISSING_OCCUPANCY = "MISSING_OCCUPANCY"

# --- Référentiels du jeu (fiche data/datasets/README.md, section 3.3) -----------------------------------------------
# Dans les fichiers historiques, ces états sont des entiers : leur rang dans la liste (0 = Inconnu).
ETATS_TRAFIC = ("Inconnu", "Fluide", "Pré-saturé", "Saturé", "Bloqué")
ETATS_BARRE = ("Inconnu", "Ouvert", "Barré", "Invalide")
# Seuils officiels du taux d'occupation k (en %) : < 15 fluide, 15 à 30 pré-saturé, 30 à 50 saturé, 50 et plus bloqué.
SEUILS_OCCUPATION = (15.0, 30.0, 50.0)
OBLIGATOIRES = ("iu_ac", "t_1h", "q")

# --- Bornes (valeurs de départ, à ajuster après mesure sur plusieurs jours) ---------------------------------------
DEBIT_MAX = 15_000.0  # véhicules par heure et par tronçon ; maximum observé le 17/10/2026 : 6 648
OCCUPATION_MAX = 100.0  # pourcentage
CALENDRIER_DEBUT = datetime(2012, 1, 1, tzinfo=UTC)  # calendrier dwh.dim_date : 2012 à 2030 inclus
CALENDRIER_FIN = datetime(2031, 1, 1, tzinfo=UTC)  # exclue
TOLERANCE_FUTUR = timedelta(seconds=5)  # même tolérance que DQ-10

ENTIER = re.compile(r"[0-9]{1,9}", re.ASCII)
NOMBRE = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?", re.ASCII)
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


@dataclass(frozen=True)
class Violation:
    regle: str
    motif: str


@dataclass(frozen=True)
class Rejet:
    ligne: int  # rang de la ligne de données dans le fichier (1 = la première, hors en-tête)
    regle: str
    motif: str
    brut: Mapping[str, str]


@dataclass(frozen=True)
class LignePropre:
    ligne: int
    road_segment_id: str  # iu_ac, sans zéros de tête
    libelle: str
    heure: datetime  # t_1h ramené en UTC, tel que le portail l'annonce (fuseau à vérifier : fiche du jeu, section 3.3)
    vehicle_count: float  # q
    occupancy_pct: float | None  # k, en % (la conversion en taux de 0 à 1 est celle du chargement)
    traffic_state: str | None
    barrier_state: str | None
    upstream_node_id: str
    downstream_node_id: str
    flags: tuple[str, ...]


# --- Lecture tolérante des champs (None quand la valeur n'a pas la forme attendue) ---------------------------------
def _texte(brut: Mapping[str, str], champ: str) -> str:
    texte = brut.get(champ) or ""
    return (texte if texte.isascii() else unicodedata.normalize("NFC", texte)).strip()


def _nombre(texte: str) -> float | None:
    if not NOMBRE.fullmatch(texte):
        return None
    valeur = float(texte)
    return valeur if math.isfinite(valeur) else None


@functools.lru_cache(maxsize=4096)  # un fichier ne compte que quelques dizaines d'heures distinctes
def _instant(texte: str) -> datetime | None:
    """Horodatage ISO 8601 **avec** fuseau, ramené en UTC."""
    try:
        instant = datetime.fromisoformat(texte)
    except ValueError:
        return None
    return instant.astimezone(UTC) if instant.tzinfo is not None else None


@functools.lru_cache(maxsize=4096)
def _date(texte: str) -> date | None:
    if not DATE.fullmatch(texte):
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def _etat(texte: str, liste: tuple[str, ...]) -> str | None:
    if texte in liste:
        return texte
    return liste[int(texte)] if texte.isascii() and texte.isdigit() and int(texte) < len(liste) else None


def etats_attendus(occupation: float) -> set[str]:
    """États d'après l'occupation. Sur un seuil exact (15, 30, 50) la notice du producteur est ambiguë : les deux passent."""
    bandes = ETATS_TRAFIC[1:]
    rang = bisect.bisect_right(SEUILS_OCCUPATION, occupation)
    attendus = {bandes[rang]}
    if occupation in SEUILS_OCCUPATION:
        attendus.add(bandes[rang - 1])
    return attendus


# --- Règles de ligne -----------------------------------------------------------------------------------------------
def regle_valeur_manquante(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    absents = [champ for champ in OBLIGATOIRES if not _texte(brut, champ)]
    if not absents:
        return None
    motif = f"champ(s) obligatoire(s) vide(s) : {', '.join(absents)}"
    if "q" in absents and _texte(brut, "k"):
        motif += " (débit absent : station de taux d'occupation seul, ou panne du comptage)"
    return Violation(MISSING_REQUIRED, motif)


def regle_type(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    problemes = []
    if _texte(brut, "iu_ac") and not ENTIER.fullmatch(_texte(brut, "iu_ac")):
        problemes.append("iu_ac n'est pas un entier")
    if _texte(brut, "t_1h") and _instant(_texte(brut, "t_1h")) is None:
        problemes.append("t_1h n'est pas un horodatage ISO 8601 avec fuseau")
    for champ in ("q", "k"):
        if _texte(brut, champ) and _nombre(_texte(brut, champ)) is None:
            problemes.append(f"{champ} n'est pas un nombre fini")
    for champ in ("date_debut", "date_fin"):
        if _texte(brut, champ) and _date(_texte(brut, champ)) is None:
            problemes.append(f"{champ} n'est pas une date AAAA-MM-JJ")
    for champ, liste in (("etat_trafic", ETATS_TRAFIC), ("etat_barre", ETATS_BARRE)):
        if _texte(brut, champ) and _etat(_texte(brut, champ), liste) is None:
            problemes.append(f"{champ} hors de la liste ({', '.join(liste)}, ou leur rang)")
    return Violation(TYPE_INVALID, "; ".join(problemes)) if problemes else None


def regle_borne(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    problemes = []
    debit = _nombre(_texte(brut, "q"))
    if debit is not None and not 0 <= debit <= DEBIT_MAX:
        problemes.append(f"q = {_texte(brut, 'q')} hors de 0 à {DEBIT_MAX:g} véhicules par heure")
    occupation = _nombre(_texte(brut, "k"))
    if occupation is not None and not 0 <= occupation <= OCCUPATION_MAX:
        problemes.append(f"k = {_texte(brut, 'k')} hors de 0 à {OCCUPATION_MAX:g} %")
    instant = _instant(_texte(brut, "t_1h"))
    if instant is not None and not CALENDRIER_DEBUT <= instant < CALENDRIER_FIN:
        problemes.append(f"t_1h = {instant:%Y-%m-%dT%H:%M:%SZ} hors du calendrier de l'entrepôt (2012 à 2030)")
    return Violation(OUT_OF_RANGE, "; ".join(problemes)) if problemes else None


def regle_heure_pleine(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    instant = _instant(_texte(brut, "t_1h"))
    if instant is not None and (instant.minute or instant.second or instant.microsecond):
        return Violation(NOT_ON_THE_HOUR, f"t_1h = {instant:%Y-%m-%dT%H:%M:%SZ} n'est pas une heure pleine (pas de temps : 1 h)")
    return None


def regle_futur(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    instant = _instant(_texte(brut, "t_1h"))
    if instant is not None and instant > maintenant + TOLERANCE_FUTUR:
        return Violation(FUTURE_TIMESTAMP, f"t_1h = {instant:%Y-%m-%dT%H:%M:%SZ} est après l'horloge ({maintenant:%Y-%m-%dT%H:%M:%SZ})")
    return None


def regle_etat(brut: Mapping[str, str], maintenant: datetime) -> Violation | None:
    """L'état de trafic est une fonction du taux d'occupation (fiche du jeu, section 3.6) : les deux doivent s'accorder."""
    etat = _etat(_texte(brut, "etat_trafic"), ETATS_TRAFIC) if _texte(brut, "etat_trafic") else None
    if etat is None:
        return None
    occupation = _nombre(_texte(brut, "k"))
    if occupation is None:
        if _texte(brut, "k") or etat == "Inconnu":
            return None  # k illisible : c'est le type qui le dit
        return Violation(STATE_MISMATCH, f"etat_trafic = {etat} alors que k est vide")
    if etat == "Inconnu":
        return Violation(STATE_MISMATCH, f"etat_trafic = Inconnu alors que k = {_texte(brut, 'k')}")
    if etat not in etats_attendus(occupation):
        attendus = " ou ".join(sorted(etats_attendus(occupation)))
        return Violation(STATE_MISMATCH, f"etat_trafic = {etat} alors que k = {_texte(brut, 'k')} donne {attendus}")
    return None


@dataclass(frozen=True)
class Regle:
    code: str
    famille: str  # valeur manquante, type, borne, cohérence, doublon (vocabulaire de l'ADR-013, section 4.3)
    description: str
    verifier: Callable[[Mapping[str, str], datetime], Violation | None] | None  # None : règle de lot (doublon)


REGLES = (
    Regle(MISSING_REQUIRED, "valeur manquante", "iu_ac, t_1h ou q vide : la ligne ne peut pas devenir un fait horaire", regle_valeur_manquante),
    Regle(TYPE_INVALID, "type", "iu_ac entier, t_1h horodatage avec fuseau, q et k nombres finis, dates AAAA-MM-JJ, états dans leur liste", regle_type),
    Regle(OUT_OF_RANGE, "borne", f"q de 0 à {DEBIT_MAX:g}, k de 0 à {OCCUPATION_MAX:g}, t_1h dans le calendrier 2012 à 2030", regle_borne),
    Regle(NOT_ON_THE_HOUR, "cohérence", "t_1h est une heure pleine", regle_heure_pleine),
    Regle(FUTURE_TIMESTAMP, "cohérence", "t_1h n'est pas postérieur à l'horloge (tolérance 5 s)", regle_futur),
    Regle(STATE_MISMATCH, "cohérence", "etat_trafic s'accorde avec k selon les seuils officiels", regle_etat),
    Regle(DUPLICATE_KEY, "doublon", "un seul enregistrement par (iu_ac, t_1h) dans un fichier : le premier est gardé", None),
)
REGLES_DE_LIGNE = tuple(regle for regle in REGLES if regle.verifier is not None)


# --- Bilan et traitement d'un lot ------------------------------------------------------------------------------------
class ErreurBilan(Exception):
    """Le bilan ne tombe pas juste : une ligne a été perdue ou comptée deux fois."""


@dataclass
class Bilan:
    lues: int = 0
    propres: int = 0
    rejetees: int = 0
    par_regle: Counter = field(default_factory=Counter)
    drapeaux: Counter = field(default_factory=Counter)

    @property
    def taux_rejet(self) -> float:
        return self.rejetees / self.lues if self.lues else 0.0

    def verifier(self) -> None:
        """Réconciliation de l'ADR-013 : lues = propres + rejetées, et chaque rejet porte une règle."""
        if self.lues != self.propres + self.rejetees or sum(self.par_regle.values()) != self.rejetees:
            raise ErreurBilan(f"lues {self.lues} ≠ propres {self.propres} + rejetées {self.rejetees} (règles : {sum(self.par_regle.values())})")

    def en_dict(self) -> dict:
        return {
            "rows_read": self.lues,
            "rows_clean": self.propres,
            "rows_rejected": self.rejetees,
            "reject_rate": round(self.taux_rejet, 6),
            "by_rule": dict(sorted(self.par_regle.items())),
            "flags": dict(sorted(self.drapeaux.items())),
        }


def construire(numero: int, brut: Mapping[str, str]) -> LignePropre:
    """Type une ligne qui a passé toutes les règles de ligne."""
    occupation = _nombre(_texte(brut, "k"))
    etat = _texte(brut, "etat_trafic")
    barre = _texte(brut, "etat_barre")
    return LignePropre(
        ligne=numero,
        road_segment_id=str(int(_texte(brut, "iu_ac"))),
        libelle=_texte(brut, "libelle"),
        heure=_instant(_texte(brut, "t_1h")),
        vehicle_count=_nombre(_texte(brut, "q")),
        occupancy_pct=occupation,
        traffic_state=_etat(etat, ETATS_TRAFIC) if etat else None,
        barrier_state=_etat(barre, ETATS_BARRE) if barre else None,
        upstream_node_id=_texte(brut, "iu_nd_amont"),
        downstream_node_id=_texte(brut, "iu_nd_aval"),
        flags=(MISSING_OCCUPANCY,) if occupation is None else (),
    )


class Nettoyeur:
    """Traite les lignes d'un fichier une à une et tient le bilan. Une instance = un fichier."""

    def __init__(self, maintenant: datetime) -> None:
        self.maintenant = maintenant
        self.bilan = Bilan()
        self._vues: dict[tuple[str, datetime], LignePropre] = {}

    def traiter(self, numero: int, brut: Mapping[str, str]) -> LignePropre | Rejet:
        self.bilan.lues += 1
        for regle in REGLES_DE_LIGNE:
            violation = regle.verifier(brut, self.maintenant)
            if violation is not None:
                return self._rejeter(numero, brut, violation)
        ligne = construire(numero, brut)
        premiere = self._vues.get((ligne.road_segment_id, ligne.heure))
        if premiere is not None:
            return self._rejeter(numero, brut, Violation(DUPLICATE_KEY, motif_doublon(premiere, ligne)))
        self._vues[(ligne.road_segment_id, ligne.heure)] = ligne
        self.bilan.propres += 1
        self.bilan.drapeaux.update(ligne.flags)
        return ligne

    def _rejeter(self, numero: int, brut: Mapping[str, str], violation: Violation) -> Rejet:
        self.bilan.rejetees += 1
        self.bilan.par_regle[violation.regle] += 1
        return Rejet(numero, violation.regle, violation.motif, dict(brut))


def motif_doublon(premiere: LignePropre, doublon: LignePropre) -> str:
    champs = ("vehicle_count", "occupancy_pct", "traffic_state", "barrier_state")
    differences = [f"{c} {getattr(premiere, c)} ≠ {getattr(doublon, c)}" for c in champs if getattr(premiere, c) != getattr(doublon, c)]
    base = f"même (iu_ac, t_1h) que la ligne {premiere.ligne}"
    return f"{base}, valeurs différentes ({'; '.join(differences)})" if differences else f"{base}, valeurs identiques"
