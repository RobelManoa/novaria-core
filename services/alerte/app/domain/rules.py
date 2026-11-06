"""Évaluation des règles d'alerte sur les indicateurs d'une minute (MS-11, ADR-028).

Fonctions pures, sans base ni bus : une fenêtre et les règles en entrée, des décisions en sortie.
Le moteur ne retient que des séries de fenêtres consécutives (en mémoire), jamais une alerte : la
base arbitre (un index unique, `min_gap_s`). Il peut donc répéter une décision sans effet de bord.

Trois règles, une par ligne de `alertes.alert_rule` :

- `congestion.persistante` (CONGESTION) : s'ouvre quand l'état stabilisé (hystérésis de
  `traitement`) est au moins `state` pendant `min_windows` fenêtres ; se résout au retour à
  FREE_FLOW (clôture de l'épisode).
- `anomalie.circulation` (TRAFFIC_ANOMALY) : s'ouvre après `min_windows` fenêtres fluides mais
  saturées (occupation ≥ `occupancy_min` ou file ≥ `queue_min_m`) ; se résout quand une fenêtre ne
  l'est plus.
- `capteur.muet` (SENSOR_FAULT) : s'ouvre après `silence_s` secondes sans aucune mesure ; se résout
  dès qu'une fenêtre contient une mesure.

L'anomalie ne regarde que les fenêtres fluides : la vitesse seule ne voit pas une saturation, c'est
son rôle. Dès que le tronçon ralentit, la congestion prend le relais (une seule alerte par épisode).
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.domain.model import WINDOW_S, Kind, Open, Resolve, Rule, Severity, Window

Decision = Open | Resolve

RANK = {"FREE_FLOW": 0, "SLOW": 1, "CONGESTED": 2}
MAX_SERIES = 10_000  # séries gardées en mémoire : au-delà, les plus anciennes sont oubliées

DEFAULTS: dict[Kind, dict[str, Any]] = {
    Kind.CONGESTION: {"state": "CONGESTED", "min_windows": 1, "severity": "WARNING"},
    Kind.TRAFFIC_ANOMALY: {
        "min_windows": 3,
        "occupancy_min": 0.8,
        "queue_min_m": 150.0,
        "severity": "INFO",
    },
    Kind.SENSOR_FAULT: {"silence_s": 60, "severity": "WARNING"},
}


def settings_of(rule: Rule) -> dict[str, Any]:
    """Les paramètres de la règle, complétés par les valeurs de départ pour ceux qui manquent."""
    return {**DEFAULTS[rule.kind], **rule.params}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# nom du paramètre -> (contrôle, ce qui est attendu)
_CHECKS: dict[Kind, dict[str, tuple[Callable[[Any], bool], str]]] = {
    Kind.CONGESTION: {
        "state": (lambda v: v in ("SLOW", "CONGESTED"), "SLOW ou CONGESTED"),
        "min_windows": (lambda v: _is_int(v) and 1 <= v <= 60, "un entier de 1 à 60"),
    },
    Kind.TRAFFIC_ANOMALY: {
        "min_windows": (lambda v: _is_int(v) and 1 <= v <= 60, "un entier de 1 à 60"),
        "occupancy_min": (lambda v: _is_number(v) and 0 < v <= 1, "un nombre de 0 (exclu) à 1"),
        "queue_min_m": (lambda v: _is_number(v) and 0 < v <= 10000, "un nombre de 0 à 10000"),
    },
    Kind.SENSOR_FAULT: {
        "silence_s": (
            lambda v: _is_int(v) and WINDOW_S <= v <= 3600,
            f"un entier de {WINDOW_S} à 3600 (la fenêtre la plus courte dure {WINDOW_S} s)",
        ),
    },
}
_SEVERITY_CHECK = (lambda v: v in tuple(Severity), "INFO, WARNING ou CRITICAL")


def invalid_params(kind: Kind, params: dict[str, Any]) -> list[tuple[str, str]]:
    """(paramètre, message) pour chaque paramètre inconnu ou hors des valeurs permises."""
    checks = {**_CHECKS[kind], "severity": _SEVERITY_CHECK}
    problems: list[tuple[str, str]] = []
    for name, value in params.items():
        if name not in checks:
            problems.append((name, f"paramètre inconnu pour une règle {kind.value}"))
        elif not checks[name][0](value):
            problems.append((name, f"valeur attendue : {checks[name][1]}"))
    return problems


@dataclass
class _Series:
    """Fenêtres consécutives qui satisfont la condition d'une règle, pour un tronçon d'un run."""

    count: int = 0
    silent_s: int = 0
    last_start: datetime | None = None


class RuleEngine:
    """Mémoire des séries. Un redémarrage la vide : une série repart de zéro, au pire une alerte
    arrive de `min_windows - 1` fenêtres plus tard ; jamais en double (la base arbitre)."""

    def __init__(self) -> None:
        self._series: OrderedDict[tuple[str, str, str], _Series] = OrderedDict()
        self._undo: list[tuple[_Series, _Series]] = []  # séries touchées par le dernier `evaluate`

    def revert(self) -> None:
        """Annule l'effet du dernier `evaluate` sur les séries.

        À appeler quand l'écriture des décisions a échoué : sans cela, la fenêtre serait déjà
        « vue » et son rejeu serait ignoré à tort.
        """
        for series, before in reversed(self._undo):
            series.count, series.silent_s, series.last_start = (
                before.count,
                before.silent_s,
                before.last_start,
            )
        self._undo = []

    def evaluate(self, window: Window, rules: list[Rule]) -> list[Decision]:
        self._undo = []
        if window.window_size_s != WINDOW_S:
            return []
        decisions: list[Decision] = []
        for rule in rules:
            if rule.enabled:
                decisions += self._apply(rule, window)
        return decisions

    def _series_of(self, rule: Rule, window: Window) -> _Series | None:
        """La série de ce tronçon, ou `None` si la fenêtre a déjà été vue (relivraison)."""
        key = (rule.rule_id, window.provenance.run_id, window.road_segment_id)
        series = self._series.get(key)
        if series is None:
            series = self._series[key] = _Series()
            if len(self._series) > MAX_SERIES:
                self._series.popitem(last=False)
        else:
            self._series.move_to_end(key)
        if series.last_start is not None and window.window_start <= series.last_start:
            return None
        self._undo.append((series, replace(series)))
        series.last_start = window.window_start
        return series

    def _apply(self, rule: Rule, window: Window) -> list[Decision]:
        series = self._series_of(rule, window)
        if series is None:
            return []
        return _EVALUATORS[rule.kind](rule, settings_of(rule), series, window)


def _congestion(rule: Rule, params: dict, series: _Series, window: Window) -> list[Decision]:
    state = window.congestion_state
    if state == "UNKNOWN":
        # Données insuffisantes : ni preuve de congestion, ni retour au fluide.
        series.count = 0
        return []
    if RANK[state] >= RANK[params["state"]]:
        series.count += 1
        if series.count >= params["min_windows"]:
            facts = {"congestion_state": state, "speed_ratio": window.speed_ratio}
            return [Open(rule, Severity(params["severity"]), window, facts)]
        return []
    series.count = 0
    # L'épisode se clôt au retour à FREE_FLOW ; entre les deux (SLOW alors qu'on attend CONGESTED),
    # il est encore ouvert.
    return [Resolve(rule.kind, window)] if state == "FREE_FLOW" else []


def _saturated(window: Window, params: dict) -> bool:
    occupancy, queue = window.occupancy_rate, window.max_queue_length_m
    return (occupancy is not None and occupancy >= params["occupancy_min"]) or (
        queue is not None and queue >= params["queue_min_m"]
    )


def _anomaly(rule: Rule, params: dict, series: _Series, window: Window) -> list[Decision]:
    if window.sample_count == 0 or window.congestion_state == "UNKNOWN":
        series.count = 0
        return []
    if window.congestion_state == "FREE_FLOW" and _saturated(window, params):
        series.count += 1
        if series.count >= params["min_windows"]:
            facts = {
                "occupancy_rate": window.occupancy_rate,
                "max_queue_length_m": window.max_queue_length_m,
            }
            return [Open(rule, Severity(params["severity"]), window, facts)]
        return []
    series.count = 0
    return [Resolve(rule.kind, window)]


def _sensor_fault(rule: Rule, params: dict, series: _Series, window: Window) -> list[Decision]:
    if window.sample_count == 0:
        series.silent_s += window.window_size_s
        if series.silent_s >= params["silence_s"]:
            facts = {"silent_s": series.silent_s, "silence_s": params["silence_s"]}
            return [Open(rule, Severity(params["severity"]), window, facts)]
        return []
    series.silent_s = 0
    return [Resolve(rule.kind, window)]


_EVALUATORS: dict[Kind, Callable[[Rule, dict, _Series, Window], list[Decision]]] = {
    Kind.CONGESTION: _congestion,
    Kind.TRAFFIC_ANOMALY: _anomaly,
    Kind.SENSOR_FAULT: _sensor_fault,
}
