"""Compare les documents MongoDB écrits par Flink au recalcul par lots (contrôle de cohérence de l'ADR-011, section 4.2).

Trois catégories, jamais mélangées :
- écart de valeur : la fenêtre existe des deux côtés mais un champ diffère (au-delà de l'arrondi) : **défaut du flux** ;
- fenêtre manquante : une fenêtre fermée par le filigrane n'est pas dans MongoDB : **défaut du flux** ;
- fenêtre en trop : MongoDB a une fenêtre que le recalcul n'a pas : **défaut du flux** (ou du recalcul).
Les fenêtres encore ouvertes à la fin (le filigrane ne les a pas atteintes) ne sont ni attendues ni comptées en erreur : elles sont
listées à part, parce que c'est le comportement normal du temps d'événement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import recalcul

TOLERANCE = 0.0011  # le dernier chiffre arrondi (3 décimales) peut différer d'une unité entre deux arrondis de flottants
CHAMPS_ENTIERS = ("sample_count", "vehicle_count", "non_valid_count", "window_size_s")
CHAMPS_REELS = ("flow_veh_per_min", "average_speed_kmh", "occupancy_rate", "max_queue_length_m")
CHAMPS_TEXTE = ("intersection_id", "source_type")


@dataclass
class Rapport:
    documents: int = 0
    attendus: int = 0
    egales: int = 0
    ecarts: list[str] = field(default_factory=list)
    manquantes: list[str] = field(default_factory=list)
    en_trop: list[str] = field(default_factory=list)
    ouvertes: int = 0

    @property
    def conforme(self) -> bool:
        return not (self.ecarts or self.manquantes or self.en_trop)


def _instant(valeur) -> int:
    """Une date de document : `{"$date": "…Z"}` (JSON étendu de mongosh) ou « …Z » ; millisecondes ignorées si nulles."""
    if isinstance(valeur, dict):
        valeur = valeur["$date"]
    if isinstance(valeur, (int, float)):
        return int(valeur // 1000)
    texte = str(valeur)
    if "." in texte:
        texte = texte.split(".")[0] + "Z"
    return recalcul.secondes(texte)


def cle_du_document(document: dict) -> recalcul.Cle:
    """La clé (tronçon, début, taille, exécution) d'un document : dans `_id` (clé primaire du sink) ou à plat."""
    source = document["_id"] if isinstance(document.get("_id"), dict) else document
    return (source["road_segment_id"], _instant(source["window_start"]), int(source["window_size_s"]), source["run_id"])


def _proche(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= TOLERANCE


def comparer(documents: list[dict], attendus: dict[recalcul.Cle, recalcul.Agregat], fermees: dict[recalcul.Cle, recalcul.Agregat]) -> Rapport:
    """Compare les documents à `attendus` (toutes les fenêtres) pour les clés de `fermees` (celles que le flux a dû émettre)."""
    rapport = Rapport(documents=len(documents), attendus=len(fermees), ouvertes=len(attendus) - len(fermees))
    trouves: dict[recalcul.Cle, dict] = {}
    for document in documents:
        trouves[cle_du_document(document)] = document
    for cle, agregat in sorted(fermees.items()):
        document = trouves.get(cle)
        etiquette = f"{cle[0]} {recalcul.iso(cle[1])} {cle[2]} s"
        if document is None:
            rapport.manquantes.append(etiquette)
            continue
        ecarts = _ecarts(document, agregat)
        if ecarts:
            rapport.ecarts.append(f"{etiquette} : {'; '.join(ecarts)}")
        else:
            rapport.egales += 1
    for cle in sorted(trouves.keys() - attendus.keys()):
        rapport.en_trop.append(f"{cle[0]} {recalcul.iso(cle[1])} {cle[2]} s")
    return rapport


def _ecarts(document: dict, agregat: recalcul.Agregat) -> list[str]:
    ecarts = []
    for champ in CHAMPS_ENTIERS:
        if int(document[champ]) != getattr(agregat, champ):
            ecarts.append(f"{champ} = {document[champ]} (attendu {getattr(agregat, champ)})")
    for champ in CHAMPS_REELS:
        if not _proche(document.get(champ), getattr(agregat, champ)):
            ecarts.append(f"{champ} = {document.get(champ)} (attendu {getattr(agregat, champ)})")
    for champ in CHAMPS_TEXTE:
        if document.get(champ) != getattr(agregat, champ):
            ecarts.append(f"{champ} = {document.get(champ)!r} (attendu {getattr(agregat, champ)!r})")
    if _instant(document["window_end"]) != agregat.window_end:
        ecarts.append(f"window_end = {_instant(document['window_end'])} (attendu {agregat.window_end})")
    return ecarts
