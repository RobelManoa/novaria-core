"""Lot ETL planifié : ingestion, nettoyage, puis chargement des fenêtres, en une commande (DAT-06).

    cd data/etl
    python -m pipelines.lot --day 2026-10-29 [--windows fenetres.csv --run-id demo-2026-10-30]

C'est la commande que lancent le `cron` de Linux et le Planificateur de tâches de Windows (data/etl/planification/), et
`python scripts/dev/dev.py etl-lot`. Chaque étape est celle de son propre pipeline, avec les mêmes options et les mêmes
variables (MONGO_URL, POSTGRES_URL). Sans `--day`, le lot traite la veille en UTC (une journée complète).

- ingestion puis nettoyage de Paris : le nettoyage a besoin du fichier brut, il est sauté si l'ingestion échoue ;
- chargement des fenêtres : indépendant du jeu de Paris (ADR-027, section 3.2), sauté sans `--windows`.
Le code de sortie est 0 si toutes les étapes tentées ont réussi, 1 sinon : le planificateur voit l'échec. Rejouer un lot est
sans effet de bord : chaque étape est idempotente (fichier identique, rejets remplacés, clé primaire de l'entrepôt).
Équivalent AWS Glue (non exécuté) : docs/03-donnees/etl-planifie-local.md.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pipelines import charger_entrepot, ingerer_paris, nettoyer_paris

REUSSIE, ECHOUEE, SAUTEE = "réussie", "ÉCHEC", "sautée"
Etape = Callable[[Sequence[str]], int]


@dataclass(frozen=True)
class Bilan:
    etape: str
    etat: str
    detail: str = ""


def la_veille(maintenant: datetime) -> date:
    return (maintenant.astimezone(UTC) - timedelta(days=1)).date()


def executer(jour: date, *, fenetres: Path | None = None, run_id: str | None = None, ingestion: Etape = ingerer_paris.principal,
             nettoyage: Etape = nettoyer_paris.principal, chargement: Etape = charger_entrepot.principal) -> list[Bilan]:
    bilans = []

    def lancer(nom: str, etape: Etape, options: list[str]) -> bool:
        print(f"\n=== {nom} ===", flush=True)
        succes = etape(options) == 0
        bilans.append(Bilan(nom, REUSSIE if succes else ECHOUEE))
        return succes

    if lancer("Ingestion de Paris", ingestion, ["--day", jour.isoformat()]):
        lancer("Nettoyage de Paris", nettoyage, ["--day", jour.isoformat()])
    else:
        bilans.append(Bilan("Nettoyage de Paris", SAUTEE, "pas de fichier brut : l'ingestion a échoué"))
    if fenetres is None:
        bilans.append(Bilan("Chargement des fenêtres", SAUTEE, "aucun fichier de fenêtres demandé (--windows)"))
    else:
        lancer("Chargement des fenêtres", chargement, ["--file", str(fenetres), "--run-id", run_id or ""])
    return bilans


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(description="Lot ETL : ingestion et nettoyage de Paris, chargement de fenêtres.")
    parseur.add_argument("--day", type=date.fromisoformat, metavar="AAAA-MM-JJ", help="jour UTC à traiter (la veille par défaut)")
    parseur.add_argument("--windows", type=Path, metavar="FICHIER", help="fichier CSV de fenêtres à charger dans l'entrepôt")
    parseur.add_argument("--run-id", help="identifiant du run des fenêtres (obligatoire avec --windows)")
    return parseur


def principal(argv: Sequence[str] | None = None, *, maintenant: Callable[[], datetime] = lambda: datetime.now(UTC),
              **etapes: Etape) -> int:
    parseur = construire_parseur()
    arguments = parseur.parse_args(argv)
    if arguments.windows and not arguments.run_id:
        parseur.error("--windows demande aussi --run-id")
    debut = maintenant()
    jour = arguments.day or la_veille(debut)
    print(f"Lot ETL du {jour} (démarré à {debut:%Y-%m-%d %H:%M:%S} UTC)")
    bilans = executer(jour, fenetres=arguments.windows, run_id=arguments.run_id, **etapes)
    print("\n=== Bilan du lot ===")
    for bilan in bilans:
        print(f"{bilan.etape:<26}: {bilan.etat}" + (f" ({bilan.detail})" if bilan.detail else ""))
    return 1 if any(bilan.etat == ECHOUEE for bilan in bilans) else 0


if __name__ == "__main__":
    sys.exit(principal())
