"""Notification du robot : le journal `notifications.log` toujours, le courriel en plus s'il est configuré."""

import os
from datetime import datetime
from pathlib import Path

from rapport import courriel, depot

SUJETS = {"INFO": "rapport hebdomadaire déposé", "ERREUR": "rapport hebdomadaire NON produit"}


def notifier(dossier: Path, niveau: str, message: str, quand: datetime, environnement: dict[str, str] | None = None, *,
             fabrique=None) -> None:
    """Écrit la ligne de journal, puis envoie le courriel. Un courriel impossible est noté dans le journal, jamais levé."""
    depot.notifier(dossier, niveau, message, quand)
    environnement = os.environ if environnement is None else environnement
    try:
        r = courriel.reglages(dict(environnement))
        if r is None:
            return
        courriel.envoyer(r, f"[Novaria] {SUJETS.get(niveau, niveau)}", f"{niveau} : {message}\n\nSource : robot du rapport hebdomadaire (IA-07). "
                         "Le rapport est dans la page « Rapports » ; ce courriel n'en contient aucune donnée.\n",
                         **({"fabrique": fabrique} if fabrique else {}))
        depot.notifier(dossier, "INFO", f"courriel envoyé à {r.destinataire}", quand)
    except (courriel.CourrielNonConfigure, courriel.ErreurCourriel) as erreur:
        depot.notifier(dossier, "AVERTISSEMENT", f"courriel non envoyé : {erreur}", quand)
