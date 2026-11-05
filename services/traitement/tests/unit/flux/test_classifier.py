"""État de congestion stabilisé (ADR-028) : seuils, nombre de fenêtres consécutives, hystérésis."""

from app.flux.classifier import Hysteresis, Observation, advance
from app.flux.rules import DEFAULT_THRESHOLDS, Thresholds

from .support import epoch_ms

T0 = epoch_ms("2026-10-20T08:00:00Z")
EMPTY = "vide"  # route vide : aucun véhicule, donc pas de vitesse


def run(series, thresholds=DEFAULT_THRESHOLDS):
    """Chaque élément : un ratio, `EMPTY` ou (complétude, ratio, véhicules). Rend les états."""
    h = Hysteresis()
    states = []
    for index, item in enumerate(series):
        if item == EMPTY:
            completeness, ratio, vehicles = 1.0, None, 0
        elif isinstance(item, tuple):
            completeness, ratio, vehicles = item
        else:
            completeness, ratio, vehicles = 1.0, item, 5
        h = advance(h, Observation(T0 + index * 60_000, completeness, ratio, vehicles), thresholds)
        states.append(h.state)
    return states


def test_commence_inconnu_et_devient_fluide_des_que_la_complétude_suffit():
    assert run([(1.0, 0.9, 5)]) == ["FREE_FLOW"]


def test_la_complétude_de_un_demi_suffit_mais_pas_en_dessous():
    assert run([(0.5, 0.9, 5)]) == ["FREE_FLOW"]
    assert run([(0.49, 0.9, 5)]) == ["UNKNOWN"]


def test_tout_etat_retombe_en_inconnu_quand_la_complétude_manque():
    low = (0.3, 0.1, 5)
    assert run([0.9, low]) == ["FREE_FLOW", "UNKNOWN"]
    assert run([0.9, 0.5, 0.5, low]) == ["FREE_FLOW", "FREE_FLOW", "SLOW", "UNKNOWN"]
    assert run([0.9, 0.3, 0.3, low]) == ["FREE_FLOW", "FREE_FLOW", "CONGESTED", "UNKNOWN"]


def test_fluide_vers_ralenti_apres_deux_fenetres_sous_0_60():
    assert run([0.9, 0.59, 0.59]) == ["FREE_FLOW", "FREE_FLOW", "SLOW"]


def test_le_seuil_de_ralentissement_est_strict():
    assert run([0.9, 0.60, 0.60, 0.60]) == ["FREE_FLOW"] * 4


def test_fluide_vers_congestionne_directement_apres_deux_fenetres_sous_0_35():
    assert run([0.9, 0.34, 0.34]) == ["FREE_FLOW", "FREE_FLOW", "CONGESTED"]


def test_ralenti_vers_congestionne_apres_deux_fenetres_sous_0_35():
    states = run([0.9, 0.5, 0.5, 0.34, 0.34])
    assert states == ["FREE_FLOW", "FREE_FLOW", "SLOW", "SLOW", "CONGESTED"]


def test_le_seuil_de_congestion_est_strict():
    assert run([0.9, 0.5, 0.5, 0.35, 0.35, 0.35]).count("CONGESTED") == 0


def test_congestionne_vers_ralenti_apres_trois_fenetres_au_dessus_de_0_45():
    states = run([0.9, 0.3, 0.3, 0.46, 0.46, 0.46])
    assert states == ["FREE_FLOW", "FREE_FLOW", "CONGESTED", "CONGESTED", "CONGESTED", "SLOW"]


def test_le_seuil_de_reprise_vers_ralenti_est_strict():
    assert run([0.9, 0.3, 0.3, 0.45, 0.45, 0.45, 0.45])[-1] == "CONGESTED"


def test_ralenti_vers_fluide_apres_trois_fenetres_au_dessus_de_0_70():
    states = run([0.9, 0.5, 0.5, 0.71, 0.71, 0.71])
    assert states == ["FREE_FLOW", "FREE_FLOW", "SLOW", "SLOW", "SLOW", "FREE_FLOW"]


def test_congestionne_vers_fluide_directement_apres_trois_fenetres_au_dessus_de_0_70():
    states = run([0.9, 0.3, 0.3, 0.71, 0.71, 0.71])
    assert states[-1] == "FREE_FLOW"
    assert "SLOW" not in states


def test_le_seuil_de_retour_au_fluide_est_strict():
    assert run([0.9, 0.5, 0.5, 0.70, 0.70, 0.70, 0.70])[-1] == "SLOW"


def test_une_serie_qui_oscille_autour_du_seuil_ne_provoque_aucune_transition():
    assert set(run([0.9] + [0.55, 0.65] * 10)) == {"FREE_FLOW"}


def test_une_serie_qui_oscille_autour_du_seuil_de_retour_ne_provoque_qu_une_transition():
    states = run([0.9, 0.5, 0.5] + [0.72, 0.65] * 10)
    assert states.count("SLOW") == len(states) - 2  # entré en ralenti une fois, jamais ressorti


def test_une_seule_fenetre_basse_ne_change_rien():
    assert set(run([0.9, 0.2, 0.9, 0.2, 0.9])) == {"FREE_FLOW"}


def test_une_fenetre_haute_interrompt_la_serie_de_degradation():
    assert set(run([0.9, 0.5, 0.8, 0.5, 0.8, 0.5])) == {"FREE_FLOW"}


