"""Le tableau local d'observabilité (MS-16) : lecture de /metrics, taux, retard Kafka, alarmes, trace, gel d'un service.

Sans Docker ni réseau : les textes Prometheus et la sortie de Kafka sont fabriqués par les tests. Lancement :
python3 -m unittest discover -s scripts/dev -p "test_tableau.py"  (Windows : py -3 ...).
"""

import json
import unittest

import observatoire as o
import tableau as tb
from test_observatoire import FauxDocker, fabriquer

METRIQUES = """# HELP novaria_http_requests_total x
# TYPE novaria_http_requests_total counter
novaria_http_requests_total{method="GET",route="/api/v1/health",service="collecte",status="2xx"} %(ok)s
novaria_http_requests_total{method="POST",route="/api/v1/measurements",service="collecte",status="2xx"} %(ok2)s
novaria_http_requests_total{method="POST",route="/api/v1/measurements",service="collecte",status="5xx"} %(erreurs)s
novaria_http_request_duration_seconds_bucket{method="POST",route="/m",service="collecte",le="0.01"} %(b1)s
novaria_http_request_duration_seconds_bucket{method="POST",route="/m",service="collecte",le="0.1"} %(b2)s
novaria_http_request_duration_seconds_bucket{method="POST",route="/m",service="collecte",le="+Inf"} %(n)s
novaria_http_request_duration_seconds_sum{method="POST",route="/m",service="collecte"} %(somme)s
novaria_http_request_duration_seconds_count{method="POST",route="/m",service="collecte"} %(n)s
novaria_circuit_state{dependency="kafka"} %(circuit)s
novaria_circuit_state{dependency="mongo"} 0
novaria_circuit_opened_total{dependency="kafka"} 1
novaria_dependency_calls_total{dependency="kafka",outcome="rejected"} 7
novaria_dependency_retries_total{dependency="mongo"} 3
novaria_process_start_time_seconds 1.7949e+09
"""


def texte(ok=10, ok2=0, erreurs=0, n=None, b1=None, b2=None, somme=0.5, circuit=0):
    n = ok2 + erreurs if n is None else n
    return METRIQUES % {"ok": ok, "ok2": ok2, "erreurs": erreurs, "n": n, "b1": n if b1 is None else b1, "b2": n if b2 is None else b2,
                        "somme": somme, "circuit": circuit}


class LecturePrometheus(unittest.TestCase):
    def test_les_echantillons_ont_un_nom_des_etiquettes_et_une_valeur(self):
        echantillons = tb.lire_prometheus(texte(ok=4))
        premier = echantillons[0]
        self.assertEqual((premier.nom, premier.etiquettes["status"], premier.valeur), ("novaria_http_requests_total", "2xx", 4.0))

    def test_les_commentaires_et_les_lignes_illisibles_sont_ignores(self):
        self.assertEqual(tb.lire_prometheus("# HELP a b\n# TYPE a counter\nn'importe quoi\na NaNx\n"), [])

    def test_les_etiquettes_echappees_sont_relues(self):
        (e,) = tb.lire_prometheus('c{x="a\\"b\\\\c"} 2\n')
        self.assertEqual(e.etiquettes["x"], 'a"b\\c')

    def test_le_releve_somme_les_routes_et_garde_les_disjoncteurs(self):
        releve = tb.releve_http(tb.lire_prometheus(texte(ok=10, ok2=20, erreurs=5, circuit=2)))
        self.assertEqual(releve["classes"], {"2xx": 30.0, "5xx": 5.0})
        self.assertEqual(releve["circuits"], {"kafka": 2, "mongo": 0})
        self.assertEqual((releve["ouvertures"]["kafka"], releve["appels"]["kafka"]["rejected"], releve["reprises"]["mongo"]), (1, 7, 3))


