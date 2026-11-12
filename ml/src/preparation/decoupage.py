"""Découpage entraînement / validation / test : par run et par scénario, et dans l'ordre du temps pour la prévision.

Deux découpages, deux usages :

- **par run et par scénario** (détection, jeu v1) : un run est dans un seul ensemble, chaque ensemble a des runs de
  chaque scénario. Il est décrit par le catalogue et son empreinte SHA-256, et vérifié contre le manifeste du jeu ;
- **dans l'ordre du temps** (prévision, séries longues comme METR-LA) : le passé apprend, le futur évalue. Un **délai de
  garde** de la taille de l'horizon écarte les lignes dont la réponse (la valeur `horizon` minutes plus tard) tombe dans
  la partie suivante : sans lui, la réponse du dernier apprentissage serait déjà la première valeur de la validation.

Tout est déterministe : aucun tirage au hasard, aucune graine.
"""

import hashlib
from collections.abc import Mapping, Sequence

from jeu_entrainement import catalogue as cat

MINUTE_MS = 60_000
PARTS_PAR_DEFAUT = (0.70, 0.15, 0.15)
PARTIES = (cat.TRAIN, cat.VALIDATION, cat.TEST)


# --- Par run et par scénario ---------------------------------------------------------------------

def affectation(catalogue: tuple[cat.RunSpec, ...] = cat.CATALOGUE) -> list[tuple[str, str, int, str]]:
    """(run_id, scénario, graine, ensemble) de chaque run, triés par run_id."""
    return sorted((r.run_id, r.scenario_id, r.seed, r.ensemble) for r in catalogue)


def empreinte_du_decoupage(catalogue: tuple[cat.RunSpec, ...] = cat.CATALOGUE) -> str:
    """SHA-256 de l'affectation (une ligne « run|scénario|graine|ensemble » par run, LF) : deux exécutions, même valeur."""
    texte = "".join(f"{run}|{scenario}|{graine}|{ensemble}\n" for run, scenario, graine, ensemble in affectation(catalogue))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def verifier_le_decoupage(catalogue: tuple[cat.RunSpec, ...] = cat.CATALOGUE) -> list[str]:
    """Les écarts du catalogue (run ou graine dans deux ensembles, scénario absent d'un ensemble) ; vide = conforme."""
    try:
        cat.verifier(catalogue)
    except cat.CatalogueInvalide as erreur:
        return str(erreur).splitlines()
    return []


def verifier_contre_le_manifeste(manifeste: Mapping, catalogue: tuple[cat.RunSpec, ...] = cat.CATALOGUE) -> list[str]:
    """Le manifeste du jeu décrit-il le découpage du catalogue ? Aucun fichier de données n'est lu.

    L'intégrité des fichiers (`construire_jeu.py --verifier`) garantit que les fichiers sont ceux du manifeste ; ce
    contrôle garantit que le manifeste range chaque run là où le catalogue le range, sans run dans deux fichiers.
    """
    ecarts = []
    attendus = {r.run_id: r for r in catalogue}
    par_run = {r["run_id"]: r for r in manifeste.get("runs", [])}
    if set(par_run) != set(attendus):
        ecarts.append(f"runs du manifeste et du catalogue différents : {sorted(set(par_run) ^ set(attendus))}")
    for run_id, run in sorted(par_run.items()):
        if run_id in attendus and (run["ensemble"], run["scenario_id"], run["seed"]) != (
            attendus[run_id].ensemble, attendus[run_id].scenario_id, attendus[run_id].seed
        ):
            ecarts.append(f"{run_id} : le manifeste le range dans {run['ensemble']}, le catalogue dans {attendus[run_id].ensemble}")
    fichiers = manifeste.get("fichiers", {})
    vus: dict[str, str] = {}
    for nom, fichier in sorted(fichiers.items()):
        for run_id in fichier["runs"]:
            if run_id in vus:
                ecarts.append(f"{run_id} figure dans {vus[run_id]} et dans {nom}")
            vus[run_id] = nom
            if run_id in attendus and nom != f"{attendus[run_id].ensemble}.parquet":
                ecarts.append(f"{run_id} est dans {nom}, le catalogue l'attend dans {attendus[run_id].ensemble}.parquet")
    return ecarts


