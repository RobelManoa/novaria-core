"""Prévisions d'un modèle entraîné sur un réseau de vitesses (IA-16, ADR-015, ADR-032).

Pour un réseau chargé dans l'entrepôt (`dwh.speed_*`), le service lit les dernières vitesses
mesurées, les passe au **modèle appris** (fichier
JSON du dossier des modèles, `app/forecast/reseau.py`) et rend, par capteur : la prévision du
modèle, celle de la persistance (la dernière
vitesse connue, la référence à battre) et, quand l'instant prévu est déjà dans l'entrepôt, la
vitesse réellement mesurée.

Honnêteté : un modèle ne sert que le réseau sur lequel il a été appris. S'il manque, ne correspond
pas aux capteurs chargés, ou si le pas du
réseau n'est pas celui du modèle, le service le dit (`ModelUnavailable`) et ne rend rien : il ne
retombe jamais sur la persistance en la
présentant comme un modèle. Un capteur absent du modèle n'a pas de prévision ; il est compté, jamais
inventé.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from app.forecast.reseau import FENETRE, FormatInvalide, ModeleReseau
from app.repositories.speed import Coverage, SpeedNetwork, SpeedRepository

MPH_EN_KMH = 1.609344
PAS = timedelta(minutes=5)
HISTORIQUE_PAS = 36  # trois heures : de quoi remplir une mesure absente par la dernière connue
HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
TAILLE_MAX_FICHIER = 64 * 1024 * 1024


class NetworkNotFound(Exception):
    pass


class ModelUnavailable(Exception):
    """Le réseau n'a pas de modèle utilisable ; le message dit pourquoi (il n'est jamais remplacé
    par une référence)."""


class NoDataBefore(Exception):
    """Aucune mesure du réseau à cette date ou avant."""


@dataclass(frozen=True)
class LoadedModel:
    model: ModeleReseau
    file_sha256: str


@dataclass(frozen=True)
class SensorForecast:
    sensor_id: str
    target_time: datetime
    predicted_speed_kmh: float
    persistence_speed_kmh: float
    observed_speed_kmh: float | None


@dataclass(frozen=True)
class ForecastResult:
    network: SpeedNetwork
    loaded: LoadedModel
    as_of: datetime
    horizon_min: int
    items: list[SensorForecast]
    sensors_without_model: int


@dataclass(frozen=True)
class NetworkSummary:
    network: SpeedNetwork
    coverage: Coverage
    model: LoadedModel | None
    model_problem: str | None


_CACHE: dict[tuple[str, int, int], LoadedModel] = {}


def model_path(models_dir: Path, network_id: str) -> Path:
    return models_dir / f"prevision-{network_id}-reseau.json"


def load_model(models_dir: Path | None, network_id: str) -> LoadedModel:
    """Lit (et garde en mémoire tant que le fichier ne change pas) le modèle du réseau, ou dit
    pourquoi on ne peut pas."""
    if models_dir is None:
        raise ModelUnavailable("Le dossier des modèles n'est pas configuré (MODELS_DIR).")
    path = model_path(models_dir, network_id)
    try:
        info = path.stat()
    except OSError as error:
        raise ModelUnavailable(f"Aucun modèle entraîné pour le réseau {network_id!r}.") from error
    if info.st_size > TAILLE_MAX_FICHIER:
        raise ModelUnavailable("Le fichier du modèle est trop gros : refusé.")
    key = (str(path), info.st_mtime_ns, info.st_size)
    if key not in _CACHE:
        try:
            raw = path.read_bytes()
            loaded = LoadedModel(ModeleReseau.depuis_octets(raw), hashlib.sha256(raw).hexdigest())
        except (OSError, FormatInvalide) as error:
            raise ModelUnavailable(f"Le fichier du modèle est refusé : {error}") from error
        _CACHE.clear()
        _CACHE[key] = loaded
    return _CACHE[key]


class SpeedForecastService:
    def __init__(self, repository: SpeedRepository, models_dir: Path | None) -> None:
        self._repository = repository
        self._models_dir = models_dir

    def networks(self) -> list[NetworkSummary]:
        summaries = []
        for network in self._repository.list_networks():
            try:
                loaded, problem = load_model(self._models_dir, network.network_id), None
            except ModelUnavailable as error:
                loaded, problem = None, str(error)
            summaries.append(
                NetworkSummary(
                    network, self._repository.coverage(network.network_id), loaded, problem
                )
            )
        return summaries

    def forecast(
        self,
        network_id: str,
        *,
        as_of: datetime | None,
        horizon_min: int,
        sensor_ids: list[str] | None,
    ) -> ForecastResult:
        network = self._repository.get_network(network_id)
        if network is None:
            raise NetworkNotFound(network_id)
        if network.step_s != 300:
            raise ModelUnavailable(
                "Le modèle est appris sur des pas de 5 minutes ; ce réseau n'en a pas."
            )
        loaded = load_model(self._models_dir, network_id)
        model = loaded.model
        in_network = set(self._repository.sensors(network_id))
        missing = [sensor for sensor in model.capteurs if sensor not in in_network]
        if missing:
            raise ModelUnavailable(
                f"Le modèle connaît {len(missing)} capteur(s) absent(s) du réseau chargé : "
                "il ne correspond plus à ce réseau."
            )
        last = self._repository.last_before(network_id, as_of)
        if last is None:
            raise NoDataBefore(network_id)
        horizon_steps = horizon_min // 5
        start = last - (HISTORIQUE_PAS - 1) * PAS
        readings = self._repository.readings(network_id, start, last + horizon_steps * PAS)
        index = {sensor: i for i, sensor in enumerate(model.capteurs)}
        grid = np.full((HISTORIQUE_PAS + horizon_steps, len(index)), np.nan)
        for reading in readings:
            row = round((reading.observed_at - start) / PAS)
            if (
                0 <= row < grid.shape[0]
                and reading.sensor_id in index
                and abs(reading.observed_at - (start + row * PAS)) < timedelta(seconds=1)
            ):
                grid[row, index[reading.sensor_id]] = reading.speed
        history = grid[:HISTORIQUE_PAS]
        speeds_mph = history * (1.0 if network.speed_unit == "mph" else 1 / MPH_EN_KMH)
        filled = speeds_mph.copy()
        for column in range(filled.shape[1]):
            known = np.nan
            for row in range(filled.shape[0]):
                if np.isnan(filled[row, column]):
                    filled[row, column] = known if not np.isnan(known) else model.moyenne
                else:
                    known = filled[row, column]
        window = slice(HISTORIQUE_PAS - FENETRE, HISTORIQUE_PAS)
        instants = np.array(
            [int((start + i * PAS).timestamp() * 1000) for i in range(HISTORIQUE_PAS)],
            dtype=np.int64,
        )
        predicted = model.predire(
            filled[window], (~np.isnan(speeds_mph[window])).astype(float), instants[window]
        )
        # Le modèle et `filled` parlent en miles par heure, quelle que soit l'unité du réseau.
        to_kmh = MPH_EN_KMH
        native_to_kmh = 1.0 if network.speed_unit == "kmh" else MPH_EN_KMH
        target_time = last + horizon_steps * PAS
        wanted = set(sensor_ids) if sensor_ids else None
        items = []
        for sensor, column in index.items():
            if wanted is not None and sensor not in wanted:
                continue
            observed = grid[HISTORIQUE_PAS + horizon_steps - 1, column]
            items.append(
                SensorForecast(
                    sensor_id=sensor,
                    target_time=target_time,
                    predicted_speed_kmh=round(
                        float(predicted[column, horizon_steps - 1]) * to_kmh, 1
                    ),
                    persistence_speed_kmh=round(float(filled[-1, column]) * to_kmh, 1),
                    observed_speed_kmh=None
                    if np.isnan(observed)
                    else round(float(observed) * native_to_kmh, 1),
                )
            )
        return ForecastResult(
            network, loaded, last, horizon_min, items, len(in_network) - len(index)
        )


def card(loaded: LoadedModel) -> dict:
    """La fiche du modèle, telle que l'entraînement l'a écrite dans le fichier (`meta`)."""
    return json.loads(json.dumps(loaded.model.meta))
