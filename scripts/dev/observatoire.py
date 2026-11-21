"""Observatoire des pannes (CLD-14) : arrêter un service, voir l'alarme se lever, retracer alarme, journal et cause.

Équivalent local de CloudWatch (ADR-025) : les alarmes sont déclarées dans `ops/alarmes.json` (versionné avant la panne),
évaluées toutes les 5 secondes sur trois signaux (état des conteneurs Docker, sondes HTTP, erreurs des journaux), et chaque
changement d'état est une ligne de la chronologie. Bibliothèque standard seulement ; Docker n'est appelé que par `Docker`
(remplaçable dans les tests). `dev.py observatoire` sert l'interface graphique, `dev.py panne` rejoue une panne en ligne de commande.

Sécurité de l'interface : elle n'écoute que sur 127.0.0.1, refuse un autre nom d'hôte (contre le rebond DNS), exige un jeton
aléatoire (tiré au lancement, lu dans la page) et une origine identique pour arrêter ou rétablir un service, et n'arrête que
les services nommés dans `ops/alarmes.json`. Les trois services du socle (bases et bus) demandent une confirmation explicite.
"""

from __future__ import annotations

import json
import re
import secrets
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import observatoire_demos as demos
import observatoire_ml
import tableau as tb

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "ops" / "alarmes.json"
PAGE = ROOT / "ops" / "observatoire" / "index.html"
OK, ALARME, INSUFFISANT = "OK", "ALARM", "INSUFFICIENT_DATA"
SIGNAUX = ("etat_conteneur", "sonde_http", "erreurs_journal", "circuit_ouvert", "taux_erreurs", "retard_kafka")
LIGNE_MAX = 260
LIGNES_PAR_SERVICE = 8
PREFIXE_COMPOSE = re.compile(r"^(?P<service>[A-Za-z0-9_.-]+?)-\d+\s+\|\s?(?P<texte>.*)$")
ERREUR_NGINX = re.compile(r"\[(error|emerg|crit|alert)\]")
REPONSE_5XX = re.compile(r'"\s5\d\d\s')


class ErreurConfiguration(Exception):
    """`ops/alarmes.json` est incohérent : message à corriger dans le fichier."""


ID_TRACE = re.compile(r"[A-Za-z0-9._:-]{3,100}")
LIGNE_HORODATEE = re.compile(r"^(?P<service>[A-Za-z0-9_.-]+?)-\d+\s+\|\s(?P<ts>\d{4}-\d\d-\d\dT[\d:.]+Z)\s(?P<texte>.*)$")
CHAMPS_JOURNAL = ("level", "message", "logger", "method", "path", "status", "duration_ms", "event_id", "request_id", "topic", "dependency", "error", "attempt")


def _resumer_ligne(texte: str) -> dict:
    """Une ligne de journal en quelques champs lisibles (JSON des services, ou ligne nginx de la passerelle)."""
    if texte.startswith("{"):
        try:
            document = json.loads(texte)
            return {"niveau": document.get("level", ""), "texte": str(document.get("message", ""))[:160],
                    "champs": {k: document[k] for k in CHAMPS_JOURNAL[2:] if k in document and document[k] not in (None, "")}}
        except ValueError:
            pass
    niveau = "ERROR" if ERREUR_NGINX.search(texte) or REPONSE_5XX.search(texte) else "INFO"
    return {"niveau": niveau, "texte": texte[:LIGNE_MAX], "champs": {}}


class ErreurPanne(Exception):
    """L'action demandée est refusée (service inconnu, panne déjà en cours, confirmation absente)."""


# --------------------------------------------------------------------------- configuration
def charger_config(chemin: Path = CONFIG) -> dict:
    config = json.loads(Path(chemin).read_text(encoding="utf-8"))
    services = config.get("services", {})
    for nom, service in services.items():
        for amont in service.get("depend_de", []):
            if amont not in services:
                raise ErreurConfiguration(f"{nom} dépend de {amont}, qui n'est pas déclaré")
    for alarme in config.get("alarmes", []):
        if alarme.get("signal") not in SIGNAUX:
            raise ErreurConfiguration(f"alarme {alarme.get('id')} : signal inconnu {alarme.get('signal')!r}")
        if int(alarme.get("evaluations", 0)) < 1:
            raise ErreurConfiguration(f"alarme {alarme['id']} : « evaluations » doit valoir au moins 1")
    for sonde in config.get("sondes_de_chaine", []):
        for nom in sonde["traverse"]:
            if nom not in services:
                raise ErreurConfiguration(f"sonde {sonde['id']} traverse {nom}, qui n'est pas déclaré")
    return config


def dependants(config: dict, service: str) -> list[str]:
    """Les services qui dépendent de `service`, directement ou non : ce que sa panne devrait toucher."""
    touches: list[str] = []
    a_voir = [service]
    while a_voir:
        courant = a_voir.pop()
        for nom, definition in config["services"].items():
            if courant in definition.get("depend_de", []) and nom not in touches and nom != service:
                touches.append(nom)
                a_voir.append(nom)
    return sorted(touches)


def sondes_declarees(config: dict, env: dict[str, str]) -> list[dict]:
    """Une sonde par service qui publie un port, plus les sondes qui traversent plusieurs services."""
    def adresse(definition: dict) -> str:
        return f"http://127.0.0.1:{env.get(definition['port_var'], definition['port'])}{definition['chemin']}"

    sondes = [{"id": nom, "libelle": f"Santé de {definition['libelle']}", "service": nom, "url": adresse(definition),
               "traverse": [nom]} for nom, definition in config["services"].items() if "port_var" in definition]
    sondes += [{"id": s["id"], "libelle": s["libelle"], "service": s["service"], "url": adresse(s), "traverse": s["traverse"]}
               for s in config.get("sondes_de_chaine", [])]
    return sondes


