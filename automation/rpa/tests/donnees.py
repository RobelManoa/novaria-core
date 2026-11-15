"""Indicateurs d'exemple (forme de `IndicatorPage` du contrat) et fausse API, pour les tests du robot."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

DEBUT = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)


def indicateur(troncon="ROAD_001", minute=0, etat="FREE_FLOW", ratio=0.9, run="run-demo", source="SIMULATED"):
    debut = DEBUT + timedelta(minutes=5 * minute)
    return {
        "indicator_id": f"{run}:{troncon}:300:{int(debut.timestamp() * 1000)}",
        "road_segment_id": troncon,
        "intersection_id": "INT_01",
        "window_start": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_size_s": 300,
        "vehicle_count": 10,
        "flow_veh_per_min": 2.0,
        "average_speed_kmh": 40.0 if ratio is not None else None,
        "occupancy_rate": 0.2,
        "max_queue_length_m": 10.0,
        "speed_ratio": ratio,
        "sample_count": 30,
        "expected_sample_count": 30,
        "completeness": 1.0,
        "congestion_state": etat,
        "classifier_version": "regles-v0",
        "provenance": {"source_type": source, "run_id": run, "scenario_id": "heure-de-pointe", "seed": 42},
    }


def jeu(n_troncons=3, fenetres=12):
    """Trois tronçons ; ROAD_002 est congestionné la moitié du temps, ROAD_003 ralenti."""
    lignes = []
    for t in range(1, n_troncons + 1):
        for m in range(fenetres):
            etat, ratio = "FREE_FLOW", 0.9
            if t == 2 and m % 2 == 0:
                etat, ratio = "CONGESTED", 0.3
            if t == 3 and m % 4 == 0:
                etat, ratio = "SLOW", 0.6
            lignes.append(indicateur(f"ROAD_{t:03d}", m, etat, ratio))
    return lignes


class FausseApi:
    """Remplace `urllib` : réponses fixes, appels notés. Les pages sont découpées comme l'API le ferait."""

    def __init__(self, lignes=None, *, mot_de_passe="secret-de-test-12", taille_page=500):
        self.lignes = lignes if lignes is not None else jeu()
        self.mot_de_passe = mot_de_passe
        self.taille_page = taille_page
        self.appels = []

    def __call__(self, requete):
        corps = requete.data.decode() if requete.data else ""
        self.appels.append((requete.get_method(), requete.full_url, dict(requete.header_items()), corps))
        if requete.full_url.endswith("/api/v1/auth/login"):
            saisie = json.loads(corps)
            if saisie["password"] != self.mot_de_passe:
                return 401, json.dumps({"code": "INVALID_CREDENTIALS"}).encode()
            return 200, json.dumps({"access_token": "jeton-opaque", "token_type": "bearer"}).encode()
        entetes = {k.lower(): v for k, v in requete.header_items()}
        if entetes.get("authorization") != "Bearer jeton-opaque":
            return 401, json.dumps({"code": "UNAUTHENTICATED"}).encode()
        debut = int(self._cursor(requete.full_url) or 0)
        page = self.lignes[debut : debut + self.taille_page]
        suivant = str(debut + self.taille_page) if debut + self.taille_page < len(self.lignes) else None
        return 200, json.dumps({"items": page, "next_cursor": suivant}).encode()

    @staticmethod
    def _cursor(url):
        from urllib.parse import parse_qs, urlsplit

        valeurs = parse_qs(urlsplit(url).query).get("cursor")
        return valeurs[0] if valeurs else None
