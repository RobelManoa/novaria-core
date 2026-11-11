"""Synthèse des indicateurs d'une période : ce que le rapport affirme, et rien d'autre."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from rapport.api import Indicateurs
from rapport.periode import Periode


@dataclass(frozen=True)
class Troncon:
    identifiant: str
    fenetres: int
    ratio_moyen: float | None  # moyenne des fenêtres qui ont un ratio de vitesse
    part_congestion: float  # parmi les fenêtres dont l'état est connu
    part_ralenti: float


@dataclass(frozen=True)
class Synthese:
    periode: Periode
    fenetres: int
    troncons: list[Troncon]
    etats: dict[str, int]
    runs: list[str]
    sources: list[str]
    scenarios: list[str]
    completude_moyenne: float | None
    tronque: bool
    premiere: str | None = None
    derniere: str | None = None
    simule: bool = field(init=False)

    def __post_init__(self) -> None:
        # Une donnée simulée n'est jamais présentée comme réelle : tout ce qui n'est pas réel est dit simulé.
        object.__setattr__(self, "simule", any(s == "SIMULATED" for s in self.sources))


def part(connus: list[dict], etat: str) -> float:
    """Part des fenêtres d'un état parmi celles dont l'état est connu (0 s'il n'y en a aucune)."""
    return sum(1 for x in connus if x["congestion_state"] == etat) / len(connus) if connus else 0.0


def moyenne(valeurs: list[float]) -> float | None:
    return sum(valeurs) / len(valeurs) if valeurs else None


def resumer(donnees: Indicateurs, periode: Periode) -> Synthese:
    par_troncon: dict[str, list[dict]] = defaultdict(list)
    for ligne in donnees.lignes:
        par_troncon[ligne["road_segment_id"]].append(ligne)
    troncons = []
    for identifiant in sorted(par_troncon):
        lignes = par_troncon[identifiant]
        connus = [x for x in lignes if x["congestion_state"] != "UNKNOWN"]
        troncons.append(
            Troncon(
                identifiant,
                len(lignes),
                moyenne([x["speed_ratio"] for x in lignes if x["speed_ratio"] is not None]),
                part(connus, "CONGESTED"),
                part(connus, "SLOW"),
            )
        )
    provenances = [x["provenance"] for x in donnees.lignes]
    debuts = sorted(x["window_start"] for x in donnees.lignes)
    return Synthese(
        periode=periode,
        fenetres=len(donnees.lignes),
        troncons=troncons,
        etats=dict(Counter(x["congestion_state"] for x in donnees.lignes)),
        runs=sorted({p["run_id"] for p in provenances}),
        sources=sorted({p["source_type"] for p in provenances}),
        scenarios=sorted({p["scenario_id"] for p in provenances if p.get("scenario_id")}),
        completude_moyenne=moyenne([x["completeness"] for x in donnees.lignes]),
        tronque=donnees.tronque,
        premiere=debuts[0] if debuts else None,
        derniere=debuts[-1] if debuts else None,
    )
