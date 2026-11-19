"""Fichiers d'entrée de SUMO pour le carrefour INT_01 : géométrie du réseau v0, feux de SUMO, demande du scénario v0.

Le carrefour reprend INT_01 du simulateur v0 : quatre approches (N, E, S, W) de 2 voies, 300 m, 50 km/h. SUMO génère ses
feux (`netconvert`, programme statique à phases opposées, **sans plan Novaria**). La demande est celle du générateur v0 :
`demande_scenario × demand_factor(ARTERIAL) × 700 véhicules/h/voie × 2 voies`, la même sur les quatre approches, avec 70 %
de tout droit, 15 % de virages à gauche et 15 % à droite. Les arrivées sont poissonniennes (`period="exp(taux)"`).

Ce qui diffère du v0, à dessein : ici **personne ne choisit l'état** (fluide, ralenti, saturé). La file naît quand la demande
dépasse ce que les feux écoulent.
"""

from pathlib import Path

from jeu_entrainement.simulation import importer_le_simulateur
from prototype_sumo import INTERSECTION, SCENARIO, SEED

APPROCHES = ("N", "E", "S", "W")
POSITION = {"N": (0, 300), "E": (300, 0), "S": (0, -300), "W": (-300, 0)}
# (approche d'arrivée) → (sortie en tout droit, à gauche, à droite) ; le véhicule venant du Nord roule vers le Sud
DESTINATIONS = {"N": ("S", "E", "W"), "E": ("W", "S", "N"), "S": ("N", "W", "E"), "W": ("E", "N", "S")}
PARTS = (0.70, 0.15, 0.15)
# Capacité d'une approche du carrefour SUMO (véhicules par heure), **mesurée** : débit de sortie sous 3 000 véhicules/h
# d'arrivée pendant 50 minutes (hors les 10 premières), moyenne de 12 mesures (4 approches × graines 1 à 3, de 834 à 876).
# `python3 scripts/dev/dev.py ml-sumo calibrer` la refait. Le v0 suppose 1 400 (2 voies × 700) : les feux par défaut de
# SUMO et les gauches non protégées écoulent beaucoup moins, ce qui est un résultat du prototype et non un réglage choisi.
CAPACITE_MESUREE_VEH_H = 855.0
PAS_DEMANDE_S = 600  # la demande change toutes les 10 minutes
INTERVALLE_S = 10
POSITION_E1_M = -100.0  # boucle 100 m avant la ligne d'arrêt (négatif : mesuré depuis la fin de la voie) ; voir la sensibilité dans le document
E2_DEBUT_M, E2_LONGUEUR_M = 10.0, 280.0


def _segments():
    _, reseau, _, _ = importer_le_simulateur()
    segments = {s.approach: s for s in reseau.SEGMENTS if s.intersection_id == INTERSECTION}
    if set(segments) != set(APPROCHES):
        raise ValueError(f"{INTERSECTION} n'a pas quatre approches dans le réseau v0")
    return segments


def debit_d_approche(debut_s: int, milieu_s: int, capacite_vph: float | None = None) -> float:
    """Véhicules par heure sur une approche, au milieu d'un pas : le calcul d'espérance du générateur v0, sans l'état voulu.

    Sans `capacite_vph`, c'est exactement la formule du v0 (700 véhicules/h/voie, soit 1 400 pour deux voies à la demande 1,0)."""
    _, _, _, scenarios = importer_le_simulateur()
    segment = next(iter(_segments().values()))
    scenario = scenarios.SCENARIOS[SCENARIO]
    secondes_du_jour = (debut_s + milieu_s) % 86400
    capacite = capacite_vph if capacite_vph is not None else scenarios.CAPACITY_PER_LANE_VEH_H * segment.lane_count
    return scenario.demand_scale * scenarios.demand_factor(segment.road_type, secondes_du_jour) * capacite


