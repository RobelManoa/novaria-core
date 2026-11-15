"""Contrôles de non-fuite sur les lignes du jeu : recalcul indépendant des variables, des réponses et du calendrier.

Chaque contrôle rend la liste de ses écarts (vide = conforme). Ils ne lisent que ce qu'on leur donne : le fichier de
test n'est jamais ouvert ici.
"""

import math
from collections.abc import Mapping

from preparation import calendrier, historique
from preparation.donnees import minute, par_serie

TOLERANCE = 1e-9
MAX_ECARTS = 5  # on rapporte les premiers écarts, pas des milliers


def _egal(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return math.isclose(a, b, rel_tol=0, abs_tol=TOLERANCE)


def _series(serie: list[dict]) -> tuple[dict[int, float | None], dict[int, float | None]]:
    return ({minute(ligne): ligne["speed_ratio"] for ligne in serie}, {minute(ligne): ligne["flow_veh_per_min"] for ligne in serie})


def _comparer(attendu: Mapping, ligne: dict, source: str, ecarts: list[str]) -> None:
    for nom, valeur in attendu.items():
        if not _egal(ligne[nom], valeur) and len(ecarts) < MAX_ECARTS:
            ecarts.append(f"{source} {ligne['road_segment_id']} {ligne['window_start']:%H:%M} : {nom} = {ligne[nom]}, recalculé {valeur}")


def controle_historique(lignes: list[dict]) -> list[str]:
    """Chaque variable décalée et chaque moyenne mobile est celle du **passé** de la série, recalculée à part."""
    ecarts: list[str] = []
    for (run, _), serie in par_serie(lignes).items():
        ratio, flux = _series(serie)
        for ligne in serie:
            _comparer(historique.colonnes_historiques(ratio, flux, minute(ligne)), ligne, run, ecarts)
    return ecarts


def controle_aucune_dependance_au_futur(lignes: list[dict]) -> list[str]:
    """Changer l'avenir d'une série ne change aucune variable de son passé.

    À la moitié de chaque série, toutes les mesures qui suivent sont remplacées par des valeurs absurdes ; les
    variables des minutes jusqu'à la moitié, recalculées sur la série abîmée, doivent rester celles du jeu.
    """
    ecarts: list[str] = []
    for (run, _), serie in par_serie(lignes).items():
        coupure = minute(serie[len(serie) // 2])
        ratio, flux = _series(serie)
        abime_ratio = {m: (9999.0 if m > coupure else v) for m, v in ratio.items()}
        abime_flux = {m: (-1.0 if m > coupure else v) for m, v in flux.items()}
        for ligne in serie:
            if minute(ligne) <= coupure:
                _comparer(historique.colonnes_historiques(abime_ratio, abime_flux, minute(ligne)), ligne, run, ecarts)
    return ecarts


def controle_reponses(lignes: list[dict]) -> list[str]:
    """Les réponses de la prévision sont la valeur du même tronçon `h` minutes plus tard (absente en fin de run)."""
    ecarts: list[str] = []
    for (run, _), serie in par_serie(lignes).items():
        ratio, _ = _series(serie)
        for ligne in serie:
            attendu = {f"speed_ratio_h{h}": historique.valeur_a(ratio, minute(ligne), h) for h in (5, 15)}
            _comparer(attendu, ligne, run, ecarts)
    return ecarts


def controle_calendrier(lignes: list[dict]) -> list[str]:
    """Les colonnes calendaires du jeu sont celles que la fonction calcule depuis `window_start`."""
    ecarts: list[str] = []
    for ligne in lignes:
        calcule = calendrier.variables_calendaires(ligne["window_start"])
        _comparer({nom: calcule[nom] for nom in ("hour_of_day", "iso_day_of_week", "is_weekend", "is_holiday")}, ligne, ligne["run_id"], ecarts)
    return ecarts


def controle_ordre_et_unicite(lignes: list[dict]) -> list[str]:
    """Une seule ligne par (run, tronçon, minute), et chaque minute est suivie de la suivante (pas de trou caché)."""
    ecarts = []
    for (run, troncon), serie in par_serie(lignes).items():
        minutes = [minute(ligne) for ligne in serie]
        if len(set(minutes)) != len(minutes):
            ecarts.append(f"{run} {troncon} : une minute figure deux fois")
        elif minutes != list(range(minutes[0], minutes[0] + len(minutes))):
            ecarts.append(f"{run} {troncon} : des minutes manquent dans la série")
    return ecarts[:MAX_ECARTS]