class Taux(unittest.TestCase):
    def releve(self, **kw):
        return tb.releve_http(tb.lire_prometheus(texte(**kw)))

    def test_debit_erreurs_et_taux_entre_deux_releves(self):
        avant = self.releve(ok=10, ok2=100, erreurs=0, somme=1.0)
        apres = self.releve(ok=10, ok2=160, erreurs=20, somme=3.0)
        calcul = tb.taux(avant, apres, 20)
        self.assertEqual(calcul["requetes"], 80)
        self.assertEqual(calcul["debit"], 4.0)
        self.assertEqual(calcul["erreurs_5xx"], 1.0)
        self.assertEqual(calcul["taux_erreurs"], 0.25)
        self.assertEqual(calcul["duree_moyenne_ms"], 25.0)

    def test_un_service_redemarre_remet_ses_compteurs_a_zero_sans_donner_de_debit_negatif(self):
        avant = self.releve(ok=1000, ok2=500, erreurs=0)
        apres = self.releve(ok=3, ok2=2, erreurs=0)
        self.assertIsNone(tb.taux(avant, apres, 10)["debit"])

    def test_sans_trafic_le_taux_d_erreurs_n_existe_pas(self):
        releve = self.releve()
        calcul = tb.taux(releve, releve, 10)
        self.assertEqual((calcul["requetes"], calcul["taux_erreurs"], calcul["debit"]), (0, None, 0.0))

    def test_le_p95_est_la_plus_petite_borne_qui_couvre_95_pour_cent_des_nouvelles_requetes(self):
        avant = {0.01: 0.0, 0.1: 0.0, float("inf"): 0.0}
        self.assertEqual(tb.p95(avant, {0.01: 96.0, 0.1: 99.0, float("inf"): 100.0}), 0.01)
        self.assertEqual(tb.p95(avant, {0.01: 50.0, 0.1: 96.0, float("inf"): 100.0}), 0.1)
        self.assertIsNone(tb.p95(avant, {0.01: 10.0, 0.1: 20.0, float("inf"): 100.0}), "au-delà de la dernière borne : inconnu")
        self.assertIsNone(tb.p95(avant, avant))


KAFKA = """GROUP           TOPIC              PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID    HOST    CLIENT-ID
alerte          traffic.indicators 0          -               0               -               novaria-alerte /1.2.3  novaria-alerte
alerte          traffic.indicators 1          14              20              6               novaria-alerte /1.2.3  novaria-alerte

GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID    HOST    CLIENT-ID
traitement-flux iot.raw         1          44              %(fin)s         %(retard)s      novaria-flux   /1.2.3  novaria-flux
traitement-entrepot traffic.indicators 1   0               20              20              novaria-flux   /1.2.3  novaria-flux
"""


class RetardKafka(unittest.TestCase):
    def test_les_lignes_de_kafka_donnent_le_retard_par_groupe_et_sujet(self):
        lignes = tb.lire_retards(KAFKA % {"fin": 144, "retard": 100})
        self.assertEqual(len(lignes), 4)
        resume = tb.resumer_kafka(lignes)
        self.assertEqual(resume["retards"][("alerte", "traffic.indicators")], 6)
        self.assertEqual(resume["retards"][("traitement-flux", "iot.raw")], 100)
        self.assertEqual(resume["retards"][("traitement-entrepot", "traffic.indicators")], 20)

    def test_un_sujet_lu_par_deux_groupes_n_est_pas_compte_deux_fois_dans_les_messages_ecrits(self):
        resume = tb.resumer_kafka(tb.lire_retards(KAFKA % {"fin": 144, "retard": 100}))
        self.assertEqual(resume["fins"]["traffic.indicators"], 20, "même partition lue par deux groupes : une seule position d'écriture")
        self.assertEqual(resume["fins"]["iot.raw"], 144)

    def test_les_en_tetes_et_les_lignes_vides_sont_ignores(self):
        self.assertEqual(tb.lire_retards("GROUP TOPIC PARTITION\n\n"), [])

    def test_un_decalage_courant_inconnu_donne_un_retard_nul_dans_la_ligne(self):
        (ligne,) = tb.lire_retards("g t 0 - 5 - c h x\n")
        self.assertEqual((ligne["courant"], ligne["fin"], ligne["retard"]), (None, 5, 0))


