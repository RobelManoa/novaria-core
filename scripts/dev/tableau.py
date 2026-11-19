"""Tableau local d'observabilité (MS-16) : débit, erreurs, latence, disjoncteurs et retard de consommation, par service.

Les services publient `GET /metrics` (texte Prometheus). Ce module lit ces textes, garde un historique court en mémoire et en tire,
entre deux relevés, ce qu'un tableau de bord montre : requêtes par seconde, erreurs 5xx par seconde, taux d'erreur, durée moyenne et
p95, état des disjoncteurs. Le retard de consommation de Kafka (« lag » : messages écrits par les producteurs et pas encore lus par un
groupe) vient de `kafka-consumer-groups.sh`, lancé dans le conteneur du broker : il n'a pas de point `/metrics` en local.

Bibliothèque standard seulement ; Docker n'est appelé que par `Observatoire` (remplaçable dans les tests).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

POINTS = 90  # une vingtaine de minutes à un relevé toutes les 5 à 10 s
FENETRE_S = 30.0  # les taux se calculent sur les 30 dernières secondes
FENETRE_RETARD_S = 120.0  # le débit qui sert à convertir un retard en secondes : assez long pour ne pas s'effondrer sur un à-coup
LIGNE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{(.*)\})?\s+(\S+)$")
ETIQUETTE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')
CIRCUIT_OUVERT = 2
VIDE = {"classes": {}, "seaux": {}, "somme": 0.0, "nombre": 0.0}


@dataclass(frozen=True)
class Echantillon:
    nom: str
    etiquettes: dict[str, str]
    valeur: float


def lire_prometheus(texte: str) -> list[Echantillon]:
    """Les échantillons d'un texte Prometheus (les lignes `# HELP` et `# TYPE` sont ignorées)."""
    echantillons = []
    for ligne in texte.splitlines():
        trouve = LIGNE.match(ligne.strip())
        if not trouve or ligne.startswith("#"):
            continue
        nom, etiquettes, valeur = trouve.groups()
        try:
            nombre = float(valeur)
        except ValueError:
            continue
        paires = {k: v.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\") for k, v in ETIQUETTE.findall(etiquettes or "")}
        echantillons.append(Echantillon(nom, paires, nombre))
    return echantillons


def releve_http(echantillons: list[Echantillon]) -> dict:
    """Ce qu'un relevé de `/metrics` apporte au tableau : totaux cumulés, durées, disjoncteurs."""
    classes: dict[str, float] = {}
    seaux: dict[float, float] = {}
    somme = nombre = 0.0
    circuits: dict[str, int] = {}
    ouvertures: dict[str, float] = {}
    appels: dict[str, dict[str, float]] = {}
    reprises: dict[str, float] = {}
    demarrage = None
    for e in echantillons:
        if e.nom == "novaria_http_requests_total":
            classes[e.etiquettes.get("status", "?")] = classes.get(e.etiquettes.get("status", "?"), 0.0) + e.valeur
        elif e.nom == "novaria_http_request_duration_seconds_bucket":
            borne = float("inf") if e.etiquettes.get("le") == "+Inf" else float(e.etiquettes.get("le", "inf"))
            seaux[borne] = seaux.get(borne, 0.0) + e.valeur
        elif e.nom == "novaria_http_request_duration_seconds_sum":
            somme += e.valeur
        elif e.nom == "novaria_http_request_duration_seconds_count":
            nombre += e.valeur
        elif e.nom == "novaria_circuit_state":
            circuits[e.etiquettes.get("dependency", "?")] = int(e.valeur)
        elif e.nom == "novaria_circuit_opened_total":
            ouvertures[e.etiquettes.get("dependency", "?")] = e.valeur
        elif e.nom == "novaria_dependency_calls_total":
            appels.setdefault(e.etiquettes.get("dependency", "?"), {})[e.etiquettes.get("outcome", "?")] = e.valeur
        elif e.nom == "novaria_dependency_retries_total":
            reprises[e.etiquettes.get("dependency", "?")] = e.valeur
        elif e.nom == "novaria_process_start_time_seconds":
            demarrage = e.valeur
    return {"classes": classes, "seaux": seaux, "somme": somme, "nombre": nombre, "circuits": circuits, "ouvertures": ouvertures,
            "appels": appels, "reprises": reprises, "demarrage": demarrage}


def p95(avant: dict[float, float], apres: dict[float, float]) -> float | None:
    """Estimation du 95e centile des durées entre deux relevés : la plus petite borne qui couvre 95 % des requêtes nouvelles."""
    bornes = sorted(apres)
    total = apres.get(float("inf"), 0.0) - avant.get(float("inf"), 0.0)
    if total <= 0:
        return None
    for borne in bornes:
        if apres[borne] - avant.get(borne, 0.0) >= 0.95 * total:
            return None if borne == float("inf") else borne
    return None


def taux(avant: dict, apres: dict, secondes: float) -> dict:
    """Débit, erreurs et durées entre deux relevés HTTP (négatif impossible : un service redémarré remet ses compteurs à zéro)."""
    if secondes <= 0 or sum(apres["classes"].values()) < sum(avant["classes"].values()):
        return {"debit": None, "erreurs_5xx": None, "taux_erreurs": None, "duree_moyenne_ms": None, "p95_ms": None, "requetes": 0}
    delta = {c: apres["classes"].get(c, 0.0) - avant["classes"].get(c, 0.0) for c in apres["classes"]}
    requetes = sum(delta.values())
    cinq = delta.get("5xx", 0.0)
    dn = apres["nombre"] - avant["nombre"]
    ds = apres["somme"] - avant["somme"]
    quantile = p95(avant["seaux"], apres["seaux"])
    return {"debit": round(requetes / secondes, 2), "erreurs_5xx": round(cinq / secondes, 2),
            "taux_erreurs": None if requetes <= 0 else round(cinq / requetes, 3),
            "duree_moyenne_ms": None if dn <= 0 else round(ds / dn * 1000, 1),
            "p95_ms": None if quantile is None else round(quantile * 1000, 1), "requetes": int(requetes)}


def lire_retards(texte: str) -> list[dict]:
    """Les lignes de `kafka-consumer-groups.sh --describe` : (groupe, sujet, partition, courant, fin, retard)."""
    lignes = []
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) < 6 or not champs[2].isdigit():
            continue
        courant = None if champs[3] == "-" else int(champs[3])
        fin = int(champs[4]) if champs[4].isdigit() else 0
        retard = int(champs[5]) if champs[5].isdigit() else 0
        lignes.append({"groupe": champs[0], "sujet": champs[1], "partition": int(champs[2]), "courant": courant, "fin": fin, "retard": retard})
    return lignes