# --------------------------------------------------------------------------- Docker (isolé pour les tests)
class Docker:
    def __init__(self, racine: Path = ROOT) -> None:
        self.racine = racine

    def _executer(self, *args: str, delai: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], cwd=self.racine, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False, timeout=delai)

    def conteneurs(self) -> dict[str, dict]:
        sortie = self._executer("compose", "ps", "-a", "--format", "json")
        if sortie.returncode:
            return {}
        texte = sortie.stdout.strip()
        documents = json.loads(texte) if texte.startswith("[") else [json.loads(ligne) for ligne in texte.splitlines() if ligne.strip()]
        return {d["Service"]: {"etat": d.get("State", ""), "sante": d.get("Health", ""), "code": d.get("ExitCode", 0),
                               "statut": d.get("Status", ""), "id": d.get("ID", "")} for d in documents}

    def inspecter_tous(self) -> list[dict]:
        """`docker inspect` complet des conteneurs du projet Compose (droits, ports, montages) : lecture seule."""
        identifiants = [c["id"] for c in self.conteneurs().values() if c.get("id")]
        if not identifiants:
            return []
        sortie = self._executer("inspect", *identifiants)
        return json.loads(sortie.stdout) if sortie.returncode == 0 and sortie.stdout.strip() else []

    def inspecter(self, service: str) -> dict:
        identifiant = self.conteneurs().get(service, {}).get("id")
        if not identifiant:
            return {}
        sortie = self._executer("inspect", identifiant, "--format", "{{json .State}}")
        try:
            etat = json.loads(sortie.stdout)
        except ValueError:
            return {}
        return {"etat": etat.get("Status"), "code": etat.get("ExitCode"), "oom": etat.get("OOMKilled"),
                "erreur": etat.get("Error", ""), "fini": etat.get("FinishedAt"), "debut": etat.get("StartedAt"),
                "sante": (etat.get("Health") or {}).get("Status", ""), "pause": bool(etat.get("Paused"))}

    def journaux(self, depuis: str | None = None, service: str | None = None, dernieres: int | None = None) -> str:
        args = ["compose", "logs", "--no-color"]
        if depuis:
            args += ["--since", depuis]
        if dernieres is not None:
            args += ["--tail", str(dernieres)]
        if service:
            args.append(service)
        return self._executer(*args).stdout

    def journaux_horodates(self, depuis: str) -> str:
        """Tous les journaux depuis `depuis`, chaque ligne précédée de son horodatage Docker (pour retracer un identifiant)."""
        return self._executer("compose", "logs", "--no-color", "--timestamps", "--since", depuis, delai=120).stdout

    def kafka_groupes(self) -> str | None:
        """Le retard de consommation de chaque groupe, lu dans le conteneur du broker (aucun point /metrics en local)."""
        sortie = self._executer("compose", "exec", "-T", "kafka", "sh", "-c",
                                "/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --all-groups 2>/dev/null", delai=60)
        return sortie.stdout if sortie.returncode == 0 else None

    def arreter(self, service: str) -> None:
        self._executer("compose", "stop", service, delai=120)

    def geler(self, service: str) -> None:
        """`docker compose pause` : le processus vit, mais ne répond plus (un service bloqué, pas arrêté)."""
        self._executer("compose", "pause", service, delai=60)

    def degeler(self, service: str) -> None:
        self._executer("compose", "unpause", service, delai=60)

    def demarrer(self, service: str) -> None:
        self._executer("compose", "start", service, delai=120)


# --------------------------------------------------------------------------- signaux
def sonder_http(url: str, delai_s: float) -> tuple[bool, str]:
    requete = urllib.request.Request(url, method="GET")  # noqa: S310 - adresses locales du fichier de configuration
    try:
        with urllib.request.urlopen(requete, timeout=delai_s) as reponse:  # noqa: S310 - adresses locales du fichier de configuration
            return reponse.status == 200, f"HTTP {reponse.status}"
    except urllib.error.HTTPError as erreur:
        return False, f"HTTP {erreur.code}"
    except TimeoutError:
        return False, "délai dépassé"
    except (urllib.error.URLError, OSError) as erreur:
        raison = getattr(erreur, "reason", erreur)
        return False, "connexion refusée" if isinstance(raison, ConnectionRefusedError) else f"injoignable ({raison.__class__.__name__})"


def _resultat(futur) -> tuple[bool, str]:
    """Le résultat d'une sonde ; une sonde qui plante est une sonde en échec, jamais un tour de mesure perdu."""
    try:
        return futur.result()
    except Exception as erreur:  # noqa: BLE001 - la boucle de mesure ne doit jamais mourir
        return False, f"sonde en erreur ({erreur.__class__.__name__})"


def decouper_journal(sortie: str) -> dict[str, list[str]]:
    """Les lignes de `docker compose logs`, rangées par service (le préfixe « nom-1  | » est retiré)."""
    par_service: dict[str, list[str]] = {}
    for ligne in sortie.splitlines():
        trouve = PREFIXE_COMPOSE.match(ligne)
        if trouve:
            par_service.setdefault(trouve["service"], []).append(trouve["texte"])
    return par_service


def est_une_erreur(ligne: str) -> bool:
    """Une ligne d'erreur : JSON de niveau ERROR ou CRITICAL, erreur nginx, ou réponse 5xx de la passerelle."""
    if ligne.startswith("{"):
        try:
            return str(json.loads(ligne).get("level", "")).upper() in ("ERROR", "CRITICAL")
        except ValueError:
            return False
    return bool(ERREUR_NGINX.search(ligne) or REPONSE_5XX.search(ligne))


def est_un_signal(ligne: str) -> bool:
    """Ligne utile à un diagnostic : une erreur, ou un avertissement (reprise, disjoncteur ouvert, publication échouée)."""
    if ligne.startswith("{"):
        try:
            return str(json.loads(ligne).get("level", "")).upper() in ("WARNING", "ERROR", "CRITICAL")
        except ValueError:
            return False
    return est_une_erreur(ligne)


