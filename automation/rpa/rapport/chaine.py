"""La chaîne complète du robot, sans Robot Framework : connexion, lecture, synthèse, PDF, dépôt."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from rapport import api, contenu, depot, notification, periode, synthese

VARIABLE_UTILISATEUR = "NOVARIA_RPA_USER"
VARIABLE_MOT_DE_PASSE = "NOVARIA_RPA_PASSWORD"  # noqa: S105 : nom de variable, pas un secret


VARIABLE_TENTATIVES = "NOVARIA_RPA_TENTATIVES"
VARIABLE_ATTENTE = "NOVARIA_RPA_ATTENTE_S"
TENTATIVES_PAR_DEFAUT = 3  # ADR-019 : « nouvelle tentative limitée, puis notification d'erreur »
ATTENTE_PAR_DEFAUT_S = 60.0

T = TypeVar("T")


class IdentifiantsAbsents(Exception):
    pass


def _entier_borne(valeur: str | None, defaut: float, bas: float, haut: float, nom: str) -> float:
    if valeur in (None, ""):
        return defaut
    try:
        nombre = float(valeur)
    except ValueError as erreur:
        raise IdentifiantsAbsents(f"{nom} doit être un nombre") from erreur
    if not bas <= nombre <= haut:
        raise IdentifiantsAbsents(f"{nom} doit être entre {bas:g} et {haut:g}")
    return nombre


def reglage_des_reprises(environnement: dict[str, str] | None = None) -> tuple[int, float]:
    """(tentatives, attente avant la deuxième, en secondes) : de 1 à 10 tentatives, de 0 à 3 600 s, doublée à chaque échec."""
    environnement = os.environ if environnement is None else environnement
    tentatives = int(_entier_borne(environnement.get(VARIABLE_TENTATIVES), TENTATIVES_PAR_DEFAUT, 1, 10, VARIABLE_TENTATIVES))
    attente = _entier_borne(environnement.get(VARIABLE_ATTENTE), ATTENTE_PAR_DEFAUT_S, 0, 3600, VARIABLE_ATTENTE)
    return tentatives, attente


def avec_reprises(action: Callable[[], T], *, environnement: dict[str, str] | None = None, dormir: Callable[[float], None] = time.sleep,
                  signaler: Callable[[str], None] | None = None) -> T:
    """Exécute `action`, la rejoue si l'API est momentanément indisponible, au plus `tentatives` fois.

    Seule une `ErreurApi` **transitoire** est rejouée (API injoignable, délai, 429, 502, 503, 504) : un mot de passe refusé
    ou une route absente échoue tout de suite. L'attente double à chaque échec. La dernière erreur est relevée telle quelle.
    """
    tentatives, attente = reglage_des_reprises(environnement)
    for numero in range(1, tentatives + 1):
        try:
            return action()
        except api.ErreurApi as erreur:
            if not erreur.transitoire or numero == tentatives:
                raise
            pause = attente * 2 ** (numero - 1)
            if signaler:
                signaler(f"tentative {numero}/{tentatives} échouée ({erreur}) : nouvelle tentative dans {pause:g} s")
            dormir(pause)
    raise AssertionError("inatteignable")  # pragma: no cover


def identifiants(environnement: dict[str, str] | None = None) -> tuple[str, str]:
    """Compte de service en lecture seule : lu dans l'environnement, jamais écrit dans un fichier."""
    environnement = os.environ if environnement is None else environnement
    utilisateur, mot_de_passe = environnement.get(VARIABLE_UTILISATEUR), environnement.get(VARIABLE_MOT_DE_PASSE)
    if not utilisateur or not mot_de_passe:
        raise IdentifiantsAbsents(f"définir {VARIABLE_UTILISATEUR} et {VARIABLE_MOT_DE_PASSE} (compte en lecture seule)")
    return utilisateur, mot_de_passe


def produire(
    base_api: str,
    dossier: Path,
    *,
    debut: str | None = None,
    fin: str | None = None,
    maintenant: datetime | None = None,
    envoyer: api.Requete | None = None,
    environnement: dict[str, str] | None = None,
    dormir: Callable[[float], None] = time.sleep,
    signaler: Callable[[str], None] | None = None,
) -> depot.Depot:
    maintenant = maintenant or datetime.now(UTC)
    quand = periode.choisir(debut, fin, maintenant)
    utilisateur, mot_de_passe = identifiants(environnement)

    def lire() -> api.Indicateurs:
        jeton = api.se_connecter(base_api, utilisateur, mot_de_passe, envoyer)
        return api.lire_indicateurs(base_api, jeton, quand.api(quand.debut), quand.api(quand.fin), envoyer=envoyer)

    donnees = avec_reprises(lire, environnement=environnement, dormir=dormir, signaler=signaler)
    resume = synthese.resumer(donnees, quand)
    pdf = contenu.assembler(resume, maintenant)
    resultat = depot.deposer(dossier, quand, contenu.titre(resume), pdf, maintenant)
    notification.notifier(dossier, "INFO", f"rapport {quand.etiquette} déposé : {resultat.metadonnees['file_name']}", maintenant, environnement)
    return resultat