class RetardEnTemps(unittest.TestCase):
    def test_le_retard_se_convertit_en_secondes_d_ecriture(self):
        self.assertEqual(tb.retard_en_secondes(1350, 15.0), 90.0)
        self.assertEqual(tb.retard_en_secondes(0, 15.0), 0.0)

    def test_un_debit_trop_faible_ou_inconnu_donne_aucune_valeur(self):
        self.assertIsNone(tb.retard_en_secondes(500, 0.05))
        self.assertIsNone(tb.retard_en_secondes(500, None))


class Historique(unittest.TestCase):
    def tableau(self, textes, kafka=None):
        horloge = {"t": 1000.0}
        file = list(textes)
        tableau = tb.Tableau({"collecte": "http://x/metrics"}, lambda: horloge["t"], lire=lambda url: file.pop(0) if file else None,
                             kafka=lambda: kafka.pop(0) if kafka else None)
        return tableau, horloge

    def test_le_debit_se_calcule_sur_la_fenetre_de_trente_secondes(self):
        tableau, horloge = self.tableau([texte(ok2=0), texte(ok2=100), texte(ok2=400)])
        for secondes in (0, 15, 30):
            horloge["t"] = 1000.0 + secondes
            tableau.mesurer(avec_kafka=False)
        ligne = tableau.service("collecte")
        self.assertEqual(ligne["debit"], 13.33)
        self.assertTrue(ligne["mesure"])

    def test_un_service_injoignable_n_est_pas_mesure_et_ne_casse_pas_les_courbes(self):
        tableau, horloge = self.tableau([texte(ok2=10), None, texte(ok2=40)])
        for secondes in (0, 10, 20):
            horloge["t"] = 1000.0 + secondes
            tableau.mesurer(avec_kafka=False)
        self.assertEqual(len(tableau.releves["collecte"]), 3)
        self.assertEqual(tableau.serie_debit("collecte"), [None], "le trou est un point vide, la courbe repart au relevé suivant")
        tableau2, _ = self.tableau([None])
        tableau2.mesurer(avec_kafka=False)
        self.assertEqual(tableau2.service("collecte"), {"id": "collecte", "mesure": False, "circuits": {}, "ouvertures": {}})

    def test_le_resume_pour_les_alarmes_liste_les_disjoncteurs_ouverts_et_le_retard_par_groupe(self):
        tableau, horloge = self.tableau([texte(ok2=0, circuit=2), texte(ok2=50, erreurs=50, circuit=2)],
                                        kafka=[KAFKA % {"fin": 144, "retard": 100}])
        tableau.mesurer(avec_kafka=True)
        horloge["t"] += 10
        tableau.mesurer(avec_kafka=False)
        resume = tableau.resume_pour_alarmes()
        self.assertEqual(resume["services"]["collecte"]["circuits_ouverts"], ["kafka"])
        self.assertEqual(resume["services"]["collecte"]["taux_erreurs"], 0.5)
        self.assertEqual({g: r["retard"] for g, r in resume["retards"].items()}, {"alerte": 6, "traitement-entrepot": 20, "traitement-flux": 100})

    def test_le_debit_d_ecriture_d_un_sujet_vient_de_la_progression_de_sa_position(self):
        tableau, horloge = self.tableau([texte(), texte(), texte()], kafka=[KAFKA % {"fin": 100, "retard": 0}, KAFKA % {"fin": 400, "retard": 0}])
        tableau.mesurer(avec_kafka=True)
        horloge["t"] += 30
        tableau.mesurer(avec_kafka=True)
        sujets = {s["sujet"]: s for s in tableau.kafka_resume()["sujets"]}
        self.assertEqual(sujets["iot.raw"]["debit"], 10.0)

    def test_un_producteur_qui_s_arrete_ne_fait_pas_exploser_le_retard_en_secondes(self):
        """Une panne de la collecte : le débit des 30 dernières secondes tombe à zéro, celui des 120 dernières reste significatif."""
        tableau, horloge = self.tableau([texte() for _ in range(12)], kafka=[KAFKA % {"fin": fin, "retard": 1500} for fin in
                                                                             (0, 1500, 3000, 4500, 6000, 6000, 6000, 6000, 6000, 6000)])
        for _ in range(10):
            tableau.mesurer(avec_kafka=True)
            horloge["t"] += 15
        groupe = next(g for g in tableau.kafka_resume()["groupes"] if g["groupe"] == "traitement-flux")
        courts = next(s for s in tableau.kafka_resume()["sujets"] if s["sujet"] == "iot.raw")
        self.assertEqual(courts["debit"], 0.0, "le débit court est nul : la collecte n'écrit plus")
        self.assertLess(groupe["retard_s"], 60, "le retard en secondes ne se divise pas par zéro")

    def test_au_demarrage_d_un_trafic_le_retard_en_secondes_utilise_le_debit_court(self):
        """Le débit des 120 dernières secondes est dilué par le silence d'avant : il gonflerait le retard."""
        tableau, horloge = self.tableau([texte() for _ in range(10)], kafka=[KAFKA % {"fin": fin, "retard": 1500} for fin in
                                                                             (0, 0, 0, 0, 0, 0, 0, 1500, 3000, 4500)])
        for _ in range(10):
            tableau.mesurer(avec_kafka=True)
            horloge["t"] += 15
        groupe = next(g for g in tableau.kafka_resume()["groupes"] if g["groupe"] == "traitement-flux")
        self.assertEqual(groupe["retard_s"], 15.0, "1500 messages à 100 messages par seconde (fenêtre courte)")

    def test_sans_lecture_de_kafka_le_tableau_le_dit(self):
        tableau, _ = self.tableau([texte()])
        tableau.mesurer(avec_kafka=True)
        self.assertEqual(tableau.kafka_resume(), {"mesure": False, "groupes": [], "sujets": []})


