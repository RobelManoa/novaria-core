"""Démonstrations de l'observatoire : flux complet (MS-15), sécurité du poste, cloud local (CLD-17) et IA.

Les quatre onglets ajoutés à l'observatoire (CLD-14, MS-16) reposent sur ce module. Rien n'est inventé : chaque démonstration
**lance une commande existante de `dev.py`** (liste fermée ci-dessous, aucun texte venu du navigateur n'est exécuté) et montre sa
sortie ; la synthèse de l'IA est **lue** dans `ml/evaluation/*.json` ; le contrôle de sécurité **interroge Docker** sur les
conteneurs en marche. Textes de présentation : `ops/presentation.json` (versionné, séparé du code).

Une seule démonstration à la fois. Une démonstration qui arrête des conteneurs (cas d'échec du flux) exige une confirmation et
n'est pas lancée pendant une panne contrôlée de l'observatoire. Bibliothèque standard seulement.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "scripts" / "dev" / "dev.py"
PRESENTATION = ROOT / "ops" / "presentation.json"
EVALUATION = ROOT / "ml" / "evaluation"
LIGNES_MAX = 500
LIGNE_MAX = 400
RESULTAT = re.compile(r"^\[(OK|ÉCHEC)\]\s+(\S+)\s+(.*)$")
GRAINE = re.compile(r"^\d{1,6}$")
THEMES = ("flux", "securite", "cloud", "ia", "entrainement")


@dataclass(frozen=True)
class Demo:
    identifiant: str
    theme: str
    libelle: str
    ce_que_ca_montre: str
    arguments: tuple[str, ...]  # arguments de dev.py
    duree: str
    arrete_des_conteneurs: bool = False
    ecrit_dans_le_depot: bool = False  # une démonstration qui modifierait des fichiers suivis n'a pas sa place ici
    pile_requise: bool = False
    accepte_graine: bool = False
    rejeu_sur_pile: bool = False  # rejouer publie aussi sur la collecte (la pile doit tourner)
    suite: tuple[tuple[str, ...], ...] = ()  # plusieurs commandes de dev.py, l'une après l'autre
    codes_ok: tuple[int, ...] = (0,)  # codes de sortie qui sont un succès : une porte fermée (1) est le résultat attendu


def _flux(identifiant: str, libelle: str, montre: str, cas: tuple[str, ...], duree: str, arrete: bool) -> Demo:
    return Demo(identifiant, "flux", libelle, montre, ("flux-complet", *cas), duree, arrete_des_conteneurs=arrete, pile_requise=True)


DEMOS: tuple[Demo, ...] = (
    _flux("flux-nominal", "Parcours nominal N1 à N7", "Un capteur simulé jusqu'à la commande de feux : compte, collecte, fenêtres de l'entrepôt, alertes, recommandation, commande de feux, commande manuelle.", ("N1", "N2", "N3", "N4", "N5", "N6", "N7"), "environ 4 min", False),
    _flux("flux-f1", "F1 · Message invalide", "Un message illisible et un message hors contrat sont refusés avec leur motif, et rien n'entre dans raw_events.", ("F1",), "environ 1 min", False),
    _flux("flux-f2", "F2 · Service arrêté (alerte-worker)", "Le travailleur d'alertes est arrêté puis relancé : aucune alerte perdue, aucun doublon.", ("F2",), "environ 2 min", True),
    _flux("flux-f3", "F3 · Broker indisponible (Kafka)", "Kafka est arrêté : la collecte répond 503 sans perdre de copie brute, puis reprend.", ("F3",), "environ 3 min", True),
    _flux("flux-f4", "F4 · Indicateurs en retard", "Le flux de traitement est arrêté : les feux passent en mode dégradé, les indicateurs rattrapent leur retard au redémarrage.", ("F4",), "environ 3 min", True),
    _flux("flux-f5", "F5 · Mode dégradé des feux", "Rejoue F4 puis lit ce qu'il a observé : plan fixe tant que les indicateurs sont en retard.", ("F4", "F5"), "environ 4 min", True),
    _flux("flux-f6", "F6 · Redémarrage du service des feux", "Le service des feux est arrêté proprement puis relancé : plan fixe au démarrage, reprise sans perte ni doublon.", ("F6",), "environ 3 min", True),
    Demo("securite-compose", "securite", "Tests de durcissement de la pile (compose)", "Ports sur 127.0.0.1, cap_drop ALL, no-new-privileges, aucun conteneur privilégié, aucune socket Docker montée.", ("__tests__", "test_compose.py"), "quelques secondes"),
    Demo("securite-verrous", "securite", "Tests des verrous de dépendances", "Chaque dépendance directe est dans le verrou, avec versions exactes et empreintes.", ("__tests__", "test_dependances.py"), "quelques secondes"),
    Demo("cloud-plan-dev", "cloud", "Plan Terraform de dev (sans compte AWS)", "Le plan de l'environnement protégé sur un état fictif : 15 ressources à créer, dépôts protégés.", ("terraform-plan-hors-ligne", "--mode", "plan", "--env", "dev"), "environ 10 s"),
    Demo("cloud-destruction-protegee", "cloud", "Destruction d'un dépôt protégé", "terraform destroy refuse : « Instance cannot be destroyed » (prevent_destroy), avant tout appel à AWS.", ("terraform-plan-hors-ligne", "--mode", "destruction-protegee"), "environ 10 s"),
    Demo("cloud-bascule-variable", "cloud", "Basculer la variable ne lève pas la protection", "Avec protected = false, le refus persiste : il faut changer le code, donc une pull request relue.", ("terraform-plan-hors-ligne", "--mode", "bascule-variable"), "environ 10 s"),
    Demo("cloud-emulateur-dev", "cloud", "apply puis second plan sur l'émulateur Moto (dev)", "apply, puis plan = « No changes », dérive volontaire détectée, correction, destruction refusée.", ("terraform-emulateur", "--env", "dev"), "environ 1 min"),
    Demo("cloud-emulateur-demo", "cloud", "apply puis second plan sur l'émulateur Moto (demo)", "Même parcours sur l'environnement jetable : la destruction est autorisée.", ("terraform-emulateur", "--env", "demo"), "environ 1 min"),
    Demo("ia-sumo", "ia", "Simuler le carrefour avec SUMO puis rejouer le run", "SUMO (dans Docker) simule 5 h du carrefour INT_01 avec une graine au choix, puis le run est rejoué dans le moteur de fenêtres du traitement.", ("ml-sumo", "simuler", "rejouer"), "environ 10 s", accepte_graine=True),
    Demo("ia-sumo-pile", "ia", "Rejouer un run SUMO neuf dans toute la pile", "Même simulation avec une graine neuve, puis les 7 200 événements sont publiés sur la collecte : traitement, entrepôt et alertes les voient comme un vrai trafic (données simulées).", ("ml-sumo", "simuler", "rejouer"), "environ 1 min 30", pile_requise=True, accepte_graine=True, rejeu_sur_pile=True),
)
ENTRAINEMENT: tuple[Demo, ...] = (
    Demo("ent-preparation", "entrainement", "Préparation : découpage et variables", "Vérifie le découpage par run et les variables permises : aucune fuite du futur, empreinte du découpage. Le test n'est pas lu.", ("preparation-check",), "quelques secondes"),
    Demo("ent-reference", "entrainement", "Référence : la règle de seuils", "Mesure la règle de seuils (ADR-028) sur l'entraînement et la validation : c'est le barème que le modèle doit battre.", ("reference-mesure",), "quelques secondes"),
    Demo("ent-evaluer", "entrainement", "Entraîner, évaluer et contrôler", "Réentraîne le candidat choisi, l'évalue sur le test et rejoue les contrôles de sécurité (S1 à S5, T1, R1) et les conditions A1 à A5 : mêmes métriques que celles enregistrées.", ("ml-pipeline", "evaluer"), "environ 5 s"),
    Demo("ent-porte", "entrainement", "Porte d'acceptation", "Dit si le modèle passe la porte. Code de sortie 1 = porte fermée : c'est le résultat attendu ici (modèle rejeté), pas une panne.", ("ml-pipeline", "porte"), "quelques secondes", codes_ok=(0, 1)),
    Demo("ent-registre", "entrainement", "Registre : quel modèle est en service ?", "Interroge le registre : aucun modèle appris n'est en service, la règle de seuils reste le classificateur (ADR-015).", ("ml-registre", "en-service"), "quelques secondes", pile_requise=True),
    Demo("ent-tout", "entrainement", "Toute la chaîne, d'un trait", "Préparation, référence, entraînement et évaluation, contrôles, puis porte : de la donnée à la décision, en direct.", ("ml-pipeline",), "environ 15 s", suite=(("preparation-check",), ("reference-mesure",), ("ml-pipeline", "evaluer"), ("ml-pipeline", "porte")), codes_ok=(0, 1)),
)
DEMOS = DEMOS + ENTRAINEMENT
PAR_ID = {d.identifiant: d for d in DEMOS}


def charger_presentation(chemin: Path = PRESENTATION) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def commandes(demo: Demo, graine: str | None = None) -> list[list[str]]:
    """Les commandes (arguments de dev.py puis hors dev.py pour les tests) à lancer, dans l'ordre."""
    if demo.suite:
        return [[sys.executable, str(DEV), *etape] for etape in demo.suite]
    if demo.arguments[0] == "__tests__":
        return [[sys.executable, "-m", "unittest", "discover", "-s", str(DEV.parent), "-p", demo.arguments[1]]]
    if demo.accepte_graine:
        g = graine or "42"
        if not GRAINE.fullmatch(g):
            raise ValueError("graine : un entier de 1 à 6 chiffres")
        pile = ["--pile"] if demo.rejeu_sur_pile else []
        return [[sys.executable, str(DEV), "ml-sumo", "simuler", "--graine", g], [sys.executable, str(DEV), "ml-sumo", "rejouer", "--graine", g, *pile]]
    return [[sys.executable, str(DEV), *demo.arguments]]


