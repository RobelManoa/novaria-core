"""Aléa sans état : chaque valeur est une fonction pure de (graine, clé).

Pas de générateur qui avance : la valeur d'un capteur à un instant ne dépend ni de l'ordre de calcul, ni des autres
capteurs, ni d'une anomalie injectée ailleurs. Rejouer, sauter dans le temps ou reprendre un run donne les mêmes
valeurs. Le résultat vient de BLAKE2b, donc il ne dépend pas de la version de Python ni de PYTHONHASHSEED.
"""

import hashlib
import math

_MANTISSA_BITS = 53


def uniform(seed: int, *key: object) -> float:
    """Réel de [0, 1) déterminé par la graine et la clé (53 bits : exact en virgule flottante, jamais 1.0)."""
    material = ":".join(str(part) for part in (seed, *key)).encode("utf-8")
    digest = hashlib.blake2b(material, digest_size=8).digest()
    return (int.from_bytes(digest, "big") >> (64 - _MANTISSA_BITS)) / (1 << _MANTISSA_BITS)


def normal(seed: int, *key: object) -> float:
    """Valeur centrée réduite (loi de Irwin-Hall à 6 termes, de variance 1) : que des additions, donc identique partout."""
    total = sum(uniform(seed, *key, "n", i) for i in range(6))
    return (total - 3.0) * math.sqrt(2.0)


def poisson(u: float, rate: float) -> int:
    """Nombre de véhicules d'un intervalle : inversion de la fonction de répartition de Poisson pour un tirage `u`."""
    if rate <= 0:
        return 0
    if rate > 500:
        raise ValueError("espérance trop grande pour l'inversion directe")
    term = math.exp(-rate)
    cumulative = term
    count = 0
    while u > cumulative and count < 10_000:
        count += 1
        term *= rate / count
        cumulative += term
    return count