class AlarmesDuTableau(unittest.TestCase):
    def setUp(self):
        self.obs, self.docker, self.horloge, _ = fabriquer()

    def retard(self, messages, secondes):
        return {"retard": messages, "retard_s": secondes, "sujet": "iot.raw"}

    def tour(self, services=None, retards=None):
        self.horloge.avancer(5)
        mesure = self.obs.mesurer()
        mesure.tableau = {"services": services or {}, "retards": retards or {}}
        for transition in self.obs.evaluateur.evaluer(mesure):
            self.obs._noter_transition(transition)

    def en_alarme(self):
        return {(a["alarme"], a["cible"]) for a in self.obs.etat()["alarmes"] if a["etat"] == o.ALARME}

    def test_un_disjoncteur_ouvert_leve_l_alarme_tout_de_suite_et_se_ferme_avec_lui(self):
        self.tour({"collecte": {"circuits_ouverts": ["kafka"], "taux_erreurs": 1.0, "requetes": 30}})
        self.assertIn(("disjoncteur-ouvert", "collecte"), self.en_alarme())
        self.tour({"collecte": {"circuits_ouverts": [], "taux_erreurs": 0.0, "requetes": 30}})
        self.assertNotIn(("disjoncteur-ouvert", "collecte"), self.en_alarme())

    def test_le_taux_d_erreurs_demande_deux_mesures_et_un_minimum_de_trafic(self):
        haut = {"collecte": {"circuits_ouverts": [], "taux_erreurs": 0.9, "requetes": 30}}
        self.tour(haut)
        self.assertNotIn(("taux-erreurs-http", "collecte"), self.en_alarme(), "une seule mesure ne suffit pas")
        self.tour(haut)
        self.assertIn(("taux-erreurs-http", "collecte"), self.en_alarme())

    def test_trop_peu_de_requetes_ne_font_pas_une_alarme_de_taux_meme_a_cent_pour_cent(self):
        peu = {"collecte": {"circuits_ouverts": [], "taux_erreurs": 1.0, "requetes": 2}}
        self.tour(peu)
        self.tour(peu)
        self.assertNotIn(("taux-erreurs-http", "collecte"), self.en_alarme())

    def test_le_retard_de_consommation_demande_trois_mesures_au_dessus_du_seuil(self):
        for _ in range(2):
            self.tour(retards={"traitement-flux": self.retard(3000, 200.0)})
        self.assertNotIn(("retard-consommation", "traitement-flux"), self.en_alarme())
        self.tour(retards={"traitement-flux": self.retard(3000, 200.0)})
        self.assertIn(("retard-consommation", "traitement-flux"), self.en_alarme())
        self.tour(retards={"traitement-flux": self.retard(30, 2.0)})
        self.assertNotIn(("retard-consommation", "traitement-flux"), self.en_alarme())

    def test_un_retard_normal_de_fenetres_ne_leve_pas_d_alarme_meme_important_en_messages(self):
        for _ in range(4):
            self.tour(retards={"traitement-flux": self.retard(1350, 90.0)})
        self.assertNotIn(("retard-consommation", "traitement-flux"), self.en_alarme())

    def test_sans_debit_d_ecriture_le_retard_n_est_pas_mesurable_en_temps_et_ne_leve_rien(self):
        for _ in range(4):
            self.tour(retards={"alerte": self.retard(500, None)})
        self.assertNotIn(("retard-consommation", "alerte"), self.en_alarme())

    def test_un_groupe_absent_ou_un_service_muet_est_une_donnee_manquante_pas_une_alarme(self):
        self.tour({"collecte": None}, retards={})
        self.assertFalse(self.en_alarme() & {("disjoncteur-ouvert", "collecte"), ("retard-consommation", "alerte")})
        self.assertEqual(self.obs.chronologie(), [], "un premier état sans donnée n'est pas un événement")


