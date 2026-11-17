"""Sauvegarde planifiée et restauration vérifiée (CLD-15) : conservation, manifeste, comparaison des totaux, isolement, planificateur.

Sans Docker : les serveurs sont remplacés par des faux, le temps par une horloge que le test fait avancer. Chaque test dit ce
qu'il prouve. Lancement : python3 -m unittest discover -s scripts/dev -p "test_sauvegarde.py"  (Windows : py -3 ...).
"""

import json
import re
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sauvegarde as s

RACINE = Path(__file__).resolve().parents[2]
MAINTENANT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def horodatage(instant: datetime) -> str:
    return instant.strftime("%Y%m%dT%H%M%SZ")


def sauvegardes(depuis_jours: int, par_jour: int = 1, base: str = "postgres") -> dict[str, datetime]:
    """Une sauvegarde par jour (ou plusieurs) à 02:00 UTC, depuis `depuis_jours` jours jusqu'à la veille de `MAINTENANT`."""
    resultat = {}
    for jour in range(1, depuis_jours + 1):
        for rang in range(par_jour):
            instant = (MAINTENANT - timedelta(days=jour)).replace(hour=2 + rang, minute=0)
            resultat[f"novaria_{horodatage(instant)}{s.EXTENSION[base]}"] = instant
    return resultat


class Conservation(unittest.TestCase):
    def test_le_nom_d_un_fichier_donne_son_instant_en_utc(self):
        self.assertEqual(s.horodatage_du_fichier("novaria_20261117T020000Z.dump"), datetime(2026, 11, 17, 2, 0, tzinfo=UTC))
        self.assertEqual(s.horodatage_du_fichier("novaria_20261117T020000Z.archive.gz"), datetime(2026, 11, 17, 2, 0, tzinfo=UTC))
        self.assertIsNone(s.horodatage_du_fichier("novaria_20261117T020000Z.dump.counts"))
        self.assertIsNone(s.horodatage_du_fichier("notes.txt"))

    def test_toute_sauvegarde_de_moins_de_24_heures_est_gardee_meme_en_double(self):
        recentes = {f"novaria_{horodatage(MAINTENANT - timedelta(hours=h))}.dump": MAINTENANT - timedelta(hours=h) for h in (1, 3, 10, 23)}
        self.assertEqual(s.a_conserver(recentes, MAINTENANT), set(recentes))

    def test_une_sauvegarde_par_jour_pendant_sept_jours_la_derniere_du_jour(self):
        existantes = sauvegardes(10, par_jour=3)
        gardees = s.a_conserver(existantes, MAINTENANT)
        jours = {}
        for nom in gardees:
            jours.setdefault(existantes[nom].date(), []).append(existantes[nom].hour)
        for jour in range(1, 7):  # les 6 jours qui précèdent aujourd'hui (le septième est couvert aussi par la fenêtre de semaine)
            date = (MAINTENANT - timedelta(days=jour)).date()
            self.assertEqual(jours[date], [4], f"{date} : seule la dernière du jour (04:00) est gardée")

    def test_une_par_semaine_pendant_quatre_semaines_puis_une_par_mois_pendant_trois_mois(self):
        existantes = sauvegardes(130)
        gardees = s.a_conserver(existantes, MAINTENANT)
        instants = sorted(existantes[nom] for nom in gardees)
        anciennes = [t for t in instants if t < MAINTENANT - timedelta(days=28)]
        mois = {(t.year, t.month) for t in anciennes}
        self.assertEqual(len(anciennes), len(mois), "au plus une sauvegarde par mois au-delà de 4 semaines")
        self.assertLessEqual(len(anciennes), 3)
        self.assertTrue(all(t >= MAINTENANT - timedelta(days=31 * 3) for t in anciennes), "rien au-delà de 3 mois")
        semaines = {t.isocalendar()[:2] for t in instants if MAINTENANT - timedelta(weeks=4) <= t < MAINTENANT - timedelta(days=7)}
        self.assertGreaterEqual(len(semaines), 3)
        self.assertLess(len(gardees), 25, "130 sauvegardes quotidiennes se réduisent à une vingtaine")

    def test_la_plus_recente_n_est_jamais_supprimee_meme_tres_ancienne(self):
        ancienne = {"novaria_20240101T020000Z.dump": datetime(2024, 1, 1, 2, tzinfo=UTC)}
        self.assertEqual(s.a_conserver(ancienne, MAINTENANT), set(ancienne))

    def test_rien_a_supprimer_quand_il_n_y_a_rien(self):
        self.assertEqual(s.a_conserver({}, MAINTENANT), set())

    def test_la_politique_est_reglable(self):
        existantes = sauvegardes(10)
        court = s.a_conserver(existantes, MAINTENANT, {"jours": 2, "semaines": 0, "mois": 0})
        self.assertLess(len(court), len(s.a_conserver(existantes, MAINTENANT)))

    def test_la_suppression_emporte_le_fichier_le_comptage_et_le_manifeste_et_rien_d_autre(self):
        with tempfile.TemporaryDirectory() as dossier:
            sous = Path(dossier) / "postgres"
            sous.mkdir()
            ancien, recent = "novaria_20260101T020000Z.dump", f"novaria_{horodatage(MAINTENANT - timedelta(hours=2))}.dump"
            for nom in (ancien, recent):
                for suffixe in ("", ".counts", ".manifest.json"):
                    (sous / f"{nom}{suffixe}").write_text("x")
            (sous / "notes.txt").write_text("à garder")
            supprimees = s.appliquer_la_conservation("postgres", Path(dossier), MAINTENANT)
            self.assertEqual(supprimees, [ancien])
            self.assertEqual(sorted(f.name for f in sous.iterdir()), sorted([recent, f"{recent}.counts", f"{recent}.manifest.json", "notes.txt"]))

    def test_simuler_ne_supprime_rien(self):
        with tempfile.TemporaryDirectory() as dossier:
            sous = Path(dossier) / "mongo"
            sous.mkdir()
            (sous / "novaria_20260101T020000Z.archive.gz").write_text("x")
            (sous / "novaria_20261117T010000Z.archive.gz").write_text("x")
            self.assertEqual(s.appliquer_la_conservation("mongo", Path(dossier), MAINTENANT, simuler=True), ["novaria_20260101T020000Z.archive.gz"])
            self.assertEqual(len(list(sous.iterdir())), 2)