def ecrire(dossier: Path, *, debut_s: int, duree_s: int, graine: int = SEED, debit_constant_vph: float | None = None, capacite_vph: float | None = None, position_e1_m: float = POSITION_E1_M) -> dict[str, Path]:
    """Écrit les fichiers d'entrée dans `dossier` et rend leurs chemins. `debut_s` : heure de début en secondes depuis minuit.

    `debit_constant_vph` impose le même débit tout le long (essai de saturation). `capacite_vph` remplace la capacité de voie du
    générateur v0 par la capacité **mesurée** du carrefour SUMO : voir `CAPACITE_MESUREE_VEH_H`."""
    dossier.mkdir(parents=True, exist_ok=True)
    segments = _segments()
    vitesse_ms = round(segments["N"].speed_limit_kmh / 3.6, 3)
    fichiers = {nom: dossier / nom for nom in ("nodes.nod.xml", "edges.edg.xml", "flows.rou.xml", "detectors.add.xml", "run.sumocfg")}

    noeuds = ['<nodes>', '  <node id="C" x="0" y="0" type="traffic_light"/>']
    noeuds += [f'  <node id="{a}" x="{x}" y="{y}" type="priority"/>' for a, (x, y) in POSITION.items()] + ['</nodes>']
    aretes = ['<edges>']
    for a in APPROCHES:
        voies = segments[a].lane_count
        aretes += [f'  <edge id="{a}_in" from="{a}" to="C" numLanes="{voies}" speed="{vitesse_ms}"/>',
                   f'  <edge id="{a}_out" from="C" to="{a}" numLanes="{voies}" speed="{vitesse_ms}"/>']
    aretes.append('</edges>')

    routes = ['<routes>', '  <vType id="voiture" length="5.0" minGap="2.5" accel="2.6" decel="4.5" sigma="0.5" maxSpeed="%s"/>' % vitesse_ms]
    for a in APPROCHES:
        for destination in DESTINATIONS[a]:
            routes.append(f'  <route id="r_{a}_{destination}" edges="{a}_in {destination}_out"/>')
    for k in range(duree_s // PAS_DEMANDE_S):
        debut, fin = k * PAS_DEMANDE_S, (k + 1) * PAS_DEMANDE_S
        par_heure = debit_constant_vph if debit_constant_vph is not None else debit_d_approche(debut_s, debut + PAS_DEMANDE_S // 2, capacite_vph)
        for a in APPROCHES:
            for destination, part in zip(DESTINATIONS[a], PARTS, strict=True):
                taux = par_heure * part / 3600
                routes.append(f'  <flow id="f_{a}_{destination}_{k:02d}" type="voiture" route="r_{a}_{destination}" begin="{debut}" end="{fin}" '
                              f'period="exp({taux:.6f})" departLane="best" departSpeed="max"/>')
    routes.append('</routes>')

    detecteurs = ['<additional>']
    for a in APPROCHES:
        for voie in range(segments[a].lane_count):
            detecteurs.append(f'  <inductionLoop id="e1_{a}_{voie}" lane="{a}_in_{voie}" pos="{position_e1_m}" period="{INTERVALLE_S}" file="e1.xml"/>')
            detecteurs.append(f'  <laneAreaDetector id="e2_{a}_{voie}" lane="{a}_in_{voie}" pos="{E2_DEBUT_M}" length="{E2_LONGUEUR_M}" period="{INTERVALLE_S}" file="e2.xml"/>')
    detecteurs.append('</additional>')

    configuration = ['<configuration>',
                     '  <input><net-file value="net.net.xml"/><route-files value="flows.rou.xml"/><additional-files value="detectors.add.xml"/></input>',
                     f'  <time><begin value="0"/><end value="{duree_s}"/></time>',
                     f'  <random_number><seed value="{graine}"/></random_number>',
                     '  <processing><time-to-teleport value="-1"/></processing>',
                     '  <report><no-step-log value="true"/><no-warnings value="true"/></report>', '</configuration>']
    for nom, lignes in (("nodes.nod.xml", noeuds), ("edges.edg.xml", aretes), ("flows.rou.xml", routes), ("detectors.add.xml", detecteurs), ("run.sumocfg", configuration)):
        fichiers[nom].write_text("\n".join(lignes) + "\n", encoding="utf-8", newline="\n")
    return fichiers
