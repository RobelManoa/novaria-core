"""Compare un run SUMO au générateur v0 sur le même carrefour (INT_01), le même scénario horaire et la même demande.

Les deux runs reçoivent **la même demande moyenne** (formule du générateur v0). Ce qui les distingue est l'origine de l'état :
dans le v0 le scénario **impose** l'état (fluide, ralenti, saturé) et en tire des mesures bruitées ; dans SUMO l'état **naît**
de la demande, des feux et du comportement des véhicules. La comparaison porte sur les mesures émises, minute par minute,
avec la règle de seuils du traitement (ADR-028, `app.flux.classifier`) appliquée aux deux de la même façon.

Rien ici ne mesure « lequel est plus réaliste » : il n'y a pas de trafic réel de ce carrefour pour trancher.
"""

import statistics
from collections import Counter, defaultdict
from decimal import Decimal

from jeu_entrainement import catalogue as cat
from jeu_entrainement import fenetres, simulation
from jeu_entrainement.lignes import rapport_de_vitesse
from mesures import reference
from prototype_sumo import INTERSECTION, SCENARIO

VITESSE_FLUIDE_KMH = 50.0
ETATS = ("FREE_FLOW", "SLOW", "CONGESTED")
BIN_MIN = 30
ROUTES = ("ROAD_001", "ROAD_002", "ROAD_003", "ROAD_004")


def run_v0(graine: int, debut: str, duree_s: int):
    """Le générateur v0, même scénario horaire, mêmes dates ; les fenêtres de 1 minute des quatre approches de INT_01."""
    spec = cat.RunSpec(f"ia11-v0-s{graine}", SCENARIO, graine, "evaluation", debut, duree_s)
    resultat = simulation.executer(spec)
    fen, _ = fenetres.calculer(resultat)
    return {k: v for k, v in fen.items() if k[0] in ROUTES}


def series(fen: dict) -> dict[str, list[tuple]]:
    """Par approche, les minutes dans l'ordre : (début ms, véhicules, ratio de vitesse ou None, file, occupation)."""
    sortie: dict[str, list[tuple]] = defaultdict(list)
    for (route, debut), w in sorted(fen.items(), key=lambda x: (x[0][0], x[0][1])):
        vitesse = w.exact_average_speed
        ratio = rapport_de_vitesse(Decimal(vitesse) if vitesse is not None else None, VITESSE_FLUIDE_KMH)
        sortie[route].append((debut, w.vehicle_count, ratio, float(w.max_queue_length_m or 0.0), float(w.occupancy_rate or 0.0)))
    return sortie


def etats(serie: list[tuple]) -> list[str]:
    """L'état annoncé par la règle de seuils à chaque minute (même fonction que pour le jeu v1)."""
    adaptee = [("run", "x", debut, vehicules, ratio, 0) for debut, vehicules, ratio, _, _ in serie]
    return reference.etats_de_la_regle(adaptee)


def resume(fen: dict) -> dict:
    s = series(fen)
    toutes = [m for serie in s.values() for m in serie]
    par_etat = Counter(e for serie in s.values() for e in etats(serie))
    total = sum(par_etat.values())
    ratios = [m[2] for m in toutes if m[2] is not None]
    par_tranche: dict[int, list] = defaultdict(list)
    debut0 = min(m[0] for m in toutes)
    for m in toutes:
        par_tranche[(m[0] - debut0) // (BIN_MIN * 60_000)].append(m)
    tranches = []
    for k in sorted(par_tranche):
        lot = par_tranche[k]
        rs = [m[2] for m in lot if m[2] is not None]
        tranches.append({"tranche": k, "vehicules_par_minute": statistics.fmean(m[1] for m in lot), "ratio_vitesse": statistics.fmean(rs) if rs else None,
                         "file_m": statistics.fmean(m[3] for m in lot), "minutes_sans_vitesse": sum(1 for m in lot if m[2] is None) / len(lot)})
    comptes = [m[1] for m in toutes]
    return {
        "minutes": total, "vehicules_par_minute_moyen": statistics.fmean(comptes), "vehicules_par_minute_ecart_type": statistics.pstdev(comptes),
        "ratio_vitesse_moyen": statistics.fmean(ratios), "ratio_vitesse_ecart_type": statistics.pstdev(ratios), "ratio_vitesse_min": min(ratios),
        "part_minutes_sans_vitesse": 1 - len(ratios) / len(toutes), "file_max_m": max(m[3] for m in toutes), "file_moyenne_m": statistics.fmean(m[3] for m in toutes),
        "etats": {e: par_etat.get(e, 0) / total for e in ETATS}, "tranches": tranches,
        "etats_par_approche": {r: {e: Counter(etats(serie)).get(e, 0) / len(serie) for e in ETATS} for r, serie in s.items()},
    }


def correlation(a: list[float], b: list[float]) -> float | None:
    """Corrélation de deux profils ; `None` quand l'un est constant (la corrélation n'y est pas définie)."""
    try:
        return statistics.correlation(a, b)
    except statistics.StatisticsError:
        return None


def comparer(fen_sumo: dict, fen_v0: dict) -> dict:
    s, v = resume(fen_sumo), resume(fen_v0)
    profil = ([t["vehicules_par_minute"] for t in s["tranches"]], [t["vehicules_par_minute"] for t in v["tranches"]])
    return {"sumo": s, "v0": v, "intersection": INTERSECTION, "correlation_profil_de_demande": correlation(*profil)}