def resumer_signaux(lignes: list[str], limite: int = LIGNES_PAR_SERVICE) -> list[str]:
    """Regroupe les lignes qui se répètent (même enregistreur, même message) : une ligne et un compte, pas cent lignes.

    Les enregistreurs de l'application (`app.*`) passent avant ceux des bibliothèques : ce sont eux qui disent ce que le service
    a décidé (« disjoncteur ouvert », « publication échouée »), pas seulement ce que son client Kafka a subi."""
    groupes: dict[tuple[str, str], dict] = {}
    for rang, ligne in enumerate(lignes):
        cle = ("nginx", re.sub(r"\d+", "#", ligne)[:90])
        horodatage = ""
        if ligne.startswith("{"):
            try:
                document = json.loads(ligne)
                cle = (str(document.get("logger", "")), str(document.get("message", "")))
                horodatage = str(document.get("ts", ""))
            except ValueError:
                pass
        groupe = groupes.setdefault(cle, {"rang": rang, "ligne": ligne, "nombre": 0, "dernier": ""})
        groupe["nombre"] += 1
        groupe["dernier"] = horodatage
    ordre = sorted(groupes.items(), key=lambda element: (not element[0][0].startswith("app"), element[1]["rang"]))
    resume = []
    for _, groupe in ordre[:limite]:
        suite = f"  (×{groupe['nombre']}, jusqu'à {groupe['dernier']})" if groupe["nombre"] > 1 else ""
        resume.append(groupe["ligne"][:LIGNE_MAX] + suite)
    return resume


def compter_erreurs(par_service: dict[str, list[str]]) -> dict[str, int]:
    return {service: sum(1 for ligne in lignes if est_une_erreur(ligne)) for service, lignes in par_service.items()}


# --------------------------------------------------------------------------- l'évaluation des alarmes
class Instantane:
    """Un tour de mesure : état des conteneurs, résultat des sondes, nombre d'erreurs par service."""

    def __init__(self, instant: float, conteneurs: dict[str, dict], sondes: dict[str, tuple[bool, str]], erreurs: dict[str, int],
                 tableau: dict | None = None) -> None:
        self.instant, self.conteneurs, self.sondes, self.erreurs = instant, conteneurs, sondes, erreurs
        self.tableau = tableau or {"services": {}, "retards": {}}  # disjoncteurs, taux d'erreurs et retards lus dans /metrics et Kafka


class Evaluateur:
    """États OK ou ALARM par couple (alarme, cible) : ALARM après `evaluations` mesures défaillantes de suite, OK dès une bonne mesure."""

    def __init__(self, config: dict, sondes: list[dict]) -> None:
        self.config = config
        self.sondes = sondes
        self.historique: dict[tuple[str, str], deque[bool | None]] = {}
        self.etats: dict[tuple[str, str], dict] = {}

    def _cibles(self, alarme: dict) -> list[str]:
        if alarme["signal"] == "sonde_http":
            return [s["id"] for s in self.sondes]
        if alarme["signal"] in ("circuit_ouvert", "taux_erreurs"):
            return [nom for nom, definition in self.config["services"].items() if definition.get("metrics")]
        if alarme["signal"] == "retard_kafka":
            return list(self.config.get("groupes_kafka", []))
        return list(self.config["services"])

    def _defaillant(self, alarme: dict, cible: str, mesure: Instantane) -> tuple[bool | None, str]:
        """(défaillant ?, raison) ; None si la mesure manque (conteneur inconnu)."""
        if alarme["signal"] == "etat_conteneur":
            conteneur = mesure.conteneurs.get(cible)
            if conteneur is None:
                return None, "conteneur absent de « docker compose ps »"
            if conteneur["etat"] != "running":
                return True, f"conteneur « {conteneur['etat']} » ({conteneur['statut']})"
            if conteneur["sante"] == "unhealthy":
                return True, "sonde de santé Docker « unhealthy »"
            return False, "conteneur « running »"
        if alarme["signal"] == "sonde_http":
            ok, detail = mesure.sondes.get(cible, (None, "pas de mesure"))
            return (None if ok is None else not ok), detail
        if alarme["signal"] in ("circuit_ouvert", "taux_erreurs"):
            return self._defaillant_metrique(alarme, mesure.tableau["services"].get(cible))
        if alarme["signal"] == "retard_kafka":
            retard = mesure.tableau["retards"].get(cible)
            if retard is None:
                return None, "groupe de consommation absent de Kafka"
            secondes = retard["retard_s"]
            if secondes is None:
                return False, f"{retard['retard']} message(s) de retard, écriture trop faible pour le mesurer en temps"
            return secondes >= float(alarme["seuil_s"]), f"{retard['retard']} message(s) de retard = {secondes:.0f} s d'écriture (seuil {alarme['seuil_s']} s)"
        nombre = mesure.erreurs.get(cible, 0)
        return nombre >= int(alarme["seuil"]), f"{nombre} ligne(s) d'erreur sur {self.config['fenetre_journal_s']} s"

    @staticmethod
    def _defaillant_metrique(alarme: dict, donnees: dict | None) -> tuple[bool | None, str]:
        """Disjoncteur ouvert ou taux d'erreurs 5xx trop haut, lus dans `/metrics` (None : le service ne répond pas à la lecture)."""
        if donnees is None:
            return None, "/metrics ne répond pas"
        if alarme["signal"] == "circuit_ouvert":
            ouverts = donnees["circuits_ouverts"]
            return bool(ouverts), f"disjoncteur ouvert : {', '.join(ouverts)}" if ouverts else "disjoncteurs fermés"
        if donnees["requetes"] < int(alarme.get("requetes_min", 5)) or donnees["taux_erreurs"] is None:
            return False, f"trafic insuffisant ({donnees['requetes']} requêtes sur la fenêtre)"
        taux = donnees["taux_erreurs"]
        return taux >= float(alarme["seuil"]), f"{taux * 100:.0f} % de réponses 5xx (seuil {float(alarme['seuil']) * 100:.0f} %)"

    def evaluer(self, mesure: Instantane) -> list[dict]:
        """Met les états à jour ; rend les transitions (une par changement d'état, hors premier état OK)."""
        transitions = []
        for alarme in self.config["alarmes"]:
            for cible in self._cibles(alarme):
                cle = (alarme["id"], cible)
                defaillant, raison = self._defaillant(alarme, cible, mesure)
                fil = self.historique.setdefault(cle, deque(maxlen=int(alarme["evaluations"])))
                fil.append(defaillant)
                ancien = self.etats.get(cle, {}).get("etat")
                if defaillant is None:
                    nouveau = INSUFFISANT
                elif len(fil) == fil.maxlen and all(v is True for v in fil):
                    nouveau = ALARME
                elif defaillant is False:
                    nouveau = OK
                else:
                    nouveau = ancien or OK
                if nouveau != ancien:
                    self.etats[cle] = {"etat": nouveau, "depuis": mesure.instant, "raison": raison}
                    # Un événement : une alarme qui se lève ou qui retombe, ou une mesure qui disparaît après avoir existé.
                    # Passer de « pas de donnée » à OK n'est pas un rétablissement : rien n'était en alarme.
                    if nouveau == ALARME or ancien == ALARME or (nouveau == INSUFFISANT and ancien is not None):
                        transitions.append({"alarme": alarme["id"], "cible": cible, "de": ancien, "vers": nouveau, "raison": raison,
                                            "instant": mesure.instant})
                else:
                    self.etats[cle]["raison"] = raison
        return transitions

    def instances(self) -> list[dict]:
        sorties = []
        for alarme in self.config["alarmes"]:
            for cible in self._cibles(alarme):
                etat = self.etats.get((alarme["id"], cible), {"etat": INSUFFISANT, "depuis": None, "raison": "pas encore mesuré"})
                service = next((s["service"] for s in self.sondes if s["id"] == cible), cible)
                sorties.append({"alarme": alarme["id"], "nom": alarme["nom"], "gravite": alarme["gravite"], "guide": alarme["guide"],
                                "cible": cible, "service": service, **etat})
        return sorties


