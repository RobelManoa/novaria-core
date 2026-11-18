"""Évaluation : rappel, précision et délai de détection, au niveau des anomalies et des épisodes d'alerte.

Définitions (les mêmes pour les règles et pour Isolation Forest) :

- **Épisode d'alerte** : les alertes d'un même capteur séparées de moins de 120 s forment un seul épisode ;
- **Anomalie détectée** : au moins une alerte du bon capteur entre le premier message touché et la fin de l'anomalie
  (augmentée de son retard de livraison) plus 120 s de tolérance ;
- **Rappel** : anomalies détectées / anomalies injectées ;
- **Délai** : instant de la première alerte moins instant du premier message touché (le `time` du message), en secondes ;
- **Précision** : épisodes qui recouvrent une anomalie injectée du même capteur / épisodes d'alerte ;
- **Fausses alertes par heure** : épisodes sans anomalie, divisés par les heures de réseau simulées ;
- **Budget** : au plus une fausse alerte par heure de réseau sur les runs de validation sans anomalie. Les seuils des règles
  et celui d'Isolation Forest sont réglés pour tenir ce même budget : la comparaison est faite à coût égal.
"""

import statistics
from dataclasses import dataclass, field

from anomalies.campagne import Banc, Injection
from anomalies.regles import Alerte

ECART_EPISODE_S = 120.0
TOLERANCE_S = 120.0
BUDGET_FAUSSES_PAR_HEURE = 1.0


@dataclass(frozen=True)
class Episode:
    capteur: str
    debut: float
    fin: float
    detecteurs: tuple[str, ...]


@dataclass
class Resultat:
    """Ce qu'un détecteur donne sur un banc : par injection, le délai (ou rien) ; et les épisodes vrais ou faux."""

    delais: list[tuple[Injection, float | None, str]] = field(default_factory=list)  # injection, délai, détecteur de la première alerte
    episodes_vrais: int = 0
    episodes_faux: int = 0
    heures: float = 0.0


def episodes(alertes: list[Alerte]) -> list[Episode]:
    sortie: list[Episode] = []
    par_capteur: dict[str, list[Alerte]] = {}
    for alerte in sorted(alertes, key=lambda a: a.a):
        par_capteur.setdefault(alerte.capteur, []).append(alerte)
    for capteur, liste in par_capteur.items():
        debut = fin = liste[0].a
        noms = {liste[0].detecteur}
        for alerte in liste[1:]:
            if alerte.a - fin > ECART_EPISODE_S:
                sortie.append(Episode(capteur, debut, fin, tuple(sorted(noms))))
                debut, noms = alerte.a, set()
            fin = alerte.a
            noms.add(alerte.detecteur)
        sortie.append(Episode(capteur, debut, fin, tuple(sorted(noms))))
    return sorted(sortie, key=lambda e: e.debut)


def fenetre(injection: Injection) -> tuple[float, float]:
    return injection.debut, injection.fin + injection.effet_max_s + TOLERANCE_S


def evaluer_banc(banc: Banc, alertes: list[Alerte]) -> Resultat:
    resultat = Resultat(heures=banc.duree_h)
    for injection in banc.injections:
        debut, fin = fenetre(injection)
        dans = sorted((a for a in alertes if a.capteur == injection.capteur and debut <= a.a <= fin), key=lambda a: a.a)
        resultat.delais.append((injection, dans[0].a - injection.debut if dans else None, dans[0].detecteur if dans else ""))
    for episode in episodes(alertes):
        vrai = any(i.capteur == episode.capteur and episode.fin >= fenetre(i)[0] and episode.debut <= fenetre(i)[1] for i in banc.injections)
        if vrai:
            resultat.episodes_vrais += 1
        else:
            resultat.episodes_faux += 1
    return resultat


def fausses_par_heure(resultats: list[Resultat]) -> float:
    heures = sum(r.heures for r in resultats)
    return sum(r.episodes_faux for r in resultats) / heures if heures else 0.0


def resume_par_type(resultats: list[Resultat]) -> dict[str, dict]:
    """Rappel et délais par type d'anomalie, sources confondues (la source est dans `source_par_type`)."""
    par_type: dict[str, list[float | None]] = {}
    for resultat in resultats:
        for injection, delai, _ in resultat.delais:
            par_type.setdefault(injection.type, []).append(delai)
    sortie = {}
    for type_, delais in par_type.items():
        trouves = [d for d in delais if d is not None]
        sortie[type_] = {
            "injectees": len(delais), "detectees": len(trouves), "rappel": len(trouves) / len(delais),
            "delai_median_s": statistics.median(trouves) if trouves else None, "delai_max_s": max(trouves) if trouves else None,
        }
    return sortie


def precision(resultats: list[Resultat]) -> float | None:
    vrais, faux = sum(r.episodes_vrais for r in resultats), sum(r.episodes_faux for r in resultats)
    return vrais / (vrais + faux) if vrais + faux else None


def source_par_type(bancs: list[Banc]) -> dict[str, str]:
    return {i.type: i.source for b in bancs for i in b.injections}


def premiers_detecteurs(resultats: list[Resultat]) -> dict[str, dict[str, int]]:
    """Pour chaque type d'anomalie, quelle règle a donné la première alerte."""
    sortie: dict[str, dict[str, int]] = {}
    for resultat in resultats:
        for injection, delai, detecteur in resultat.delais:
            if delai is not None:
                sortie.setdefault(injection.type, {}).setdefault(detecteur, 0)
                sortie[injection.type][detecteur] += 1
    return sortie