def test_la_fenetre_d_entree_compte_dans_la_serie():
    # la première fenêtre complète fait sortir de UNKNOWN et compte déjà pour le ralentissement
    assert run([0.5, 0.5]) == ["FREE_FLOW", "SLOW"]


def test_une_fenetre_inconnue_interrompt_les_series():
    assert run([0.9, 0.5, (0.2, 0.5, 5), 0.5]) == ["FREE_FLOW", "FREE_FLOW", "UNKNOWN", "FREE_FLOW"]


def test_une_route_vide_est_fluide():
    assert run([EMPTY] * 5) == ["FREE_FLOW"] * 5


def test_une_route_vide_ne_compte_pas_comme_ralentissement():
    assert set(run([0.9, EMPTY, EMPTY, EMPTY])) == {"FREE_FLOW"}


def test_trois_fenetres_de_route_vide_levent_la_congestion():
    states = run([0.9, 0.3, 0.3, EMPTY, EMPTY, EMPTY])
    assert states[-1] == "FREE_FLOW"


def test_un_ratio_absent_malgre_des_vehicules_n_apporte_aucune_preuve():
    # vitesse manquante alors que des véhicules ont passé : la série est interrompue
    unknown_speed = (1.0, None, 8)
    assert run([0.9, 0.5, unknown_speed, 0.5]) == ["FREE_FLOW"] * 4


def test_les_seuils_sont_reglables_sans_toucher_au_code():
    strict = Thresholds(slow_below=0.8, degrade_windows=1)
    assert run([0.9, 0.7], strict) == ["FREE_FLOW", "SLOW"]


def test_memorise_le_debut_de_la_serie_et_le_ratio_minimum():
    h = Hysteresis()
    for index, ratio in enumerate([0.9, 0.5, 0.4, 0.3]):
        h = advance(h, Observation(T0 + index * 60_000, 1.0, ratio, 5))

    assert h.slow == 3
    assert h.slow_since == T0 + 60_000
    assert h.slow_min == 0.3


def test_memorise_le_debut_de_la_serie_de_retour_et_celui_du_trou():
    h = Hysteresis()
    for index, ratio in enumerate([0.9, 0.5, 0.5, 0.8, 0.8]):
        h = advance(h, Observation(T0 + index * 60_000, 1.0, ratio, 5))
    assert h.free_since == T0 + 3 * 60_000

    h = advance(h, Observation(T0 + 5 * 60_000, 0.1, 0.8, 5))
    h = advance(h, Observation(T0 + 6 * 60_000, 0.1, 0.8, 5))
    assert (h.state, h.gap_since) == ("UNKNOWN", T0 + 5 * 60_000)


# -------------------------------------------- retour des données après un trou (dictionnaire, 12)

GAP = (0.1, 0.9, 5)  # complétude insuffisante : UNKNOWN


def test_apres_un_trou_en_congestion_le_retour_est_reclasse_avec_les_seuils_d_entree():
    base = [0.9, 0.3, 0.3, GAP, GAP]  # CONGESTED puis deux fenêtres inconnues

    assert run(base + [0.3])[-1] == "CONGESTED"  # sous 0,35
    assert run(base + [0.35])[-1] == "SLOW"  # 0,35 n'est pas sous 0,35
    assert run(base + [0.5])[-1] == "SLOW"  # sous 0,60
    assert run(base + [0.6])[-1] == "FREE_FLOW"  # 0,60 n'est pas sous 0,60
    assert run(base + [0.9])[-1] == "FREE_FLOW"


def test_apres_un_trou_en_ralenti_une_fenetre_tres_basse_donne_congestionne():
    assert run([0.9, 0.5, 0.5, GAP, 0.3])[-1] == "CONGESTED"


def test_apres_un_trou_une_route_vide_est_fluide_et_un_ratio_absent_ne_conclut_pas():
    base = [0.9, 0.3, 0.3, GAP]

    assert run(base + [EMPTY])[-1] == "FREE_FLOW"
    assert run(base + [(1.0, None, 8)])[-1] == "UNKNOWN"  # des véhicules sans vitesse : on attend


def test_deux_trous_de_suite_gardent_l_etat_d_avant_le_premier():
    assert run([0.9, 0.3, 0.3, GAP, GAP, GAP, 0.3])[-1] == "CONGESTED"


def test_apres_un_trou_en_fluide_le_retour_suit_le_diagramme():
    # FREE_FLOW -> UNKNOWN -> FREE_FLOW, même avec un ratio bas : une fenêtre ne dégrade pas
    assert run([0.9, GAP, 0.3]) == ["FREE_FLOW", "UNKNOWN", "FREE_FLOW"]


def test_un_trou_au_demarrage_ne_garde_aucun_etat_anterieur():
    assert run([GAP, 0.3]) == ["UNKNOWN", "FREE_FLOW"]


def test_apres_un_trou_les_series_repartent_de_zero():
    # reclassé SLOW à 0,5 ; si les deux 0,3 d'avant le trou comptaient encore, un seul 0,3 de plus
    # ramènerait en CONGESTED (série de 2 sous 0,35) ; or la série repart de zéro.
    assert run([0.9, 0.3, 0.3, GAP, 0.5, 0.3])[-2:] == ["SLOW", "SLOW"]
