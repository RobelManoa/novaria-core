"""Mesure : durée et mémoire de chaque moteur sur des tailles croissantes, et parité de leurs résultats.

Chaque moteur tourne dans **son propre processus** (`python -m bigdata nettoyer`), jamais dans celui qui mesure :
- la durée est celle que le moteur mesure en interne, du début de son travail à son bilan (démarrage de la machine
  virtuelle Java de Spark compris : c'est un coût réel, il est aussi donné à part) ; elle exclut la vérification ;
- la mémoire est le **pic de la somme des PSS** (mémoire propre de chaque processus plus sa part des pages partagées) de
  l'arbre de processus, échantillonné toutes les 0,2 s dans `/proc` : Linux seulement ;
- la vérification (`verifier`) relit les sorties dans un autre processus, hors mesure, et compare les empreintes.
"""

import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

INTERVALLE_S = 0.2


def pss_ko(pid: int) -> int:
    """Mémoire proportionnelle (PSS) d'un processus, en ko ; 0 s'il a disparu."""
    try:
        with open(f"/proc/{pid}/smaps_rollup", encoding="ascii") as fichier:
            for ligne in fichier:
                if ligne.startswith("Pss:"):
                    return int(ligne.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def descendants(racine: int) -> list[int]:
    """La racine et tous ses descendants, d'après les parents lus dans `/proc/<pid>/stat`."""
    enfants: dict[int, list[int]] = {}
    for nom in os.listdir("/proc"):
        if not nom.isdigit():
            continue
        try:
            with open(f"/proc/{nom}/stat", encoding="utf-8", errors="replace") as fichier:
                contenu = fichier.read()
            parent = int(contenu[contenu.rindex(")") + 2:].split()[1])  # le nom du processus peut contenir des espaces
        except (OSError, ValueError, IndexError):
            continue
        enfants.setdefault(parent, []).append(int(nom))
    trouves, a_voir = [], [racine]
    while a_voir:
        pid = a_voir.pop()
        trouves.append(pid)
        a_voir.extend(enfants.get(pid, []))
    return trouves


class Echantillonneur(threading.Thread):
    """Relève périodiquement la mémoire de l'arbre de processus et garde le pic."""

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.pic_ko = 0
        self._arret = threading.Event()

    def run(self) -> None:
        while not self._arret.is_set():
            self.pic_ko = max(self.pic_ko, sum(pss_ko(p) for p in descendants(self.pid)))
            self._arret.wait(INTERVALLE_S)

    def arreter(self) -> int:
        self._arret.set()
        self.join()
        return self.pic_ko


def lancer(commande: list[str]) -> tuple[dict, int]:
    """Lance une commande du prototype ; rend son document JSON (dernière ligne) et le pic de mémoire en Mio."""
    processus = subprocess.Popen(commande, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    echantillonneur = Echantillonneur(processus.pid)
    echantillonneur.start()
    sortie, erreur = processus.communicate()
    pic_ko = echantillonneur.arreter()
    if processus.returncode != 0:
        raise RuntimeError(f"{' '.join(commande)} : code {processus.returncode}\n{erreur[-2000:]}")
    return json.loads(sortie.strip().splitlines()[-1]), round(pic_ko / 1024)


def decouper(spec: str) -> tuple[str, int]:
    """« spark:4 » -> ("spark", 4) ; « python-sequentiel » -> ("python-sequentiel", 1)."""
    nom, _, coeurs = spec.partition(":")
    return nom, int(coeurs) if coeurs else 1


def commande_de(sous_commande: str, moteur: str, coeurs: int, jours: int, arguments: Namespace) -> list[str]:
    return [
        sys.executable, "-m", "bigdata", sous_commande, "--moteur", moteur, "--coeurs", str(coeurs), "--jours", str(jours),
        "--dossier", str(arguments.dossier), "--sortie", str(arguments.sortie), "--memoire-spark", arguments.memoire_spark,
        "--temporaire", arguments.temporaire,
    ]


def environnement() -> dict:
    """Où la mesure a tourné : une durée sans sa machine ne dit rien."""
    def lire(chemin: str) -> str:
        try:
            return Path(chemin).read_text(encoding="utf-8").strip()
        except OSError:
            return "inconnu"

    java = subprocess.run(["java", "-version"], capture_output=True, text=True, check=False).stderr.splitlines()
    try:
        import pyspark

        version_spark = pyspark.__version__
    except ImportError:
        version_spark = "absent"
    return {
        "python": platform.python_version(), "pyspark": version_spark, "java": java[0] if java else "absent",
        "coeurs_visibles": os.cpu_count(), "cpu_max_cgroup": lire("/sys/fs/cgroup/cpu.max"),
        "memoire_max_cgroup": lire("/sys/fs/cgroup/memory.max"), "noyau": platform.release(),
    }


def mesurer(arguments: Namespace) -> dict:
    from bigdata import jeu

    tailles = [int(j) for j in str(arguments.jours).split(",")]
    moteurs = [decouper(m) for m in arguments.moteurs.split(",")]
    mesures, parites = [], []
    for jours in tailles:
        fichiers = jeu.fichiers_du_jeu(arguments.dossier, jours)
        octets, lignes = jeu.octets_et_lignes(fichiers, arguments.dossier)
        empreintes: dict[str, dict] = {}
        for moteur, coeurs in moteurs:
            essais = []
            for _ in range(arguments.repetitions):
                resultat, pic = lancer(commande_de("nettoyer", moteur, coeurs, jours, arguments))
                essais.append({"secondes": resultat["secondes"], "demarrage": resultat["secondes_demarrage"], "pic_mio": pic})
            verification, _ = lancer(commande_de("verifier", moteur, coeurs, jours, arguments))
            etiquette = f"{moteur}:{coeurs}"
            empreintes[etiquette] = {k: verification[k] for k in ("propres", "rejets")}
            attendu = verification["attendu"]
            bilan = resultat["bilan"]
            mesures.append({
                "moteur": moteur, "coeurs": coeurs, "jours": jours, "fichiers": len(fichiers), "lignes": lignes, "octets": octets,
                "essais": essais, "mediane_s": statistics.median(e["secondes"] for e in essais),
                "mediane_demarrage_s": statistics.median(e["demarrage"] for e in essais),
                "pic_mio": max(e["pic_mio"] for e in essais),
                "lignes_par_seconde": round(lignes / statistics.median(e["secondes"] for e in essais)),
                "bilan_egal_a_la_verite_terrain": all(bilan[c] == attendu[c] for c in ("rows_read", "rows_clean", "rows_rejected", "by_rule", "flags")),
            })
        premiere = next(iter(empreintes.values()))
        parites.append({"jours": jours, "empreintes_identiques": all(e == premiere for e in empreintes.values()), "moteurs": list(empreintes)})
    # Le rapport est le document JSON rendu sur la sortie standard : le rediriger vers un fichier (`> mesure.json`).
    return {"environnement": environnement(), "mesures": mesures, "parite": parites, "horodatage": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
