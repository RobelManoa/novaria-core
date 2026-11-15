"""Réglage sur la validation, validation croisée groupée par run, choix du candidat (cadrage ML, sections 6 et 7).

Règles, fixées avant l'entraînement :

1. un candidat est essayé avec **au plus 12 réglages** ; chacun est mesuré sur la **validation** ;
2. un réglage est **éligible** si ses fausses alertes restent sous 0,10 par tronçon et par jour (A5) ; s'il clignote, sa
   variante avec confirmation sur 2 fenêtres est jugée à son tour ;
3. le réglage retenu a le meilleur F1 macro de validation parmi les éligibles (brut d'abord, confirmé seulement si aucun
   réglage brut n'est éligible) ;
4. entre candidats : le meilleur F1 macro de validation, mais à moins de 0,002 d'écart le plus simple (la régression
   logistique) ;
5. la validation croisée groupée par run **ne choisit rien** : elle mesure la stabilité du réglage retenu.
"""

import statistics
from dataclasses import dataclass

from entrainement import acceptation, candidats, evaluation
from entrainement.candidats import Candidat
from mesures.metriques import Mesures
from preparation import ajustement, decoupage, variables


@dataclass
class Essai:
    indice: int
    params: dict
    brut: Mesures
    confirme: Mesures
    avertissements: list[str]

    @property
    def eligible_brut(self) -> bool:
        return acceptation.eligible(self.brut)

    @property
    def eligible_confirme(self) -> bool:
        return acceptation.eligible(self.confirme)

    def en_dict(self) -> dict:
        return {"indice": self.indice, "params": self.params, "avertissements": self.avertissements,
                "eligible_brut": self.eligible_brut, "eligible_confirme": self.eligible_confirme,
                "brut": self.brut.en_dict(), "confirme": self.confirme.en_dict()}


@dataclass
class Retenu:
    essai: Essai
    variante: str  # « brut » ou « confirme »

    @property
    def mesures(self) -> Mesures:
        return self.essai.brut if self.variante == "brut" else self.essai.confirme


def essayer_la_grille(c: Candidat, entrainement: list[dict], validation: list[dict], runs_entrainement, message=lambda _: None) -> list[Essai]:
    if len(c.grille) > candidats.MAX_COMBINAISONS:
        raise ValueError(f"{c.nom} : {len(c.grille)} réglages, le cadrage en permet {candidats.MAX_COMBINAISONS} au plus")
    preparation = evaluation.preparer(entrainement, runs_entrainement)
    x_train, y_train = preparation.transformer(entrainement, imputer=c.imputer)
    x_val, _ = preparation.transformer(validation, imputer=c.imputer)
    essais = []
    for indice, params in enumerate(c.grille):
        modele, avertissements = candidats.ajuster(c, params, x_train, y_train)
        predits = [str(e) for e in modele.predict(x_val)]
        essai = Essai(indice, params, evaluation.mesurer_predictions(validation, predits, False),
                      evaluation.mesurer_predictions(validation, predits, True), avertissements)
        message(f"  {c.nom} {indice + 1}/{len(c.grille)} {params} : F1 macro {essai.brut.f1_macro:.4f}, fausses alertes {essai.brut.alertes.fausses_par_troncon_et_jour:.2f}")
        essais.append(essai)
    return essais


def retenir(essais: list[Essai]) -> Retenu | None:
    """Le meilleur réglage éligible (brut d'abord) ; le premier de la grille à égalité parfaite ; `None` si aucun."""
    for variante, eligible, mesures in (("brut", lambda e: e.eligible_brut, lambda e: e.brut), ("confirme", lambda e: e.eligible_confirme, lambda e: e.confirme)):
        valables = [e for e in essais if eligible(e)]
        if valables:
            return Retenu(max(valables, key=lambda e: (mesures(e).f1_macro, -e.indice)), variante)
    return None


def choisir_le_candidat(retenus: dict[str, Retenu | None]) -> tuple[str | None, str]:
    """(nom du candidat, raison). L'ordre de `candidats.CANDIDATS` est celui de la simplicité."""
    eligibles = {nom: r for nom, r in retenus.items() if r is not None}
    if not eligibles:
        return None, "aucun candidat éligible : tous dépassent 0,10 fausse alerte par tronçon et par jour, même avec confirmation"
    ordre = [c.nom for c in candidats.CANDIDATS if c.nom in eligibles]
    meilleur = max(ordre, key=lambda nom: eligibles[nom].mesures.f1_macro)
    f1 = {nom: eligibles[nom].mesures.f1_macro for nom in ordre}
    proches = [nom for nom in ordre if f1[meilleur] - f1[nom] < acceptation.ECART_D_EGALITE]
    if len(proches) > 1 and ordre[0] in proches and proches[0] != meilleur:
        return proches[0], (f"{meilleur} a le meilleur F1 macro de validation ({f1[meilleur]:.4f}), mais {proches[0]} est à moins de "
                            f"{acceptation.ECART_D_EGALITE} ({f1[proches[0]]:.4f}) : le plus simple est retenu")
    return meilleur, f"meilleur F1 macro de validation parmi les candidats éligibles ({f1[meilleur]:.4f})"


def validation_croisee_groupee(c: Candidat, retenu: Retenu, lignes: list[dict], runs: list[tuple[str, str]]) -> dict:
    """Trois plis (un run de chaque scénario mis de côté) sur entraînement + validation : stabilité du réglage retenu."""
    plis = decoupage.plis_par_run(runs)
    resultats = []
    for numero, a_part in enumerate(plis, start=1):
        a_part_set = set(a_part)
        apprentissage = [ligne for ligne in lignes if ligne["run_id"] not in a_part_set]
        evaluation_pli = [ligne for ligne in lignes if ligne["run_id"] in a_part_set]
        preparation = evaluation.preparer(apprentissage, {ligne["run_id"] for ligne in apprentissage})
        x, y = preparation.transformer(apprentissage, imputer=c.imputer)
        modele, _ = candidats.ajuster(c, retenu.essai.params, x, y)
        _, predits = evaluation.predictions(modele, preparation, evaluation_pli, c.imputer)
        m = evaluation.mesurer_predictions(evaluation_pli, predits, retenu.variante == "confirme")
        r = evaluation.mesurer_la_regle(evaluation_pli)
        resultats.append({"pli": numero, "runs_a_part": a_part, "modele": m.en_dict(), "regle": r.en_dict()})
    return {"plis": resultats, "modele": _resume(resultats, "modele"), "regle": _resume(resultats, "regle")}


def _resume(plis: list[dict], cle: str) -> dict:
    resume = {}
    for nom in ("f1_macro", "rappel_congested", "fausses_alertes_par_troncon_et_jour"):
        valeurs = [p[cle][nom] for p in plis]
        resume[nom] = {"moyenne": round(statistics.fmean(valeurs), 4), "ecart_type": round(statistics.stdev(valeurs), 4) if len(valeurs) > 1 else 0.0,
                       "min": min(valeurs), "max": max(valeurs)}
    return resume
