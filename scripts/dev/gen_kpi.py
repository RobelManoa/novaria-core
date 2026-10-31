#!/usr/bin/env python3
"""Génère la migration des vues d'indicateurs à partir de data/dwh/sql/kpi/ (DAT-07).

Les fichiers `data/dwh/sql/kpi/NN_*.sql` sont la source : une vue par fichier, relue et testée là. La migration
`db/postgres/migrations/0006_kpi_vues.sql` n'en est que la concaténation, parce que le conteneur de migration ne monte que
`db/postgres/migrations`. Un test (`test_kpi.py`) échoue si les deux divergent.

    python scripts/dev/gen_kpi.py

Une migration appliquée ne se réécrit pas. Pour modifier un indicateur après l'application de la 0006 : changer le fichier de
`data/dwh/sql/kpi/`, puis écrire une nouvelle migration `NNNN_kpi_….sql` qui fait `DROP VIEW` puis recrée la vue, et adapter le
test de synchronisation. Le script n'a ni option ni chemin en argument : il écrit toujours la 0006.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DOSSIER = RACINE / "data" / "dwh" / "sql" / "kpi"
MIGRATION = RACINE / "db" / "postgres" / "migrations" / "0006_kpi_vues.sql"
ENTETE = (
    "-- 0006 · Vues d'indicateurs décisionnels (DAT-07) : cinq vues dwh.kpi_*, lecture seule.\n"
    "-- Généré par scripts/dev/gen_kpi.py depuis data/dwh/sql/kpi/ : ne pas modifier à la main.\n"
    "-- Définitions, sources, limites : docs/03-donnees/kpi.md.\n"
)


def fichiers() -> list[Path]:
    return sorted(DOSSIER.glob("[0-9][0-9]_*.sql"))


def generer() -> str:
    morceaux = [ENTETE]
    for fichier in fichiers():
        texte = fichier.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n") + "\n"
        morceaux.append(f"\n-- ===== {fichier.name} =====\n{texte}")
    return "".join(morceaux)


def principal() -> int:
    MIGRATION.write_text(generer(), encoding="utf-8", newline="\n")
    print(f"{MIGRATION.relative_to(RACINE).as_posix()} : {len(fichiers())} fichiers de vue")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
