"""Bibliothèque Robot Framework du rapport hebdomadaire (IA-07, ADR-019).

Chaque mot-clé enveloppe une étape du paquet `rapport`. Le compte de service se lit dans
l'environnement (`NOVARIA_RPA_USER`, `NOVARIA_RPA_PASSWORD`) : aucun secret ne passe en argument,
donc aucun n'entre dans `output.xml` ni dans `log.html`.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from robot.api import logger
from robot.api.deco import keyword, library

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rapport import api, chaine, contenu, depot, periode, synthese  # noqa: E402


@library(scope="SUITE", auto_keywords=False)
class NovariaRapport:
    @keyword("Choisir la période")
    def choisir_la_periode(self, debut: str = "", fin: str = ""):
        """Période demandée (`AAAA-MM-JJ`, fin exclue) ou, sans date, la semaine précédente."""
        choisie = periode.choisir(debut or None, fin or None, datetime.now(UTC))
        logger.info(f"Période : {choisie.libelle} ({choisie.etiquette})")
        return choisie

    def __init__(self) -> None:
        # Le jeton reste dans la bibliothèque : s'il passait par une variable Robot (`${jeton}`), il
        # serait écrit dans `output.xml` et `log.html`.
        self._jeton: str | None = None

    @keyword("Se connecter")
    def se_connecter(self, base_api: str) -> None:
        """Ouvre une session avec le compte de service en lecture seule ; le jeton n'est pas rendu."""
        utilisateur, mot_de_passe = chaine.identifiants()
        self._jeton = api.se_connecter(base_api, utilisateur, mot_de_passe)

    @keyword("Lire les indicateurs")
    def lire_les_indicateurs(self, base_api: str, quand):
        if self._jeton is None:
            raise AssertionError("Se connecter doit précéder la lecture des indicateurs")
        donnees = api.lire_indicateurs(base_api, self._jeton, quand.api(quand.debut), quand.api(quand.fin))
        logger.info(f"{len(donnees.lignes)} fenêtres lues (tronqué : {donnees.tronque})")
        return donnees

    @keyword("Résumer")
    def resumer(self, donnees, quand):
        return synthese.resumer(donnees, quand)

    @keyword("Assembler le rapport")
    def assembler_le_rapport(self, resume):
        """Le PDF du rapport, en octets."""
        return contenu.assembler(resume, datetime.now(UTC))

    @keyword("Déposer le rapport")
    def deposer_le_rapport(self, dossier: str, quand, resume, pdf):
        resultat = depot.deposer(Path(dossier), quand, contenu.titre(resume), pdf, datetime.now(UTC))
        logger.info(f"Rapport {resultat.identifiant} déposé : {resultat.metadonnees['file_name']} (remplacé : {resultat.remplace})")
        return resultat

    @keyword("Notifier")
    def notifier(self, dossier: str, niveau: str, message: str):
        """Notification simulée : une ligne dans `notifications.log`."""
        depot.notifier(Path(dossier), niveau, message, datetime.now(UTC))
