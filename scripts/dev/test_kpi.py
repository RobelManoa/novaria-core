"""Contrôle des indicateurs décisionnels (issue DAT-07) : bibliothèque standard seulement, sans base.

Critère d'acceptation : chaque indicateur se recalcule à partir de la source annoncée. Le recalcul lui-même se joue dans PostgreSQL
(`python scripts/dev/dev.py db-check-kpi`, voir docs/03-donnees/kpi.md, section 4). Ce test vérifie ce qui le rend possible et honnête :
- chaque indicateur a sa vue, sa fiche (source, calcul, limites, décision) et son contrôle de recalcul ;
- la migration est la concaténation exacte des fichiers de data/dwh/sql/kpi/ ;
- les vues sont en lecture seule et ne lisent que les sources annoncées ;
- le contrôle de recalcul ne laisse rien en base et compare bien trois valeurs.

Lancement : python3 -m unittest discover -s scripts/dev -p "test_kpi.py"   (Windows : py -3 ...)
"""
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import dev
import gen_kpi

RACINE = Path(__file__).resolve().parents[2]
DOSSIER = RACINE / "data" / "dwh" / "sql" / "kpi"
FICHE = RACINE / "docs" / "03-donnees" / "kpi.md"
VERIFICATION = DOSSIER / "controle" / "verifier.sql"
MIGRATION = RACINE / "db" / "postgres" / "migrations" / "0006_kpi_vues.sql"
# (numéro, fichier, vue, tables sources annoncées)
INDICATEURS = [
    ("KPI-01", "01_part_temps_congestionne.sql", "dwh.kpi_part_temps_congestionne", {"dwh.fact_traffic_window"}),
    ("KPI-02", "02_duree_episodes.sql", "dwh.kpi_duree_episodes", {"dwh.fact_congestion_episode"}),
    ("KPI-03", "03_delai_detection.sql", "dwh.kpi_delai_detection", {"alertes.alert", "dwh.fact_congestion_episode", "dwh.fact_traffic_window"}),
    ("KPI-04", "04_alertes_par_jour.sql", "dwh.kpi_alertes_par_jour", {"alertes.alert"}),
    ("KPI-05", "05_vitesse_relative_horaire.sql", "dwh.kpi_vitesse_relative_horaire", {"dwh.fact_traffic_window"}),
]
DIMENSIONS = {"dwh.dim_road_segment", "dwh.dim_date"}
CHAMPS_DE_FICHE = ("Définition", "Source", "Calcul", "Décision", "Limites")


def lire(chemin: Path) -> str:
    return chemin.read_text(encoding="utf-8").replace("\r\n", "\n")