# --------------------------------------------------------------------------- cause d'un arrêt
def diagnostiquer(inspection: dict, dernieres_lignes: list[str]) -> dict:
    """La cause d'un conteneur qui ne répond plus, déduite de ce que Docker et le journal ont enregistré (pas de l'injection)."""
    etat, code = inspection.get("etat"), inspection.get("code")
    indices = [f"état Docker « {etat} », code de sortie {code}"] if etat else []
    if inspection.get("pause"):
        return {"constat": "service gelé (docker pause) : le processus vit mais ne répond plus, ses requêtes expirent",
                "gravite": "blocage", "indices": [*indices, "État Docker : en pause (Paused = vrai)"]}
    if inspection.get("oom"):
        return {"constat": "tué par manque de mémoire (OOMKilled)", "gravite": "plantage", "indices": [*indices, "OOMKilled = vrai"]}
    if etat == "running" and inspection.get("sante") == "unhealthy":
        return {"constat": "processus vivant mais sonde de santé en échec : service bloqué ou dépendance coupée",
                "gravite": "blocage", "indices": [*indices, "sonde de santé « unhealthy »"]}
    if etat == "exited" and code == 0:
        arret = any("Shutting down" in ligne or "shutdown complete" in ligne.lower() for ligne in dernieres_lignes)
        return {"constat": "arrêt ordonné : signal d'arrêt reçu puis sortie propre (code 0), ce n'est pas un plantage",
                "gravite": "arret volontaire", "indices": [*indices, *(["le journal se termine par la séquence d'arrêt (Shutting down)"] if arret else [])]}
    if etat == "exited" and code == 137:
        return {"constat": "tué de force (SIGKILL, code 137) : `docker kill`, ou manque de mémoire non signalé", "gravite": "plantage", "indices": indices}
    if etat == "exited" and code == 143:
        return {"constat": "arrêté par SIGTERM (code 143) : arrêt demandé ; normal pour un processus Java comme Kafka, sinon le service ne gère pas SIGTERM", "gravite": "arret volontaire", "indices": indices}
    if etat == "exited":
        derniere = next((ligne for ligne in reversed(dernieres_lignes) if est_une_erreur(ligne)), "")
        return {"constat": f"plantage : le processus a quitté avec le code {code}", "gravite": "plantage",
                "indices": [*indices, *([f"dernière erreur du journal : {derniere[:LIGNE_MAX]}"] if derniere else [])]}
    return {"constat": f"état inattendu « {etat} »", "gravite": "inconnue", "indices": indices}


