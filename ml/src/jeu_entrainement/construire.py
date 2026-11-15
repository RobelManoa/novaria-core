"""Construction du jeu : de chaque run du catalogue aux fichiers Parquet, au manifeste et à la fiche de provenance.

    python3 ml/src/construire_jeu.py [--sortie data/datasets/novaria-congestion-v1]

Tout est déterministe : mêmes graines et même code, mêmes octets (et donc mêmes empreintes SHA-256). Ni date, ni
chemin de la machine, ni nom d'utilisateur n'entrent dans les fichiers.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from jeu_entrainement import VERSION_DU_CODE, catalogue as cat
from jeu_entrainement import fenetres, lignes, parquet, provenance, simulation
from stockage import ouvrir_magasin_de_jeu, ranger_a_l_identique, sha256

RACINE = simulation.RACINE
SORTIE_PAR_DEFAUT = RACINE / "data" / "datasets" / cat.JEU_ID


@dataclass(frozen=True)
class Jeu:
    dossier: Path
    manifeste: dict


def empreinte_du_jeu(fichiers: dict[str, dict]) -> str:
    """Empreinte d'ensemble : SHA-256 de la liste « nom empreinte » triée par nom de fichier."""
    texte = "\n".join(f"{nom} {fichiers[nom]['sha256']}" for nom in sorted(fichiers)) + "\n"
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def absences(ligne_par_colonne: list[tuple]) -> dict[str, int]:
    """Nombre de valeurs absentes par colonne facultative."""
    resultat = {}
    for indice, colonne in enumerate(lignes.COLONNES):
        if colonne.facultative:
            resultat[colonne.nom] = sum(1 for ligne in ligne_par_colonne if ligne[indice] is None)
    return resultat


def construire(sortie: Path = SORTIE_PAR_DEFAUT, runs: tuple[cat.RunSpec, ...] = cat.CATALOGUE, *, message=lambda _: None) -> Jeu:
    cat.verifier(runs)
    par_ensemble: dict[str, list[tuple]] = {e: [] for e in cat.ENSEMBLES}
    description_des_runs = []
    version_generateur = ""
    for spec in runs:
        message(f"  {spec.run_id} : {spec.scenario_id}, graine {spec.seed}, {spec.duree_s // 3600} h")
        resultat = simulation.executer(spec)
        version_generateur = resultat.version_du_generateur
        toutes, moteur = fenetres.calculer(resultat)
        lignes_du_run, qualite = lignes.lignes_du_run(resultat, toutes)
        par_ensemble[spec.ensemble] += lignes_du_run
        indice_etat = lignes.NOMS.index("label_state")
        description_des_runs.append({
            "run_id": spec.run_id, "scenario_id": spec.scenario_id, "seed": spec.seed, "ensemble": spec.ensemble,
            "debut": f"2026-10-20T{spec.debut}:00Z", "duree_s": spec.duree_s, "anomalies": list(spec.anomalies),
            "note": spec.note, "lignes": len(lignes_du_run),
            "etats": {e: n for e, n in sorted(Counter(x[indice_etat] for x in lignes_du_run).items())},
            "qualite": qualite,
            "moteur": {cle: moteur.get(cle, 0) for cle in ("accepted", "duplicates", "late", "excluded", "empty_windows")},
            "messages_livres": len(resultat.livraisons), "capteur_muet_intervalles": sum(1 for v in resultat.verite if "SILENT" in v["anomalies"]),
        })
    magasin = ouvrir_magasin_de_jeu(sortie)  # port ObjectStore (ADR-025) : jamais d'écriture directe
    fichiers: dict[str, dict] = {}
    for ensemble in cat.ENSEMBLES:
        nom = f"{ensemble}.parquet"
        octets = parquet.encoder(lignes.COLONNES, par_ensemble[ensemble])
        fichiers[nom] = {
            "ensemble": ensemble, "lignes": len(par_ensemble[ensemble]), "octets": len(octets),
            "sha256": ranger_a_l_identique(magasin, nom, octets), "runs": [s.run_id for s in runs if s.ensemble == ensemble],
            "valeurs_absentes": absences(par_ensemble[ensemble]),
            "etats": {e: n for e, n in sorted(Counter(x[lignes.NOMS.index("label_state")] for x in par_ensemble[ensemble]).items())},
        }
    manifeste = {
        "dataset_id": cat.JEU_ID, "version": cat.NUMERO_DE_VERSION,
        "origine": {
            "source_type": "SIMULATED", "generateur": "simulator/novaria_sim", "version_du_generateur": version_generateur,
            "version_du_constructeur": VERSION_DU_CODE, "moteur_de_fenetres": "services/traitement/app/flux/windows.py",
            "format": "Parquet, colonnes PLAIN, sans compression, écrit par ml/src/jeu_entrainement/parquet.py",
        },
        "colonnes": [{"nom": c.nom, "type": c.type, "facultative": c.facultative} for c in lignes.COLONNES],
        "fichiers": fichiers, "runs": description_des_runs, "empreinte_du_jeu": empreinte_du_jeu(fichiers),
    }
    texte_du_manifeste = json.dumps(manifeste, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ranger_a_l_identique(magasin, "manifest.json", texte_du_manifeste.encode("utf-8"))
    ranger_a_l_identique(magasin, "PROVENANCE.md", provenance.rediger(manifeste).encode("utf-8"))
    return Jeu(sortie, manifeste)