def resumer_kafka(lignes: list[dict]) -> dict:
    """Retard par (groupe, sujet) et position d'écriture par sujet (sans compter deux fois un sujet lu par deux groupes)."""
    retards: dict[tuple[str, str], int] = {}
    fins: dict[str, dict[int, int]] = {}
    for ligne in lignes:
        cle = (ligne["groupe"], ligne["sujet"])
        retards[cle] = retards.get(cle, 0) + ligne["retard"]
        fins.setdefault(ligne["sujet"], {})[ligne["partition"]] = ligne["fin"]
    return {"retards": retards, "fins": {sujet: sum(parts.values()) for sujet, parts in fins.items()}}


def retard_en_secondes(retard: int, debit_ecriture: float | None, plancher: float = 0.2) -> float | None:
    """Le retard en temps : combien de secondes d'écriture il représente. Un consommateur à fenêtres (le flux) ne valide ses
    positions qu'à la fermeture des fenêtres : son retard en messages est toujours « débit × durée des fenêtres », pas un arriéré.
    Sous `plancher` messages par seconde, le temps n'a pas de sens : `None`."""
    if debit_ecriture is None or debit_ecriture < plancher:
        return None
    return round(retard / debit_ecriture, 1)


def http_texte(url: str, delai_s: float = 3.0) -> str | None:
    requete = urllib.request.Request(url, method="GET")  # noqa: S310 - adresses locales du fichier de configuration
    try:
        with urllib.request.urlopen(requete, timeout=delai_s) as reponse:  # noqa: S310
            return reponse.read().decode("utf-8", errors="replace") if reponse.status == 200 else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