def iso(instant: float | None) -> str | None:
    return None if instant is None else datetime.fromtimestamp(instant, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- l'observatoire
class Observatoire:
    def __init__(self, config: dict, docker: Docker, env: dict[str, str], horloge: Callable[[], float] = time.time,
                 sonder: Callable[[str, float], tuple[bool, str]] = sonder_http) -> None:
        self.config, self.docker, self.horloge, self.sonder = config, docker, horloge, sonder
        self.sondes = sondes_declarees(config, env)
        self.evaluateur = Evaluateur(config, self.sondes)
        self.evenements: list[dict] = []
        self.panne: dict | None = None
        self.derniere: Instantane | None = None
        self.env = env
        metriques = {nom: f"http://127.0.0.1:{env.get(d['port_var'], d['port'])}/metrics" for nom, d in config["services"].items() if d.get("metrics")}
        self.tableau = tb.Tableau(metriques, horloge, kafka=docker.kafka_groupes)
        self._tours = 0
        self.taches = demos.Taches()
        self.verrou = threading.RLock()
        self.arret = threading.Event()
        self.fil: threading.Thread | None = None

    # -- mesure
    def mesurer(self) -> Instantane:
        delai = float(self.config["delai_sonde_s"])
        with ThreadPoolExecutor(max_workers=max(1, len(self.sondes))) as pool:
            futures = {s["id"]: pool.submit(self.sonder, s["url"], delai) for s in self.sondes}
            conteneurs = self.docker.conteneurs()
            erreurs = compter_erreurs(decouper_journal(self.docker.journaux(depuis=f"{int(self.config['fenetre_journal_s'])}s")))
            sondes = {identifiant: _resultat(futur) for identifiant, futur in futures.items()}
        self.tableau.mesurer(avec_kafka=self._tours % 2 == 0)  # Kafka : un appel Docker, un tour sur deux
        self._tours += 1
        return Instantane(self.horloge(), conteneurs, sondes, erreurs, self.tableau.resume_pour_alarmes())

    def tour(self) -> None:
        mesure = self.mesurer()
        with self.verrou:
            self.derniere = mesure
            for transition in self.evaluateur.evaluer(mesure):
                self._noter_transition(transition)

    def _noter_transition(self, t: dict) -> None:
        alarme = next(a for a in self.config["alarmes"] if a["id"] == t["alarme"])
        depuis = None if not self.panne else round(t["instant"] - self.panne["debut"], 1)
        verbe = "se déclenche" if t["vers"] == ALARME else "revient à OK" if t["vers"] == OK else "manque de données"
        self.evenements.append({"instant": t["instant"], "type": "alarme", "service": t["cible"], "alarme": t["alarme"], "vers": t["vers"],
                                "depuis_injection_s": depuis, "texte": f"Alarme « {alarme['nom']} » sur {t['cible']} {verbe} : {t['raison']}"})
        if self.panne and t["vers"] == ALARME:
            self.panne["alarmes"].setdefault((t["alarme"], t["cible"]), {"declenchee": t["instant"], "ok": None})
        if self.panne and t["vers"] == OK and (t["alarme"], t["cible"]) in self.panne["alarmes"]:
            self.panne["alarmes"][(t["alarme"], t["cible"])]["ok"] = t["instant"]

    def demarrer(self) -> None:
        def boucle() -> None:
            while not self.arret.is_set():
                try:
                    self.tour()
                except Exception as erreur:  # noqa: BLE001 - la boucle de mesure ne doit jamais mourir
                    with self.verrou:
                        self.evenements.append({"instant": self.horloge(), "type": "observatoire", "service": "", "texte": f"tour de mesure raté : {erreur.__class__.__name__}"})
                self.arret.wait(float(self.config["periode_s"]))
        self.fil = threading.Thread(target=boucle, name="observatoire", daemon=True)
        self.fil.start()

    def arreter_mesure(self) -> None:
        self.arret.set()
        if self.fil:
            self.fil.join(timeout=15)

    # -- panne
    def injecter(self, service: str, confirmer: bool = False, mode: str = "stop") -> dict:
        definition = self.config["services"].get(service)
        if definition is None:
            raise ErreurPanne(f"service inconnu : {service}")
        with self.verrou:
            if self.panne and self.panne["retabli"] is None:
                raise ErreurPanne(f"une panne est déjà en cours sur {self.panne['service']} : la rétablir d'abord")
        if definition["groupe"] == "socle" and not confirmer:
            raise ErreurPanne(f"{definition['libelle']} fait partie du socle : confirmation explicite requise")
        if mode not in ("stop", "pause"):
            raise ErreurPanne(f"mode inconnu : {mode} (stop ou pause)")
        instant = self.horloge()
        (self.docker.geler if mode == "pause" else self.docker.arreter)(service)
        with self.verrou:
            self.panne = {"service": service, "debut": instant, "retabli": None, "alarmes": {}, "reprise": None, "mode": mode}
            verbe = "Gel volontaire" if mode == "pause" else "Arrêt volontaire"
            self.evenements.append({"instant": instant, "type": "injection", "service": service,
                                    "texte": f"{verbe} de {definition['libelle']} (docker compose {'pause' if mode == 'pause' else 'stop'} {service})"})
        return {"service": service, "debut": iso(instant), "mode": mode}

    def retablir(self) -> dict:
        with self.verrou:
            panne = self.panne
        if not panne or panne["retabli"] is not None:
            raise ErreurPanne("aucune panne en cours")
        panne["preuves"] = self._collecter_preuves(panne)
        instant = self.horloge()
        (self.docker.degeler if panne.get("mode") == "pause" else self.docker.demarrer)(panne["service"])
        with self.verrou:
            panne["retabli"] = instant
            commande = "unpause" if panne.get("mode") == "pause" else "start"
            self.evenements.append({"instant": instant, "type": "retablissement", "service": panne["service"],
                                    "texte": f"Rétablissement de {self.config['services'][panne['service']]['libelle']} (docker compose {commande})"})
        return {"service": panne["service"], "retabli": iso(instant)}

    def tout_est_ok(self) -> bool:
        with self.verrou:
            etats = [e["etat"] for e in self.evaluateur.etats.values()]
            return OK in etats and ALARME not in etats  # une mesure qui manque (INSUFFICIENT_DATA) n'est pas une alarme

    # -- lecture
    def etat(self) -> dict:
        with self.verrou:
            mesure = self.derniere
            instances = self.evaluateur.instances()
            panne = None if not self.panne else {"service": self.panne["service"], "debut": iso(self.panne["debut"]),
                                                 "retabli": iso(self.panne["retabli"]), "en_cours": self.panne["retabli"] is None, "mode": self.panne.get("mode", "stop")}
        en_alarme: dict[str, list[str]] = {}
        for instance in instances:
            if instance["etat"] == ALARME:
                en_alarme.setdefault(instance["service"], []).append(instance["alarme"])
        services = []
        for nom, definition in self.config["services"].items():
            conteneur = (mesure.conteneurs.get(nom) if mesure else None) or {}
            sondes = [{"id": s["id"], "libelle": s["libelle"], "resultat": (mesure.sondes.get(s["id"]) if mesure else None)}
                      for s in self.sondes if s["service"] == nom]
            services.append({"id": nom, "libelle": definition["libelle"], "groupe": definition["groupe"], "role": definition["role"],
                             "effet": definition["effet"], "depend_de": definition["depend_de"], "dependants": dependants(self.config, nom),
                             "etat": conteneur.get("etat", "inconnu"), "sante": conteneur.get("sante", ""), "statut": conteneur.get("statut", ""),
                             "alarmes": en_alarme.get(nom, []), "sondes": sondes})
        return {"instant": iso(mesure.instant if mesure else None), "services": services, "alarmes": instances, "panne": panne}

    # -- démonstrations (flux complet, sécurité, cloud local, IA) : voir observatoire_demos.py
    def demos(self) -> dict:
        return demos.catalogue(self.taches) | {"presentation": demos.charger_presentation()}

    def lancer_demo(self, identifiant: str, confirmer: bool, graine: str | None) -> dict:
        try:
            return self.taches.demarrer(identifiant, confirmer, graine, panne_en_cours=bool(self.panne and self.panne["retabli"] is None))
        except (KeyError, PermissionError, RuntimeError, ValueError) as erreur:
            raise ErreurPanne(str(erreur.args[0] if isinstance(erreur, KeyError) else erreur)) from None

    def arreter_demo(self) -> dict:
        try:
            return self.taches.arreter()
        except RuntimeError as erreur:
            raise ErreurPanne(str(erreur)) from None

    def securite(self) -> dict:
        return demos.constat_securite(self.docker.inspecter_tous)

    def chronologie(self) -> list[dict]:
        with self.verrou:
            return [{**e, "horodatage": iso(e["instant"])} for e in self.evenements]

    def journal(self, service: str, dernieres: int = 40) -> list[str]:
        if service not in self.config["services"]:
            raise ErreurPanne(f"service inconnu : {service}")
        lignes = decouper_journal(self.docker.journaux(service=service, dernieres=dernieres)).get(service, [])
        return [ligne[:LIGNE_MAX * 2] for ligne in lignes]

    def _collecter_preuves(self, panne: dict) -> dict:
        """Journaux, inspection et cause du service arrêté. Figés au rétablissement : un conteneur relancé n'a plus rien à dire."""
        service = panne["service"]
        # Le service arrêté : ses dernières lignes d'avant la panne comptent (la séquence d'arrêt, ce qui précède).
        avant_arret = decouper_journal(self.docker.journaux(depuis=iso(panne["debut"] - 90), service=service)).get(service, [])
        inspection = self.docker.inspecter(service)
        journaux = {service: [ligne[:LIGNE_MAX] for ligne in avant_arret[-LIGNES_PAR_SERVICE:]]}
        # Les autres : seulement les erreurs écrites depuis l'arrêt, pas celles d'une panne précédente.
        for nom, lignes in decouper_journal(self.docker.journaux(depuis=iso(panne["debut"]))).items():
            if nom != service and (signaux := [ligne for ligne in lignes if est_un_signal(ligne)]):
                journaux[nom] = resumer_signaux(signaux)
        tableau = self.donnees_tableau()
        return {"cause": diagnostiquer(inspection, avant_arret[-10:]), "inspection": inspection, "journaux": journaux,
                "tableau": {"services": tableau["services"], "kafka": tableau["kafka"]}}

    # -- tableau local (MS-16)
    def donnees_tableau(self) -> dict:
        """Ce que montre l'onglet « Tableau » : débit, erreurs, durées, disjoncteurs, retard de consommation, trafic simulé."""
        with self.verrou:
            erreurs = dict(self.derniere.erreurs) if self.derniere else {}
            actives = [{"alarme": a["alarme"], "cible": a["cible"], "raison": a["raison"], "gravite": a["gravite"]}
                       for a in self.evaluateur.instances() if a["etat"] == ALARME]
        services = []
        for nom in self.tableau.metriques:
            ligne = self.tableau.service(nom)
            services.append({**ligne, "libelle": self.config["services"][nom]["libelle"], "serie": self.tableau.serie_debit(nom),
                             "erreurs_journal": erreurs.get(nom, 0)})
        autres = [{"id": nom, "libelle": d["libelle"], "erreurs_journal": erreurs.get(nom, 0)}
                  for nom, d in self.config["services"].items() if nom not in self.tableau.metriques and d["groupe"] != "socle"]
        return {"instant": iso(self.horloge()), "services": services, "autres": autres, "kafka": self.tableau.kafka_resume(),
                "trafic": self.trafic_etat(), "alarmes_actives": actives, "fenetre_s": tb.FENETRE_S}

    def trace(self, identifiant: str) -> dict:
        """Toutes les lignes de journal, de tous les services, qui portent cet identifiant, dans l'ordre du temps."""
        if not ID_TRACE.fullmatch(identifiant or ""):
            raise ErreurPanne("identifiant de corrélation attendu : 3 à 100 caractères parmi lettres, chiffres, . _ : -")
        lignes = []
        for brut in self.docker.journaux_horodates("30m").splitlines():
            if identifiant not in brut:
                continue
            trouve = LIGNE_HORODATEE.match(brut)
            if trouve:
                lignes.append({"service": trouve["service"], "horodatage": trouve["ts"], **_resumer_ligne(trouve["texte"])})
        lignes.sort(key=lambda ligne: ligne["horodatage"])
        chemin: list[str] = []
        for ligne in lignes:
            if ligne["service"] not in chemin:  # l'ordre d'apparition : par où l'identifiant est passé
                chemin.append(ligne["service"])
        return {"identifiant": identifiant, "lignes": lignes[:100], "chemin": chemin, "tronque": len(lignes) > 100}

    def _simulateur(self, methode: str, corps: dict | None = None) -> tuple[int, dict]:
        port = self.env.get("SIMULATOR_PORT", "8005")
        requete = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/run", method=methode, headers={"Content-Type": "application/json"},
                                         data=None if corps is None else json.dumps(corps).encode())  # noqa: S310 - adresse locale
        try:
            with urllib.request.urlopen(requete, timeout=10) as reponse:  # noqa: S310 - adresses locales du fichier de configuration
                return reponse.status, json.loads(reponse.read() or b"{}")
        except urllib.error.HTTPError as erreur:
            try:
                return erreur.code, json.loads(erreur.read() or b"{}")
            finally:
                erreur.close()
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return 0, {}

    def trafic_etat(self) -> dict:
        statut, corps = self._simulateur("GET")
        return {"disponible": statut == 200, "etat": corps.get("state"), "run": corps.get("run_id"), "envoyes": corps.get("delivered"), "erreurs": (corps.get("collecte") or {}).get("errors")}

    def trafic(self, action: str, debit: float = 15.0) -> dict:
        """Lance ou arrête un run du simulateur vers la collecte : sans trafic, le tableau n'a rien à montrer."""
        if action == "stop":
            statut, corps = self._simulateur("DELETE")
        elif action == "start":
            corps_demande = {"scenario": "heure-de-pointe", "seed": 7, "rate": max(1.0, min(float(debit), 100.0)), "sink": "collecte",
                             "duration": "30m", "run_id": f"obs-{secrets.token_hex(3)}"}
            statut, corps = self._simulateur("POST", corps_demande)
        else:
            raise ErreurPanne("action inconnue : start ou stop")
        if statut not in (200, 201, 202):
            raise ErreurPanne(f"le simulateur a répondu {statut} : {corps.get('detail') or corps.get('error') or 'injoignable'}")
        return self.trafic_etat()

    # -- retracer alarme, journal et cause
    def rapport(self) -> dict | None:
        with self.verrou:
            panne = self.panne
            if not panne:
                return None
            evenements = [e for e in self.evenements if e["instant"] >= panne["debut"] - 1]
            alarmes_vues = dict(panne["alarmes"])
        service = panne["service"]
        preuves = panne.get("preuves") or self._collecter_preuves(panne)
        cause, inspection, journaux = preuves["cause"], preuves["inspection"], preuves["journaux"]
        tableau = preuves.get("tableau")
        alarmes = []
        for (identifiant, cible), vue in sorted(alarmes_vues.items(), key=lambda item: item[1]["declenchee"]):
            definition = next(a for a in self.config["alarmes"] if a["id"] == identifiant)
            alarmes.append({"alarme": identifiant, "nom": definition["nom"], "cible": cible, "gravite": definition["gravite"],
                            "guide": definition["guide"], "declenchee": iso(vue["declenchee"]),
                            "delai_detection_s": round(vue["declenchee"] - panne["debut"], 1),
                            "retour_ok": iso(vue["ok"]), "retour_ok_apres_s": None if vue["ok"] is None else round(vue["ok"] - panne["debut"], 1)})
        prevu = dependants(self.config, service)
        observe = sorted({self._service_de(a["cible"]) for a in alarmes} - {service})
        fin = panne["retabli"] or self.horloge()
        return {"service": service, "libelle": self.config["services"][service]["libelle"], "effet_documente": self.config["services"][service]["effet"],
                "injection": iso(panne["debut"]), "retablissement": iso(panne["retabli"]), "duree_panne_s": round(fin - panne["debut"], 1),
                "premiere_alarme_s": alarmes[0]["delai_detection_s"] if alarmes else None, "alarmes": alarmes, "cause": cause,
                "inspection": inspection, "journaux": journaux, "tableau": tableau, "impact": {"prevu": prevu, "observe_en_alarme": observe},
                "chronologie": [{"horodatage": iso(e["instant"]), "type": e["type"], "service": e["service"], "texte": e["texte"],
                                 "depuis_injection_s": round(e["instant"] - panne["debut"], 1)} for e in evenements]}

    def _service_de(self, cible: str) -> str:
        return next((s["service"] for s in self.sondes if s["id"] == cible), cible)


