"""Cohérence du choix de la base non relationnelle (issue DOC-10) : bibliothèque standard seulement.

MongoDB est la base non relationnelle du projet (ADR-002). DynamoDB et DocumentDB ne peuvent apparaître que
là où ils sont expliqués : option écartée, ou simple verrou d'état Terraform.
Lancement : python3 -m unittest discover -s scripts/dev   (Windows : py -3 -m unittest discover -s scripts/dev)
"""
import re
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
ADR = DOCS / "01-architecture" / "adr"
AUTORISES = {
    "dynamodb": {"ADR-002-postgresql-mongodb.md", "ADR-020-terraform.md", "correction-diapositive-architecture.md"},
    "documentdb": {"ADR-022-hebergement-mongodb.md", "correction-diapositive-architecture.md"},
}


def fichiers_avec(nom: str) -> set[str]:
    return {
        chemin.name
        for chemin in DOCS.rglob("*.md")
        if re.search(nom, chemin.read_text(encoding="utf-8"), re.IGNORECASE)
    }


class BaseNonRelationnelle(unittest.TestCase):
    def test_dynamodb_n_apparait_que_la_ou_il_est_explique(self):
        self.assertEqual(sorted(fichiers_avec("dynamodb") - AUTORISES["dynamodb"]), [])

    def test_documentdb_n_apparait_que_la_ou_il_est_explique(self):
        self.assertEqual(sorted(fichiers_avec("documentdb") - AUTORISES["documentdb"]), [])

    def test_adr_002_retient_mongodb_et_ecarte_dynamodb(self):
        texte = (ADR / "ADR-002-postgresql-mongodb.md").read_text(encoding="utf-8")
        self.assertRegex(texte, r"\| \*\*C\. PostgreSQL \+ MongoDB\*\* .*\*\*Retenue\*\*")
        self.assertRegex(texte, r"\| D\. PostgreSQL \+ DynamoDB .*Écartée")

    def test_adr_020_precise_que_dynamodb_n_est_pas_la_base_du_projet(self):
        texte = (ADR / "ADR-020-terraform.md").read_text(encoding="utf-8")
        self.assertIn("sans lien avec la base non relationnelle du projet, qui est MongoDB", texte)

    def test_le_nombre_de_mentions_de_mongodb_domine_dans_les_adr(self):
        mentions = sum(len(re.findall("mongodb", p.read_text(encoding="utf-8"), re.IGNORECASE)) for p in ADR.glob("ADR-*.md"))
        self.assertGreater(mentions, 50)


if __name__ == "__main__":
    unittest.main()