def sans_commentaires(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


class Vues(unittest.TestCase):
    def test_il_y_a_exactement_cinq_indicateurs_numerotes(self):
        self.assertEqual([f.name for f in gen_kpi.fichiers()], [fichier for _, fichier, _, _ in INDICATEURS])

    def test_chaque_fichier_cree_une_vue_et_la_commente(self):
        for numero, fichier, vue, _ in INDICATEURS:
            with self.subTest(numero=numero):
                sql = lire(DOSSIER / fichier)
                self.assertEqual(re.findall(r"CREATE VIEW (\S+) AS", sql), [vue])
                self.assertIn(f"COMMENT ON VIEW {vue} IS", sql)
                self.assertTrue(sql.startswith(f"-- {numero} · "), "le fichier s'ouvre par le numéro et le nom de l'indicateur")
                for mot in ("-- Source", "-- Calcul", "-- Fiche : docs/03-donnees/kpi.md"):
                    self.assertIn(mot, sql)

    def test_les_vues_sont_en_lecture_seule(self):
        for _, fichier, _, _ in INDICATEURS:
            with self.subTest(fichier=fichier):
                sql = sans_commentaires(lire(DOSSIER / fichier)).upper()
                for interdit in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", "DROP ", "ALTER ", "GRANT "):
                    self.assertNotIn(interdit, sql)

    def test_chaque_vue_ne_lit_que_les_sources_annoncees(self):
        for numero, fichier, _, sources in INDICATEURS:
            with self.subTest(numero=numero):
                lues = set(re.findall(r"\b(?:FROM|JOIN)\s+((?:dwh|alertes)\.\w+)", sans_commentaires(lire(DOSSIER / fichier))))
                self.assertEqual(lues - DIMENSIONS, sources)

    def test_une_vue_garde_la_provenance_et_l_execution(self):
        for numero, fichier, _, _ in INDICATEURS:
            with self.subTest(numero=numero):
                sql = sans_commentaires(lire(DOSSIER / fichier))
                self.assertRegex(sql, r"\brun_id\b")
                self.assertRegex(sql, r"\bsource_type\b")
                self.assertRegex(sql, r"GROUP BY[^;]*\brun_id\b")

    def test_les_vues_sur_les_fenetres_separent_les_tailles(self):
        for fichier in ("01_part_temps_congestionne.sql", "05_vitesse_relative_horaire.sql"):
            with self.subTest(fichier=fichier):
                sql = sans_commentaires(lire(DOSSIER / fichier))
                self.assertRegex(sql, r"GROUP BY[^;]*window_size_s")

    def test_les_jours_sont_en_utc(self):
        for _, fichier, _, _ in INDICATEURS:
            sql = sans_commentaires(lire(DOSSIER / fichier))
            self.assertNotRegex(sql, r"(?i)AT TIME ZONE '(?!UTC')")
            self.assertNotRegex(sql, r"(?i)\bnow\(\)|current_date|current_timestamp", "une vue ne dépend pas de l'heure à laquelle on la lit")

    def test_le_seuil_de_detection_est_celui_de_l_adr_028_et_du_dictionnaire(self):
        sql = lire(DOSSIER / "03_delai_detection.sql")
        self.assertEqual(re.findall(r"SELECT (0\.\d+)::numeric AS ratio_montee", sql), ["0.35"])
        self.assertIn("ratio < 0,35 pendant 2 fenêtres", lire(RACINE / "docs" / "03-donnees" / "dictionnaire-de-donnees.md"))
        self.assertIn("ratio < 0,35 pendant 2 fenêtres", lire(RACINE / "docs" / "01-architecture" / "adr" / "ADR-028-etats-de-congestion-et-alertes.md"))
        self.assertIn("0,35", lire(FICHE))


class Migration(unittest.TestCase):
    def test_la_migration_est_la_concatenation_exacte_des_fichiers(self):
        self.assertEqual(lire(MIGRATION), gen_kpi.generer(), "régénérer : python scripts/dev/gen_kpi.py")

    def test_la_migration_a_le_nom_attendu_par_le_script_de_migration(self):
        self.assertRegex(MIGRATION.name, r"^[0-9]{4}_[a-z0-9_]+\.sql$")
        self.assertEqual(gen_kpi.MIGRATION, MIGRATION)
        numeros = sorted(p.name[:4] for p in MIGRATION.parent.glob("*.sql"))
        self.assertEqual(numeros, sorted(set(numeros)), "numéros de migration uniques")

    def test_la_migration_ne_cree_que_des_vues(self):
        sql = sans_commentaires(lire(MIGRATION))
        self.assertEqual(len(re.findall(r"CREATE VIEW ", sql)), 5)
        self.assertNotRegex(sql, r"CREATE TABLE|CREATE INDEX|INSERT INTO")

    def test_le_generateur_ne_prend_ni_option_ni_chemin(self):
        import inspect

        self.assertEqual(list(inspect.signature(gen_kpi.principal).parameters), [])


class Fiche(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texte = lire(FICHE)

    def section(self, numero: str) -> str:
        debut = self.texte.index(f"### {numero} · ")
        fin = self.texte.find("\n### ", debut + 1)
        fin = fin if fin != -1 else self.texte.index("\n## ", debut)
        return self.texte[debut:fin]

    def test_chaque_indicateur_a_une_fiche_complete(self):
        for numero, _, _, sources in INDICATEURS:
            with self.subTest(numero=numero):
                fiche = self.section(numero)
                for champ in CHAMPS_DE_FICHE:
                    self.assertRegex(fiche, rf"\| \*\*{champ}s?\*\* \|", f"{numero} : champ « {champ} » absent")
                for source in sources:
                    self.assertIn(source.split(".")[1], fiche, f"{numero} : source {source} non citée")

    def test_chaque_vue_est_citee_dans_la_vue_d_ensemble(self):
        ensemble = self.texte[self.texte.index("## 2. Vue d'ensemble"):self.texte.index("## 3. Fiches")]
        for numero, _, vue, _ in INDICATEURS:
            with self.subTest(numero=numero):
                self.assertRegex(ensemble, rf"\| {numero} \|[^\n]*`{re.escape(vue)}`")

    def test_aucune_vue_du_dossier_n_est_sans_fiche(self):
        for vue in re.findall(r"CREATE VIEW (\S+) AS", "".join(lire(f) for f in gen_kpi.fichiers())):
            self.assertIn(f"`{vue}`", self.texte)

    def test_la_fiche_cite_les_quatre_indicateurs_de_congestion_demandes(self):
        for terme in ("Part du temps en état CONGESTED", "Durée moyenne des épisodes", "Délai de détection", "Alertes par jour"):
            self.assertIn(terme, self.texte)

    def test_la_fiche_renvoie_a_la_commande_de_recalcul_et_aux_fichiers(self):
        for lien in ("db-check-kpi", "controle/verifier.sql", "0006_kpi_vues.sql", "data/dwh/sql/kpi/"):
            self.assertIn(lien, self.texte)
        self.assertTrue((DOSSIER / "controle" / "verifier.sql").is_file())

    def test_les_liens_relatifs_de_la_fiche_existent(self):
        for cible in re.findall(r"\]\((?!http|#)([^)#]+)(?:#[^)]*)?\)", self.texte):
            with self.subTest(cible=cible):
                self.assertTrue((FICHE.parent / cible).exists(), cible)

    def test_le_nombre_de_comparaisons_annonce_est_celui_du_controle(self):
        controle = lire(VERIFICATION)
        annonce = int(re.search(r"verifies <> (\d+) THEN", controle).group(1))
        self.assertEqual(annonce, 39)
        self.assertIn(f"{annonce} comparaisons", self.texte)
        self.assertIn(f"pour {annonce} grandeurs", self.texte)

    def test_les_valeurs_calculees_a_la_main_sont_celles_du_controle(self):
        controle = lire(VERIFICATION)
        for valeur in ("0.2143", "0.8333", "300.0", "240.0", "155.0", "180.0", "0.553", "0.500"):
            with self.subTest(valeur=valeur):
                self.assertIn(f"'{valeur}'", controle)
                self.assertIn(valeur.replace(".", ","), self.texte)


class Verification(unittest.TestCase):
    def setUp(self):
        self.sql = lire(VERIFICATION)

    def test_tout_est_annule_a_la_fin(self):
        instructions = [ligne.strip() for ligne in sans_commentaires(self.sql).splitlines() if ligne.strip()]
        self.assertIn("BEGIN;", instructions)
        self.assertEqual(instructions[-1], "ROLLBACK;")
        self.assertNotIn("COMMIT;", instructions)
        self.assertEqual(instructions.index("BEGIN;"), 1, "BEGIN suit immédiatement le réglage ON_ERROR_STOP")

    def test_le_script_s_arrete_au_premier_ecart(self):
        self.assertIn("\\set ON_ERROR_STOP on", self.sql)
        self.assertIn("RAISE EXCEPTION", self.sql)

    def test_le_jeu_n_ecrit_que_dans_une_execution_fabriquee(self):
        ecritures = re.findall(r"INSERT INTO ([\w.]+)", self.sql)
        self.assertEqual(sorted(set(ecritures)), ["alertes.alert", "controle", "dwh.fact_congestion_episode", "dwh.fact_traffic_window"])
        self.assertEqual(set(re.findall(r"'(kpi-[a-z]+)'", self.sql)), {"kpi-controle"})
        self.assertNotRegex(self.sql, r"(?i)DELETE FROM|TRUNCATE|DROP TABLE|UPDATE dwh|UPDATE alertes")
        self.assertIn("'SIMULATED'", self.sql)
        self.assertNotIn("REAL_", self.sql, "jamais présenté comme une mesure réelle")

    def test_chaque_indicateur_a_sa_section_de_comparaison(self):
        for numero, _, _, _ in INDICATEURS:
            with self.subTest(numero=numero):
                self.assertIn(f"-- {numero} : ", self.sql)
                self.assertIn(f"'{numero}'", self.sql)

    def test_chaque_vue_n_est_lue_qu_une_fois_et_le_recalcul_ne_passe_donc_pas_par_elle(self):
        for numero, _, vue, _ in INDICATEURS:
            with self.subTest(numero=numero):
                self.assertEqual(sans_commentaires(self.sql).count(vue), 1, f"{numero} : la vue ne sert qu'à la colonne « vue »")

    def test_les_comparaisons_portent_sur_trois_valeurs(self):
        self.assertIn("(rang serial, kpi text, grandeur text, vue text, recalcul text, attendu text)", self.sql)
        self.assertIn("vue = recalcul AND recalcul = attendu", self.sql)
        self.assertIn("vue IS DISTINCT FROM recalcul OR recalcul IS DISTINCT FROM attendu", self.sql)


class Commande(unittest.TestCase):
    def test_la_commande_existe(self):
        args = dev.build_parser().parse_args(["db-check-kpi"])
        self.assertEqual(args.command, "db-check-kpi")

    def test_elle_envoie_le_script_a_psql_dans_le_conteneur_et_rend_son_code(self):
        for code in (0, 3):
            fin = subprocess.CompletedProcess([], code, stdout="resultat\n", stderr="psql:<stdin>:9: ERREUR\n")
            with self.subTest(code=code), mock.patch.object(dev, "require_env"), \
                    mock.patch.object(dev, "compose", return_value=fin) as lancer, mock.patch("builtins.print") as imprime:
                self.assertEqual(dev.cmd_db_check_kpi(None), code)
            options = lancer.call_args.kwargs
            self.assertEqual(lancer.call_args.args[:4], ("exec", "-T", "postgres", "sh"))
            self.assertIn("ON_ERROR_STOP=1", lancer.call_args.args[5])
            self.assertEqual(options["input_text"], lire(VERIFICATION).replace("\r\n", "\n"))
            self.assertIs(options["check"], False)
            sorties = " ".join(str(appel.args[0]) for appel in imprime.call_args_list)
            self.assertIn("resultat", sorties)
            self.assertIn("verifier.sql:9: ERREUR", sorties, "le nom du fichier remplace <stdin>")

    def test_le_chemin_du_script_est_celui_du_depot(self):
        self.assertEqual(dev.KPI_VERIFICATION, VERIFICATION)


if __name__ == "__main__":
    unittest.main()
