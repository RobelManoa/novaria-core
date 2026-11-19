"""Banc d'essai : des runs du simulateur, leurs messages tels que livrés et la vérité des anomalies injectées.

Le jeu `novaria-congestion-v1` n'est pas lu : ses fichiers et son empreinte restent intacts. Les runs d'ici ont leurs
propres graines (101 et plus) et trois rôles qui ne se recouvrent pas :

| Rôle | Runs | Sert à |
|---|---|---|
| `apprentissage` | 3 runs sans anomalie + 3 runs à anomalies + 2 runs synthétiques | ajuster Isolation Forest sur un flux **non étiqueté** (aucune étiquette n'est lue) |
| `validation` | 6 runs sans anomalie + 3 runs à anomalies de réglage | fixer les seuils (règles et Isolation Forest) sans toucher à l'évaluation |
| `evaluation` | 12 runs du simulateur + 2 runs à injections synthétiques | mesurer rappel, précision et délai |

Le simulateur n'injecte que quatre anomalies (`aberrante`, `muet`, `retard`, `doublon`). Un capteur figé (plateau) et une
chute de débit n'en font pas partie : les trois runs `synthetique-*` les ajoutent **après coup** sur les messages livrés,
et le rapport les marque « synthétique » pour qu'on ne les confonde pas avec une injection du simulateur.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import NamedTuple

from jeu_entrainement import simulation
from jeu_entrainement.catalogue import RunSpec

APPRENTISSAGE, VALIDATION, EVALUATION = "apprentissage", "validation", "evaluation"
HEURE = 3600
PLAGES = {"journee-calme": ("08:00", 3 * HEURE), "heure-de-pointe": ("07:00", 3 * HEURE), "incident-ponctuel": ("07:30", 3 * HEURE)}
INTERVALLE_S = 10
SIMULATEUR, SYNTHETIQUE = "simulateur", "synthétique"


class Mesure(NamedTuple):
    """Un message tel qu'il est livré : l'instant de livraison, l'instant de mesure et les trois valeurs lues."""

    livre: float  # secondes Unix de la livraison
    instant: float  # secondes Unix de fin de l'intervalle (le `time` du message)
    capteur: str
    ident: str
    vehicules: int
    vitesse: float | None  # absente quand aucun véhicule n'est passé
    occupation: float


@dataclass(frozen=True)
class Injection:
    """Une anomalie injectée : sur quel capteur, quand (premier et dernier intervalle touchés) et par qui."""

    type: str  # aberrante, muet, retard, doublon, plateau, chute
    capteur: str
    debut: float  # `time` du premier message touché
    fin: float  # `time` du dernier message touché
    effet_max_s: float  # plus longue attente avant que l'effet arrive (retard, copie tardive)
    source: str
    detail: str = ""


@dataclass(frozen=True)
class Banc:
    spec: RunSpec
    role: str
    mesures: list
    injections: list
    debut: float
    fin: float

    @property
    def duree_h(self) -> float:
        return (self.fin - self.debut) / HEURE


def _epoch(texte: str) -> float:
    return datetime.fromisoformat(texte.replace("Z", "+00:00")).timestamp()


def _mesures(resultat) -> list[Mesure]:
    sortie = []
    for livraison in resultat.livraisons:
        evenement, donnees = livraison.event, livraison.event["data"]
        sortie.append(Mesure(livraison.emit_at.timestamp(), _epoch(evenement["time"]), donnees["sensor_id"], evenement["id"],
                             donnees["vehicle_count"], donnees.get("average_speed_kmh"), donnees["occupancy_rate"]))
    return sortie


def _injections_du_simulateur(config) -> list[Injection]:
    sortie = []
    for a in config.anomalies:
        debut = a.start.timestamp()
        fin = a.last.timestamp()
        attente = {"retard": a.delay_s, "doublon": a.lag_s}.get(a.kind, 0)
        detail = {"aberrante": a.variant, "retard": f"{a.delay_s} s", "doublon": f"{a.copies} copie(s)"}.get(a.kind, f"{a.intervals * INTERVALLE_S} s")
        sortie.append(Injection(a.kind, a.sensor_id, debut, fin, float(attente), SIMULATEUR, detail))
    return sortie