def resumer(lignes: list[str]) -> list[dict]:
    """Les lignes « [OK] N1 … » du flux complet, en objets pour l'interface."""
    resultats = []
    for ligne in lignes:
        trouve = RESULTAT.match(ligne)
        if trouve:
            resultats.append({"ok": trouve.group(1) == "OK", "cas": trouve.group(2), "texte": trouve.group(3)})
    return resultats


class Taches:
    """Une démonstration à la fois, en arrière-plan ; sa sortie est gardée (500 lignes) pour que la page la montre."""

    def __init__(self, racine: Path = ROOT, horloge: Callable[[], float] = time.time, lanceur: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self.racine, self.horloge, self.lanceur = racine, horloge, lanceur
        self.verrou = threading.Lock()
        self.courante: dict | None = None
        self.processus: subprocess.Popen | None = None
        self.historique: dict[str, dict] = {}  # dernier résultat de chaque démonstration

    def demarrer(self, identifiant: str, confirmer: bool = False, graine: str | None = None, panne_en_cours: bool = False) -> dict:
        demo = PAR_ID.get(identifiant)
        if demo is None:
            raise KeyError("démonstration inconnue")
        if demo.arrete_des_conteneurs and not confirmer:
            raise PermissionError("cette démonstration arrête puis relance des conteneurs : confirmation requise")
        if demo.arrete_des_conteneurs and panne_en_cours:
            raise RuntimeError("une panne contrôlée est en cours : rétablissez-la avant de lancer ce cas")
        suite = commandes(demo, graine)
        with self.verrou:
            if self.courante and self.courante["etat"] == "en_cours":
                raise RuntimeError(f"« {self.courante['libelle']} » est déjà en cours")
            self.courante = {"id": demo.identifiant, "libelle": demo.libelle, "theme": demo.theme, "etat": "en_cours", "debut": self.horloge(), "fin": None, "code": None, "lignes": deque(maxlen=LIGNES_MAX), "commande": " && ".join(" ".join(c) for c in suite), "codes_ok": demo.codes_ok}
            tache = self.courante
        threading.Thread(target=self._executer, args=(tache, suite), daemon=True).start()
        return self._vue(tache)

    def _executer(self, tache: dict, suite: list[list[str]]) -> None:
        code = 0
        try:
            for commande in suite:
                tache["lignes"].append("$ " + " ".join(Path(c).name if c.startswith("/") else c for c in commande))
                self.processus = self.lanceur(commande, cwd=self.racine, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
                for ligne in self.processus.stdout or ():
                    tache["lignes"].append(ligne.rstrip("\n")[:LIGNE_MAX])
                code = self.processus.wait()
                if code not in tache["codes_ok"]:
                    break
        except OSError as erreur:
            tache["lignes"].append(f"impossible de lancer la commande : {type(erreur).__name__}")
            code = 127
        finally:
            with self.verrou:
                tache["code"], tache["fin"] = code, self.horloge()
                if tache["etat"] != "arrete":
                    tache["etat"] = "ok" if code in tache["codes_ok"] else "echec"
                self.historique[tache["id"]] = self._vue(tache, avec_lignes=False)
                self.processus = None

    def arreter(self) -> dict:
        with self.verrou:
            tache, processus = self.courante, self.processus
            if not tache or tache["etat"] != "en_cours":
                raise RuntimeError("aucune démonstration en cours")
            tache["etat"] = "arrete"
        if processus is not None:
            processus.terminate()
        return self._vue(tache)

    def _vue(self, tache: dict | None, avec_lignes: bool = True) -> dict | None:
        if tache is None:
            return None
        lignes = list(tache["lignes"])
        vue = {k: tache[k] for k in ("id", "libelle", "theme", "etat", "debut", "fin", "code", "commande")}
        vue["resultats"] = resumer(lignes)
        if avec_lignes:
            vue["lignes"] = lignes
        return vue

    def etat(self) -> dict:
        with self.verrou:
            return {"courante": self._vue(self.courante), "historique": dict(self.historique)}


def catalogue(taches: Taches) -> dict:
    etat = taches.etat()
    return {
        "demos": [{"id": d.identifiant, "theme": d.theme, "libelle": d.libelle, "montre": d.ce_que_ca_montre, "duree": d.duree, "arrete_des_conteneurs": d.arrete_des_conteneurs, "pile_requise": d.pile_requise, "accepte_graine": d.accepte_graine, "dernier": etat["historique"].get(d.identifiant)} for d in DEMOS],
        "courante": etat["courante"],
    }


# --------------------------------------------------------------------------- sécurité : constat sur les conteneurs en marche
def _publie_hors_boucle_locale(ports: dict | None) -> list[str]:
    exposes = []
    for port, liens in (ports or {}).items():
        for lien in liens or []:
            if lien.get("HostIp") not in ("127.0.0.1", "::1"):
                exposes.append(f"{port} sur {lien.get('HostIp') or '0.0.0.0'}")
    return exposes


def evaluer_conteneur(inspection: dict) -> dict:
    """Un conteneur : droits abandonnés, élévation de privilèges, mode privilégié, ports hors 127.0.0.1."""
    hote = inspection.get("HostConfig") or {}
    options = hote.get("SecurityOpt") or []
    etiquettes = (inspection.get("Config") or {}).get("Labels") or {}
    return {
        "service": etiquettes.get("com.docker.compose.service") or inspection.get("Name", "").lstrip("/"),
        "utilisateur": (inspection.get("Config") or {}).get("User") or "root (image)",
        "cap_drop_all": "ALL" in [c.upper() for c in (hote.get("CapDrop") or [])],
        "no_new_privileges": any(o.replace(":", "=").lower() == "no-new-privileges=true" or o.lower() == "no-new-privileges" for o in options),
        "privilegie": bool(hote.get("Privileged")),
        "reseau_hote": hote.get("NetworkMode") == "host",
        "ports_exposes": _publie_hors_boucle_locale((inspection.get("NetworkSettings") or {}).get("Ports")),
        "sock_docker": any("docker.sock" in (m.get("Source") or "") for m in (inspection.get("Mounts") or [])),
    }


def constat_securite(inspecter_tout: Callable[[], list[dict]]) -> dict:
    try:
        brut = inspecter_tout()
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"disponible": False, "conteneurs": [], "resume": "Docker injoignable : impossible de lire les conteneurs."}
    if not brut:
        return {"disponible": True, "conteneurs": [], "graves": [], "resume": "Aucun conteneur en marche : lancez la pile (dev.py up) pour que le constat porte sur quelque chose."}
    lignes = sorted((evaluer_conteneur(i) for i in brut), key=lambda c: c["service"])
    graves = [c["service"] for c in lignes if c["privilegie"] or c["reseau_hote"] or c["ports_exposes"] or c["sock_docker"]]
    return {"disponible": True, "conteneurs": lignes, "graves": graves,
            "resume": f"{len(lignes)} conteneur(s) lus ; " + ("aucun privilégié, aucun port hors 127.0.0.1." if not graves else "à corriger : " + ", ".join(graves))}


# --------------------------------------------------------------------------- IA : synthèse lue dans ml/evaluation
def _lire(nom: str, dossier: Path = EVALUATION) -> dict | None:
    try:
        return json.loads((dossier / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def synthese_ia(dossier: Path = EVALUATION) -> dict:
    """Chiffres lus dans les sorties versionnées ; une valeur absente reste absente (« non disponible »), jamais inventée."""
    anomalies, prevision, sumo, selection = (_lire(n, dossier) for n in ("anomalies.json", "prevision.json", "sumo.json", "selection.json"))
    sortie: dict = {"anomalies": None, "prevision": None, "sumo": None, "detection": None}
    if anomalies:
        sortie["anomalies"] = [{"detecteur": nom, "precision": d.get("precision"), "fausses_par_heure": d.get("fausses_par_heure"),
                                "rappel_par_type": {t: v.get("rappel") for t, v in (d.get("par_type") or {}).items()},
                                "delai_median_s": {t: v.get("delai_median_s") for t, v in (d.get("par_type") or {}).items()}}
                               for nom, d in (anomalies.get("detecteurs") or {}).items()]
    if prevision:
        sortie["prevision"] = {"horizons": prevision.get("horizons"), "source": prevision.get("source"), "simule": prevision.get("simule")}
    if sumo:
        sortie["sumo"] = {"capacite_mesuree_vph": sumo.get("capacite_mesuree_vph"), "run": sumo.get("run"), "rejeu_moteur": sumo.get("rejeu_moteur"), "comparaison": sumo.get("comparaison")}
    if selection:
        sortie["detection"] = {"choix": selection.get("choix"), "regle_de_choix": selection.get("regle_de_choix")}
    return sortie
