"""Variables calendaires d'un instant (UTC), pour la détection comme pour la prévision.

Le jeu v1 n'a qu'un jour simulé : ces variables y sont constantes (fiche de provenance, section 8) et le cadrage les
interdit pour la détection. Elles servent la prévision sur un jeu qui couvre des semaines (IA-10) : la fonction se
calcule depuis l'instant seul, jamais depuis une colonne du jeu.
"""

import math
from collections.abc import Collection
from datetime import UTC, date, datetime

NOMS = ("hour_of_day", "iso_day_of_week", "is_weekend", "is_holiday", "hour_sin", "hour_cos", "dow_sin", "dow_cos")


def variables_calendaires(instant: datetime, jours_feries: Collection[date] = ()) -> dict[str, float | int | bool]:
    """Heure, jour de semaine ISO, week-end, jour férié, et les deux angles (heure, jour) en sinus et cosinus.

    Les angles évitent la fausse distance entre 23 h et 0 h. `jours_feries` : aucun calendrier n'est chargé (question
    Q3 de DAT-10 sans réponse) ; sans liste, `is_holiday` vaut toujours faux, comme dans le jeu v1.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("l'instant doit porter un fuseau : le calendrier se calcule en UTC")
    instant = instant.astimezone(UTC)
    fraction_d_heure = instant.hour + instant.minute / 60
    fraction_de_semaine = (instant.isoweekday() - 1) + fraction_d_heure / 24
    return {
        "hour_of_day": instant.hour,
        "iso_day_of_week": instant.isoweekday(),
        "is_weekend": instant.isoweekday() >= 6,
        "is_holiday": instant.date() in set(jours_feries),
        "hour_sin": math.sin(2 * math.pi * fraction_d_heure / 24),
        "hour_cos": math.cos(2 * math.pi * fraction_d_heure / 24),
        "dow_sin": math.sin(2 * math.pi * fraction_de_semaine / 7),
        "dow_cos": math.cos(2 * math.pi * fraction_de_semaine / 7),
    }
