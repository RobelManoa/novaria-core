"""Cas de référence des contrats d'événements : exemples valides et cas invalides, partagés par les tests.

Utilisé par contracts/tests/test_events.py et par services/*/tests/contract/ (parité avec les modèles Pydantic).
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "events" / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def mutate(name, change):
    event = copy.deepcopy(load(name))
    change(event)
    return event


# (description, exemple de départ, modification, fragment attendu dans le message d'erreur)
INVALID_CASES = [
    ("champ inconnu dans l'enveloppe", "mesure-valide.json", lambda e: e.update(extra=1), "extra"),
    ("champ inconnu dans data", "mesure-valide.json", lambda e: e["data"].update(vitesse_mph=30), "vitesse_mph"),
    ("type inconnu", "mesure-valide.json", lambda e: e.update(type="novaria.autre.v1"), "type inconnu"),
    ("date sans fuseau", "mesure-valide.json", lambda e: e.update(time="2026-10-20T08:00:10"), "does not match"),
    ("date avec décalage au lieu de UTC", "mesure-valide.json", lambda e: e.update(time="2026-10-20T10:00:10+02:00"), "does not match"),
    ("identifiant de carrefour mal formé", "mesure-valide.json", lambda e: e.update(subject="carrefour-1"), "does not match"),
    ("vitesse négative", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=-1), "minimum"),
    ("vitesse hors borne (200 km/h)", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=250), "maximum"),
    ("taux d'occupation supérieur à 1", "mesure-valide.json", lambda e: e["data"].update(occupancy_rate=1.4), "maximum"),
    ("nombre de véhicules fractionnaire", "mesure-valide.json", lambda e: e["data"].update(vehicle_count=2.5), "integer"),
    ("vitesse présente alors qu'aucun véhicule", "mesure-route-vide.json", lambda e: e["data"].update(average_speed_kmh=30), "null"),
    ("mesure VALID sans vitesse malgré des véhicules", "mesure-valide.json", lambda e: e["data"].update(average_speed_kmh=None), "number"),
    ("mesure VALID sans taux d'occupation", "mesure-valide.json", lambda e: e["data"].update(occupancy_rate=None), "number"),
    ("statut de qualité inconnu", "mesure-valide.json", lambda e: e["data"]["quality"].update(status="GOOD"), "GOOD"),
    ("drapeau de qualité inconnu", "mesure-partielle.json", lambda e: e["data"]["quality"].update(flags=["BIZARRE"]), "BIZARRE"),
    ("provenance absente", "mesure-valide.json", lambda e: e["data"].pop("provenance"), "provenance"),
    ("simulation sans graine", "mesure-valide.json", lambda e: e["data"]["provenance"].pop("seed"), "seed"),
    ("simulation sans scénario", "mesure-valide.json", lambda e: e["data"]["provenance"].pop("scenario_id"), "scenario_id"),
    ("origine historique sans jeu de données", "mesure-valide.json",
     lambda e: e["data"]["provenance"].update(source_type="REAL_HISTORICAL"), "dataset_id"),
    ("origine inconnue", "mesure-valide.json", lambda e: e["data"]["provenance"].update(source_type="IMAGINARY"), "IMAGINARY"),
    ("fenêtre de 2 minutes", "indicateur-fluide.json", lambda e: e["data"].update(window_size_s=120), "120"),
    ("état de congestion inconnu", "indicateur-fluide.json", lambda e: e["data"].update(congestion_state="JAMMED"), "JAMMED"),
    ("ratio de vitesse non nul sans vitesse", "indicateur-route-vide.json", lambda e: e["data"].update(speed_ratio=0.5), "null"),
    ("congestion sans ratio de vitesse", "indicateur-congestion.json", lambda e: e["data"].update(speed_ratio=None), "number"),
    ("mesures attendues à zéro", "indicateur-fluide.json", lambda e: e["data"].update(expected_sample_count=0), "minimum"),
    ("alerte résolue sans date de résolution", "alerte-resolue.json", lambda e: e["data"].update(resolved_at=None), "string"),
    ("alerte non résolue avec une date de résolution", "alerte-creee.json",
     lambda e: e["data"].update(resolved_at="2026-10-20T09:00:00Z"), "null"),
    ("alerte non résolue avec un mode de résolution", "alerte-creee.json", lambda e: e["data"].update(resolution="AUTO"), "null"),
    ("état d'alerte inconnu", "alerte-creee.json", lambda e: e["data"].update(state="CLOSED"), "CLOSED"),
    ("identifiant d'alerte qui n'est pas un UUID", "alerte-creee.json", lambda e: e["data"].update(alert_id="abc"), "uuid"),
    # Règles sémantiques (comparaison entre champs)
    ("subject différent du carrefour de data", "mesure-valide.json", lambda e: e.update(subject="INT_02"), "subject"),
    ("id de mesure qui ne suit pas la convention", "mesure-valide.json", lambda e: e.update(id="n-importe-quoi"), "id de mesure"),
    ("fenêtre non alignée", "indicateur-fluide.json",
     lambda e: (e["data"].update(window_start="2026-10-20T08:00:07Z"), e.update(time="2026-10-20T08:01:07Z")), "aligné"),
    ("time d'un indicateur différent de la fin de fenêtre", "indicateur-fluide.json", lambda e: e.update(time="2026-10-20T08:00:00Z"), "fin de fenêtre"),
    ("alerte résolue avant d'être ouverte", "alerte-resolue.json", lambda e: e["data"].update(resolved_at="2026-10-20T08:00:00Z"), "précéder"),
    ("identifiant d'alerte avec des tirets mais non hexadécimal", "alerte-creee.json",
     lambda e: e["data"].update(alert_id="zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"), "uuid"),
    ("indicateur sans véhicule mais avec une vitesse", "indicateur-route-vide.json",
     lambda e: e["data"].update(average_speed_kmh=30, speed_ratio=0.5), "null"),
    # --- traffic.recommendations ---
    ("recommandation avec une seule phase", "recommandation-plan.json", lambda e: e["data"]["phases"].pop(), "too short"),
    ("phase de recommandation sans approche au vert", "recommandation-plan.json",
     lambda e: e["data"]["phases"][0].update(green_approaches=[]), "[]"),
    ("approche inconnue", "recommandation-plan.json", lambda e: e["data"]["phases"][0].update(green_approaches=["X"]), "'X'"),
    ("durée de phase nulle", "recommandation-plan.json", lambda e: e["data"]["phases"][0].update(duration_s=0), "minimum"),
    ("champ inconnu dans une phase", "recommandation-plan.json", lambda e: e["data"]["phases"][0].update(extra=1), "extra"),
    ("méthode de calcul inconnue", "recommandation-plan.json", lambda e: e["data"]["method"].update(kind="MACHINE_LEARNING"), "MACHINE_LEARNING"),
    ("score de modèle supérieur à 1", "recommandation-plan.json", lambda e: e["data"]["model"].update(score=1.5), "maximum"),
    ("identifiant de recommandation qui n'est pas un UUID", "recommandation-plan.json",
     lambda e: e["data"].update(recommendation_id="abc"), "uuid"),
    ("recommandation sans indicateur d'entrée", "recommandation-plan.json", lambda e: e["data"]["inputs"].update(indicator_ids=[]), "[]"),
    ("recommandation sans provenance", "recommandation-plan.json", lambda e: e["data"].pop("provenance"), "provenance"),
    ("domaine incorrect pour une recommandation", "recommandation-plan.json", lambda e: e.update(domain="signal"), "traffic"),
    ("id différent de recommendation_id", "recommandation-plan.json", lambda e: e.update(id="autre-id"), "recommendation_id"),
    ("fin de validité antérieure à l'émission", "recommandation-plan.json",
     lambda e: e["data"].update(valid_until="2026-10-20T08:20:00Z"), "valid_until"),
    ("cycle différent de la somme des phases", "recommandation-plan.json", lambda e: e["data"].update(cycle_s=70), "cycle_s"),
    ("identifiant de phase en double", "recommandation-plan.json", lambda e: e["data"]["phases"][1].update(phase_id="P1"), "double"),
    ("approche en double dans une phase", "recommandation-plan.json",
     lambda e: e["data"]["phases"][0].update(green_approaches=["N", "N"]), "non-unique"),
    ("indicateur d'entrée en double", "recommandation-plan.json",
     lambda e: e["data"]["inputs"].update(indicator_ids=["a", "a"]), "non-unique"),
    # --- signal.status ---
    ("mode de feux inconnu", "etat-feux-recommandation-appliquee.json", lambda e: e["data"].update(mode="AUTO"), "AUTO"),
    ("identifiant de phase mal formé", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"].update(current_phase_id="phase1"), "does not match"),
    ("durée minimale absente d'une phase d'état", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"]["phases"][0].pop("min_duration_s"), "min_duration_s"),
    ("décision refusée sans motif", "etat-feux-commande-refusee.json", lambda e: e["data"]["decision"].update(refusal_reason=None), "string"),
    ("motif de refus en minuscules", "etat-feux-commande-refusee.json",
     lambda e: e["data"]["decision"].update(refusal_reason="unsafe"), "does not match"),
    ("décision appliquée avec un motif de refus", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"]["decision"].update(refusal_reason="UNSAFE_COMMAND"), "null"),
    ("commande manuelle sans identifiant de commande", "etat-feux-commande-refusee.json",
     lambda e: e["data"]["decision"].update(reference_id=None), "string"),
    ("retour au plan fixe avec un identifiant de référence", "etat-feux-plan-fixe.json",
     lambda e: e["data"]["decision"].update(reference_id="9d8c7b6a-5e4f-4d3c-b2a1-0a9b8c7d6e5f"), "null"),
    ("retour au plan fixe en mode automatique", "etat-feux-plan-fixe.json", lambda e: e["data"].update(mode="AUTOMATIC"), "DEGRADED_FIXED_PLAN"),
    ("phase courante absente du plan", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"].update(current_phase_id="P9"), "current_phase_id"),
    ("début de phase postérieur à l'événement", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"].update(phase_started_at="2026-10-20T08:21:30Z"), "phase_started_at"),
    ("durée inférieure à la durée minimale", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"]["phases"][0].update(duration_s=5), "min_duration_s"),
    ("identifiant de phase d'état en double", "etat-feux-recommandation-appliquee.json",
     lambda e: e["data"]["phases"][1].update(phase_id="P1"), "double"),
    ("drapeau de qualité en double", "mesure-partielle.json",
     lambda e: e["data"]["quality"].update(flags=["MISSING_SPEED", "MISSING_SPEED"]), "non-unique"),
    # --- errors.dlq ---
    ("famille de rejet inconnue", "rejet-contrat.json", lambda e: e["data"].update(reason_code="BIZARRE"), "BIZARRE"),
    ("rejet sans détail", "rejet-contrat.json", lambda e: e["data"].pop("reason"), "reason"),
    ("sujet d'origine inconnu", "rejet-contrat.json", lambda e: e["data"].update(source_topic="autre.sujet"), "autre.sujet"),
    ("rejet d'un message du sujet des rejets", "rejet-contrat.json", lambda e: e["data"].update(source_topic="errors.dlq"), "errors.dlq"),
    ("aucune tentative", "rejet-contrat.json", lambda e: e["data"].update(attempts=0), "minimum"),
    ("rejet sans charge d'origine", "rejet-contrat.json", lambda e: e["data"].pop("original_payload"), "original_payload"),
    ("message illisible avec une charge qui est un objet", "rejet-illisible.json",
     lambda e: e["data"].update(original_payload={"a": 1}), "string"),
    ("sujet UNKNOWN alors que le carrefour est connu", "rejet-contrat.json", lambda e: e.update(subject="UNKNOWN"), "UNKNOWN"),
    ("sujet de carrefour alors que le carrefour est inconnu", "rejet-illisible.json", lambda e: e.update(subject="INT_01"), "UNKNOWN"),
    ("sujet mal formé pour un rejet", "rejet-contrat.json", lambda e: e.update(subject="carrefour-1"), "does not match"),
    ("rejected_at sans fuseau", "rejet-contrat.json", lambda e: e["data"].update(rejected_at="2026-10-20T08:00:11"), "does not match"),
    ("time différent de rejected_at", "rejet-contrat.json", lambda e: e.update(time="2026-10-20T08:00:15Z"), "rejected_at"),
    ("champ inconnu dans un rejet", "rejet-contrat.json", lambda e: e["data"].update(service="collecte"), "service"),
    # --- sujet UNKNOWN réservé à errors.dlq ---
    ("sujet UNKNOWN sur une mesure", "mesure-valide.json", lambda e: e.update(subject="UNKNOWN"), "does not match"),
    ("sujet UNKNOWN sur un indicateur", "indicateur-fluide.json", lambda e: e.update(subject="UNKNOWN"), "does not match"),
    ("sujet UNKNOWN sur une alerte", "alerte-creee.json", lambda e: e.update(subject="UNKNOWN"), "does not match"),
    ("domaine inconnu", "mesure-valide.json", lambda e: e.update(domain="water"), "water"),
]