class Tableau:
    """L'historique des relevés et les taux calculés. `metriques` : service -> adresse de `/metrics`."""

    def __init__(self, metriques: dict[str, str], horloge: Callable[[], float], lire: Callable[[str], str | None] = http_texte,
                 kafka: Callable[[], str | None] = lambda: None) -> None:
        self.metriques, self.horloge, self.lire, self.kafka = metriques, horloge, lire, kafka
        self.releves: dict[str, deque] = {s: deque(maxlen=POINTS) for s in metriques}
        self.series: dict[str, deque] = {s: deque(maxlen=POINTS) for s in metriques}
        self.kafka_dernier: dict | None = None
        self.kafka_historique: deque = deque(maxlen=POINTS)
        self.retards_series: dict[tuple[str, str], deque] = {}

    def mesurer(self, avec_kafka: bool = True) -> None:
        instant = self.horloge()
        for service, url in self.metriques.items():
            texte = self.lire(url)
            if texte is None:
                self.releves[service].append((instant, None))
                continue
            self.releves[service].append((instant, releve_http(lire_prometheus(texte))))
        if avec_kafka:
            texte = self.kafka()
            if texte:
                resume = resumer_kafka(lire_retards(texte))
                self.kafka_dernier = {"instant": instant, **resume}
                self.kafka_historique.append((instant, resume["fins"]))
                for cle, retard in resume["retards"].items():
                    self.retards_series.setdefault(cle, deque(maxlen=POINTS)).append((instant, retard))

    def _paire(self, service: str) -> tuple[tuple[float, dict], tuple[float, dict]] | None:
        """Le relevé le plus récent et celui d'au moins `FENETRE_S` plus tôt (le plus ancien sinon)."""
        valides = [(t, r) for t, r in self.releves[service] if r is not None]
        if len(valides) < 2 or self.releves[service][-1][1] is None:
            return None
        dernier = valides[-1]
        ancien = next((x for x in reversed(valides[:-1]) if dernier[0] - x[0] >= FENETRE_S), valides[0])
        return ancien, dernier

    def service(self, nom: str) -> dict:
        derniers = self.releves[nom]
        if not derniers or derniers[-1][1] is None:
            return {"id": nom, "mesure": False, "circuits": {}, "ouvertures": {}}
        dernier = derniers[-1][1]
        paire = self._paire(nom)
        calcul = taux(paire[0][1], paire[1][1], paire[1][0] - paire[0][0]) if paire else taux(VIDE, VIDE, 0)
        return {"id": nom, "mesure": True, **calcul, "circuits": dernier["circuits"], "ouvertures": dernier["ouvertures"], "reprises": dernier["reprises"],
                "appels": dernier["appels"], "total_requetes": int(sum(dernier["classes"].values())), "total_5xx": int(dernier["classes"].get("5xx", 0)),
                "demarrage": dernier["demarrage"]}

    def serie_debit(self, nom: str) -> list[float | None]:
        """Débit instantané entre relevés consécutifs, pour la courbe (une valeur par relevé)."""
        points: list[float | None] = []
        precedent = None
        for instant, releve in self.releves[nom]:
            if releve is None:
                points.append(None)
                precedent = None
                continue
            if precedent is not None:
                points.append(taux(precedent[1], releve, instant - precedent[0])["debit"])
            precedent = (instant, releve)
        return points[-60:]

    def _debit_sujet(self, sujet: str, fenetre_s: float) -> float | None:
        """Messages écrits par seconde sur un sujet, entre le dernier relevé et celui d'au moins `fenetre_s` plus tôt."""
        historique = list(self.kafka_historique)
        if len(historique) < 2 or sujet not in historique[-1][1]:
            return None
        ancien = next((x for x in reversed(historique[:-1]) if historique[-1][0] - x[0] >= fenetre_s), historique[0])
        secondes = historique[-1][0] - ancien[0]
        if secondes <= 0 or sujet not in ancien[1]:
            return None
        return round(max(historique[-1][1][sujet] - ancien[1][sujet], 0) / secondes, 2)

    def _debit_reference(self, sujet: str) -> float | None:
        """Le plus grand des débits d'écriture des 30 et des 120 dernières secondes : au démarrage d'un trafic, la fenêtre courte
        donne le vrai débit ; quand un producteur s'arrête, la fenêtre longue garde la mémoire de ce qu'il écrivait."""
        valeurs = [v for v in (self._debit_sujet(sujet, FENETRE_S), self._debit_sujet(sujet, FENETRE_RETARD_S)) if v is not None]
        return max(valeurs) if valeurs else None

    def kafka_resume(self) -> dict:
        """Retard par groupe et sujet, débit d'écriture par sujet (messages par seconde, sur la fenêtre) et courbes de retard.

        Le retard en secondes se calcule avec le plus grand des débits des 30 et des 120 dernières secondes :
        quand le producteur s'arrête, le débit court tombe à zéro et diviserait le retard par presque rien ; au
        démarrage d'un trafic, le débit long est encore trop bas et gonflerait le retard."""
        if not self.kafka_dernier:
            return {"mesure": False, "groupes": [], "sujets": []}
        sujets = [{"sujet": s, "ecrits": fin, "debit": self._debit_sujet(s, FENETRE_S)} for s, fin in self.kafka_dernier["fins"].items()]
        longs = {s["sujet"]: self._debit_reference(s["sujet"]) for s in sujets}
        groupes = [{"groupe": g, "sujet": s, "retard": r, "retard_s": retard_en_secondes(r, longs.get(s)),
                    "serie": [v for _, v in self.retards_series.get((g, s), [])][-60:]}
                   for (g, s), r in sorted(self.kafka_dernier["retards"].items())]
        return {"mesure": True, "instant": self.kafka_dernier["instant"], "groupes": groupes, "sujets": sorted(sujets, key=lambda x: x["sujet"])}

    def resume_pour_alarmes(self) -> dict:
        """Ce que les alarmes lisent : disjoncteurs ouverts et taux d'erreurs par service, retard par groupe."""
        services = {}
        for nom in self.metriques:
            donnees = self.service(nom)
            if not donnees["mesure"]:
                services[nom] = None
                continue
            services[nom] = {"circuits_ouverts": sorted(d for d, e in donnees["circuits"].items() if e == CIRCUIT_OUVERT),
                             "taux_erreurs": donnees.get("taux_erreurs"), "requetes": donnees.get("requetes", 0)}
        retards: dict[str, dict] = {}
        for (groupe, sujet), retard in (self.kafka_dernier or {}).get("retards", {}).items():
            secondes = retard_en_secondes(retard, self._debit_reference(sujet))
            actuel = retards.get(groupe)
            if actuel is None or (secondes or 0) >= (actuel["retard_s"] or 0):
                retards[groupe] = {"retard": retard, "retard_s": secondes, "sujet": sujet}
        return {"services": services, "retards": retards}
