"""Variables et réponses du jeu : une ligne par tronçon et par minute (dictionnaire de données, section 9).

Règles :
- `label_state` vient de la **vérité terrain du simulateur** (l'état voulu par le scénario), jamais de la règle de
  seuils de l'ADR-028 : sinon le modèle réapprendrait la règle qu'il doit battre ;
- les variables d'historique (`*_lag1` à `lag5`, moyennes mobiles) ne regardent que le **passé** de la ligne ;
- les réponses de prévision (`speed_ratio_h5`, `speed_ratio_h15`) regardent l'avenir de la même série ;
- une valeur qui n'existe pas (route vide, début de run, fin de run, capteur muet) est absente (`null`), jamais inventée.
"""

import math
from collections import Counter
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from jeu_entrainement.parquet import Colonne
from jeu_entrainement.simulation import ResultatRun, importer_le_simulateur

MINUTE_MS = 60_000
RATIO_MAX = Decimal("9.999")
LAGS = (1, 2, 3, 4, 5)
MOYENNES = (5, 15)
HORIZONS = (5, 15)  # minutes

_CLE = [Colonne("run_id", "string", False), Colonne("scenario_id", "string", False), Colonne("seed", "int64", False),
        Colonne("road_segment_id", "string", False), Colonne("window_start", "timestamp", False)]
_MESURES = [Colonne("vehicle_count", "int32", False), Colonne("flow_veh_per_min", "double", False),
            Colonne("average_speed_kmh", "double"), Colonne("occupancy_rate", "double"),
            Colonne("max_queue_length_m", "double"), Colonne("speed_ratio", "double")]
_HISTORIQUE = ([Colonne(f"speed_ratio_lag{k}", "double") for k in LAGS] + [Colonne(f"flow_lag{k}", "double") for k in LAGS]
               + [Colonne(f"speed_ratio_ma{n}", "double") for n in MOYENNES] + [Colonne(f"flow_ma{n}", "double") for n in MOYENNES])
_CALENDRIER = [Colonne("hour_of_day", "int32", False), Colonne("iso_day_of_week", "int32", False),
               Colonne("is_weekend", "bool", False), Colonne("is_holiday", "bool", False)]
_TRONCON = [Colonne("lane_count", "int32", False), Colonne("length_m", "int32", False),
            Colonne("free_flow_speed_kmh", "double", False), Colonne("road_type", "string", False)]
_REPONSES = [Colonne("label_state", "string", False)] + [Colonne(f"speed_ratio_h{h}", "double") for h in HORIZONS]

COLONNES: tuple[Colonne, ...] = tuple(_CLE + _MESURES + _HISTORIQUE + _CALENDRIER + _TRONCON + _REPONSES)
NOMS = tuple(c.nom for c in COLONNES)
GROUPES = {"clé": _CLE, "mesures": _MESURES, "historique": _HISTORIQUE, "calendrier": _CALENDRIER,
           "tronçon": _TRONCON, "réponses": _REPONSES}
ETATS = ("FREE_FLOW", "SLOW", "CONGESTED")


def arrondir(valeur: Decimal | None, decimales: int) -> float | None:
    """Arrondi des colonnes de l'entrepôt : moitié vers le haut, comme PostgreSQL et le traitement en flux."""
    if valeur is None:
        return None
    return float(valeur.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP))


