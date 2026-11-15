"""Du rapport JSON de `mesurer` aux tableaux Markdown du compte rendu (docs/03-donnees/prototype-bigdata.md)."""

import json
from pathlib import Path


def _etiquette(mesure: dict) -> str:
    return mesure["moteur"] if mesure["moteur"] == "python-sequentiel" else f"{mesure['moteur']} ({mesure['coeurs']} cœurs)"


def _par_taille(rapport: dict) -> dict[int, dict[str, dict]]:
    tailles: dict[int, dict[str, dict]] = {}
    for mesure in rapport["mesures"]:
        tailles.setdefault(mesure["jours"], {})[_etiquette(mesure)] = mesure
    return dict(sorted(tailles.items()))


def _nombre(valeur: float, chiffres: int = 1) -> str:
    return f"{valeur:,.{chiffres}f}".replace(",", " ").replace(".", ",")


def tableau_durees(rapport: dict) -> str:
    """Durée médiane (s) par taille et par moteur, avec le débit en lignes par seconde."""
    tailles = _par_taille(rapport)
    moteurs = list(dict.fromkeys(e for t in tailles.values() for e in t))
    lignes = ["| Jours | Lignes | Taille | " + " | ".join(moteurs) + " |", "|---|---:|---:|" + "---:|" * len(moteurs)]
    for jours, mesures in tailles.items():
        une = next(iter(mesures.values()))
        cellules = []
        for moteur in moteurs:
            m = mesures.get(moteur)
            cellules.append("—" if m is None else f"{_nombre(m['mediane_s'])} s ({_nombre(m['lignes_par_seconde'], 0)} l/s)")
        lignes.append(f"| {jours} | {_nombre(une['lignes'], 0)} | {_nombre(une['octets'] / 1e6, 0)} Mo | " + " | ".join(cellules) + " |")
    return "\n".join(lignes)


def tableau_memoire(rapport: dict) -> str:
    """Pic de mémoire (Mio, somme des PSS de l'arbre de processus) par taille et par moteur."""
    tailles = _par_taille(rapport)
    moteurs = list(dict.fromkeys(e for t in tailles.values() for e in t))
    lignes = ["| Jours | " + " | ".join(moteurs) + " |", "|---|" + "---:|" * len(moteurs)]
    for jours, mesures in tailles.items():
        lignes.append(f"| {jours} | " + " | ".join("—" if moteur not in mesures else f"{_nombre(mesures[moteur]['pic_mio'], 0)} Mio" for moteur in moteurs) + " |")
    return "\n".join(lignes)


def tableau_demarrage(rapport: dict) -> str:
    """Part du démarrage de la machine virtuelle Java dans la durée de PySpark."""
    lignes = ["| Jours | Moteur | Démarrage | Durée totale | Part |", "|---|---|---:|---:|---:|"]
    for jours, mesures in _par_taille(rapport).items():
        for etiquette, m in mesures.items():
            if m["moteur"] == "spark":
                lignes.append(f"| {jours} | {etiquette} | {_nombre(m['mediane_demarrage_s'])} s | {_nombre(m['mediane_s'])} s | {_nombre(100 * m['mediane_demarrage_s'] / m['mediane_s'], 0)} % |")
    return "\n".join(lignes)


def rapports_de_duree(rapport: dict, reference: str, autre: str) -> list[tuple[int, float | None]]:
    """Pour chaque taille : durée de `reference` divisée par celle de `autre` (> 1 : `autre` est plus rapide)."""
    resultat = []
    for jours, mesures in _par_taille(rapport).items():
        if reference in mesures and autre in mesures:
            resultat.append((jours, mesures[reference]["mediane_s"] / mesures[autre]["mediane_s"]))
        else:
            resultat.append((jours, None))
    return resultat


def point_de_croisement(rapport: dict, rapide_a_grande_taille: str, reference: str) -> int | None:
    """La plus petite taille (en jours) où `rapide_a_grande_taille` bat `reference` ; `None` s'il ne la bat sur aucune."""
    for jours, rapport_de_duree in rapports_de_duree(rapport, reference, rapide_a_grande_taille):
        if rapport_de_duree is not None and rapport_de_duree > 1:
            return jours
    return None


def tableau_rapports(rapport: dict) -> str:
    """Combien de fois PySpark (4 cœurs) est plus lent (< 1) ou plus rapide (> 1) que chaque ETL Python, par taille."""
    spark = next((e for t in _par_taille(rapport).values() for e in t if e.startswith("spark") and "4" in e), None)
    lignes = ["| Jours | ETL séquentiel ÷ PySpark | ETL réparti ÷ PySpark |", "|---|---:|---:|"]
    if spark is None:
        return "\n".join(lignes)
    sequentiel = dict(rapports_de_duree(rapport, "python-sequentiel", spark))
    parallele = next((e for t in _par_taille(rapport).values() for e in t if e.startswith("python-parallele")), None)
    reparti = dict(rapports_de_duree(rapport, parallele, spark)) if parallele else {}
    for jours in sequentiel:
        lignes.append(f"| {jours} | {'—' if sequentiel[jours] is None else _nombre(sequentiel[jours], 2)} | {'—' if reparti.get(jours) is None else _nombre(reparti[jours], 2)} |")
    return "\n".join(lignes)


def tableau_parite(rapport: dict) -> str:
    lignes = ["| Jours | Moteurs comparés | Empreintes identiques | Bilan = vérité terrain |", "|---|---|---|---|"]
    verite: dict[int, bool] = {}
    for mesure in rapport["mesures"]:
        verite[mesure["jours"]] = verite.get(mesure["jours"], True) and mesure["bilan_egal_a_la_verite_terrain"]
    for parite in rapport["parite"]:
        lignes.append(f"| {parite['jours']} | {', '.join(parite['moteurs'])} | {'oui' if parite['empreintes_identiques'] else '**NON**'} | {'oui' if verite[parite['jours']] else '**NON**'} |")
    return "\n".join(lignes)


def environnement(rapport: dict) -> str:
    e = rapport["environnement"]
    return (
        f"Python {e['python']}, PySpark {e['pyspark']}, {e['java']}, noyau {e['noyau']} ; {e['coeurs_visibles']} cœurs visibles, "
        f"limite du conteneur `cpu.max` = {e['cpu_max_cgroup']} (quota et période en µs), `memory.max` = {e['memoire_max_cgroup']} octets."
    )


def rendre(chemin: Path) -> str:
    """Tous les tableaux d'un rapport JSON, prêts à coller."""
    rapport = json.loads(Path(chemin).read_text(encoding="utf-8"))
    return "\n\n".join((
        f"Environnement : {environnement(rapport)}", "Durées (médiane)", tableau_durees(rapport), "Pic de mémoire", tableau_memoire(rapport),
        "Démarrage de PySpark", tableau_demarrage(rapport), "Rapport des durées", tableau_rapports(rapport), "Parité", tableau_parite(rapport),
    ))
