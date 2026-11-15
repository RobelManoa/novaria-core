"""La décision du pipeline : conditions de performance A1 à A5 **et** contrôles de sécurité bloquants, et son rapport.

La décision se **recalcule** à chaque étape depuis ses éléments : un fichier `decision.json` dont le verdict n'est pas celui
que ses propres conditions donnent est refusé (étapes séparées, fichier modifiable entre deux).
"""

import json
from pathlib import Path

import pipeline


class DecisionIncoherente(RuntimeError):
    pass


class Bloque(RuntimeError):
    """La porte est fermée : un modèle sous le seuil (ou non conforme) n'est pas enregistré."""


def decider(conditions: list[dict], controles: list[dict]) -> tuple[bool, list[str]]:
    """Accepté si toutes les conditions de performance sont remplies et tous les contrôles bloquants sont **vérifiés**."""
    raisons = [f"{c['condition']} manquée : {c['libelle']} (modèle {c['modele']}, exigé {c['exige']})" for c in conditions if not c["remplie"]]
    for c in controles:
        if c["bloquant"] and c["ok"] is not True:
            etat = "non vérifié" if c["ok"] is None else "en échec"
            raisons.append(f"{c['code']} {etat} : {c['libelle']} ({c['detail']})")
    return not raisons, raisons


def lire(chemin: Path | None = None) -> dict:
    chemin = chemin or pipeline.DECISION
    if not chemin.is_file():
        raise DecisionIncoherente(f"{chemin.name} absent : faire d'abord l'étape « evaluer »")
    try:
        decision = json.loads(chemin.read_text(encoding="utf-8"))
        accepte, raisons = decider(decision["conditions"], decision["securite"])
        attendu = "accepté" if accepte else "rejeté"
        if decision["decision"] != attendu:
            raise DecisionIncoherente(f"la décision écrite est « {decision['decision']} » mais ses conditions donnent « {attendu} » : fichier modifié")
    except (ValueError, KeyError, TypeError) as erreur:
        raise DecisionIncoherente(f"{chemin.name} illisible ou incomplet ({erreur!r})") from erreur
    decision["raisons"] = raisons
    return decision


def _etat(ok: bool | None) -> str:
    return "non vérifié" if ok is None else ("oui" if ok else "**non**")


def rapport(decision: dict) -> str:
    """Le résumé lisible (Markdown), ajouté au résumé de l'exécution GitHub Actions."""
    t = decision["tracabilite"]
    lignes = [
        "## Pipeline MLSecOps (IA-05)", "",
        f"**Décision : modèle {decision['decision']}**" + ("" if decision["decision"] == "accepté" else " : **non enregistré** (la règle de seuils reste le classificateur en service)"), "",
        "| Champ | Valeur |", "|---|---|",
        f"| Run | `{decision['run_id']}` |", f"| Candidat | {decision['candidat']} ({decision['variante']}), réglage `{json.dumps(decision['params'], ensure_ascii=False)}` |",
        f"| Jeu | `{t['dataset_id']}`, empreinte `{t['dataset_sha256']}` |", f"| Révision du code | `{t['git_sha']}`" + (" (code non commité)" if t["code_modifie_non_commite"] else "") + " |",
        f"| Graine | {t['seed']} |", "| Versions | " + ", ".join(f"{k} {v}" for k, v in t["versions"].items()) + " |",
        f"| Sélection figée (SHA-256) | `{decision['selection_sha256']}` |", "",
        "### Seuil d'acceptation (cadrage ML, section 6) : performance sur le test", "",
        "| N° | Condition | Modèle | Exigé | Remplie |", "|---|---|---|---|---|",
    ]
    lignes += [f"| {c['condition']} | {c['libelle']} | {c['modele']} | {c['exige']} | {_etat(c['remplie'])} |" for c in decision["conditions"]]
    lignes += ["", "### Contrôles de sécurité", "", "| N° | Contrôle | Bloquant | Résultat | Détail |", "|---|---|---|---|---|"]
    lignes += [f"| {c['code']} | {c['libelle']} | {'oui' if c['bloquant'] else 'non'} | {_etat(c['ok'])} | {c['detail']} |" for c in decision["securite"]]
    if decision["raisons"]:
        lignes += ["", "### Pourquoi la porte est fermée", ""] + [f"- {r}" for r in decision["raisons"]]
    return "\n".join(lignes) + "\n"
