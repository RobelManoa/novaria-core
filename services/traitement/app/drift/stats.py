"""Indice de stabilité de population (PSI, Population Stability Index), bibliothèque standard.

Compare la distribution d'une variable dans une période de référence (le jeu d'entraînement) à
celle d'une période courante. Les tranches viennent des quantiles de la référence : chacune contient
à peu près autant de valeurs de référence, donc un décalage se voit aux extrémités.

    PSI = somme sur les tranches de (courante - référence) * ln(courante / référence)
    avec, pour chaque tranche, la part des valeurs courantes puis celle des valeurs de référence

Lecture usuelle : moins de 0,10 stable ; de 0,10 à 0,25 décalage modéré ; au-delà de 0,25
décalage important. Ce sont des valeurs de départ, à régler par l'expérience (ADR-017).
"""

import math
from bisect import bisect_right
from collections.abc import Sequence

BINS = 10
# Une tranche vide ferait diverger le logarithme : on la remplace par une très petite part.
FLOOR = 1e-4


def quantile_edges(reference: Sequence[float], bins: int = BINS) -> list[float]:
    """Bornes internes des tranches : les quantiles de la référence, sans doublon.

    Une variable presque constante donne moins de tranches ; une variable parfaitement constante
    donne une seule borne (sa valeur), de sorte que toute valeur plus basse sorte de la tranche.
    """
    ordered = sorted(reference)
    if not ordered:
        raise ValueError("référence vide")
    edges: list[float] = []
    for i in range(1, bins):
        position = i * (len(ordered) - 1) / bins
        low = int(position)
        fraction = position - low
        value = ordered[low] + fraction * (ordered[min(low + 1, len(ordered) - 1)] - ordered[low])
        if not edges or value > edges[-1]:
            edges.append(value)
    return edges or [ordered[0]]


def shares(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    """Part des valeurs dans chaque tranche, de la plus basse à la plus haute."""
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    total = len(values)
    return [count / total for count in counts]


def population_stability_index(
    reference: Sequence[float], current: Sequence[float], bins: int = BINS
) -> float:
    """PSI de `current` par rapport à `reference`. Les deux séries doivent être non vides."""
    if not current:
        raise ValueError("série courante vide")
    edges = quantile_edges(reference, bins)
    expected = shares(reference, edges)
    actual = shares(current, edges)
    total = 0.0
    for e, a in zip(expected, actual, strict=True):
        e, a = max(e, FLOOR), max(a, FLOOR)
        total += (a - e) * math.log(a / e)
    return total
