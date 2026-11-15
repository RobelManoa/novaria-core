"""Planificateur hebdomadaire portable : lance une commande chaque semaine, sans cron ni Planificateur de tâches.

    python -m rapport.planificateur --jour lundi --heure 07:00 --dossier var/reports -- <commande du robot>

Le planificateur attend le prochain créneau (heure locale du poste), lance la commande, écrit une ligne de journal, et recommence.
Au démarrage, **si le rapport de la dernière semaine terminée n'est pas déposé**, il le produit tout de suite (rattrapage : un
poste éteint le lundi matin ne perd pas le rapport). Relancer la commande est sans effet de bord (un rapport par semaine, ADR-019).
C'est la même commande que `cron` ou le Planificateur de tâches lanceraient : `dev.py rpa-report`.
"""

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, time as heure_du_jour, timedelta, tzinfo
from pathlib import Path

from rapport import depot, periode

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
PAS_DE_VEILLE_S = 30  # l'attente se fait par petits pas : un poste mis en veille ou une horloge corrigée ne décale pas le créneau


class HoraireInvalide(ValueError):
    pass


def lire_heure(texte: str) -> heure_du_jour:
    try:
        heures, minutes = texte.split(":")
        return heure_du_jour(int(heures), int(minutes))
    except ValueError as erreur:
        raise HoraireInvalide(f"heure « {texte} » : écrire HH:MM (de 00:00 à 23:59)") from erreur


def lire_jour(texte: str) -> int:
    nom = texte.strip().lower()
    if nom not in JOURS:
        raise HoraireInvalide(f"jour « {texte} » : {', '.join(JOURS)}")
    return JOURS.index(nom)


def _a_heure_locale(jour_calendaire, heure: heure_du_jour, fuseau: tzinfo | None) -> datetime:
    """`heure` de ce jour, à l'heure du poste : l'heure d'été est celle **du jour visé**, pas celle d'aujourd'hui."""
    naive = datetime.combine(jour_calendaire, heure)
    return naive.astimezone() if fuseau is None else naive.replace(tzinfo=fuseau)


def prochain_creneau(maintenant: datetime, jour: int, heure: heure_du_jour, fuseau: tzinfo | None = None) -> datetime:
    """Le prochain `jour` (0 = lundi) à `heure`, heure locale (`fuseau`, ou celui du poste), strictement après `maintenant`."""
    local = maintenant.astimezone(fuseau)
    candidat = _a_heure_locale(local.date() + timedelta(days=(jour - local.weekday()) % 7), heure, fuseau)
    return candidat if candidat > local else _a_heure_locale(candidat.date() + timedelta(days=7), heure, fuseau)


def verifier_le_creneau(creneau: datetime) -> None:
    """Le robot rapporte la **semaine ISO précédente** (UTC) : le créneau ne doit pas tomber dans la semaine UTC d'avant.

    Lundi 07:00 à UTC+14 est encore le dimanche en UTC : la semaine à rapporter ne serait pas terminée.
    """
    local, en_utc = creneau, creneau.astimezone(UTC)
    if en_utc.isocalendar()[:2] < local.isocalendar()[:2]:
        raise HoraireInvalide(f"créneau du {JOURS[local.weekday()]} {local:%H:%M} : il tombe encore le {JOURS[en_utc.weekday()]} en UTC "
                              f"({en_utc:%H:%M} UTC), la semaine à rapporter n'est pas terminée ; choisir une heure plus tardive")


def rapport_a_rattraper(dossier: Path, maintenant: datetime) -> bool:
    """Vrai si le rapport de la semaine ISO précédente (UTC) n'est pas déposé : ses métadonnées sont écrites en dernier."""
    quand = periode.choisir(None, None, maintenant.astimezone(UTC))
    return not (dossier / f"{depot.identifiant(quand)}.json").is_file()


def executer(commande: list[str]) -> int:
    return subprocess.run(commande, check=False).returncode  # noqa: S603 : la commande est celle que l'opérateur a écrite


def boucle(jour: int, heure: heure_du_jour, commande: list[str], dossier: Path, *, rattrapage: bool = True,
           maintenant: Callable[[], datetime] = lambda: datetime.now(UTC), dormir: Callable[[float], None] = time.sleep,
           lancer: Callable[[list[str]], int] = executer, journal: Callable[[str], None] = lambda texte: print(texte, flush=True), executions: int | None = None,
           fuseau: tzinfo | None = None) -> int:
    """Attend chaque créneau et lance la commande. `executions` borne le nombre de lancements (essais) ; sinon, sans fin."""
    lancements = 0

    def lancer_maintenant(raison: str) -> None:
        nonlocal lancements
        journal(f"{maintenant().astimezone(fuseau):%Y-%m-%d %H:%M:%S} : lancement ({raison})")
        code = lancer(commande)
        lancements += 1
        journal(f"{maintenant().astimezone(fuseau):%Y-%m-%d %H:%M:%S} : terminé, code de sortie {code}")

    if rattrapage and rapport_a_rattraper(dossier, maintenant()):
        lancer_maintenant("rattrapage : le rapport de la dernière semaine n'est pas déposé")
    while executions is None or lancements < executions:
        creneau = prochain_creneau(maintenant(), jour, heure, fuseau)
        verifier_le_creneau(creneau)
        journal(f"{maintenant().astimezone(fuseau):%Y-%m-%d %H:%M:%S} : prochain lancement {JOURS[creneau.weekday()]} {creneau:%d/%m/%Y à %H:%M}")
        while maintenant() < creneau:
            dormir(min(PAS_DE_VEILLE_S, max((creneau - maintenant()).total_seconds(), 0.0)))
        lancer_maintenant("créneau hebdomadaire")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    separation = argv.index("--") if "--" in argv else len(argv)
    options, commande = argv[:separation], argv[separation + 1:]
    parser = argparse.ArgumentParser(prog="python -m rapport.planificateur", description=__doc__.splitlines()[0])
    parser.add_argument("--jour", default="lundi", help="jour de la semaine (lundi par défaut)")
    parser.add_argument("--heure", default="07:00", help="HH:MM, heure du poste (07:00 par défaut)")
    parser.add_argument("--dossier", type=Path, default=Path("var/reports"), help="dossier de dépôt, pour le rattrapage")
    parser.add_argument("--sans-rattrapage", action="store_true", help="n'attend que le créneau, même si le rapport de la semaine manque")
    parser.add_argument("--executions", type=int, help="s'arrête après ce nombre de lancements (essai)")
    arguments = parser.parse_args(options)
    if not commande:
        print("Refusé : la commande du robot suit « -- » (python -m rapport.planificateur --jour lundi -- dev.py rpa-report)", file=sys.stderr)
        return 2
    try:
        return boucle(lire_jour(arguments.jour), lire_heure(arguments.heure), commande, arguments.dossier,
                      rattrapage=not arguments.sans_rattrapage, executions=arguments.executions)
    except HoraireInvalide as erreur:
        print(f"Refusé : {erreur}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Planificateur arrêté.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