def executer(spec: RunSpec, role: str) -> Banc:
    resultat = simulation.executer(spec)
    config = resultat.config
    return Banc(spec, role, _mesures(resultat), _injections_du_simulateur(config), config.start.timestamp(), config.end.timestamp())


# --------------------------------------------------------------------------- injections synthétiques (hors simulateur)
def figer(mesures: list[Mesure], capteur: str, debut: float, fin: float) -> list[Mesure]:
    """Capteur figé : dès `debut`, il répète les valeurs de son dernier message avant `debut` (nouvel identifiant, même contenu)."""
    avant = [m for m in mesures if m.capteur == capteur and m.instant < debut and m.vehicules >= 1]
    reference = max(avant, key=lambda m: m.instant)
    return [m._replace(vehicules=reference.vehicules, vitesse=reference.vitesse, occupation=reference.occupation)
            if m.capteur == capteur and debut <= m.instant <= fin else m for m in mesures]


def chuter(mesures: list[Mesure], capteur: str, debut: float, fin: float, reste: float = 0.1) -> list[Mesure]:
    """Chute de débit : le comptage et l'occupation tombent à `reste` de leur valeur, la vitesse ne bouge pas."""
    return [m._replace(vehicules=int(m.vehicules * reste), occupation=round(m.occupation * reste, 3),
                       vitesse=m.vitesse if int(m.vehicules * reste) else None)
            if m.capteur == capteur and debut <= m.instant <= fin else m for m in mesures]


# --------------------------------------------------------------------------- les runs
CAPTEURS = ("SENSOR_002", "SENSOR_011", "SENSOR_019", "SENSOR_005", "SENSOR_014", "SENSOR_022")
DEPARTS_S = (2400, 4800, 7200)

# trois injections par run, de force différente : (texte du simulateur sans `sensor` ni `at`)
FORCES = {
    "muet": ("duration=5m", "duration=10m", "duration=20m"),
    "retard": ("duration=10m,delay=45", "duration=10m,delay=120", "duration=10m,delay=300"),
    "doublon": ("duration=10m,copies=1,lag=2", "duration=10m,copies=2,lag=3", "duration=10m,copies=2,lag=3"),
    "aberrante": ("duration=10s,variant=vitesse", "duration=30s,variant=debit", "duration=60s,variant=vitesse-nulle"),
}


def _specs_evaluation() -> list[RunSpec]:
    runs, graine = [], 301
    for decalage, (scenario, (debut, duree)) in enumerate(PLAGES.items()):
        court = scenario.split("-")[-1]
        for type_, forces in FORCES.items():
            textes = tuple(f"{type_}:sensor={CAPTEURS[(decalage + rang) % len(CAPTEURS)]},at=+{DEPARTS_S[rang]},{force}" for rang, force in enumerate(forces))
            runs.append(RunSpec(f"ia09-{court}-{type_}-s{graine}", scenario, graine, EVALUATION, debut, duree, textes, f"3 × {type_}"))
            graine += 1
    return runs


def _specs_normales(role: str, premiere_graine: int) -> list[RunSpec]:
    return [RunSpec(f"ia09-{role[:3]}-{scenario.split('-')[-1]}-s{premiere_graine + rang}", scenario, premiere_graine + rang, role, debut, duree, (), "sans anomalie")
            for rang, (scenario, (debut, duree)) in enumerate(PLAGES.items())]


APPRENTISSAGE_RUNS = _specs_normales(APPRENTISSAGE, 101)
VALIDATION_RUNS = _specs_normales(VALIDATION, 111) + _specs_normales(VALIDATION, 114)
EVALUATION_RUNS = _specs_evaluation()
# Runs synthétiques : deux plateaux et deux chutes par run. Seuls les 8 capteurs des carrefours à deux voies (SENSOR_001 à
# 008) voient assez de trafic aux heures de pointe pour qu'une chute de débit existe : pas de run synthétique en journée calme.
SYNTHETIQUES = (("heure-de-pointe", 331), ("incident-ponctuel", 332))
INJECTIONS_SYNTHETIQUES = (("plateau", "SENSOR_001", 2400, 300), ("chute", "SENSOR_002", 3000, 300),
                           ("plateau", "SENSOR_006", 4800, 600), ("chute", "SENSOR_003", 5400, 600))


