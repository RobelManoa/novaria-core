"""Contrôle des spécifications v1 (issue DOC-05) : bibliothèque standard seulement.

Critère d'acceptation : chaque exigence a une priorité et une preuve attendue. Ce test lit
docs/02-specifications/exigences.md, parcours.md et regles-de-gestion.md et vérifie :
- chaque exigence : identifiant bien formé et unique, critère, priorité (Doit, Devrait, Pourrait), preuve, état, issues du backlog ;
- chaque cas d'échec et chaque règle de gestion : renvoi vers des exigences qui existent, statut valide ;
- les liens relatifs des documents, et le bilan chiffré de exigences.md ;
- que le travail du backlog qui produit du code ou des données est couvert par au moins une exigence.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_specifications.py"   (Windows : py -3 ...)
"""
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SPEC = RACINE / "docs" / "02-specifications"
FICHIERS = ["README.md", "exigences.md", "parcours.md", "regles-de-gestion.md"]
PRIORITES = ("Doit", "Devrait", "Pourrait")
ETATS = ("Prouvé", "Partiel", "À faire")
STATUTS_CE = ("Défini", "Proposé")
STATUTS_RG = ("Définie", "Proposée")
DOMAINES = ("COL", "TRA", "ALE", "REP", "API", "TDB", "DON", "IA", "NFR")
MOTIF_EXIGENCE = re.compile(r"EXG-(?:%s)-\d{2}" % "|".join(DOMAINES))
# Issues du backlog qui livrent du code ou des données : chacune doit servir au moins une exigence.
ISSUES_A_COUVRIR = {
    "MS-03", "MS-04", "MS-06", "MS-07", "MS-08", "MS-09", "MS-10", "MS-11", "MS-12", "MS-13", "MS-14", "MS-15", "MS-16",
    "BE-02", "BE-03", "BE-04", "BE-05", "BE-06", "BE-07", "BE-08",
    "DAT-02", "DAT-03", "DAT-04", "DAT-05", "DAT-07",
    "IA-01", "IA-02", "IA-03", "IA-04", "IA-05", "IA-06", "IA-07", "IA-08", "IA-09", "IA-10",
    "FE-03", "FE-04", "FE-05", "FE-06", "FE-07", "CLD-07", "CLD-15",
}


def lire(nom: str) -> str:
    return (SPEC / nom).read_text(encoding="utf-8")


def lignes_de_tableau(nom: str, prefixe: str):
    """Cellules de chaque ligne de tableau dont la première cellule commence par `prefixe`."""
    for ligne in lire(nom).splitlines():
        if ligne.startswith(f"| {prefixe}"):
            yield [c.strip() for c in ligne.strip().strip("|").split("|")]


def identifiants_du_backlog() -> set[str]:
    sys.path.insert(0, str(RACINE / "scripts" / "github"))
    ancien = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # un fichier .pyc de ce dossier est suivi par Git : ne pas le réécrire
    try:
        import issues_data
        import issues_microservices  # noqa: F401  (étend issues_data.ISSUES)
        import issues_suite  # noqa: F401
        import issues_v3

        issues_v3.apply_amendments(issues_data.ISSUES)
        return {issue["id"] for issue in issues_data.ISSUES}
    finally:
        sys.dont_write_bytecode = ancien
        sys.path.remove(str(RACINE / "scripts" / "github"))


class Specifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exigences = list(lignes_de_tableau("exigences.md", "EXG-"))
        cls.cas = list(lignes_de_tableau("parcours.md", "CE-"))
        cls.regles = list(lignes_de_tableau("regles-de-gestion.md", "RG-"))
        cls.ids = {ligne[0] for ligne in cls.exigences}
        cls.backlog = identifiants_du_backlog()

    # --- exigences ---------------------------------------------------------------------------------------------
    def test_il_y_a_des_exigences_dans_chaque_domaine(self):
        par_domaine = Counter(ligne[0].split("-")[1] for ligne in self.exigences)
        self.assertEqual(sorted(par_domaine), sorted(DOMAINES))
        self.assertGreaterEqual(len(self.exigences), 40)

    def test_chaque_ligne_d_exigence_a_sept_colonnes(self):
        for ligne in self.exigences:
            with self.subTest(exigence=ligne[0]):
                self.assertEqual(len(ligne), 7)

    def test_identifiants_bien_formes_uniques_et_continus(self):
        identifiants = [ligne[0] for ligne in self.exigences]
        self.assertEqual(len(identifiants), len(set(identifiants)), "identifiant en double")
        for identifiant in identifiants:
            self.assertRegex(identifiant, rf"^{MOTIF_EXIGENCE.pattern}$")
        for domaine in DOMAINES:
            numeros = [int(i[-2:]) for i in identifiants if i.split("-")[1] == domaine]
            self.assertEqual(numeros, list(range(1, len(numeros) + 1)), f"numérotation du domaine {domaine}")

    def test_chaque_exigence_a_un_critere_une_priorite_et_une_preuve(self):
        for identifiant, contexte, critere, priorite, preuve, etat, issues in self.exigences:
            with self.subTest(exigence=identifiant):
                self.assertTrue(contexte.startswith("**"), "le contexte commence par l'intitulé en gras")
                self.assertGreater(len(critere), 20, "critère mesurable absent")
                self.assertIn(priorite, PRIORITES)
                self.assertGreater(len(preuve), 8, "preuve attendue absente")
                self.assertNotRegex(preuve + critere, r"(?i)à compléter|todo|à définir par")

    def test_chaque_exigence_a_un_etat_valide(self):
        for ligne in self.exigences:
            with self.subTest(exigence=ligne[0]):
                self.assertTrue(ligne[5].startswith(ETATS), ligne[5])

    def test_un_etat_partiel_dit_ce_qui_existe_et_ce_qui_manque(self):
        for ligne in self.exigences:
            if ligne[5].startswith("Partiel"):
                with self.subTest(exigence=ligne[0]):
                    self.assertRegex(ligne[5], r"^Partiel : .{15,}")

    def test_les_issues_citees_existent_au_backlog(self):
        for ligne in self.exigences:
            cites = re.findall(r"[A-Z]+-\d+", ligne[6])
            with self.subTest(exigence=ligne[0]):
                self.assertTrue(cites, "aucune issue liée")
                self.assertLessEqual(set(cites), self.backlog, "issue inconnue du backlog")

    def test_le_travail_du_backlog_est_couvert_par_une_exigence(self):
        liees = {i for ligne in self.exigences for i in re.findall(r"[A-Z]+-\d+", ligne[6])}
        self.assertLessEqual(ISSUES_A_COUVRIR, self.backlog, "liste de contrôle périmée")
        self.assertEqual(sorted(ISSUES_A_COUVRIR - liees), [], "issues sans exigence")

    def test_le_bilan_correspond_au_tableau(self):
        texte = lire("exigences.md")
        priorites = Counter(ligne[3] for ligne in self.exigences)
        etats = Counter(next(e for e in ETATS if ligne[5].startswith(e)) for ligne in self.exigences)
        attendu = {
            "Exigences": str(len(self.exigences)),
            "Doit / Devrait / Pourrait": " / ".join(str(priorites[p]) for p in PRIORITES),
            "Prouvé / Partiel / À faire": " / ".join(str(etats[e]) for e in ETATS),
        }
        for mesure, valeur in attendu.items():
            with self.subTest(mesure=mesure):
                self.assertIn(f"| {mesure} | {valeur} |", texte)

    # --- cas d'échec et règles ---------------------------------------------------------------------------------
    def test_chaque_cas_d_echec_renvoie_a_des_exigences_qui_existent(self):
        identifiants = [ligne[0] for ligne in self.cas]
        self.assertEqual(identifiants, [f"CE-{n:02d}" for n in range(1, len(identifiants) + 1)])
        for ligne in self.cas:
            with self.subTest(cas=ligne[0]):
                self.assertEqual(len(ligne), 6)
                self.assertTrue(ligne[4].startswith(STATUTS_CE), ligne[4])
                cites = set(MOTIF_EXIGENCE.findall(ligne[5]))
                self.assertTrue(cites)
                self.assertLessEqual(cites, self.ids)

    def test_chaque_regle_a_un_controle_et_renvoie_a_des_exigences_qui_existent(self):
        identifiants = [ligne[0] for ligne in self.regles]
        self.assertEqual(identifiants, [f"RG-{n:02d}" for n in range(1, len(identifiants) + 1)])
        for ligne in self.regles:
            with self.subTest(regle=ligne[0]):
                self.assertEqual(len(ligne), 6)
                self.assertGreater(len(ligne[2]), 10, "contrôle absent")
                self.assertTrue(ligne[4].startswith(STATUTS_RG), ligne[4])
                cites = set(MOTIF_EXIGENCE.findall(ligne[5]))
                self.assertTrue(cites)
                self.assertLessEqual(cites, self.ids)

    def test_aucune_reference_a_une_exigence_inexistante(self):
        for nom in FICHIERS:
            inconnues = set(MOTIF_EXIGENCE.findall(lire(nom))) - self.ids
            with self.subTest(fichier=nom):
                self.assertEqual(sorted(inconnues), [])

    def test_les_exigences_fonctionnelles_apparaissent_dans_un_parcours_ou_une_regle(self):
        contexte = lire("parcours.md") + lire("regles-de-gestion.md")
        for identifiant in sorted(self.ids):
            if identifiant.split("-")[1] == "NFR":
                continue
            with self.subTest(exigence=identifiant):
                self.assertIn(identifiant, contexte)

    # --- documents ---------------------------------------------------------------------------------------------
    def test_les_liens_relatifs_se_resolvent(self):
        for nom in FICHIERS:
            for cible in re.findall(r"\]\(([^)\s]+)\)", lire(nom)):
                if cible.startswith(("http", "#", "mailto:")):
                    continue
                with self.subTest(fichier=nom, lien=cible):
                    self.assertTrue((SPEC / cible.split("#")[0]).exists())

    def test_les_documents_sont_sans_marqueur_de_travail(self):
        for nom in FICHIERS[1:]:
            with self.subTest(fichier=nom):
                self.assertNotRegex(lire(nom), r"\[À COMPLÉTER|TODO|XXX")

    def test_les_chiffres_du_readme_correspondent_aux_documents(self):
        readme = lire("README.md")
        parcours = len(re.findall(r"^### P\d+\.", lire("parcours.md"), re.M))
        for attendu in (
            f"{len(self.exigences)} exigences vérifiables",
            f"{parcours} parcours nominaux et {len(self.cas)} cas d'échec",
            f"{len(self.regles)} règles sur",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, readme)

    def test_le_readme_liste_les_trois_documents(self):
        readme = lire("README.md")
        for nom in FICHIERS[1:]:
            self.assertIn(f"]({nom})", readme)


if __name__ == "__main__":
    unittest.main()
