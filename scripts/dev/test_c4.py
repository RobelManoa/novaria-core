"""Contrôle des diagrammes C4 (issue DOC-03) : bibliothèque standard seulement.

Critère d'acceptation : les trois vues portent les mêmes noms. Chaque nom employé sur la première ligne d'une
étiquette de diagramme doit figurer dans le catalogue de docs/01-architecture/c4/README.md.

Lancement : python3 -m unittest discover -s scripts/dev   (Windows : py -3 -m unittest discover -s scripts/dev)
"""
import re
import unittest
from pathlib import Path

C4 = Path(__file__).resolve().parents[2] / "docs" / "01-architecture" / "c4"
VUES = ["01-contexte.md", "02-conteneurs.md", "03-composants.md"]
ETIQUETTE = re.compile(r'\b\w+\s*(?:\[\(|\(\[|\[\[|\[|\(\()\s*"([^"]+)"')


def lire(nom: str) -> str:
    return (C4 / nom).read_text(encoding="utf-8")


def noms_du_catalogue() -> set[str]:
    """Première cellule de chaque ligne de tableau entre « ## Catalogue » et le titre suivant."""
    texte = lire("README.md")
    debut = texte.index("## Catalogue des noms")
    fin = texte.index("\n## ", debut + 1)
    noms = set()
    for ligne in texte[debut:fin].splitlines():
        if not ligne.startswith("|"):
            continue
        cellule = ligne.strip().strip("|").split("|")[0].strip()
        if cellule and cellule != "Nom" and not set(cellule) <= {"-", " "}:
            noms.add(cellule)
    return noms


def etiquettes(nom_de_vue: str) -> list[tuple[str, str]]:
    """(vue, première ligne de l'étiquette) pour chaque nœud de chaque bloc Mermaid."""
    resultat = []
    for bloc in re.findall(r"```mermaid\n(.*?)```", lire(nom_de_vue), re.S):
        for ligne in bloc.splitlines():
            if ligne.strip().startswith("subgraph"):
                continue
            for etiquette in ETIQUETTE.findall(ligne):
                resultat.append((nom_de_vue, etiquette.split("<br/>")[0].strip()))
    return resultat


class DiagrammesC4(unittest.TestCase):
    def test_le_catalogue_n_est_pas_vide(self):
        self.assertGreaterEqual(len(noms_du_catalogue()), 40)

    def test_chaque_vue_contient_un_diagramme(self):
        for vue in VUES:
            with self.subTest(vue=vue):
                self.assertTrue(etiquettes(vue), f"{vue} : aucun nœud Mermaid trouvé")

    def test_chaque_nom_employe_figure_au_catalogue(self):
        catalogue = noms_du_catalogue()
        inconnus = sorted({f"{vue} : {nom}" for vue in VUES for _, nom in etiquettes(vue) if nom not in catalogue})
        self.assertEqual(inconnus, [], "Noms absents du catalogue du README (ou nom différent d'une vue à l'autre)")

    def test_les_conteneurs_de_la_vue_2_reviennent_dans_la_vue_3(self):
        """Les éléments cités en vue 3 comme voisins gardent le nom de la vue 2."""
        vue2 = {nom for _, nom in etiquettes("02-conteneurs.md")}
        for nom in ("Passerelle d'API", "Bus d'événements", "Modèle IA", "PostgreSQL", "MongoDB", "API métier"):
            with self.subTest(nom=nom):
                self.assertIn(nom, vue2)

    def test_la_legende_et_les_vues_sont_liees(self):
        readme = lire("README.md")
        for vue in VUES:
            self.assertIn(vue, readme)


if __name__ == "__main__":
    unittest.main()
