"""Mise en page du rapport hebdomadaire : de la synthèse au PDF."""

from datetime import datetime

from rapport.pdf import Document
from rapport.synthese import Synthese, Troncon

TOP = 10
TOUS_JUSQU_A = 40


def pourcent(part: float) -> str:
    return f"{part * 100:.1f} %".replace(".", ",")


def ratio(valeur: float | None) -> str:
    return "n/d" if valeur is None else f"{valeur:.3f}".replace(".", ",")


def tableau(troncons: list[Troncon]) -> list[str]:
    lignes = [f"{'Tronçon':<10}{'Fenêtres':>9}{'Ratio moyen':>13}{'Congestion':>12}{'Ralenti':>10}"]
    lignes += [
        f"{t.identifiant:<10}{t.fenetres:>9}{ratio(t.ratio_moyen):>13}"
        f"{pourcent(t.part_congestion):>12}{pourcent(t.part_ralenti):>10}"
        for t in troncons
    ]
    return lignes


def titre(synthese: Synthese) -> str:
    return f"Rapport hebdomadaire Novaria Core, {synthese.periode.libelle}"


def assembler(synthese: Synthese, genere_le: datetime) -> bytes:
    document = Document(titre(synthese), genere_le)
    document.titre_principal(titre(synthese))
    document.paragraphe(
        f"Semaine {synthese.periode.etiquette}. Généré le {genere_le:%d/%m/%Y à %H:%M} UTC par le robot "
        "du rapport hebdomadaire, sans intervention manuelle."
    )
    if synthese.simule:
        document.section("Origine des données : simulées")
        document.paragraphe(
            "Ce rapport décrit des données simulées par le simulateur de Novaria Core. Il ne décrit "
            "aucun trafic réel et ne doit pas être présenté comme tel.",
            gras=True,
        )
    else:
        document.section("Origine des données")
    document.paragraphe(
        f"Sources : {', '.join(synthese.sources) or 'aucune'}. "
        f"Scénarios : {', '.join(synthese.scenarios) or 'aucun'}. "
        f"Exécutions : {', '.join(synthese.runs) or 'aucune'}."
    )

    document.section("Chiffres clés")
    if synthese.fenetres == 0:
        document.paragraphe("Aucun indicateur n'existe sur cette période : il n'y a rien à résumer.", gras=True)
    else:
        document.paragraphe(
            f"{synthese.fenetres} fenêtres de 5 minutes sur {len(synthese.troncons)} tronçons, du "
            f"{synthese.premiere} au {synthese.derniere}. Complétude moyenne des mesures : "
            f"{pourcent(synthese.completude_moyenne or 0.0)}."
        )
        total = sum(synthese.etats.values())
        document.paragraphe(
            "États de circulation : "
            + ", ".join(
                f"{etat} {pourcent(nombre / total)}" for etat, nombre in sorted(synthese.etats.items())
            )
            + "."
        )
    if synthese.tronque:
        document.paragraphe(
            "Attention : la lecture a été interrompue au plafond de pages ; la synthèse est partielle.",
            gras=True,
        )

    if synthese.troncons:
        classes = sorted(synthese.troncons, key=lambda t: (-t.part_congestion, t.identifiant))
        document.section(f"Tronçons les plus congestionnés (les {TOP} premiers)")
        document.tableau(tableau(classes[:TOP]))
        if len(synthese.troncons) <= TOUS_JUSQU_A:
            document.section("Tous les tronçons")
            document.tableau(tableau(synthese.troncons))
    document.section("Limites")
    document.paragraphe(
        "Le ratio de vitesse est la vitesse moyenne divisée par la vitesse en circulation fluide. Les "
        "parts de congestion et de ralentissement se calculent sur les fenêtres dont l'état est connu. "
        "Le robot lit l'API et dépose ce fichier : il ne commande aucun équipement et ne modifie aucune "
        "donnée."
    )
    return document.octets()
