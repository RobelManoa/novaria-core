"""Le simulateur vers la collecte (MS-16) : reprises, disjoncteur, identifiant de corrélation propagé.

Un faux serveur dont on commande la panne : 503 tant que `panne` est vrai. Aucune attente réelle : l'horloge et le sommeil sont
remplacés. Lancement : python3 -m unittest discover -s simulator/tests -p "test_resilience_collecte.py".
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import ROOT, config, play  # noqa: F401 - helpers place le simulateur dans sys.path
from novaria_sim.sinks import CORRELATION_HEADER, CollecteSink


class Collecte:
    def __init__(self):
        self.panne, self.requetes, self.en_tetes = False, 0, []
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                faux.requetes += 1
                faux.en_tetes.append(self.headers.get(CORRELATION_HEADER))
                corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                code, reponse = (503, {"code": "UPSTREAM_UNAVAILABLE"}) if faux.panne else (202, {"event_id": corps["id"], "status": "ACCEPTED"})
                octets = json.dumps(reponse).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(octets)))
                self.end_headers()
                self.wfile.write(octets)

            def log_message(self, *args):
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.serveur.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.serveur.shutdown()
        self.serveur.server_close()


class Horloge:
    maintenant = 1000.0

    def __call__(self):
        return self.maintenant


def livraisons(n):
    return play(config(minutes=1))[0][:n]


class Reprises(unittest.TestCase):
    def sink(self, url, horloge=None, attentes=None, **options):
        return CollecteSink(url, clock=horloge or Horloge(), sleep=(attentes if attentes is not None else []).append, **options)

    def test_un_503_passager_est_rejoue_avec_une_attente_croissante_puis_accepte(self):
        attentes = []
        with Collecte() as collecte:
            sink = self.sink(collecte.url, attentes=attentes, attempts=3, retry_base_s=0.1)
            collecte.panne = True

            def retablir(duree):
                attentes.append(duree)
                collecte.panne = len(attentes) < 2  # la panne cesse après la deuxième attente

            sink.sleep = retablir
            sink.send(livraisons(1)[0])
            sink.close()
        self.assertEqual(sink.receipts.accepted, 1)
        self.assertEqual(sink.receipts.errors, 0)
        self.assertEqual(len(attentes), 2)
        self.assertGreater(attentes[1], attentes[0])
        self.assertEqual(sink.retries, 2)
        self.assertEqual(collecte.requetes, 3)

    def test_une_panne_qui_dure_est_comptee_apres_toutes_les_tentatives(self):
        with Collecte() as collecte:
            collecte.panne = True
            sink = self.sink(collecte.url, attempts=3)
            sink.send(livraisons(1)[0])
            sink.close()
        self.assertEqual((sink.receipts.accepted, sink.receipts.errors, sink.receipts.last_error), (0, 1, "Unavailable"))
        self.assertEqual(collecte.requetes, 3)

    def test_un_422_n_est_jamais_rejoue(self):
        with Collecte() as collecte:
            sink = self.sink(collecte.url)
            livraison = livraisons(1)[0]
            livraison.event["data"]["vehicle_count"] = -1
            collecte.panne = False
            sink.send(livraison)
            sink.close()
        self.assertEqual(collecte.requetes, 1)


class Disjoncteur(unittest.TestCase):
    def test_apres_cinq_envois_en_echec_les_suivants_echouent_sans_appeler_la_collecte(self):
        with Collecte() as collecte:
            collecte.panne = True
            sink = CollecteSink(collecte.url, attempts=1, circuit_failures=5, clock=Horloge(), sleep=lambda _: None)
            for livraison in livraisons(12):
                sink.send(livraison)
            sink.close()
        self.assertEqual(collecte.requetes, 5, "le disjoncteur s'ouvre au cinquième échec")
        self.assertEqual(sink.receipts.errors, 12, "aucun message n'est caché : tous comptés en erreur")
        self.assertEqual(sink.receipts.last_error, "disjoncteur ouvert")
        self.assertEqual(sink.circuit_opened, 1)

    def test_la_collecte_revenue_un_essai_referme_le_disjoncteur(self):
        horloge = Horloge()
        with Collecte() as collecte:
            collecte.panne = True
            sink = CollecteSink(collecte.url, attempts=1, circuit_failures=2, circuit_reset_s=10, clock=horloge, sleep=lambda _: None)
            for livraison in livraisons(4):
                sink.send(livraison)
            avant = collecte.requetes
            collecte.panne = False
            sink.send(livraisons(5)[4])
            self.assertEqual(collecte.requetes, avant, "ouvert : le message n'est pas envoyé")
            horloge.maintenant += 11
            sink.send(livraisons(6)[5])
            sink.send(livraisons(7)[6])
            sink.close()
        self.assertEqual(collecte.requetes, avant + 2)
        self.assertEqual(sink.receipts.accepted, 2)


class Correlation(unittest.TestCase):
    def test_chaque_requete_porte_l_identifiant_de_correlation_du_message(self):
        with Collecte() as collecte:
            sink = CollecteSink(collecte.url, clock=Horloge(), sleep=lambda _: None)
            envoyees = livraisons(3)
            for livraison in envoyees:
                sink.send(livraison)
            sink.close()
        self.assertEqual(collecte.en_tetes, [livraison.event["correlation_id"] for livraison in envoyees])
        self.assertTrue(all(valeur and valeur.startswith("corr-") for valeur in collecte.en_tetes))

    def test_un_identifiant_qui_n_est_pas_sobre_n_est_pas_envoye(self):
        with Collecte() as collecte:
            sink = CollecteSink(collecte.url, clock=Horloge(), sleep=lambda _: None)
            livraison = livraisons(1)[0]
            livraison.event["correlation_id"] = "a b\nc"
            sink.send(livraison)
            sink.close()
        self.assertEqual(collecte.en_tetes, [None])


class MemeCode(unittest.TestCase):
    def test_le_fichier_de_resilience_est_le_meme_dans_la_collecte_et_dans_le_simulateur(self):
        collecte = (ROOT / "services" / "collecte" / "app" / "core" / "resilience.py").read_text(encoding="utf-8")
        simulateur = (ROOT / "simulator" / "novaria_sim" / "resilience.py").read_text(encoding="utf-8")
        self.assertEqual(collecte, simulateur)


if __name__ == "__main__":
    unittest.main()