def rapport_de_vitesse(vitesse: Decimal | None, vitesse_fluide: float) -> float | None:
    if vitesse is None:
        return None
    ratio = (vitesse / Decimal(repr(vitesse_fluide))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return arrondir(min(RATIO_MAX, ratio), 3)


def moyenne(valeurs: list[float]) -> float | None:
    return round(math.fsum(valeurs) / len(valeurs), 6) if valeurs else None


def etats_voulus(resultat: ResultatRun) -> dict[tuple[str, int], list[str]]:
    """Les états voulus par le scénario, par (tronçon, minute) : un par capteur et par intervalle de 10 s.

    Un intervalle appartient à la minute qui contient son **début**, comme les mesures dans le moteur de fenêtres.
    """
    from jeu_entrainement.fenetres import epoch_ms

    par_minute: dict[tuple[str, int], list[str]] = {}
    for ligne in resultat.verite:
        debut = epoch_ms(ligne["time"]) - 10_000
        par_minute.setdefault((ligne["road_segment_id"], debut - debut % MINUTE_MS), []).append(ligne["label_state"])
    return par_minute


def etat_de_la_minute(etats: list[str]) -> str:
    """L'état le plus fréquent de la minute ; à égalité, le dernier arrivé (l'état qui s'installe)."""
    nombres = Counter(etats)
    return max(nombres, key=lambda etat: (nombres[etat], len(etats) - 1 - etats[::-1].index(etat)))


def lignes_du_run(resultat: ResultatRun, fenetres: dict) -> tuple[list[tuple], dict]:
    """Les lignes du run, triées par tronçon puis par minute, et les mesures de qualité à consigner."""
    _, reseau, _, _ = importer_le_simulateur()
    troncons = reseau.SEGMENT_BY_ID
    voulus = etats_voulus(resultat)
    config = resultat.config
    serie: dict[str, dict[int, tuple[float | None, float]]] = {}
    base: dict[tuple[str, int], tuple] = {}
    for (troncon, debut), fenetre in fenetres.items():
        fluide = troncons[troncon].free_flow_speed_kmh
        flux = arrondir(Decimal(fenetre.vehicle_count) / Decimal(1), 2)
        ratio = rapport_de_vitesse(fenetre.exact_average_speed, fluide)
        serie.setdefault(troncon, {})[debut] = (ratio, flux)
        base[(troncon, debut)] = (
            fenetre.vehicle_count, flux, arrondir(fenetre.exact_average_speed, 1), arrondir(fenetre.exact_occupancy, 3),
            arrondir(fenetre.exact_max_queue, 1), ratio, fenetre.sample_count,
        )
    lignes: list[tuple] = []
    qualite = {"fenetres": 0, "fenetres_vides": 0, "fenetres_incompletes": 0, "etats_melanges": 0}
    for troncon_id in sorted(serie):
        troncon, valeurs = troncons[troncon_id], serie[troncon_id]
        for debut in sorted(valeurs):
            mesures = base[(troncon_id, debut)]
            ratio_passe = lambda k, d=debut, v=valeurs: v[d - k * MINUTE_MS][0] if d - k * MINUTE_MS in v else None  # noqa: E731
            flux_passe = lambda k, d=debut, v=valeurs: v[d - k * MINUTE_MS][1] if d - k * MINUTE_MS in v else None  # noqa: E731
            etats = voulus[(troncon_id, debut)]
            qualite["fenetres"] += 1
            qualite["fenetres_vides"] += mesures[6] == 0
            qualite["fenetres_incompletes"] += 0 < mesures[6] < 6
            qualite["etats_melanges"] += len(set(etats)) > 1
            moment = datetime.fromtimestamp(debut / 1000, UTC)
            futur = lambda h, d=debut, v=valeurs: v[d + h * MINUTE_MS][0] if d + h * MINUTE_MS in v else None  # noqa: E731
            lignes.append((
                config.run_id, config.scenario_id, config.seed, troncon_id, moment,
                mesures[0], mesures[1], mesures[2], mesures[3], mesures[4], mesures[5],
                *(ratio_passe(k) for k in LAGS), *(flux_passe(k) for k in LAGS),
                *(moyenne([x for k in range(1, n + 1) if (x := ratio_passe(k)) is not None]) for n in MOYENNES),
                *(moyenne([x for k in range(1, n + 1) if (x := flux_passe(k)) is not None]) for n in MOYENNES),
                moment.hour, moment.isoweekday(), moment.isoweekday() >= 6, False,
                troncon.lane_count, troncon.length_m, float(troncon.free_flow_speed_kmh), troncon.road_type,
                etat_de_la_minute(etats), *(futur(h) for h in HORIZONS),
            ))
    return lignes, qualite