class Manifeste(unittest.TestCase):
    def test_le_manifeste_porte_l_empreinte_la_taille_et_le_releve(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "novaria_20261117T020000Z.dump"
            fichier.write_bytes(b"contenu de sauvegarde")
            manifeste = s.ecrire_manifeste(fichier, "postgres", {"tables": {"a.b": {"lignes": 2, "controle": "7"}}}, MAINTENANT)
            self.assertEqual(manifeste["taille"], 21)
            self.assertEqual(manifeste["sha256"], s.empreinte(fichier))
            self.assertEqual(s.lire_manifeste(fichier), manifeste)
            self.assertFalse(list(Path(dossier).glob("*.part")), "écriture atomique : aucun fichier temporaire ne reste")

    def test_un_fichier_modifie_est_detecte_par_son_empreinte(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "novaria_20261117T020000Z.dump"
            fichier.write_bytes(b"abcdef")
            s.ecrire_manifeste(fichier, "postgres", {}, MAINTENANT)
            self.assertEqual(s.verifier_le_fichier("postgres", fichier)["base"], "postgres")
            fichier.write_bytes(b"abcdeX")
            with self.assertRaisesRegex(s.Echec, "a changé depuis la sauvegarde"):
                s.verifier_le_fichier("postgres", fichier)

    def test_sans_manifeste_ou_pour_une_autre_base_la_verification_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "novaria_20261117T020000Z.dump"
            fichier.write_bytes(b"x")
            with self.assertRaisesRegex(s.Echec, "manifeste absent"):
                s.verifier_le_fichier("postgres", fichier)
            s.ecrire_manifeste(fichier, "mongo", {}, MAINTENANT)
            with self.assertRaisesRegex(s.Echec, "base inattendue"):
                s.verifier_le_fichier("postgres", fichier)

    def test_la_derniere_sauvegarde_est_la_plus_recente_par_son_nom(self):
        with tempfile.TemporaryDirectory() as dossier:
            sous = Path(dossier) / "postgres"
            sous.mkdir()
            for nom in ("novaria_20261001T020000Z.dump", "novaria_20261117T020000Z.dump", "novaria_20261105T020000Z.dump"):
                (sous / nom).write_bytes(b"x")
            self.assertEqual(s.derniere_sauvegarde("postgres", Path(dossier)).name, "novaria_20261117T020000Z.dump")
            self.assertIsNone(s.derniere_sauvegarde("mongo", Path(dossier)))


RELEVE = {"tables": {"dwh.fait": {"lignes": 10, "controle": "123"}, "app.users": {"lignes": 2, "controle": "9"}},
          "indexes": ["dwh.fait_pkey"], "vues": {"dwh.v": 10}, "droits": "abc", "contraintes_non_validees": 0, "totaux": {"fenetres": [10, 55, 1]}}


class Comparaison(unittest.TestCase):
    def copie(self):
        return json.loads(json.dumps(RELEVE))

    def test_deux_releves_identiques_n_ont_aucun_ecart(self):
        self.assertEqual(s.comparer(RELEVE, self.copie()), [])

    def test_une_ligne_de_moins_est_nommee_avec_la_table(self):
        autre = self.copie()
        autre["tables"]["dwh.fait"]["lignes"] = 9
        self.assertEqual(s.comparer(RELEVE, autre), ["dwh.fait : 10 lignes à la sauvegarde, 9 restaurées"])

    def test_meme_nombre_de_lignes_mais_contenu_different_est_detecte(self):
        autre = self.copie()
        autre["tables"]["app.users"]["controle"] = "10"
        ecarts = s.comparer(RELEVE, autre)
        self.assertEqual(len(ecarts), 1)
        self.assertIn("contenu différent", ecarts[0])

    def test_table_absente_d_un_cote_ou_de_l_autre(self):
        autre = self.copie()
        del autre["tables"]["app.users"]
        autre["tables"]["app.neuve"] = {"lignes": 0, "controle": "0"}
        ecarts = s.comparer(RELEVE, autre)
        self.assertIn("app.neuve : absente de la sauvegarde", ecarts)
        self.assertIn("app.users : absente de la restauration", ecarts)

    def test_structure_droits_vues_et_totaux_comptent(self):
        for cle, valeur in (("droits", "autre"), ("indexes", []), ("vues", {"dwh.v": 0}), ("totaux", {"fenetres": [10, 56, 1]}), ("contraintes_non_validees", 1)):
            autre = self.copie()
            autre[cle] = valeur
            self.assertTrue(s.comparer(RELEVE, autre), cle)

    def test_mongo_index_et_validateur_comptent(self):
        a = {"collections": {"raw": {"lignes": 3, "controle": "5", "index": [{"nom": "ttl", "ttl": 10}], "validateur": 7}}}
        b = json.loads(json.dumps(a))
        self.assertEqual(s.comparer(a, b), [])
        b["collections"]["raw"]["index"][0]["ttl"] = 11
        b["collections"]["raw"]["validateur"] = 8
        self.assertEqual(len(s.comparer(a, b)), 2)

    def test_memes_donnees_ignore_la_structure_pour_detecter_une_base_en_mouvement(self):
        autre = self.copie()
        autre["droits"] = "autre"
        self.assertTrue(s.memes_donnees(RELEVE, autre))
        autre["tables"]["dwh.fait"]["lignes"] = 11
        self.assertFalse(s.memes_donnees(RELEVE, autre))


class LectureDesReleves(unittest.TestCase):
    def test_la_sortie_de_psql_devient_un_releve(self):
        texte = "\n".join(["T|alertes.alert|8|-245", "T|dwh.fait|9792|1234", "I|dwh.fait_pkey", "V|dwh.v_indicator|9792", "D|5c48", "C|0",
                           "S|fenetres|9792|139597|11", "S|comptes|2", "16.15"])
        releve = s.lire_releve_pg(texte)
        self.assertEqual(releve["tables"]["dwh.fait"], {"lignes": 9792, "controle": "1234"})
        self.assertEqual(releve["tables"]["alertes.alert"]["controle"], "-245")
        self.assertEqual(releve["totaux"], {"fenetres": [9792, 139597, 11], "comptes": [2]})
        self.assertEqual((releve["indexes"], releve["vues"], releve["droits"], releve["serveur"]), (["dwh.fait_pkey"], {"dwh.v_indicator": 9792}, "5c48", "16.15"))

    def test_mongosh_peut_ecrire_des_lignes_avant_le_json(self):
        texte = 'Current Mongosh Log ID: abc\n{"collections": {}, "totaux": {"rejets": 7}, "serveur": "7.0.45"}\n'
        self.assertEqual(s.lire_releve_mongo(texte)["totaux"], {"rejets": 7})
        with self.assertRaises(s.Echec):
            s.lire_releve_mongo("pas de json ici")

    def test_les_requetes_de_releve_sont_deterministes_et_sans_secret(self):
        self.assertIn("SET timezone TO 'UTC'", s.SQL_RELEVE)
        self.assertIn("ORDER BY 1;", s.SQL_RELEVE)
        for texte in (s.SQL_RELEVE, s.JS_RELEVE):
            self.assertNotRegex(texte, r"(?i)password|passwd|secret")


class FauxServeurs(s.Serveurs):
    """Remplace Docker : les relevés viennent d'une liste, la sauvegarde crée vraiment un fichier."""

    def __init__(self, dossier: Path, releves: dict[str, list[dict]]):
        super().__init__(Path(dossier))
        self.dossier, self.releves, self.numero = Path(dossier), releves, 0

    def releve(self, base, base_pg=None):
        return self.releves[base].pop(0)

    def compose(self, *args, **kwargs):
        base = "postgres" if "backup-postgres" in args else "mongo"
        self.numero += 1
        nom = f"novaria_20261117T0200{self.numero:02d}Z{s.EXTENSION[base]}"
        (self.dossier / base).mkdir(exist_ok=True)
        (self.dossier / base / nom).write_bytes(b"sauvegarde " + str(self.numero).encode())

        class Sortie:
            returncode, stderr, stdout = 0, "", f"Sauvegarde créée : {nom} (11 octets)"
        return Sortie()


class CycleDeSauvegarde(unittest.TestCase):
    def test_une_base_stable_donne_un_manifeste_et_une_seule_sauvegarde(self):
        with tempfile.TemporaryDirectory() as dossier:
            serveurs = FauxServeurs(Path(dossier), {"postgres": [RELEVE, RELEVE]})
            manifeste = s.sauvegarder_une_base(serveurs, "postgres", Path(dossier), afficher=lambda _: None, maintenant=lambda: MAINTENANT)
            self.assertEqual(manifeste["releve"], RELEVE)
            self.assertEqual(len(list((Path(dossier) / "postgres").glob("*.dump"))), 1)

    def test_une_base_qui_bouge_pendant_la_sauvegarde_est_refusee_puis_refaite(self):
        bougee = json.loads(json.dumps(RELEVE))
        bougee["tables"]["dwh.fait"]["lignes"] = 11
        with tempfile.TemporaryDirectory() as dossier:
            serveurs = FauxServeurs(Path(dossier), {"postgres": [RELEVE, bougee, bougee, bougee]})
            messages = []
            manifeste = s.sauvegarder_une_base(serveurs, "postgres", Path(dossier), afficher=messages.append, maintenant=lambda: MAINTENANT)
            self.assertEqual(manifeste["releve"]["tables"]["dwh.fait"]["lignes"], 11)
            self.assertTrue(any("a changé pendant la sauvegarde" in m for m in messages))
            self.assertEqual(len(list((Path(dossier) / "postgres").glob("*.dump"))), 1, "la sauvegarde refusée est supprimée")

    def test_une_base_qui_ne_se_stabilise_jamais_fait_echouer_la_sauvegarde(self):
        def instable(n):
            r = json.loads(json.dumps(RELEVE))
            r["tables"]["dwh.fait"]["lignes"] = n
            return r
        with tempfile.TemporaryDirectory() as dossier:
            serveurs = FauxServeurs(Path(dossier), {"postgres": [instable(n) for n in range(10)]})
            with self.assertRaisesRegex(s.Echec, "change trop vite"):
                s.sauvegarder_une_base(serveurs, "postgres", Path(dossier), afficher=lambda _: None)
            self.assertEqual(list((Path(dossier) / "postgres").glob("*.dump")), [])

    def test_le_nom_du_fichier_est_lu_dans_la_sortie_du_script(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.assertEqual(s.lancer_la_sauvegarde(FauxServeurs(Path(dossier), {}), "mongo"), "novaria_20261117T020001Z.archive.gz")


class EnvironnementIsoleDuRepertoire(unittest.TestCase):
    """Le fichier Compose de l'environnement isolé : ce qui le rend isolé est écrit, donc vérifié par un test."""

    @classmethod
    def setUpClass(cls):
        cls.compose = (RACINE / "compose.restauration.yml").read_text(encoding="utf-8")

    def test_le_reseau_est_interne_et_aucun_port_n_est_publie(self):
        self.assertRegex(self.compose, r"(?m)^networks:\n  isolee:\n    internal: true")
        self.assertNotRegex(self.compose, r"(?m)^\s+ports:")
        self.assertEqual(self.compose.count("networks: [isolee]"), 2)

    def test_les_sauvegardes_sont_montees_en_lecture_seule(self):
        self.assertEqual(self.compose.count("./backups:/backups:ro"), 2)

    def test_aucun_mot_de_passe_n_est_ecrit_dans_le_fichier(self):
        for ligne in self.compose.splitlines():
            if re.match(r"\s+[A-Z_]*(PASSWORD|_USER)[A-Z_]*:", ligne):
                self.assertIn("${R_", ligne, ligne)

    def test_les_scripts_d_initialisation_sont_ceux_de_la_pile_de_travail(self):
        self.assertIn("./db/postgres/init:/docker-entrypoint-initdb.d:ro", self.compose)
        self.assertIn("./db/mongo/init:/docker-entrypoint-initdb.d:ro", self.compose)

    def test_chaque_essai_tire_ses_propres_mots_de_passe_et_son_projet(self):
        a, b = s.EnvironnementIsole(administrateur_pg="novaria_admin"), s.EnvironnementIsole(administrateur_pg="novaria_admin")
        self.assertNotEqual(a.projet, b.projet)
        for cle in ("R_POSTGRES_PASSWORD", "R_PG_PASSWORD", "R_MONGO_ROOT_PASSWORD", "R_MONGO_PASSWORD"):
            self.assertNotEqual(a.environnement[cle], b.environnement[cle])
            self.assertGreaterEqual(len(a.environnement[cle]), 24)
        self.assertEqual(a.environnement["R_POSTGRES_USER"], "novaria_admin", "même nom d'administrateur : pg_restore le cite dans les droits par défaut")
        self.assertTrue(a.projet.startswith("novaria-restauration-") and a.projet != "novaria-core")

    def test_les_scripts_de_sauvegarde_acceptent_keep_zero_pour_ne_pas_faire_de_rotation_par_nombre(self):
        for script in ("db/postgres/ops.sh", "db/mongo/ops.sh"):
            texte = (RACINE / script).read_text(encoding="utf-8")
            self.assertIn('if [ "$KEEP" -gt 0 ]; then', texte, script)


class Planificateur(unittest.TestCase):
    def test_le_prochain_creneau_est_aujourd_hui_s_il_n_est_pas_passe_sinon_demain(self):
        matin = datetime(2026, 11, 17, 1, 30)
        self.assertEqual(s.prochain_creneau(matin, "02:00"), datetime(2026, 11, 17, 2, 0))
        self.assertEqual(s.prochain_creneau(datetime(2026, 11, 17, 2, 0), "02:00"), datetime(2026, 11, 18, 2, 0), "à 02:00 pile, le créneau est passé")
        self.assertEqual(s.prochain_creneau(datetime(2026, 11, 17, 23, 59), "02:00"), datetime(2026, 11, 18, 2, 0))

    def test_le_rattrapage_se_declenche_quand_une_base_n_a_pas_de_sauvegarde_recente(self):
        recent, vieux = MAINTENANT - timedelta(hours=3), MAINTENANT - timedelta(hours=30)
        self.assertFalse(s.doit_rattraper({"postgres": recent, "mongo": recent}, MAINTENANT))
        self.assertTrue(s.doit_rattraper({"postgres": recent, "mongo": vieux}, MAINTENANT))
        self.assertTrue(s.doit_rattraper({"postgres": None, "mongo": recent}, MAINTENANT))

    def jouer(self, **options):
        horloge = {"t": datetime(2026, 11, 17, 1, 0)}
        attentes, appels, messages = [], [], []
        echouer_au = options.pop("echouer_au", None)

        def dormir(secondes):
            attentes.append(secondes)
            horloge["t"] += timedelta(seconds=secondes)

        def cycle():
            appels.append(horloge["t"])
            if echouer_au == len(appels):
                raise RuntimeError("Docker injoignable")

        reussis = s.planifier(cycle, horloge=lambda: horloge["t"], dormir=dormir, afficher=messages.append, **options)
        return reussis, attentes, appels, messages

    def test_attend_le_creneau_lance_et_recommence_le_lendemain(self):
        reussis, attentes, appels, _ = self.jouer(heure="02:00", executions=2, sans_rattrapage=True)
        self.assertEqual(reussis, 2)
        self.assertEqual(appels, [datetime(2026, 11, 17, 2, 0), datetime(2026, 11, 18, 2, 0)])
        self.assertEqual(attentes, [3600, 86400])

    def test_rattrape_au_demarrage_une_sauvegarde_manquante(self):
        vieux = {"postgres": datetime(2026, 11, 10, tzinfo=UTC), "mongo": None}
        reussis, _, appels, messages = self.jouer(heure="02:00", executions=2, derniere=lambda: {k: (v and v.replace(tzinfo=None)) for k, v in vieux.items()})
        self.assertEqual(len(appels), 2)
        self.assertEqual(appels[0], datetime(2026, 11, 17, 1, 0), "le rattrapage part tout de suite")
        self.assertIn("rattrapage", messages[0])

    def test_un_echec_est_journalise_et_n_arrete_pas_le_planificateur(self):
        reussis, _, appels, messages = self.jouer(heure="02:00", executions=3, sans_rattrapage=True, echouer_au=2)
        self.assertEqual((len(appels), reussis), (3, 2))
        self.assertTrue(any("ÉCHEC : RuntimeError : Docker injoignable" in m for m in messages))

    def test_le_mode_essai_dort_un_intervalle_fixe_sans_rattrapage(self):
        reussis, attentes, appels, _ = self.jouer(toutes_les_s=15, executions=3)
        self.assertEqual((reussis, attentes), (3, [15, 15, 15]))


class Modeles(unittest.TestCase):
    def test_le_modele_cron_lance_les_commandes_du_depot_et_garde_le_code_de_sortie(self):
        cron = (RACINE / "ops" / "planification" / "novaria-sauvegarde.cron").read_text(encoding="utf-8")
        self.assertIn("scripts/dev/dev.py sauvegarde >> var/log/sauvegarde.log 2>&1", cron)
        self.assertIn("scripts/dev/dev.py restauration >> var/log/restauration.log 2>&1", cron)
        self.assertEqual(len(re.findall(r"(?m)^[0-9*]", cron)), 2)

    def test_le_modele_windows_cree_deux_taches_sans_stocker_de_mot_de_passe(self):
        ps = (RACINE / "ops" / "planification" / "installer-tache-windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("scripts\\dev\\dev.py sauvegarde", ps)
        self.assertIn("scripts\\dev\\dev.py restauration", ps)
        self.assertNotRegex(ps, r"(?i)-Password|-RunLevel Highest")

    def test_les_commandes_existent_dans_dev_py(self):
        import dev

        parser = dev.build_parser()
        for ligne in (["sauvegarde"], ["sauvegarde-liste"], ["restauration", "--controles-negatifs"], ["sauvegarde-planifier", "--toutes-les", "15", "--executions", "3"]):
            parser.parse_args(ligne)


if __name__ == "__main__":
    unittest.main()
