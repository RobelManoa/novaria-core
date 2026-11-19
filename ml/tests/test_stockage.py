"""Port `ObjectStore` (ADR-025, LOC-05) : un test de contrat joué sur chaque adaptateur, la liste par préfixe, le choix de
l'adaptateur par `STORAGE_BACKEND`, et la preuve que les modèles et les jeux de données passent par le port.

Un seul adaptateur est écrit (le dossier local). Une doublure en mémoire joue les mêmes tests : elle montre que le
contrat ne dépend pas du disque, donc qu'un futur adaptateur S3 pourra le passer sans changer le code appelant.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401 : chemins d'import

from jeu_entrainement import construire, integrite
from preparation import donnees
from stockage import (
    BACKEND_LOCAL,
    LISTE_MAX,
    ObjectStore,
    ObjetAbsent,
    ObjetDejaEcrit,
    StockageErreur,
    StockageLocal,
    StockageNonConfigure,
    ouvrir_magasin,
    ouvrir_magasin_de_jeu,
    ranger_a_l_identique,
    sha256,
    verifier_la_cle,
)
from stockage import objets
from tests.support import petit_catalogue


class StockageEnMemoire:
    """Doublure du port : mêmes règles que `StockageLocal`, sans disque. Sert au contrat et à la preuve de passage."""

    def __init__(self) -> None:
        self.objets: dict[str, bytes] = {}
        self.appels: list[tuple[str, str]] = []

    def put(self, cle: str, octets: bytes, *, remplacer: bool = False) -> str:
        self.appels.append(("put", cle))
        verifier_la_cle(cle, majuscules=True)
        if cle in self.objets and not remplacer:
            raise ObjetDejaEcrit(cle)
        self.objets[cle] = octets
        return sha256(octets)

    def get(self, cle: str) -> bytes:
        self.appels.append(("get", cle))
        verifier_la_cle(cle, majuscules=True)
        if cle not in self.objets:
            raise ObjetAbsent(cle)
        return self.objets[cle]

    def exists(self, cle: str) -> bool:
        self.appels.append(("exists", cle))
        return verifier_la_cle(cle, majuscules=True) in self.objets

    def list(self, prefixe: str = "") -> list[str]:
        self.appels.append(("list", prefixe))
        return sorted(cle for cle in self.objets if cle.startswith(prefixe))


class ContratDuPort:
    """Ce que tout adaptateur doit tenir ; `fabriquer()` rend un magasin vide."""

    def fabriquer(self) -> ObjectStore:
        raise NotImplementedError

    def test_ecrire_puis_relire_a_l_identique(self):
        magasin = self.fabriquer()
        self.assertEqual(magasin.put("run-1/modele.json", b"abc"), sha256(b"abc"))
        self.assertEqual(magasin.get("run-1/modele.json"), b"abc")
        self.assertTrue(magasin.exists("run-1/modele.json"))

    def test_une_cle_absente(self):
        magasin = self.fabriquer()
        self.assertFalse(magasin.exists("run-1/absent.json"))
        with self.assertRaises(ObjetAbsent):
            magasin.get("run-1/absent.json")

    def test_un_objet_versionne_ne_se_reecrit_pas_sauf_le_pointeur(self):
        magasin = self.fabriquer()
        magasin.put("run-1/modele.json", b"v1")
        with self.assertRaises(ObjetDejaEcrit):
            magasin.put("run-1/modele.json", b"v2")
        self.assertEqual(magasin.get("run-1/modele.json"), b"v1")
        magasin.put("en-service.json", b"a")
        magasin.put("en-service.json", b"b", remplacer=True)
        self.assertEqual(magasin.get("en-service.json"), b"b")

    def test_lister_par_prefixe_dans_l_ordre(self):
        magasin = self.fabriquer()
        for cle in ("run-2/modele.json", "run-1/manifeste.json", "run-1/modele.json", "en-service.json"):
            magasin.put(cle, b"x")
        self.assertEqual(magasin.list(), ["en-service.json", "run-1/manifeste.json", "run-1/modele.json", "run-2/modele.json"])
        self.assertEqual(magasin.list("run-1/"), ["run-1/manifeste.json", "run-1/modele.json"])
        self.assertEqual(magasin.list("run-1/mo"), ["run-1/modele.json"])  # un préfixe, pas un dossier (comme S3)
        self.assertEqual(magasin.list("inconnu/"), [])

    def test_un_magasin_vide_ne_liste_rien(self):
        self.assertEqual(self.fabriquer().list(), [])


class ContratLocal(ContratDuPort, unittest.TestCase):
    def fabriquer(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        return StockageLocal(Path(dossier.name))

    def test_un_dossier_absent_ne_liste_rien(self):
        self.assertEqual(StockageLocal(Path(tempfile.gettempdir()) / "novaria-absent-xyz").list(), [])


class ContratEnMemoire(ContratDuPort, unittest.TestCase):
    def fabriquer(self):
        return StockageEnMemoire()


class ListeLocale(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.racine = Path(self._tmp.name)
        self.magasin = StockageLocal(self.racine)

    def test_ni_fichier_d_ecriture_en_cours_ni_nom_hors_regle(self):
        self.magasin.put("run-1/modele.json", b"x")
        (self.racine / "run-1" / ".ecriture-abc").write_bytes(b"partiel")
        (self.racine / "run-1" / "Majuscule.json").write_bytes(b"x")
        (self.racine / "run-1" / "avec espace.json").write_bytes(b"x")
        self.assertEqual(self.magasin.list(), ["run-1/modele.json"])

    def test_un_lien_symbolique_n_est_pas_liste(self):
        externe = tempfile.TemporaryDirectory()
        self.addCleanup(externe.cleanup)
        exterieur = Path(externe.name)
        (exterieur / "secret.json").write_bytes(b"secret")
        try:
            (self.racine / "lien.json").symlink_to(exterieur / "secret.json")
            (self.racine / "dossier-lien").symlink_to(exterieur, target_is_directory=True)
        except OSError:
            self.skipTest("liens symboliques indisponibles sur ce système de fichiers")
        self.magasin.put("vrai.json", b"x")
        self.assertEqual(self.magasin.list(), ["vrai.json"])

    def test_la_liste_ne_descend_pas_plus_bas_que_les_cles(self):
        self.magasin.put("a/b/c/d.json", b"x")  # quatre segments : permis
        profond = self.racine / "a" / "b" / "c" / "e" / "f.json"
        profond.parent.mkdir()
        profond.write_bytes(b"x")  # cinq segments : jamais une clé
        self.assertEqual(self.magasin.list(), ["a/b/c/d.json"])

    def test_un_objet_devenu_trop_gros_est_refuse_a_la_lecture(self):
        petit = StockageLocal(self.racine, taille_max=4)
        (self.racine / "gros.json").write_bytes(b"12345")  # posé sans passer par le port
        with self.assertRaises(StockageErreur):
            petit.get("gros.json")

    def test_une_ecriture_concurrente_est_refusee_sans_laisser_de_fichier_temporaire(self):
        with mock.patch.object(objets.os, "link", side_effect=FileExistsError), self.assertRaises(ObjetDejaEcrit):
            self.magasin.put("run-1/modele.json", b"x")
        self.assertEqual(self.magasin.list(), [])
        self.assertEqual([p.name for p in (self.racine / "run-1").iterdir()], [])

    def test_un_prefixe_invalide_est_refuse(self):
        for prefixe in ("../", "a/../b", "/a", "a//b", "a b", "a\x00", "é", "x" * 401):
            with self.subTest(prefixe=prefixe), self.assertRaises(StockageErreur):
                self.magasin.list(prefixe)

    def test_un_prefixe_trop_large_est_refuse(self):
        with mock.patch.object(objets, "LISTE_MAX", 2):
            for numero in range(3):
                self.magasin.put(f"run-{numero}/modele.json", b"x")
            with self.assertRaises(StockageErreur):
                self.magasin.list()
            self.assertEqual(len(self.magasin.list("run-0")), 1)
        self.assertEqual(LISTE_MAX, 10_000)

    def test_les_majuscules_sont_refusees_sauf_sur_demande(self):
        with self.assertRaises(StockageErreur):
            self.magasin.put("PROVENANCE.md", b"x")
        jeu = StockageLocal(self.racine, majuscules=True)
        jeu.put("PROVENANCE.md", b"x")
        self.assertEqual(jeu.list(), ["PROVENANCE.md"])
        self.assertEqual(self.magasin.list(), [])  # le magasin strict ne lit pas ce nom


class Fabrique(unittest.TestCase):
    def test_local_est_le_defaut(self):
        self.assertIsInstance(ouvrir_magasin(Path("x"), {}), StockageLocal)
        self.assertIsInstance(ouvrir_magasin(Path("x"), {"STORAGE_BACKEND": BACKEND_LOCAL}), StockageLocal)

    def test_un_autre_adaptateur_est_une_erreur_de_configuration(self):
        for nom in ("s3", "S3", "seaweedfs", ""):
            with self.subTest(nom=nom), self.assertRaises(StockageNonConfigure) as contexte:
                ouvrir_magasin(Path("x"), {"STORAGE_BACKEND": nom})
            self.assertIn("S3 est documenté, non exécuté", str(contexte.exception))

    def test_l_environnement_du_processus_est_lu_par_defaut(self):
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "s3"}), self.assertRaises(StockageNonConfigure):
            ouvrir_magasin(Path("x"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(ouvrir_magasin(Path("x")), StockageLocal)

    def test_le_magasin_d_un_jeu_a_une_taille_et_des_cles_adaptees(self):
        magasin = ouvrir_magasin_de_jeu(Path("x"), {})
        self.assertGreater(magasin.taille_max, objets.TAILLE_MAX)
        self.assertTrue(magasin.majuscules)
        with self.assertRaises(StockageNonConfigure):
            ouvrir_magasin_de_jeu(Path("x"), {"STORAGE_BACKEND": "s3"})


class RangerALIdentique(unittest.TestCase):
    def test_meme_contenu_sans_effet_autre_contenu_refuse(self):
        magasin = StockageEnMemoire()
        self.assertEqual(ranger_a_l_identique(magasin, "jeu/a.parquet", b"1"), sha256(b"1"))
        self.assertEqual(ranger_a_l_identique(magasin, "jeu/a.parquet", b"1"), sha256(b"1"))
        with self.assertRaises(ObjetDejaEcrit):
            ranger_a_l_identique(magasin, "jeu/a.parquet", b"2")
        self.assertEqual(magasin.objets, {"jeu/a.parquet": b"1"})
        self.assertEqual([appel for appel in magasin.appels if appel[0] == "put"], [("put", "jeu/a.parquet")])  # une seule écriture


class ModelesEtJeuxPassentParLePort(unittest.TestCase):
    """Critère de LOC-05 : le stockage des modèles et des jeux de données passe par le port."""

    def test_la_construction_du_jeu_ecrit_par_le_port_et_pas_sur_le_disque(self):
        magasin = StockageEnMemoire()
        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(construire, "ouvrir_magasin_de_jeu", return_value=magasin):
            jeu = construire.construire(Path(dossier) / "jeu", petit_catalogue())
            self.assertEqual(list(Path(dossier).iterdir()), [], "rien n'est écrit hors du port")
        self.assertEqual(sorted(magasin.objets), ["PROVENANCE.md", "manifest.json", "test.parquet", "train.parquet", "validation.parquet"])
        for nom, fichier in jeu.manifeste["fichiers"].items():
            self.assertEqual(sha256(magasin.objets[nom]), fichier["sha256"])
            self.assertEqual(len(magasin.objets[nom]), fichier["octets"])

    def test_la_verification_du_jeu_lit_par_le_port(self):
        magasin = StockageEnMemoire()
        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(construire, "ouvrir_magasin_de_jeu", return_value=magasin):
            construire.construire(Path(dossier) / "jeu", petit_catalogue())
        magasin.appels.clear()
        with mock.patch.object(integrite, "ouvrir_magasin_de_jeu", return_value=magasin):
            self.assertEqual(integrite.verifier(Path("inexistant")), [])
        self.assertIn(("get", "manifest.json"), magasin.appels)
        self.assertIn(("list", ""), magasin.appels)
        magasin.objets["train.parquet"] = magasin.objets["train.parquet"][:-1] + b"X"  # un octet change : le port le voit
        with mock.patch.object(integrite, "ouvrir_magasin_de_jeu", return_value=magasin):
            self.assertTrue(any("train.parquet" in ecart for ecart in integrite.verifier(Path("inexistant"))))

    def test_la_lecture_du_jeu_passe_par_le_port(self):
        magasin = StockageEnMemoire()
        with tempfile.TemporaryDirectory() as dossier, mock.patch.object(construire, "ouvrir_magasin_de_jeu", return_value=magasin):
            construire.construire(Path(dossier) / "jeu", petit_catalogue())
        magasin.appels.clear()
        with mock.patch.object(donnees, "ouvrir_magasin_de_jeu", return_value=magasin):
            lignes = donnees.charger("train", Path("inexistant"))
        self.assertTrue(lignes)
        self.assertEqual(magasin.appels, [("get", "train.parquet")])

    def test_un_jeu_absent_est_signale_par_le_port(self):
        with tempfile.TemporaryDirectory() as dossier, self.assertRaises(ObjetAbsent):
            donnees.charger("train", Path(dossier))

    def test_reconstruire_a_l_identique_est_sans_effet_un_autre_contenu_est_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            sortie = Path(dossier) / "jeu"
            premier = construire.construire(sortie, petit_catalogue())
            second = construire.construire(sortie, petit_catalogue())
            self.assertEqual(premier.manifeste["empreinte_du_jeu"], second.manifeste["empreinte_du_jeu"])
            with self.assertRaises(ObjetDejaEcrit):
                construire.construire(sortie, petit_catalogue(decalage_graine=1))

    def test_le_registre_range_les_modeles_par_le_port(self):
        from registre import __main__ as cli

        self.assertIsInstance(cli.magasin(), StockageLocal)
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "s3"}), self.assertRaises(cli.Configuration):
            cli.magasin()


if __name__ == "__main__":
    unittest.main()
