"""La lignée d'un modèle : de lui à son entraînement, à son code (Git) et à son jeu de données, et la preuve que les maillons tiennent.

Critère de l'issue IA-04 : « un modèle en service est relié à son entraînement et à son jeu de données ». `verifier_la_chaine`
rend ce qui est **vérifié**, ce qui est **faux** (écarts), ce qui est **douteux** (avertissements) et ce qui n'a **pas pu
l'être** (non vérifié) : une chaîne qu'on n'a pas contrôlée n'est pas déclarée bonne.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from jeu_entrainement import integrite
from jeu_entrainement.simulation import RACINE
from registre import documents
from registre.format_lineaire import NOM as FORMAT
from registre.registre import POINTEUR, cle_du_manifeste, cle_du_modele
from stockage import ObjectStore, StockageErreur, sha256


@dataclass
class Lignee:
    run_id: str
    chaine: dict = field(default_factory=dict)  # les maillons : entraînement, code, jeu, modèle
    verifie: list[str] = field(default_factory=list)
    ecarts: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    non_verifie: list[str] = field(default_factory=list)

    @property
    def intacte(self) -> bool:
        return not self.ecarts

    def en_dict(self) -> dict:
        return {"run_id": self.run_id, "chaine": self.chaine, "verifie": self.verifie, "ecarts": self.ecarts,
                "avertissements": self.avertissements, "non_verifie": self.non_verifie, "intacte": self.intacte}


def _commit_existe(sha: str, depot: Path) -> bool | None:
    """`True` si le dépôt connaît ce commit, `False` sinon, `None` si Git est indisponible."""
    try:
        return subprocess.run(["git", "-C", str(depot), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, check=False).returncode == 0
    except OSError:
        return None


def verifier_la_chaine(run: dict, objets: ObjectStore, *, jeu: Path | None = None, depot: Path = RACINE) -> Lignee:
    resultat = Lignee(run["run_id"])
    resultat.chaine = {
        "entrainement": {"run_id": run["run_id"], "status": run["status"], "created_at": run["created_at"].isoformat(), "seed": run["seed"]},
        "code": {"git_sha": run["git_sha"], "git_dirty": run.get("git_dirty")},
        "jeu": {"dataset_id": run.get("dataset_id"), "dataset_sha256": run["dataset_sha256"]},
        "modele": {"model_sha256": run.get("model_sha256"), "model_uri": run.get("model_uri"), "model_format": run.get("model_format")},
    }
    if run["status"] != documents.REGISTERED:
        resultat.ecarts.append(f"le run est « {run['status']} » : il n'a pas de modèle enregistré")
        return resultat
    _verifier_le_modele(run, objets, resultat)
    _verifier_le_code(run, depot, resultat)
    _verifier_le_jeu(run, jeu, resultat)
    return resultat


def _verifier_le_modele(run: dict, objets: ObjectStore, resultat: Lignee) -> None:
    run_id = run["run_id"]
    try:
        octets = objets.get(cle_du_modele(run_id))
        manifeste = json.loads(objets.get(cle_du_manifeste(run_id)).decode("utf-8"))
    except (StockageErreur, ValueError) as erreur:
        resultat.ecarts.append(f"modèle ou manifeste illisible dans le magasin ({erreur})")
        return
    if sha256(octets) == run["model_sha256"]:
        resultat.verifie.append("le fichier du modèle a l'empreinte SHA-256 enregistrée dans model_runs")
    else:
        resultat.ecarts.append("le fichier du modèle n'a pas l'empreinte enregistrée dans model_runs (altéré ou remplacé)")
    if run.get("model_format") != FORMAT:
        resultat.ecarts.append(f"format {run.get('model_format')!r} : seul {FORMAT} se charge")
    if run.get("model_uri") != f"local:{cle_du_modele(run_id)}":
        resultat.ecarts.append(f"model_uri {run.get('model_uri')!r} différent de l'emplacement du modèle")
    differences = [nom for nom in ("run_id", "git_sha", "dataset_sha256", "seed", "model_sha256", "model_format")
                   if not isinstance(manifeste, dict) or manifeste.get(nom) != run.get(nom)]
    if differences:
        resultat.ecarts.append(f"le manifeste du magasin diffère de model_runs : {differences}")
    else:
        resultat.verifie.append("le manifeste (run, révision Git, jeu, graine, modèle) est celui de model_runs")
    try:
        pointeur = json.loads(objets.get(POINTEUR).decode("utf-8"))
    except (StockageErreur, ValueError):
        pointeur = {}
    resultat.chaine["en_service"] = pointeur.get("run_id") == run_id
    if not resultat.chaine["en_service"]:
        resultat.avertissements.append("ce modèle n'est pas celui que désigne le pointeur « en service »")


def _verifier_le_code(run: dict, depot: Path, resultat: Lignee) -> None:
    existe = _commit_existe(run["git_sha"], depot)
    if existe is None:
        resultat.non_verifie.append("git est indisponible : la révision n'a pas été cherchée")
    elif existe:
        resultat.verifie.append(f"la révision Git {run['git_sha'][:10]} existe dans ce dépôt")
    else:
        resultat.avertissements.append(f"la révision {run['git_sha'][:10]} est introuvable dans ce dépôt (commit d'une branche supprimée après une fusion par squash, ou dépôt incomplet)")
    if run.get("git_dirty"):
        resultat.avertissements.append("l'entraînement a tourné avec du code non commité : la révision Git ne suffit pas à le refaire")
    elif run.get("git_dirty") is None:
        resultat.non_verifie.append("l'état du code (commité ou non) n'a pas été enregistré")


def _verifier_le_jeu(run: dict, jeu: Path | None, resultat: Lignee) -> None:
    if jeu is None:
        resultat.non_verifie.append("jeu de données non fourni : son empreinte n'a pas été recalculée (--jeu)")
        return
    ecarts = integrite.verifier(jeu, run["dataset_sha256"])
    if ecarts:
        resultat.ecarts += [f"jeu : {e}" for e in ecarts]
    else:
        resultat.verifie.append("le jeu de données du disque est celui de l'entraînement (SHA-256 recalculés)")
