"""Catalogue des runs du jeu v1 et leur découpage (ADR-027, règles 4 et 8).

Un run = un scénario du simulateur + une graine + une plage horaire + des anomalies injectées. Les trois
scénarios (journée calme, heure de pointe, incident ponctuel) donnent les situations ; les anomalies
« capteur muet », « message en retard » et « message en doublon » sont injectées dans plusieurs runs de chacun.

Découpage **par run** : un `run_id` appartient à un seul ensemble, jamais deux. Il est aussi **par scénario** :
chaque ensemble contient des runs de chacun des trois scénarios, pour que l'évaluation ne repose pas sur une
situation que le modèle n'a jamais vue. Limite connue : la graine ne change que le bruit des mesures, pas le
calendrier des états du scénario (simulator/novaria_sim/scenarios.py) ; deux runs du même scénario ont donc le
même calendrier de congestion. Évaluer sur un scénario jamais vu exige un quatrième scénario (voir PROVENANCE.md).
"""

from collections import Counter
from dataclasses import dataclass

JEU_ID = "novaria-congestion-v1"
NUMERO_DE_VERSION = 1
TRAIN, VALIDATION, TEST = "train", "validation", "test"
ENSEMBLES = (TRAIN, VALIDATION, TEST)
SCENARIOS = ("journee-calme", "heure-de-pointe", "incident-ponctuel")
TYPES_D_ANOMALIE = ("muet", "retard", "doublon")


class CatalogueInvalide(ValueError):
    pass


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    scenario_id: str
    seed: int
    ensemble: str
    debut: str  # heure UTC de début, « HH:MM », le jour des exemples du contrat (2026-10-20)
    duree_s: int
    anomalies: tuple[str, ...] = ()  # écriture de la ligne de commande du simulateur, `at` en « +secondes »
    note: str = ""

    @property
    def types_d_anomalie(self) -> tuple[str, ...]:
        return tuple(sorted({a.partition(":")[0] for a in self.anomalies}))


HEURE = 3600
CATALOGUE: tuple[RunSpec, ...] = (
    # --- Journée calme : tout reste fluide, 08:00 à 14:00 (le jour par défaut dure 24 h, la nuit est vide)
    RunSpec("ds1-calme-s11", "journee-calme", 11, TRAIN, "08:00", 6 * HEURE, note="sans anomalie"),
    RunSpec("ds1-calme-s12", "journee-calme", 12, TRAIN, "08:00", 6 * HEURE,
            ("muet:sensor=SENSOR_003,at=+3600,duration=10m",), "capteur muet pendant 10 minutes"),
    RunSpec("ds1-calme-s13", "journee-calme", 13, VALIDATION, "08:00", 6 * HEURE,
            ("retard:sensor=SENSOR_010,at=+1800,duration=20m,delay=120",), "messages en retard de 2 minutes (refusés par le traitement)"),
    RunSpec("ds1-calme-s14", "journee-calme", 14, TEST, "08:00", 6 * HEURE,
            ("doublon:sensor=SENSOR_001,at=+1200,duration=30m,copies=2,lag=3",), "messages reçus trois fois"),
    # --- Heure de pointe : les approches Nord et Ouest se saturent entre 07:20 et 08:50 (décalage par tronçon)
    RunSpec("ds1-pointe-s21", "heure-de-pointe", 21, TRAIN, "06:00", 5 * HEURE, note="sans anomalie"),
    RunSpec("ds1-pointe-s22", "heure-de-pointe", 22, TRAIN, "06:00", 5 * HEURE,
            ("retard:sensor=SENSOR_002,at=+5400,duration=30m,delay=120",
             "doublon:sensor=SENSOR_004,at=+5400,duration=30m,copies=1,lag=2"), "retards et doublons pendant la montée"),
    RunSpec("ds1-pointe-s23", "heure-de-pointe", 23, VALIDATION, "06:00", 5 * HEURE,
            ("muet:sensor=SENSOR_001,at=+6000,duration=15m",), "capteur muet pendant la saturation"),
    RunSpec("ds1-pointe-s24", "heure-de-pointe", 24, TEST, "06:00", 5 * HEURE,
            ("retard:sensor=SENSOR_002,at=+6600,duration=20m,delay=120",
             "muet:sensor=SENSOR_004,at=+7200,duration=10m"), "retards puis capteur muet"),
    # --- Incident ponctuel : ROAD_005 de 08:10 à 08:35, les autres approches de INT_02 ralentissent
    RunSpec("ds1-incident-s31", "incident-ponctuel", 31, TRAIN, "07:30", 3 * HEURE, note="sans anomalie"),
    RunSpec("ds1-incident-s32", "incident-ponctuel", 32, TRAIN, "07:30", 3 * HEURE,
            ("muet:sensor=SENSOR_005,at=+2400,duration=20m",), "le capteur de l'incident se tait pendant l'incident"),
    RunSpec("ds1-incident-s33", "incident-ponctuel", 33, VALIDATION, "07:30", 3 * HEURE,
            ("doublon:sensor=SENSOR_006,at=+2400,duration=20m,copies=2,lag=3",), "messages reçus trois fois"),
    RunSpec("ds1-incident-s34", "incident-ponctuel", 34, TEST, "07:30", 3 * HEURE,
            ("retard:sensor=SENSOR_007,at=+2400,duration=20m,delay=120",), "messages en retard de 2 minutes (refusés par le traitement)"),
)


def par_ensemble(catalogue: tuple[RunSpec, ...] = CATALOGUE) -> dict[str, tuple[RunSpec, ...]]:
    return {ensemble: tuple(r for r in catalogue if r.ensemble == ensemble) for ensemble in ENSEMBLES}


def verifier(catalogue: tuple[RunSpec, ...] = CATALOGUE, *, scenarios: tuple[str, ...] = SCENARIOS) -> None:
    """Refuse un catalogue dont le découpage fuirait : recouvrement de runs ou ensemble qui manque un scénario."""
    problemes = []
    for ensemble in Counter(r.ensemble for r in catalogue):
        if ensemble not in ENSEMBLES:
            problemes.append(f"ensemble inconnu : {ensemble!r}")
    for nom, valeurs in (("run_id", [r.run_id for r in catalogue]), ("graine", [r.seed for r in catalogue])):
        doublons = sorted({v for v, n in Counter(valeurs).items() if n > 1}, key=str)
        if doublons:
            problemes.append(f"{nom} en double (un run, une graine, un ensemble) : {doublons}")
    for ensemble in ENSEMBLES:
        runs = [r for r in catalogue if r.ensemble == ensemble]
        if not runs:
            problemes.append(f"l'ensemble {ensemble} est vide")
        manquants = sorted(set(scenarios) - {r.scenario_id for r in runs})
        if runs and manquants:
            problemes.append(f"l'ensemble {ensemble} n'a aucun run des scénarios {manquants}")
    for run in catalogue:
        if run.scenario_id not in scenarios:
            problemes.append(f"{run.run_id} : scénario {run.scenario_id!r} hors catalogue")
        if run.duree_s <= 0 or run.duree_s % 60:
            problemes.append(f"{run.run_id} : la durée est un nombre entier de minutes")
    if problemes:
        raise CatalogueInvalide("\n".join(problemes))