def _lignes_du_tableau(tableau: dict | None) -> list[str]:
    """Le tableau d'un rapport : une ligne par service qui publie /metrics, une par groupe Kafka."""
    if not tableau:
        return ["  (non relevé)"]
    lignes = []
    for s in tableau["services"]:
        if not s.get("mesure"):
            lignes.append(f"  {s['id']:<10} /metrics muet")
            continue
        circuits = ", ".join(f"{d} {['fermé', 'semi-ouvert', 'OUVERT'][e]}" for d, e in s["circuits"].items()) or "-"
        taux = "-" if s.get("taux_erreurs") is None else f"{s['taux_erreurs'] * 100:.0f} %"
        lignes.append(f"  {s['id']:<10} {s.get('debit')} req/s · 5xx {s.get('erreurs_5xx')}/s ({taux}) · p95 {s.get('p95_ms')} ms · disjoncteurs : {circuits}")
    kafka = tableau.get("kafka") or {}
    for g in kafka.get("groupes", []):
        lignes.append(f"  kafka {g['groupe']} / {g['sujet']} : retard {g['retard']} message(s)" + ("" if g.get("retard_s") is None else f" = {g['retard_s']:.0f} s d'écriture"))
    return lignes or ["  (vide)"]


def rapport_texte(r: dict) -> str:
    """Le rapport en texte : ce que `dev.py panne` affiche et ce que le guide de diagnostic reprend."""
    lignes = [f"Panne contrôlée : {r['libelle']} ({r['service']})", f"  Arrêt volontaire : {r['injection']}",
              f"  Première alarme  : {'aucune' if r['premiere_alarme_s'] is None else str(r['premiere_alarme_s']) + ' s après l’arrêt'}",
              f"  Rétablissement   : {r['retablissement'] or 'non rétabli'}", "", "1. Alarmes"]
    lignes += [f"  [{a['gravite']}] {a['nom']} sur {a['cible']} : déclenchée à {a['declenchee']} (+{a['delai_detection_s']} s)"
               + ("" if a["retour_ok"] is None else f", retour à OK à +{a['retour_ok_apres_s']} s") for a in r["alarmes"]] or ["  aucune"]
    lignes += ["", "2. Journaux"]
    for service, extraits in r["journaux"].items():
        lignes.append(f"  {service} :")
        lignes += [f"    {extrait}" for extrait in extraits] or ["    (rien)"]
    lignes += ["", "3. Tableau (au moment du rétablissement)", *_lignes_du_tableau(r.get("tableau")), "", "4. Cause", f"  {r['cause']['constat']}",
               *[f"  - {indice}" for indice in r["cause"]["indices"]], "", "5. Impact", f"  Prévu (services qui dépendent de {r['service']}) : {', '.join(r['impact']['prevu']) or 'aucun'}",
               f"  Observé (services avec une alarme) : {', '.join(r['impact']['observe_en_alarme']) or 'aucun'}", "", "6. Chronologie"]
    lignes += [f"  +{e['depuis_injection_s']:>6} s  {e['texte']}" for e in r["chronologie"]]
    return "\n".join(lignes)


