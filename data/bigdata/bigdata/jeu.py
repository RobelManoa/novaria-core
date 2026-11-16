"""Le jeu de fichiers sur lequel les moteurs travaillent : un dossier de fichiers bruts journaliers et leur vérité terrain."""

import json
from pathlib import Path

from bigdata.generer import Attendu

INDEX = "attendu.json"  # nom du fichier brut -> ce que le nettoyage doit en tirer (vérité terrain du générateur)


def fichiers_du_jeu(dossier: Path, jours: int | None = None) -> list[Path]:
    """Les `jours` premiers fichiers bruts (par ordre de nom, donc de date) ; tous si `jours` est absent."""
    fichiers = sorted(chemin for chemin in Path(dossier).glob("*.csv") if chemin.is_file())
    if jours is not None:
        if jours > len(fichiers):
            raise ValueError(f"{jours} jours demandés, {len(fichiers)} fichiers dans {dossier} : lancer « generer » d'abord")
        fichiers = fichiers[:jours]
    return fichiers


def enregistrer_attendu(dossier: Path, attendus: dict[str, dict]) -> None:
    """Ajoute des fichiers à l'index de vérité terrain (les entrées existantes sont conservées)."""
    chemin = Path(dossier) / INDEX
    existant = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
    existant.update(attendus)
    chemin.write_text(json.dumps(dict(sorted(existant.items())), indent=1, sort_keys=True) + "\n", encoding="utf-8")


def attendu_des(dossier: Path, fichiers: list[Path]) -> dict:
    """La vérité terrain de plusieurs fichiers, additionnée (forme de `Bilan.en_dict`, sans le taux)."""
    index = json.loads((Path(dossier) / INDEX).read_text(encoding="utf-8"))
    total = Attendu()
    for fichier in fichiers:
        entree = index[fichier.name]
        total.lues += entree["rows_read"]
        total.propres += entree["rows_clean"]
        total.rejetees += entree["rows_rejected"]
        total.par_regle.update(entree["by_rule"])
        total.drapeaux.update(entree["flags"])
    return total.en_dict()


def octets_et_lignes(fichiers: list[Path], dossier: Path) -> tuple[int, int]:
    """Taille cumulée (octets) et nombre de lignes de données des fichiers."""
    attendu = attendu_des(dossier, fichiers)
    return sum(f.stat().st_size for f in fichiers), attendu["rows_read"]