def plis_par_run(runs: Sequence[tuple[str, str]]) -> list[list[str]]:
    """Validation croisée groupée par run : un pli met de côté le k-ième run de **chaque scénario**.

    `runs` : couples (run_id, scénario). Un run n'est jamais coupé entre apprentissage et validation, et chaque pli garde
    tous les scénarios dans l'apprentissage (il reste un autre run de chacun). Le nombre de plis est celui du scénario
    qui a le moins de runs ; les runs en trop vont dans le dernier pli. Aucun tirage au hasard.
    """
    par_scenario: dict[str, list[str]] = {}
    for run_id, scenario in sorted(runs):
        par_scenario.setdefault(scenario, []).append(run_id)
    plis = min(len(ids) for ids in par_scenario.values())
    if plis < 2:
        raise ValueError("au moins deux runs par scénario sont nécessaires pour une validation croisée groupée")
    resultat: list[list[str]] = [[] for _ in range(plis)]
    for ids in par_scenario.values():
        for rang, run_id in enumerate(ids):
            resultat[min(rang, plis - 1)].append(run_id)
    return [sorted(pli) for pli in resultat]


# --- Dans l'ordre du temps -----------------------------------------------------------------------

def _verifier_les_parts(parts: Sequence[float]) -> None:
    if len(parts) != 3 or any(p <= 0 for p in parts) or abs(sum(parts) - 1) > 1e-9:
        raise ValueError(f"trois parts positives de somme 1 attendues, reçu {tuple(parts)}")


def decouper_dans_l_ordre_du_temps(
    instants_ms: Sequence[int], parts: Sequence[float] = PARTS_PAR_DEFAUT, horizon_min: int = 15
) -> dict[str, list[int]]:
    """Indices (de `instants_ms`) de l'entraînement, de la validation, du test, et des lignes écartées par le délai de garde.

    Les instants sont ceux d'une ou de plusieurs séries (millisecondes). Les bornes sont les instants du rang
    `parts[0] × n` et `(parts[0] + parts[1]) × n` : une ligne est dans la partie de son instant, sauf si sa réponse
    (`instant + horizon`) atteint la partie suivante : elle est alors écartée. Plusieurs lignes au même instant vont
    toutes dans la même partie.
    """
    _verifier_les_parts(parts)
    if horizon_min < 0:
        raise ValueError("l'horizon ne peut pas être négatif")
    n = len(instants_ms)
    if n < 10:
        raise ValueError(f"trop peu de lignes pour trois parties : {n}")
    ordre = sorted(range(n), key=lambda i: (instants_ms[i], i))
    borne_validation = instants_ms[ordre[round(parts[0] * n)]]
    borne_test = instants_ms[ordre[round((parts[0] + parts[1]) * n)]]
    garde = horizon_min * MINUTE_MS
    resultat: dict[str, list[int]] = {cat.TRAIN: [], cat.VALIDATION: [], cat.TEST: [], "ecartes": []}
    for i in ordre:
        t = instants_ms[i]
        if t >= borne_test:
            resultat[cat.TEST].append(i)
        elif t >= borne_validation:
            resultat[cat.VALIDATION if t + garde < borne_test else "ecartes"].append(i)
        else:
            resultat[cat.TRAIN if t + garde < borne_validation else "ecartes"].append(i)
    return resultat


def plis_temporels(instants_ms: Sequence[int], plis: int = 3, horizon_min: int = 15) -> list[dict[str, list[int]]]:
    """Validation croisée dans l'ordre du temps, à fenêtre croissante (réglage des hyperparamètres de la prévision).

    L'ensemble est coupé en `plis + 1` blocs de même effectif ; au pli `j`, le bloc `j` valide et tout ce qui le précède
    (moins le délai de garde) apprend. Le premier bloc n'est jamais validé : il n'a pas de passé.
    """
    n = len(instants_ms)
    if plis < 1 or n < 10 * (plis + 1) or horizon_min < 0:
        raise ValueError(f"découpage impossible : {n} lignes, {plis} plis, horizon {horizon_min}")
    ordre = sorted(range(n), key=lambda i: (instants_ms[i], i))
    bornes = [instants_ms[ordre[round(j * n / (plis + 1))]] for j in range(1, plis + 1)] + [None]
    garde = horizon_min * MINUTE_MS
    resultat = []
    for j in range(plis):
        debut, fin = bornes[j], bornes[j + 1]
        pli: dict[str, list[int]] = {"apprentissage": [], "validation": []}
        for i in ordre:
            t = instants_ms[i]
            if debut <= t and (fin is None or t < fin):
                pli["validation"].append(i)
            elif t + garde < debut:
                pli["apprentissage"].append(i)
        resultat.append(pli)
    return resultat


def empreinte_des_indices(partition: Mapping[str, Sequence[int]]) -> str:
    """SHA-256 d'un découpage (« partie : indices » par ligne, parties triées) : la preuve qu'il se refait à l'identique."""
    texte = "".join(f"{nom}:{','.join(map(str, indices))}\n" for nom, indices in sorted(partition.items()))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()
