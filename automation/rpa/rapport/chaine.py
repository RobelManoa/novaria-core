"""La chaîne complète du robot, sans Robot Framework : connexion, lecture, synthèse, PDF, dépôt."""

import os
from datetime import UTC, datetime
from pathlib import Path

from rapport import api, contenu, depot, periode, synthese

VARIABLE_UTILISATEUR = "NOVARIA_RPA_USER"
VARIABLE_MOT_DE_PASSE = "NOVARIA_RPA_PASSWORD"  # noqa: S105 : nom de variable, pas un secret


class IdentifiantsAbsents(Exception):
    pass


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
) -> depot.Depot:
    maintenant = maintenant or datetime.now(UTC)
    quand = periode.choisir(debut, fin, maintenant)
    utilisateur, mot_de_passe = identifiants(environnement)
    jeton = api.se_connecter(base_api, utilisateur, mot_de_passe, envoyer)
    donnees = api.lire_indicateurs(base_api, jeton, quand.api(quand.debut), quand.api(quand.fin), envoyer=envoyer)
    resume = synthese.resumer(donnees, quand)
    pdf = contenu.assembler(resume, maintenant)
    resultat = depot.deposer(dossier, quand, contenu.titre(resume), pdf, maintenant)
    depot.notifier(dossier, "INFO", f"rapport {quand.etiquette} déposé : {resultat.metadonnees['file_name']}", maintenant)
    return resultat
