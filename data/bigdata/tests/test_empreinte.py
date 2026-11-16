"""L'empreinte des résultats : des entiers identiques sur les deux moteurs, indépendants de l'ordre des lignes."""

import json
import tempfile
import unittest
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from bigdata import empreinte


def ecrire_sorties(dossier: Path, nom: str, propres: list[list[str]], rejets: list[dict]) -> None:
    (dossier / "propre").mkdir(exist_ok=True)
    (dossier / "rejets").mkdir(exist_ok=True)
    stem = nom.removesuffix(".csv")
    entete = ";".join(empreinte.COLONNES_PROPRES)
    (dossier / "propre" / f"{stem}.csv").write_text("\n".join([entete, *[";".join(ligne) for ligne in propres]]) + "\n", encoding="utf-8")
    (dossier / "rejets" / f"{stem}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rejets), encoding="utf-8")


LIGNE_A = ["12", "Rue_A", "2026-10-18T10:00:00Z", "199.0", "2.03556", "Fluide", "Ouvert", "1", "2", "", "1"]
LIGNE_B = ["13", "Rue_B", "2026-10-18T10:00:00Z", "10.5", "", "Inconnu", "Ouvert", "3", "4", "MISSING_OCCUPANCY", "2"]
REJET = {"source_ref": "f.csv#3", "rule": "TYPE_INVALID", "reason": "x", "payload": {}}


class Empreinte(unittest.TestCase):
    def test_entier_est_floor_de_x_fois_echelle_plus_un_demi(self):
        self.assertEqual(empreinte.entier("199.0", 1000), "199000")
        self.assertEqual(empreinte.entier("2.03556", 100_000), "203556")
        self.assertEqual(empreinte.entier("0.0005", 1000), "1")  # arrondi à la demi-unité supérieure
        self.assertEqual(empreinte.entier("", 1000), "")

    def test_la_ligne_canonique_porte_le_fichier_et_les_montants_entiers(self):
        self.assertEqual(
            empreinte.ligne_canonique("f.csv", LIGNE_B),
            "f.csv|13|Rue_B|2026-10-18T10:00:00Z|10500||Inconnu|Ouvert|3|4|MISSING_OCCUPANCY|2",
        )

    def test_empreinte_des_sorties_python(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            ecrire_sorties(dossier, "f.csv", [LIGNE_A, LIGNE_B], [REJET, REJET | {"source_ref": "f.csv#4", "rule": "DUPLICATE_KEY"}])
            resultat = empreinte.depuis_les_sorties_python(dossier, ["f.csv"])
        self.assertEqual(resultat["propres"]["lignes"], 2)
        self.assertEqual(resultat["propres"]["debit_milliemes"], 199_000 + 10_500)
        self.assertEqual((resultat["propres"]["occupations"], resultat["propres"]["occupation_cent_milliemes"]), (1, 203_556))
        self.assertEqual(
            resultat["propres"]["somme_crc"],
            empreinte.crc(empreinte.ligne_canonique("f.csv", LIGNE_A)) + empreinte.crc(empreinte.ligne_canonique("f.csv", LIGNE_B)),
        )
        self.assertEqual(resultat["rejets"]["par_regle"], {"DUPLICATE_KEY": 1, "TYPE_INVALID": 1})
        self.assertEqual(resultat["rejets"]["somme_crc"], empreinte.crc("f.csv#3|TYPE_INVALID") + empreinte.crc("f.csv#4|DUPLICATE_KEY"))

    def test_l_ordre_des_lignes_ne_change_pas_l_empreinte_mais_une_valeur_oui(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            ecrire_sorties(dossier, "f.csv", [LIGNE_A, LIGNE_B], [REJET])
            endroit = empreinte.depuis_les_sorties_python(dossier, ["f.csv"])
            ecrire_sorties(dossier, "f.csv", [LIGNE_B, LIGNE_A], [REJET])
            envers = empreinte.depuis_les_sorties_python(dossier, ["f.csv"])
            ecrire_sorties(dossier, "f.csv", [LIGNE_A, LIGNE_B[:3] + ["10.6"] + LIGNE_B[4:]], [REJET])
            modifie = empreinte.depuis_les_sorties_python(dossier, ["f.csv"])
        self.assertEqual(endroit, envers)
        self.assertNotEqual(endroit["propres"], modifie["propres"])

    def test_le_vide(self):
        self.assertEqual(empreinte.vide()["propres"]["lignes"], 0)


if __name__ == "__main__":
    unittest.main()
