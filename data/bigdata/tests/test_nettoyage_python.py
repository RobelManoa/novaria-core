"""Les deux lancements de l'ETL Python : même résultat, séquentiel ou réparti par fichier."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests import support  # noqa: F401 : chemins d'import

from bigdata import empreinte, generer, nettoyage_python


def deux_jours(dossier: Path) -> list[Path]:
    return [generer.ecrire_le_jour(dossier, date(2026, 10, jour), capteurs=60).chemin for jour in (1, 2)]


class EtlPython(unittest.TestCase):
    def test_sequentiel_et_parallele_rendent_le_meme_bilan_et_les_memes_fichiers(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            fichiers = deux_jours(dossier)
            sequentiel = nettoyage_python.sequentiel(fichiers, generer.MAINTENANT)
            empreinte_sequentielle = empreinte.depuis_les_sorties_python(dossier, [f.name for f in fichiers])
            for sortie in ("propre", "rejets"):
                for fichier in (dossier / sortie).iterdir():
                    fichier.unlink()
            parallele = nettoyage_python.parallele(fichiers, generer.MAINTENANT, 2)
            empreinte_parallele = empreinte.depuis_les_sorties_python(dossier, [f.name for f in fichiers])
        self.assertEqual(sequentiel, parallele)
        self.assertEqual(empreinte_sequentielle, empreinte_parallele)
        self.assertEqual(sequentiel["rows_read"], sequentiel["rows_clean"] + sequentiel["rows_rejected"])

    def test_additionner_somme_les_compteurs_et_les_regles(self):
        a = {"rows_read": 3, "rows_clean": 2, "rows_rejected": 1, "by_rule": {"TYPE_INVALID": 1}, "flags": {"MISSING_OCCUPANCY": 1}}
        b = {"rows_read": 2, "rows_clean": 1, "rows_rejected": 1, "by_rule": {"TYPE_INVALID": 1}, "flags": {}}
        self.assertEqual(
            nettoyage_python.additionner([a, b]),
            {"rows_read": 5, "rows_clean": 3, "rows_rejected": 2, "by_rule": {"TYPE_INVALID": 2}, "flags": {"MISSING_OCCUPANCY": 1}},
        )
        self.assertEqual(nettoyage_python.additionner([])["rows_read"], 0)

    def test_au_moins_un_processus(self):
        with self.assertRaises(ValueError):
            nettoyage_python.parallele([], generer.MAINTENANT, 0)


if __name__ == "__main__":
    unittest.main()
