"""Critère de MS-07 : un même scénario rejoué avec la même graine produit les mêmes messages."""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from helpers import SIMULATOR, START, config, digest, lines, play

from novaria_sim.pacing import Pacer
from novaria_sim.run import Run
from novaria_sim.runner import execute

APP = SIMULATOR / "app.py"


class MemesMessages(unittest.TestCase):
    def test_meme_graine_meme_scenario_memes_messages(self):
        premier = lines(play(config())[0])
        second = lines(play(config())[0])
        self.assertEqual(premier, second)
        self.assertEqual(len(premier), 24 * 60)  # 24 capteurs, 60 intervalles de 10 s

    def test_les_trois_scenarios_sont_rejouables(self):
        for scenario in ("journee-calme", "heure-de-pointe", "incident-ponctuel"):
            with self.subTest(scenario=scenario):
                self.assertEqual(lines(play(config(scenario))[0]), lines(play(config(scenario))[0]))

    def test_une_autre_graine_change_les_mesures_pas_le_calendrier_des_etats(self):
        un, truth_un, _ = play(config(seed=1, start=datetime(2026, 10, 20, 8, 0, tzinfo=UTC)))
        deux, truth_deux, _ = play(config(seed=2, start=datetime(2026, 10, 20, 8, 0, tzinfo=UTC)))
        self.assertNotEqual(lines(un), lines(deux))
        self.assertEqual([r["label_state"] for r in truth_un], [r["label_state"] for r in truth_deux])

    def test_un_instant_donne_la_meme_mesure_quel_que_soit_le_debut_du_run(self):
        # Les valeurs viennent de (graine, capteur, instant) : reprendre un run plus tard ne change pas le recouvrement.
        long = {d.event["id"]: d for d in play(config(minutes=10))[0]}
        court = play(config(minutes=5, start=START + timedelta(minutes=3)))[0]
        self.assertTrue(court)
        for delivery in court:
            self.assertEqual(delivery.event, long[delivery.event["id"]].event)

    def test_le_debit_ne_change_aucun_message(self):
        sans_frein = lines(play(config())[0])

        class Horloge:
            now = 0.0

            def clock(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        class Collecteur:
            def __init__(self):
                self.lines = []

            def send(self, delivery):
                from novaria_sim.events import to_line

                self.lines.append(to_line(delivery.event))

            def close(self):
                pass

        horloge, sink = Horloge(), Collecteur()
        execute(Run(config()), [sink], None, Pacer(1000.0, horloge.clock, horloge.sleep))
        self.assertEqual(sink.lines, sans_frein)

    def test_empreinte_epinglee(self):
        """Empreinte du run de référence : elle change si le format, le modèle ou l'aléa changent (alors la mettre à
        jour, et dire dans la revue que les runs déjà produits ne se rejouent plus à l'identique)."""
        cfg = config("incident-ponctuel", 42, minutes=5, start=datetime(2026, 10, 20, 8, 10, tzinfo=UTC), run_id="run-demo-0001")
        self.assertEqual(digest(lines(play(cfg)[0])), EMPREINTE_REFERENCE)


EMPREINTE_REFERENCE = "a343235fab8b571f0f64003121efa6a21b2de46f4dcc3b77092cf88e4c9224c6"


class EntreProcessus(unittest.TestCase):
    """Un set ou un dict ne doit jamais décider de l'ordre : PYTHONHASHSEED change d'un processus à l'autre."""

    def lancer(self, dossier: Path, hashseed: str) -> dict[str, bytes]:
        environnement = {**os.environ, "PYTHONHASHSEED": hashseed}
        resultat = subprocess.run(
            [sys.executable, str(APP), "run", "--scenario", "heure-de-pointe", "--seed", "42", "--run-id", "run-processus",
             "--start", "2026-10-20T07:30:00Z", "--duration", "5m", "--out", str(dossier),
             "--anomaly", "muet:sensor=SENSOR_007,at=+60,duration=40s", "--anomaly", "doublon:sensor=SENSOR_001,at=+30"],
            env=environnement, capture_output=True, text=True, check=False,
        )
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        return {fichier.name: fichier.read_bytes() for fichier in sorted(dossier.iterdir())}

    def test_deux_processus_ecrivent_des_fichiers_identiques_octet_pour_octet(self):
        with tempfile.TemporaryDirectory() as racine:
            a = self.lancer(Path(racine) / "a", "1")
            b = self.lancer(Path(racine) / "b", "987654")
        self.assertEqual(set(a), {"mesures.jsonl", "verite-terrain.jsonl", "manifest.json"})
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