REGLAGE_PLAN = (("muet", "SENSOR_008", 2400, "duration=8m"), ("retard", "SENSOR_015", 3000, "duration=8m,delay=90"),
                ("doublon", "SENSOR_020", 3600, "duration=8m,copies=2,lag=3"), ("aberrante", "SENSOR_003", 4200, "duration=20s,variant=vitesse"),
                ("aberrante", "SENSOR_012", 4800, "duration=20s,variant=debit"), ("aberrante", "SENSOR_017", 5400, "duration=20s,variant=vitesse-nulle"))
REGLAGE_SYNTHETIQUES = (("plateau", "SENSOR_005", 6000, 360), ("chute", "SENSOR_007", 7200, 360))


def _decaler(capteur: str, decalage: int) -> str:
    return f"SENSOR_{(int(capteur[7:]) - 1 + decalage) % 24 + 1:03d}"


def _specs_reglage(role: str = VALIDATION, premiere_graine: int = 121, decalage: int = 0) -> list[RunSpec]:
    """Trois runs à six anomalies chacun ; `decalage` change les capteurs et les instants (apprentissage ≠ validation)."""
    runs = []
    for rang, (scenario, (debut, duree)) in enumerate(PLAGES.items()):
        textes = tuple(f"{t}:sensor={_decaler(c, decalage)},at=+{depart + 100 * decalage},{force}" for t, c, depart, force in REGLAGE_PLAN)
        runs.append(RunSpec(f"ia09-{role[:3]}-anom-{scenario.split('-')[-1]}-s{premiere_graine + rang}", scenario, premiere_graine + rang, role, debut, duree, textes, "anomalies de réglage"))
    return runs


def banc_synthetique(scenario: str, graine: int, injections_plan=INJECTIONS_SYNTHETIQUES, role: str = EVALUATION) -> Banc:
    debut_texte, duree = PLAGES[scenario]
    spec = RunSpec(f"ia09-synth-{scenario.split('-')[-1]}-s{graine}", scenario, graine, role, debut_texte, duree, (), "plateaux et chutes ajoutés après coup")
    banc = executer(spec, role)
    mesures, injections = banc.mesures, []
    for type_, capteur, depart, longueur in injections_plan:
        premier = banc.debut + depart
        dernier = premier + longueur
        mesures = figer(mesures, capteur, premier, dernier) if type_ == "plateau" else chuter(mesures, capteur, premier, dernier)
        injections.append(Injection(type_, capteur, premier, dernier, 0.0, SYNTHETIQUE, f"{longueur // 60} min"))
    return replace(banc, mesures=mesures, injections=injections)


def tous_les_bancs(roles=(APPRENTISSAGE, VALIDATION, EVALUATION)) -> dict[str, list[Banc]]:
    bancs: dict[str, list[Banc]] = {role: [] for role in roles}
    if APPRENTISSAGE in roles:
        bancs[APPRENTISSAGE] = [executer(s, APPRENTISSAGE) for s in APPRENTISSAGE_RUNS + _specs_reglage(APPRENTISSAGE, 131, 7)]
        plan = (("plateau", "SENSOR_008", 6000, 360), ("chute", "SENSOR_004", 7500, 360))
        bancs[APPRENTISSAGE] += [banc_synthetique(sc, 251 + i, plan, APPRENTISSAGE) for i, sc in enumerate(("heure-de-pointe", "incident-ponctuel"))]
    if VALIDATION in roles:
        bancs[VALIDATION] = [executer(s, VALIDATION) for s in VALIDATION_RUNS + _specs_reglage()]
        bancs[VALIDATION] += [banc_synthetique(sc, 241 + i, REGLAGE_SYNTHETIQUES, VALIDATION) for i, sc in enumerate(("heure-de-pointe", "incident-ponctuel"))]
    if EVALUATION in roles:
        bancs[EVALUATION] = [executer(s, EVALUATION) for s in EVALUATION_RUNS] + [banc_synthetique(*c) for c in SYNTHETIQUES]
    return bancs
