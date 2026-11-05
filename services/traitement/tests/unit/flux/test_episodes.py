"""Épisodes de congestion (ADR-028, dictionnaire 7.2) : ouverture, suivi, clôture, identité."""

import uuid

from app.flux.classifier import Hysteresis, Observation, advance
from app.flux.episodes import EpisodeTracker

from .support import epoch_ms

T0 = epoch_ms("2026-10-20T08:00:00Z")


def play(series, tracker=None):
    """Rend la liste des (index de fenêtre, enregistrement d'épisode) émis."""
    tracker = tracker or EpisodeTracker("r1", "SIMULATED", "ROAD_001")
    h = Hysteresis()
    out = []
    for index, item in enumerate(series):
        completeness, ratio, vehicles = item if isinstance(item, tuple) else (1.0, item, 5)
        obs = Observation(T0 + index * 60_000, completeness, ratio, vehicles)
        new = advance(h, obs)
        record = tracker.observe(h, new, obs)
        if record is not None:
            out.append((index, record))
        h = new
    return out


def at(index):
    return T0 + index * 60_000


def test_aucun_episode_tant_que_la_circulation_est_fluide():
    assert play([0.9, 0.8, 0.9, 0.7]) == []


def test_l_episode_s_ouvre_a_la_confirmation_et_date_de_la_premiere_fenetre_degradee():
    records = play([0.9, 0.5, 0.4])  # fenêtres 1 et 2 dégradées, confirmées à la 2

    index, opened = records[0]
    assert index == 2
    assert opened.started_at_ms == at(1)
    assert opened.ended_at_ms is None
    assert opened.peak_state == "SLOW"
    assert opened.window_count == 2
    assert opened.min_speed_ratio == 0.4


def test_chaque_fenetre_degradee_met_l_episode_a_jour():
    records = play([0.9, 0.5, 0.5, 0.45, 0.2])

    assert [r.window_count for _, r in records] == [2, 3, 4]
    assert [r.min_speed_ratio for _, r in records] == [0.5, 0.45, 0.2]


def test_le_pic_monte_avec_l_etat_et_ne_redescend_pas():
    records = play([0.9, 0.3, 0.3, 0.46, 0.46, 0.46])

    assert [r.peak_state for _, r in records] == ["CONGESTED"] * 4
    assert (
        records[-1][1].window_count == 5
    )  # fenêtres 1 à 5 : l'épisode reste ouvert en passant à SLOW


def test_l_episode_se_ferme_au_retour_au_fluide_a_la_premiere_fenetre_de_la_serie_de_retour():
    records = play([0.9, 0.5, 0.5, 0.8, 0.8, 0.8])

    index, closed = records[-1]
    assert index == 5
    assert closed.started_at_ms == at(1)
    assert closed.ended_at_ms == at(3)  # la reprise stable commence à la fenêtre 3
    assert closed.peak_state == "SLOW"
    # à la clôture, le compte est celui de [début, fin[ : fenêtres 1 et 2, pas la reprise
    assert closed.window_count == 2


def test_aucune_ecriture_pour_une_fenetre_sans_changement_apres_la_cloture():
    assert play([0.9, 0.5, 0.5, 0.8, 0.8, 0.8, 0.9, 0.9, 0.9])[-1][0] == 5


def test_un_second_episode_a_une_autre_identite():
    records = play([0.9, 0.5, 0.5, 0.8, 0.8, 0.8, 0.5, 0.5])

    first, second = records[0][1], records[-1][1]
    assert first.started_at_ms == at(1) and second.started_at_ms == at(6)
    assert first.episode_id != second.episode_id


def test_l_identifiant_est_stable_d_un_rejeu_a_l_autre():
    a = play([0.9, 0.5, 0.5])[0][1]
    b = play([0.9, 0.5, 0.5])[0][1]
    other_run = play([0.9, 0.5, 0.5], EpisodeTracker("r2", "SIMULATED", "ROAD_001"))[0][1]

    assert a.episode_id == b.episode_id
    assert str(uuid.UUID(a.episode_id)) == a.episode_id
    assert other_run.episode_id != a.episode_id


def test_un_trou_de_donnees_garde_l_episode_ouvert_sans_le_prolonger():
    gap = (0.1, 0.9, 5)
    records = play([0.9, 0.5, 0.5, gap, gap])

    assert [r.window_count for _, r in records] == [2]  # rien n'est écrit pendant le trou


def test_le_retour_des_donnees_apres_un_trou_ferme_l_episode_au_debut_du_trou():
    gap = (0.1, 0.9, 5)
    records = play([0.9, 0.5, 0.5, gap, gap, 0.9])

    index, closed = records[-1]
    assert index == 5
    assert closed.ended_at_ms == at(3)  # on ne sait pas ce qui s'est passé pendant le trou
    assert closed.window_count == 2


def test_une_route_vide_ferme_l_episode_comme_une_route_fluide():
    records = play([0.9, 0.3, 0.3, (1.0, None, 0), (1.0, None, 0), (1.0, None, 0)])

    assert records[-1][1].ended_at_ms == at(3)


def test_un_ratio_absent_ne_baisse_pas_le_minimum():
    records = play([0.9, 0.5, 0.5, (1.0, None, 3)])

    assert records[-1][1].min_speed_ratio == 0.5


def test_le_retour_des_donnees_avec_une_circulation_toujours_degradee_prolonge_l_episode():
    gap = (0.1, 0.9, 5)
    records = play([0.9, 0.3, 0.3, gap, gap, 0.3, 0.3])

    ids = {r.episode_id for _, r in records}
    assert len(ids) == 1  # le même épisode : ni clos ni rouvert
    assert all(r.ended_at_ms is None for _, r in records)
    assert [r.window_count for _, r in records] == [2, 3, 4]  # le trou n'est pas compté
    assert records[-1][1].started_at_ms == at(1)


def test_le_retour_des_donnees_avec_un_ralentissement_leger_garde_l_episode_ouvert():
    gap = (0.1, 0.9, 5)
    records = play([0.9, 0.3, 0.3, gap, 0.5])

    last = records[-1][1]
    assert last.ended_at_ms is None and last.peak_state == "CONGESTED"
    assert last.min_speed_ratio == 0.3


def test_un_ratio_au_dessus_du_seuil_d_entree_apres_le_trou_ferme_l_episode_au_debut_du_trou():
    gap = (0.1, 0.9, 5)
    records = play([0.9, 0.3, 0.3, gap, 0.6])

    assert records[-1][1].ended_at_ms == at(3)
