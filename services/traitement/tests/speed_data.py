"""Un petit réseau de vitesses, son dépôt de mesures et un modèle JSON de la bonne forme, pour
tester sans base ni PyTorch (IA-16)."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np

from app.forecast.reseau import PAS_PAR_SEMAINE, formes_attendues
from app.repositories.speed import Coverage, SpeedNetwork, SpeedReading

T0 = datetime(2012, 6, 20, 8, 0, tzinfo=UTC)
SENSORS = ["773869", "767541", "716328", "718141"]
NETWORK = SpeedNetwork(
    "metr-la", "METR-LA (essai)", "Réseau d'essai", "REAL_HISTORICAL", 300, "mph"
)
CACHE = 4

META = {
    "reseau": "metr-la",
    "jeu": "METR-LA",
    "type_de_source": "REAL_HISTORICAL",
    "nom": "reseau-spatio-temporel",
    "version": "1",
    "entraine_le": "2026-11-22T14:00:00Z",
    "poids": 123,
    "horizons_min": [5, 10, 15, 20, 25, 30],
    "periodes": {
        "apprentissage": {
            "debut": "2012-03-01T00:55:00Z",
            "fin": "2012-05-23T06:35:00Z",
            "pas": 100,
        },
        "test": {"debut": "2012-06-10T03:35:00Z", "fin": "2012-06-27T23:55:00Z", "pas": 50},
    },
    "test": {
        "15": {
            "mae_modele": 2.9,
            "mae_persistance": 3.5,
            "gain": 0.17,
            "intervalle_95": [-0.6, -0.5],
            "mae_hgb_ia16": 2.88,
        }
    },
    "variables": ["vitesse des 12 derniers pas"],
    "limites": ["appris sur METR-LA seulement"],
}


def model_bytes(sensors=None, meta=None, seed=1) -> bytes:
    sensors = sensors or SENSORS
    n = len(sensors)
    rng = np.random.default_rng(seed)
    poids = {
        nom: np.round(rng.normal(scale=0.3, size=forme), 6).tolist()
        for nom, forme in formes_attendues(CACHE).items()
    }
    document = {
        "format": "novaria-modele-reseau",
        "version": 1,
        "capteurs": list(sensors),
        "moyenne": 55.0,
        "ecart": 12.0,
        "echelle_sortie": 10.0,
        "adjacence": (np.eye(n)).tolist(),
        "habituel": np.zeros((PAS_PAR_SEMAINE, n)).tolist(),
        "poids": poids,
        "meta": meta or META,
    }
    return json.dumps(document).encode("utf-8")


def speed(sensor_rank: int, step: int) -> float:
    """Une vitesse connue de chaque capteur et pas, en mph : de quoi retrouver la valeur lue."""
    return round(40.0 + sensor_rank * 5 + (step % 7) * 0.5, 2)


class FakeSpeedRepository:
    """Quatre capteurs, des mesures toutes les 5 minutes de T0 − 5 h à T0 + 1 h ; le capteur 2 n'a
    aucune mesure au pas T0."""

    def __init__(
        self, network: SpeedNetwork = NETWORK, sensors=None, first_step=-60, last_step=12
    ) -> None:
        self.network = network
        self.sensor_ids = list(sensors or SENSORS)
        self.first_step, self.last_step = first_step, last_step

    def _rows(self) -> list[SpeedReading]:
        rows = []
        for step in range(self.first_step, self.last_step + 1):
            for rank, sensor in enumerate(self.sensor_ids):
                if rank == 2 and step == 0:
                    continue
                rows.append(
                    SpeedReading(T0 + timedelta(minutes=5 * step), sensor, speed(rank, step))
                )
        return rows

    def list_networks(self):
        return [self.network]

    def get_network(self, network_id):
        return self.network if network_id == self.network.network_id else None

    def sensors(self, network_id):
        return list(self.sensor_ids)

    def coverage(self, network_id):
        rows = self._rows()
        return Coverage(
            rows[0].observed_at,
            rows[-1].observed_at,
            self.last_step - self.first_step + 1,
            len(self.sensor_ids),
        )

    def last_before(self, network_id, at):
        instants = sorted({r.observed_at for r in self._rows()})
        keep = [i for i in instants if at is None or i <= at]
        return keep[-1] if keep else None

    def readings(self, network_id, start, end):
        return [r for r in self._rows() if start <= r.observed_at <= end]
