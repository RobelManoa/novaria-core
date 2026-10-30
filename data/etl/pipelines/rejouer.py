"""Rejeu du chargement et rapport de comparaison (DAT-06) : mêmes totaux avant et après, par la clé d'idempotence.

    cd data/etl
    python -m pipelines.rejouer --file fenetres.csv --run-id demo-2026-10-30 --from-scratch --report rapport.md

Trois passes sur le même fichier et le même run_id, totaux relevés dans l'entrepôt après chacune :
1. chargement initial ;
2. rejeu à l'identique : aucune ligne créée, aucune valeur changée ;
3. reprise après incident : une partie des lignes du run est supprimée (chargement interrompu), puis le fichier est
   rechargé : les lignes manquantes reviennent, rien n'est dupliqué.
Le rapport conclut « identiques » si les trois relevés (lignes, véhicules, débit, empreinte) sont égaux. Le job AWS Glue
équivalent n'est pas exécuté (ADR-023, ADR-025) : sa colonne reste « non exécuté ».
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pipelines.charger_entrepot import (
    Entrepot,
    EntrepotPostgres,
    ErreurChargement,
    Resultat,
    Totaux,
    charger_fichier,
)
from pipelines.sorties import ErreurSortie, RejetsPostgres, SortieRejets

PART_RETIREE = 10  # la reprise retire un dixième des lignes du run (au moins une)


class EntrepotRejouable(Entrepot, Protocol):
    def supprimer(self, run_id: str, nombre: int | None = None) -> int:
        """Supprime les `nombre` premières lignes du run (dans l'ordre de leur clé), ou toutes si `nombre` est vide."""


@dataclass(frozen=True)
class Passe:
    nom: str
    resultat: Resultat
    retirees: int = 0  # lignes supprimées juste avant cette passe


@dataclass(frozen=True)
class Comparaison:
    passes: tuple[Passe, ...]
    purge: int | None  # lignes du run supprimées avant la première passe ; vide si l'état de départ a été conservé

    @property
    def totaux(self) -> list[Totaux]:
        return [passe.resultat.totaux for passe in self.passes]

    @property
    def identiques(self) -> bool:
        return all(totaux == self.totaux[0] for totaux in self.totaux)


def rejouer(fichier: Path, run_id: str, *, entrepot: EntrepotRejouable, rejets_pg: SortieRejets | None = None,
            repartir_de_zero: bool = False) -> Comparaison:
    purge = entrepot.supprimer(run_id) if repartir_de_zero else None
    passes = [Passe("Chargement initial", charger_fichier(fichier, run_id, entrepot=entrepot, rejets_pg=rejets_pg))]
    passes.append(Passe("Rejeu à l'identique", charger_fichier(fichier, run_id, entrepot=entrepot, rejets_pg=rejets_pg)))
    retirees = entrepot.supprimer(run_id, max(1, passes[0].resultat.totaux.lignes // PART_RETIREE))
    passes.append(Passe("Reprise après suppression", charger_fichier(fichier, run_id, entrepot=entrepot, rejets_pg=rejets_pg), retirees))
    return Comparaison(tuple(passes), purge)


def rapport(comparaison: Comparaison, *, fichier: Path, run_id: str, instant: datetime) -> str:
    premiere = comparaison.passes[0].resultat
    lignes = [
        "# Rapport de comparaison — rejeu du chargement (DAT-06)",
        "",
        f"- Date : {instant:%Y-%m-%d %H:%M} UTC",
        f"- Fichier : `{fichier.name}` (sha256 `{premiere.sha256[:12]}…`), {premiere.lues} lignes lues",
        f"- Run : `{run_id}`",
        "- Clé d'idempotence : clé primaire de `dwh.fact_traffic_window` (tronçon, début, taille de fenêtre, run_id)",
        "- État de départ : " + ("run supprimé avant la première passe (" + str(comparaison.purge) + " lignes)" if comparaison.purge is not None
                                else "conservé tel quel (la première passe peut donc être elle-même un rejeu)"),
        "",
        "| Passe | Lignes retirées avant | Chargées | Rejetées | Créées | Lignes en base | Véhicules | Débit | Empreinte |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for passe in comparaison.passes:
        r, t = passe.resultat, passe.resultat.totaux
        lignes.append(f"| {passe.nom} | {passe.retirees} | {r.chargees} | {r.rejetees} | {r.inserees} | {t.lignes} | {t.vehicules} | {t.debit} "
                      f"| `{t.empreinte}` |")
    lignes += [
        "",
        "## Verdict",
        "",
        ("**Totaux identiques** aux trois passes : le rejeu ne crée aucune ligne, ne change aucune valeur, et la reprise rétablit "
         "exactement les lignes supprimées." if comparaison.identiques else
         "**Totaux DIFFÉRENTS** : l'idempotence n'est pas démontrée, voir le tableau ci-dessus."),
        "",
        "## Comparaison avec AWS Glue",
        "",
        "Le job Glue équivalent est documenté (`docs/03-donnees/etl-planifie-local.md`) et **non exécuté** : exécution locale d'abord "
        "(ADR-023, ADR-025). Colonne Glue : non exécuté ; aucun total Glue n'est annoncé ici.",
        "",
    ]
    return "\n".join(lignes)


class EntrepotPostgresRejouable(EntrepotPostgres):
    def supprimer(self, run_id: str, nombre: int | None = None) -> int:
        import psycopg

        limite = "" if nombre is None else " ORDER BY window_start, road_segment_key, window_size_s LIMIT %s"
        sql = (
            "DELETE FROM dwh.fact_traffic_window f USING (SELECT road_segment_key, window_start, window_size_s "  # noqa: S608 - fragment constant, valeurs par paramètres
            f"FROM dwh.fact_traffic_window WHERE run_id = %s{limite}) d "
            "WHERE f.run_id = %s AND f.road_segment_key = d.road_segment_key AND f.window_start = d.window_start "
            "AND f.window_size_s = d.window_size_s"
        )
        parametres = (run_id, run_id) if nombre is None else (run_id, nombre, run_id)
        try:
            with self._connexion.transaction(), self._connexion.cursor() as curseur:
                curseur.execute(sql, parametres)
                return curseur.rowcount
        except psycopg.Error as erreur:
            raise ErreurSortie(f"Suppression des lignes du run impossible ({type(erreur).__name__}).") from erreur


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(description="Charge un fichier de fenêtres trois fois et compare les totaux de l'entrepôt.")
    parseur.add_argument("--file", type=Path, required=True, help="fichier CSV de fenêtres")
    parseur.add_argument("--run-id", required=True, help="identifiant du run (les lignes des autres runs ne sont jamais touchées)")
    parseur.add_argument("--from-scratch", action="store_true", help="supprime d'abord les lignes de ce run (première passe sur base vide)")
    parseur.add_argument("--report", type=Path, help="écrit le rapport de comparaison (Markdown) dans ce fichier")
    parseur.add_argument("--postgres-url", default=os.environ.get("POSTGRES_URL"), help="adresse PostgreSQL (sinon variable POSTGRES_URL)")
    return parseur


def principal(argv: Sequence[str] | None = None, *, entrepot: EntrepotRejouable | None = None, rejets_pg: SortieRejets | None = None,
              maintenant: datetime | None = None) -> int:
    arguments = construire_parseur().parse_args(argv)
    try:
        if entrepot is None:
            if not arguments.postgres_url:
                raise ErreurChargement("Adresse PostgreSQL absente : variable POSTGRES_URL ou option --postgres-url "
                                       "(python scripts/dev/dev.py etl-rejouer la construit depuis .env).")
            entrepot = EntrepotPostgresRejouable.depuis_url(arguments.postgres_url)
            rejets_pg = RejetsPostgres(entrepot.connexion)
        comparaison = rejouer(arguments.file, arguments.run_id, entrepot=entrepot, rejets_pg=rejets_pg, repartir_de_zero=arguments.from_scratch)
    except (ErreurChargement, ErreurSortie) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1
    finally:
        if hasattr(entrepot, "fermer"):
            entrepot.fermer()
    texte = rapport(comparaison, fichier=arguments.file, run_id=arguments.run_id, instant=maintenant or datetime.now(UTC))
    if arguments.report:
        arguments.report.write_text(texte, encoding="utf-8", newline="\n")
    print(texte)
    return 0 if comparaison.identiques else 2


if __name__ == "__main__":
    sys.exit(principal())
