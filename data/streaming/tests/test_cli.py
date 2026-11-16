import unittest
from pathlib import Path
from unittest import mock

from streaming import cli, mongo, simulateur

from .donnees import mesure


class Simulateur(unittest.TestCase):
    def test_la_commande_reprend_tous_les_reglages_de_l_essai(self):
        essai = simulateur.Essai(scenario="heure-de-pointe", graine=3, debut="2026-10-20T06:00:00Z", duree="5m", run_id="r-1",
                                 anomalies=("doublon:sensor=SENSOR_001,at=+20", "retard:sensor=SENSOR_002,at=+40,delay=25"))
        commande = simulateur.commande(essai, python="py")
        self.assertEqual(commande[0], "py")
        self.assertEqual(commande[commande.index("--scenario") + 1], "heure-de-pointe")
        self.assertEqual(commande[commande.index("--seed") + 1], "3")
        self.assertEqual(commande[commande.index("--run-id") + 1], "r-1")
        self.assertEqual([commande[i + 1] for i, mot in enumerate(commande) if mot == "--anomaly"], list(essai.anomalies))
        self.assertIn("--stdout", commande)

    def test_la_ligne_kafka_a_pour_cle_le_carrefour_et_pour_valeur_le_message_sur_une_ligne(self):
        ligne = simulateur.ligne_kafka(mesure("2026-10-20T08:00:10Z"))
        cle, _, valeur = ligne.decode().rstrip("\n").partition("|")
        self.assertEqual(cle, "INT_01")
        self.assertNotIn("\n", valeur)
        self.assertTrue(valeur.startswith('{"id"'))

    def test_une_cle_qui_contient_le_separateur_est_refusee(self):
        message = mesure("2026-10-20T08:00:10Z")
        message["subject"] = "INT|01"
        with self.assertRaises(ValueError):
            simulateur.ligne_kafka(message)

    def test_le_simulateur_est_reproductible_pour_la_meme_graine(self):
        essai = simulateur.Essai(duree="1m")
        self.assertEqual(simulateur.messages(essai), simulateur.messages(essai))
        self.assertEqual(len(simulateur.messages(essai)), 144)  # 24 capteurs, un message toutes les 10 s


class Commandes(unittest.TestCase):
    def test_compose_prend_le_fichier_de_la_racine_puis_celui_du_prototype(self):
        commande = cli.commande_compose("up", "-d")
        self.assertEqual(commande[:7], ["docker", "compose", "-f", "docker-compose.yml", "-f", "data/streaming/compose.yml", "up"])
        self.assertTrue((cli.RACINE / "docker-compose.yml").exists() and (cli.RACINE / "data/streaming/compose.yml").exists())

    def test_les_valeurs_du_job_visent_les_noms_du_reseau_compose(self):
        configuration = cli.Configuration(mot_de_passe="mdp-d-essai")
        with mock.patch.object(cli, "lire_env", return_value={"MONGO_DB": "novaria"}):
            valeurs = cli.valeurs_du_job(configuration, "g")
        self.assertEqual(valeurs["KAFKA_SERVEURS"], "kafka:9092")
        self.assertEqual(valeurs["SUJET"], "iot.raw")
        self.assertTrue(valeurs["MONGO_URI"].startswith(f"mongodb://{mongo.UTILISATEUR}:mdp-d-essai@mongo:27017/novaria"))

    def test_le_mot_de_passe_passe_par_l_environnement_jamais_par_les_arguments(self):
        configuration = cli.Configuration(projet="p", ports={"KAFKA_PORT": "1"}, mot_de_passe="mdp-d-essai")
        env = configuration.environnement()
        self.assertEqual(env[mongo.VARIABLE_MOT_DE_PASSE], "mdp-d-essai")
        self.assertEqual(env["COMPOSE_PROJECT_NAME"], "p")
        with mock.patch.object(cli, "executer") as executer, mock.patch.object(cli, "texte", return_value="PRET"), \
                mock.patch.object(cli, "ENV_FILE", Path(__file__)):
            cli.demarrer(configuration)
        for appel in executer.call_args_list:
            self.assertNotIn("mdp-d-essai", " ".join(appel.args[1]))

    def test_le_job_envoie_le_sql_sur_l_entree_standard_pas_dans_les_arguments(self):
        configuration = cli.Configuration(mot_de_passe="mdp-d-essai")
        sortie = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(cli, "lire_env", return_value={"MONGO_DB": "novaria"}), mock.patch.object(cli, "executer", return_value=sortie) as executer:
            cli.soumettre(configuration)
        arguments = executer.call_args.args[1]
        self.assertNotIn("mdp-d-essai", " ".join(arguments))
        self.assertIn("mdp-d-essai", executer.call_args.kwargs["entree"])
        self.assertIn("-Xmx256m", " ".join(arguments))

    def test_une_erreur_de_flink_est_remontee_sans_le_mot_de_passe(self):
        configuration = cli.Configuration(mot_de_passe="mdp-d-essai")
        sortie = mock.Mock(returncode=0, stdout=b"[ERROR] uri mongodb://u:mdp-d-essai@mongo", stderr=b"")
        with mock.patch.object(cli, "lire_env", return_value={}), mock.patch.object(cli, "executer", return_value=sortie):
            with self.assertRaises(cli.ErreurFlux) as erreur:
                cli.soumettre(configuration)
        self.assertNotIn("mdp-d-essai", str(erreur.exception))
        self.assertIn("***", str(erreur.exception))

    def test_un_mot_de_passe_existant_est_repris_sans_toucher_a_env(self):
        configuration = cli.Configuration()
        with mock.patch.dict("os.environ", {mongo.VARIABLE_MOT_DE_PASSE: "deja-la"}), mock.patch.object(cli, "ENV_FILE") as env:
            cli.preparer_mot_de_passe(configuration, ecrire_dans_env=True)
        self.assertEqual(configuration.mot_de_passe, "deja-la")
        env.open.assert_not_called()

    def test_un_nouveau_mot_de_passe_jetable_n_est_pas_ecrit_sur_le_disque(self):
        configuration = cli.Configuration()
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(cli, "lire_env", return_value={}), mock.patch.object(cli, "ENV_FILE") as env:
            cli.preparer_mot_de_passe(configuration, ecrire_dans_env=False)
        self.assertGreaterEqual(len(configuration.mot_de_passe), 24)
        env.open.assert_not_called()

    def test_l_analyseur_connait_les_commandes_et_les_reglages_de_l_essai(self):
        arguments = cli.construire_analyseur().parse_args(["demo", "--graine", "9", "--anomalie", "doublon:sensor=SENSOR_001,at=+20", "--garder"])
        self.assertEqual((arguments.commande, arguments.graine, arguments.garder), ("demo", 9, True))
        self.assertEqual(cli.essai_depuis(arguments).anomalies, ("doublon:sensor=SENSOR_001,at=+20",))


if __name__ == "__main__":
    unittest.main()