# --------------------------------------------------------------------------- panne en ligne de commande
def rejouer_panne(obs: Observatoire, service: str, duree_s: int = 70, attente_alarme_s: int = 60, attente_reprise_s: int = 180,
                  afficher: Callable[[str], None] = print, attendre: Callable[[float], None] = time.sleep, trafic: bool = False,
                  mode: str = "stop", echauffement_s: int = 45) -> dict:
    """Arrête le service, attend l'alarme, laisse la panne durer, rétablit, attend le retour à OK. Rétablit toujours, même sur erreur."""
    try:
        if trafic:
            afficher("Trafic simulé vers la collecte…")
            obs.trafic("start")
            attendre(echauffement_s)
        depart = time.monotonic() + 150
        while time.monotonic() < depart and not obs.tout_est_ok():
            attendre(3)  # un départ propre : sinon les délais mesurés seraient faux
        if not obs.tout_est_ok():
            en_alarme = sorted(f"{a['alarme']} ({a['cible']})" for a in obs.etat()["alarmes"] if a["etat"] == ALARME)
            raise ErreurPanne("la pile n'est pas saine avant la panne, rien n'a été arrêté : " + ", ".join(en_alarme))
        afficher("Départ propre : toutes les alarmes à OK.")
        afficher(f"{'Gel' if mode == 'pause' else 'Arrêt'} volontaire de {service}…")
        obs.injecter(service, confirmer=True, mode=mode)
        try:
            attendu = time.monotonic() + attente_alarme_s
            while time.monotonic() < attendu and not any(k == ("service-arrete", service) for k in obs.panne["alarmes"]):
                attendre(1)
            afficher("Alarme levée." if ("service-arrete", service) in obs.panne["alarmes"] else "Aucune alarme dans le délai.")
            attendre(duree_s)
        finally:
            obs.retablir()
    finally:
        if trafic:
            try:
                obs.trafic("stop")
            except ErreurPanne:
                pass  # le run s'est peut-être déjà terminé : rien à arrêter
    attendu = time.monotonic() + attente_reprise_s
    while time.monotonic() < attendu and not obs.tout_est_ok():
        attendre(2)
    rapport = obs.rapport()
    rapport["tout_est_ok"] = obs.tout_est_ok()
    return rapport


