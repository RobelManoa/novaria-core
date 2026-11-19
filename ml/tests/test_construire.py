"""Construction du jeu : reproductibilité (même graine, même empreinte), non-recouvrement des runs, fiche de provenance."""

import hashlib
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.support import RACINE, petit_catalogue

from jeu_entrainement import catalogue as cat
from jeu_entrainement import construire, lignes, parquet, provenance

VERSIONNE = RACINE / "data" / "datasets" / cat.JEU_ID


def sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


class JeuConstruit(unittest.TestCase):
    """Trois constructions du petit catalogue : deux avec les mêmes graines (A, B), une avec d'autres graines (C)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        base = Path(cls._tmp.name)
        cls.a = construire.construire(base / "a", petit_catalogue())
        cls.b = construire.construire(base / "b", petit_catalogue())
        cls.c = construire.construire(base / "c", petit_catalogue(decalage_graine=1000))

    # --- Critère : deux exécutions avec la même graine donnent la même empreinte --------------------------

    def test_deux_executions_avec_les_memes_graines_donnent_les_memes_empreintes(self):
        for nom in ("train.parquet", "validation.parquet", "test.parquet"):
            self.assertEqual(sha(self.a.dossier / nom), sha(self.b.dossier / nom), nom)
        self.assertEqual(self.a.manifeste["empreinte_du_jeu"], self.b.manifeste["empreinte_du_jeu"])

    def test_les_fichiers_sont_identiques_octet_pour_octet_y_compris_fiche_et_manifeste(self):
        for nom in ("train.parquet", "validation.parquet", "test.parquet", "manifest.json", "PROVENANCE.md"):
            self.assertEqual((self.a.dossier / nom).read_bytes(), (self.b.dossier / nom).read_bytes(), nom)

    def test_une_autre_graine_donne_une_autre_empreinte(self):
        self.assertNotEqual(self.a.manifeste["empreinte_du_jeu"], self.c.manifeste["empreinte_du_jeu"])
        for nom in ("train.parquet", "validation.parquet", "test.parquet"):
            self.assertNotEqual(sha(self.a.dossier / nom), sha(self.c.dossier / nom), nom)

    def test_ni_chemin_ni_date_dans_les_fichiers_ecrits(self):
        for nom in ("manifest.json", "PROVENANCE.md", "train.parquet"):
            octets = (self.a.dossier / nom).read_bytes()
            self.assertNotIn(str(self.a.dossier).encode(), octets, nom)
            self.assertNotIn(b"/home/", octets, nom)

    def test_les_fins_de_ligne_sont_lf(self):
        for nom in ("manifest.json", "PROVENANCE.md"):
            self.assertNotIn(b"\r", (self.a.dossier / nom).read_bytes(), nom)

    # --- Critère : aucun run_id commun entre entraînement et test ------------------------------------------

    def lire(self, jeu, ensemble):
        return parquet.decoder((jeu.dossier / f"{ensemble}.parquet").read_bytes())[1]

    def test_aucun_run_id_n_est_commun_entre_les_fichiers_ecrits(self):
        runs = {e: {ligne[0] for ligne in self.lire(self.a, e)} for e in cat.ENSEMBLES}
        for e1, e2 in itertools.combinations(cat.ENSEMBLES, 2):
            self.assertEqual(runs[e1] & runs[e2], set(), f"{e1} et {e2} ont un run en commun")
        self.assertEqual(len(runs[cat.TRAIN] | runs[cat.VALIDATION] | runs[cat.TEST]), 9)

    def test_les_runs_des_fichiers_sont_ceux_du_catalogue_et_du_manifeste(self):
        for ensemble in cat.ENSEMBLES:
            dans_le_fichier = {ligne[0] for ligne in self.lire(self.a, ensemble)}
            attendus = {r.run_id for r in petit_catalogue() if r.ensemble == ensemble}
            self.assertEqual(dans_le_fichier, attendus, ensemble)
            self.assertEqual(set(self.a.manifeste["fichiers"][f"{ensemble}.parquet"]["runs"]), attendus)

    def test_aucune_graine_n_est_commune_entre_les_fichiers_ecrits(self):
        graines = {e: {ligne[2] for ligne in self.lire(self.a, e)} for e in cat.ENSEMBLES}
        for e1, e2 in itertools.combinations(cat.ENSEMBLES, 2):
            self.assertEqual(graines[e1] & graines[e2], set())

    def test_chaque_fichier_contient_les_trois_scenarios(self):
        for ensemble in cat.ENSEMBLES:
            self.assertEqual({ligne[1] for ligne in self.lire(self.a, ensemble)}, set(cat.SCENARIOS), ensemble)

    def test_aucune_cle_n_est_en_double_dans_un_fichier_ni_entre_fichiers(self):
        cles = []
        for ensemble in cat.ENSEMBLES:
            cles += [(l[0], l[3], l[4]) for l in self.lire(self.a, ensemble)]  # noqa: E741
        self.assertEqual(len(cles), len(set(cles)))

    # --- Contenu -------------------------------------------------------------------------------------------

    def test_les_fichiers_ont_les_colonnes_du_dictionnaire_et_le_nombre_de_lignes_du_manifeste(self):
        for ensemble in cat.ENSEMBLES:
            colonnes, rows = parquet.decoder((self.a.dossier / f"{ensemble}.parquet").read_bytes())
            self.assertEqual(colonnes, list(lignes.COLONNES))
            self.assertEqual(len(rows), self.a.manifeste["fichiers"][f"{ensemble}.parquet"]["lignes"])
            self.assertGreater(len(rows), 1000)

    def test_les_labels_sont_les_trois_etats_et_les_trois_apparaissent(self):
        etats = set()
        for ensemble in cat.ENSEMBLES:
            etats |= {ligne[lignes.NOMS.index("label_state")] for ligne in self.lire(self.a, ensemble)}
        self.assertEqual(etats, set(lignes.ETATS))

    def test_les_lignes_sont_triees_par_troncon_puis_par_minute_dans_chaque_run(self):
        for ensemble in cat.ENSEMBLES:
            par_run = {}
            for ligne in self.lire(self.a, ensemble):
                par_run.setdefault(ligne[0], []).append((ligne[3], ligne[4]))
            for run, cles in par_run.items():
                self.assertEqual(cles, sorted(cles), run)

    # --- Manifeste et fiche --------------------------------------------------------------------------------

    def test_le_manifeste_donne_les_vraies_empreintes_et_tailles(self):
        for nom, fichier in self.a.manifeste["fichiers"].items():
            chemin = self.a.dossier / nom
            self.assertEqual(fichier["sha256"], sha(chemin))
            self.assertEqual(fichier["octets"], chemin.stat().st_size)

    def test_l_empreinte_du_jeu_se_recalcule_depuis_les_fichiers(self):
        texte = "".join(f"{nom} {sha(self.a.dossier / nom)}\n" for nom in sorted(self.a.manifeste["fichiers"]))
        self.assertEqual(hashlib.sha256(texte.encode()).hexdigest(), self.a.manifeste["empreinte_du_jeu"])

    def test_le_fichier_manifest_json_est_celui_que_la_fonction_rend(self):
        ecrit = json.loads((self.a.dossier / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(ecrit, json.loads(json.dumps(self.a.manifeste)))

    def test_la_fiche_porte_toutes_les_rubriques_de_l_adr_027_et_les_empreintes_reelles(self):
        fiche = (self.a.dossier / "PROVENANCE.md").read_text(encoding="utf-8")
        for rubrique in ("Identifiant et version", "Origine", "Licence et conditions", "Période et couverture", "Variables et unités",
                         "Qualité mesurée", "Limites", "Empreinte"):
            self.assertIn(rubrique, fiche)
        for nom in self.a.manifeste["fichiers"]:
            self.assertIn(sha(self.a.dossier / nom), fiche)
        self.assertIn(self.a.manifeste["empreinte_du_jeu"], fiche)
        self.assertIn("SIMULATED", fiche)
        self.assertIn("jamais être présenté comme tel", fiche)

    def test_la_fiche_se_regenere_a_l_identique_depuis_le_manifeste(self):
        self.assertEqual(provenance.rediger(self.a.manifeste), (self.a.dossier / "PROVENANCE.md").read_text(encoding="utf-8"))

    def test_un_lecteur_independant_relit_les_fichiers_ecrits(self):
        try:
            import pyarrow.parquet as lecteur
        except ImportError:
            self.skipTest("pyarrow n'est pas installé (outil d'essai, pas une dépendance du jeu)")
        for ensemble in cat.ENSEMBLES:
            table = lecteur.read_table(self.a.dossier / f"{ensemble}.parquet")
            self.assertEqual(table.schema.names, list(lignes.NOMS))
            relues = list(zip(*[table.column(i).to_pylist() for i in range(table.num_columns)], strict=True))
            self.assertEqual(relues, self.lire(self.a, ensemble))


class JeuVersionne(unittest.TestCase):
    """La fiche et le manifeste commités (data/datasets/novaria-congestion-v1/) doivent rester ceux du code."""

    def setUp(self):
        if not (VERSIONNE / "manifest.json").is_file():
            self.skipTest("le jeu v1 n'est pas encore construit dans data/datasets/ (python3 ml/src/construire_jeu.py)")
        self.manifeste = json.loads((VERSIONNE / "manifest.json").read_text(encoding="utf-8"))

    def test_le_manifeste_versionne_decrit_le_catalogue_actuel(self):
        attendus = [(r.run_id, r.scenario_id, r.seed, r.ensemble, r.duree_s, list(r.anomalies)) for r in cat.CATALOGUE]
        presents = [(r["run_id"], r["scenario_id"], r["seed"], r["ensemble"], r["duree_s"], r["anomalies"]) for r in self.manifeste["runs"]]
        self.assertEqual(presents, attendus, "le catalogue a changé : reconstruire le jeu et commiter la fiche")

    def test_la_fiche_versionnee_est_celle_du_manifeste_versionne(self):
        self.assertEqual(provenance.rediger(self.manifeste), (VERSIONNE / "PROVENANCE.md").read_text(encoding="utf-8"))

    def test_les_colonnes_du_manifeste_sont_celles_du_code(self):
        self.assertEqual([c["nom"] for c in self.manifeste["colonnes"]], list(lignes.NOMS))

    def test_les_runs_du_manifeste_ne_se_recouvrent_pas(self):
        par_ensemble = {e: {r["run_id"] for r in self.manifeste["runs"] if r["ensemble"] == e} for e in cat.ENSEMBLES}
        for e1, e2 in itertools.combinations(cat.ENSEMBLES, 2):
            self.assertEqual(par_ensemble[e1] & par_ensemble[e2], set())

    @unittest.skipUnless(os.environ.get("NOVARIA_JEU_COMPLET") == "1", "reconstruction complète (40 s) : NOVARIA_JEU_COMPLET=1")
    def test_reconstruire_le_jeu_complet_redonne_l_empreinte_de_la_fiche(self):
        with tempfile.TemporaryDirectory() as tmp:
            jeu = construire.construire(Path(tmp) / "jeu")
        self.assertEqual(jeu.manifeste["empreinte_du_jeu"], self.manifeste["empreinte_du_jeu"])
        for nom, fichier in jeu.manifeste["fichiers"].items():
            self.assertEqual(fichier["sha256"], self.manifeste["fichiers"][nom]["sha256"], nom)


if __name__ == "__main__":
    unittest.main()