class GelEtTrace(unittest.TestCase):
    def setUp(self):
        self.obs, self.docker, self.horloge, _ = fabriquer()
        self.horloge.avancer(5)
        self.obs.tour()

    def test_un_service_gele_leve_l_alarme_d_etat_et_la_cause_dit_gele(self):
        self.obs.injecter("collecte", mode="pause")
        for _ in range(2):
            self.horloge.avancer(5)
            self.obs.tour()
        self.assertIn(("pause", "collecte"), self.docker.appels)
        self.assertIn(("service-arrete", "collecte"), {(a["alarme"], a["cible"]) for a in self.obs.etat()["alarmes"] if a["etat"] == o.ALARME})
        self.assertIn("gelé", self.obs.rapport()["cause"]["constat"])
        self.assertEqual(self.obs.etat()["panne"]["mode"], "pause")
        self.obs.retablir()
        self.assertIn(("unpause", "collecte"), self.docker.appels)

    def test_un_mode_inconnu_est_refuse(self):
        with self.assertRaises(o.ErreurPanne):
            self.obs.injecter("collecte", mode="detruire")
        self.assertEqual(self.docker.appels, [])

    def test_la_trace_suit_un_identifiant_de_service_en_service_dans_l_ordre_du_temps(self):
        journal = "\n".join([
            "traitement-flux-1  | 2026-11-17T13:00:03.500Z " + json.dumps({"level": "INFO", "message": "indicateur publié", "correlation_id": "corr-77", "topic": "traffic.indicators"}),
            "collecte-1  | 2026-11-17T13:00:01.100Z " + json.dumps({"level": "INFO", "message": "mesure acceptée", "correlation_id": "corr-77", "event_id": "e1", "request_id": "r9"}),
            "collecte-1  | 2026-11-17T13:00:01.200Z " + json.dumps({"level": "INFO", "message": "autre", "correlation_id": "corr-88"}),
            'passerelle-1  | 2026-11-17T13:00:02.000Z 172.19.0.1 "GET /x" 503 0.001 corr-77',
            "alerte-1  | 2026-11-17T13:00:04.000Z " + json.dumps({"level": "INFO", "message": "alerte créée", "correlation_id": "corr-77"}),
        ])
        self.docker.journaux_horodates = lambda depuis: journal
        trace = self.obs.trace("corr-77")
        self.assertEqual(trace["chemin"], ["collecte", "passerelle", "traitement-flux", "alerte"])
        self.assertEqual([ligne["texte"][:20] for ligne in trace["lignes"]][:2], ["mesure acceptée", '172.19.0.1 "GET /x" '])
        self.assertEqual(trace["lignes"][1]["niveau"], "ERROR")
        self.assertNotIn("corr-88", json.dumps(trace))
        self.assertEqual(trace["lignes"][0]["champs"]["request_id"], "r9")

    def test_la_trace_refuse_un_identifiant_qui_n_est_pas_sobre(self):
        for mauvais in ("", "a b", "x;rm -rf", "é" * 5, "ab", "x" * 101):
            with self.assertRaises(o.ErreurPanne):
                self.obs.trace(mauvais)

    def test_le_tableau_assemble_services_kafka_et_trafic_sans_planter_quand_rien_ne_repond(self):
        self.obs.trafic_etat = lambda: {"disponible": False, "etat": None, "run": None, "envoyes": None}
        donnees = self.obs.donnees_tableau()
        self.assertEqual({s["id"] for s in donnees["services"]}, {"collecte", "traitement", "alerte", "reponse"})
        self.assertFalse(donnees["kafka"]["mesure"])
        self.assertIn("passerelle", {a["id"] for a in donnees["autres"]})
        self.assertNotIn("postgres", {a["id"] for a in donnees["autres"]})

    def test_le_trafic_refuse_une_action_inconnue(self):
        with self.assertRaises(o.ErreurPanne):
            self.obs.trafic("tout casser")