# --------------------------------------------------------------------------- interface graphique
def requete_autorisee(hote: str | None, origine: str | None, jeton_recu: str | None, jeton: str, port: int, ecriture: bool) -> bool:
    """Garde de l'interface : hôte local seulement ; pour une écriture, origine identique et jeton exact."""
    if hote not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return False
    if not ecriture:
        return True
    return origine in (f"http://127.0.0.1:{port}", f"http://localhost:{port}") and secrets.compare_digest(jeton_recu or "", jeton)


def fabriquer_gestionnaire(obs: Observatoire, jeton: str, port: int) -> type[BaseHTTPRequestHandler]:
    class Gestionnaire(BaseHTTPRequestHandler):
        server_version = "Observatoire"

        def log_message(self, *_: object) -> None:  # silence : la page interroge toutes les 2 s
            return

        def _repondre(self, code: int, corps: bytes, type_: str = "application/json; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(corps)

        def _json(self, code: int, document: object) -> None:
            self._repondre(code, json.dumps(document, ensure_ascii=False).encode("utf-8"))

        def _autorise(self, ecriture: bool) -> bool:
            if requete_autorisee(self.headers.get("Host"), self.headers.get("Origin"), self.headers.get("X-Observatoire-Jeton"), jeton, port, ecriture):
                return True
            self._json(403, {"erreur": "requête refusée"})
            return False

        def do_GET(self) -> None:  # noqa: N802 - nom imposé par http.server
            if not self._autorise(False):
                return
            adresse = urlparse(self.path)
            if adresse.path == "/":
                page = PAGE.read_text(encoding="utf-8").replace("__JETON__", jeton)
                self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif adresse.path == "/api/etat":
                self._json(200, obs.etat())
            elif adresse.path == "/api/chronologie":
                self._json(200, obs.chronologie())
            elif adresse.path == "/api/rapport":
                self._json(200, obs.rapport())
            elif adresse.path == "/api/tableau":
                self._json(200, obs.donnees_tableau())
            elif adresse.path == "/api/trafic":
                self._json(200, obs.trafic_etat())
            elif adresse.path == "/api/demos":
                self._json(200, obs.demos())
            elif adresse.path == "/api/securite":
                self._json(200, obs.securite())
            elif adresse.path == "/api/ia":
                self._json(200, demos.synthese_ia())
            elif adresse.path == "/api/entrainement":
                self._json(200, observatoire_ml.carte())
            elif adresse.path == "/api/trace":
                try:
                    self._json(200, obs.trace(parse_qs(adresse.query).get("id", [""])[0]))
                except ErreurPanne as erreur:
                    self._json(400, {"erreur": str(erreur)})
            elif adresse.path == "/api/journal":
                try:
                    self._json(200, obs.journal(parse_qs(adresse.query).get("service", [""])[0]))
                except ErreurPanne as erreur:
                    self._json(404, {"erreur": str(erreur)})
            else:
                self._json(404, {"erreur": "introuvable"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._autorise(True):
                return
            longueur = min(int(self.headers.get("Content-Length") or 0), 2048)
            try:
                corps = json.loads(self.rfile.read(longueur) or b"{}")
                if urlparse(self.path).path == "/api/panne":
                    self._json(200, obs.injecter(str(corps.get("service", "")), corps.get("confirmer") is True, str(corps.get("mode", "stop"))))
                elif urlparse(self.path).path == "/api/trafic":
                    self._json(200, obs.trafic(str(corps.get("action", "")), float(corps.get("debit", 15))))
                elif urlparse(self.path).path == "/api/demos/lancer":
                    graine = corps.get("graine")
                    self._json(200, obs.lancer_demo(str(corps.get("id", "")), corps.get("confirmer") is True, None if graine is None else str(graine)))
                elif urlparse(self.path).path == "/api/demos/arreter":
                    self._json(200, obs.arreter_demo())
                elif urlparse(self.path).path == "/api/retablir":
                    self._json(200, obs.retablir())
                else:
                    self._json(404, {"erreur": "introuvable"})
            except ErreurPanne as erreur:
                self._json(409, {"erreur": str(erreur)})
            except ValueError:
                self._json(400, {"erreur": "corps JSON attendu"})

    return Gestionnaire


def servir(obs: Observatoire, port: int, afficher: Callable[[str], None] = print) -> None:
    """Sert l'interface sur 127.0.0.1 jusqu'à Ctrl-C ou SIGTERM ; rétablit alors le service arrêté s'il y en a un."""
    jeton = secrets.token_urlsafe(24)
    serveur = ThreadingHTTPServer(("127.0.0.1", port), fabriquer_gestionnaire(obs, jeton, port))
    obs.demarrer()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))  # un arrêt par `kill` rétablit aussi le service
    afficher(f"Observatoire des pannes : http://127.0.0.1:{port}/  (Ctrl-C pour arrêter ; un service arrêté est alors rétabli)")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()
        obs.arreter_mesure()
        try:
            obs.taches.arreter()  # une démonstration en cours est interrompue avec l'observatoire
        except RuntimeError:
            pass
        if obs.panne and obs.panne["retabli"] is None:
            afficher(f"Rétablissement de {obs.panne['service']}…")
            obs.retablir()