class ResumeDesSignaux(unittest.TestCase):
    def ligne(self, logger, message, ts="2026-11-17T18:00:00.000Z", level="WARNING"):
        return json.dumps({"ts": ts, "level": level, "logger": logger, "message": message})

    def test_cent_lignes_identiques_deviennent_une_ligne_et_un_compte(self):
        lignes = [self.ligne("kafka.cluster", "No node available", ts=f"2026-11-17T18:00:{i % 60:02d}.000Z") for i in range(100)]
        (resume,) = o.resumer_signaux(lignes)
        self.assertIn("(×100, jusqu'à 2026-11-17T18:00:39.000Z)", resume)

    def test_les_decisions_du_service_passent_avant_le_bruit_de_la_bibliotheque(self):
        lignes = [self.ligne("kafka.cluster", f"bruit {i}") for i in range(10)]
        lignes += [self.ligne("app.resilience", "disjoncteur ouvert"), self.ligne("app.kafka", "publication échouée", level="ERROR")]
        resume = o.resumer_signaux(lignes, limite=3)
        self.assertEqual([json.loads(x.split("  (×")[0])["message"] for x in resume[:2]], ["disjoncteur ouvert", "publication échouée"])
        self.assertEqual(len(resume), 3)

    def test_les_lignes_nginx_qui_ne_different_que_par_des_chiffres_sont_regroupees(self):
        lignes = [f'2026/11/17 18:00:0{i} [error] 32#32: *{i}00 connect() failed (113: Host is unreachable)' for i in range(5)]
        (resume,) = o.resumer_signaux(lignes)
        self.assertIn("×5", resume)

    def test_une_ligne_unique_n_a_pas_de_compte(self):
        (resume,) = o.resumer_signaux([self.ligne("app.x", "une fois")])
        self.assertNotIn("×", resume)


class DocumentEtConfiguration(unittest.TestCase):
    def test_les_quatre_services_qui_publient_des_metriques_sont_declares(self):
        config = o.charger_config()
        self.assertEqual({n for n, d in config["services"].items() if d.get("metrics")}, {"collecte", "traitement", "alerte", "reponse"})
        for nom in ("collecte", "traitement", "alerte", "reponse"):
            self.assertIn("port_var", config["services"][nom])

    def test_les_groupes_kafka_surveilles_sont_ceux_des_services(self):
        config = o.charger_config()
        self.assertEqual(set(config["groupes_kafka"]), {"traitement-flux", "alerte", "reponse"})
        self.assertEqual(set(config["groupes_kafka_non_surveilles"]), {"traitement-entrepot"})
        self.assertTrue(config["groupes_kafka_non_surveilles"]["traitement-entrepot"].strip(), "une absence d'alarme se justifie par écrit")


if __name__ == "__main__":
    unittest.main()
