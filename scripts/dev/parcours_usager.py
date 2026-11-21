"""Le parcours de bout en bout AVEC L'USAGER (CIT-07) : mesure, indicateur, alerte, affichage citoyen, puis une panne.

Ajouté aux cas de `dev.py parcours` (CLD-13). Même principe : la pile locale réelle, des données **simulées**, un vrai navigateur.

| Cas | Ce qui est joué | Ce qui est vérifié |
|---|---|---|
| U1 | Quatre minutes de mesures congestionnées d'un carrefour libre, run neuf, envoyées à la collecte | 96 mesures acceptées (202) |
| U2 | Lecture de l'indicateur par l'API d'équipe (jeton `viewer`) | Les quatre tronçons ont, minute par minute, l'état annoncé par la règle de seuils (le classificateur du traitement lui-même) |
| U3 | Le service des alertes crée les alertes ; lecture par l'API **publique**, sans jeton | Quatre alertes `congestion.persistante`, et l'API publique en rend les six champs de la liste blanche, `simulated` vrai, `Cache-Control: public, max-age=5` |
| U4 | Chromium (écran de téléphone) ouvre l'application citoyenne (ADR-031 : « Mes trajets ») | Première visite : des trajets proposés, rien de gardé sur l'appareil. Le citoyen ajoute SON trajet (deux tronçons du carrefour de l'essai) et lit le verdict que la règle donne pour l'état PUBLIC de ces tronçons (Libre, Ralenti, Bloqué…) avec sa phrase ; « Me prévenir » ; après rechargement le trajet est retrouvé ; une seule clé sur l'appareil, aucun cookie, aucun code du système à l'écran |
| U5 | **Échec** : le service de circulation (`traitement`) est arrêté | API publique : 503 sans détail ni cache. Page ouverte : le trajet reste et « Mise à jour impossible… dernière information connue » ; page neuve : « momentanément indisponible », « Réessayer », aucun mot technique ; reprise : tout se rétablit |

Les cas U1 à U4 forment une chaîne : si l'un échoue, les suivants ne sont pas joués. U5 suit U1 à U3 (il lui faut l'état de la circulation).
Les alertes d'essai sont refermées à la fin (minutes fluides envoyées), même après un échec ; le service des alertes est toujours relancé.

Les mesures sont simulées, d'un carrefour choisi parmi INT_06 à INT_02 (INT_01 est celui du parcours nominal) : un rejeu rapproché prend un
autre carrefour, car le service des feux ignore une recommandation plus ancienne que la dernière reçue.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable

import citoyen_delai
import flux_complet as flux
import parcours
from parcours import Contexte, Echec, _exiger

CITOYEN = parcours.ROOT / "citizen"
CAPTURES = parcours.ROOT / "docs" / "Capture d'ecran"
CONGESTIONNEES = (True,) * 4
FLUIDES = (False,) * 4
ATTENTE_INDICATEURS_S = 150
ATTENTE_ALERTES_S = 150
ATTENTE_REPRISE_S = 120
DELAI_NAVIGATEUR_S = 60
CHAMPS_PUBLICS = {"alert_id", "road_segment_id", "intersection_id", "severity", "opened_at", "simulated"}
SERVICE_CIRCULATION = "traitement"  # sert `GET /api/v1/public/congestion`, la donnée de « Mes trajets »


# --------------------------------------------------------------------------- aides
def lire_public(pile: parcours.Pile, chemin: str) -> tuple[int, dict[str, str], object]:
    """Un `GET` public, sans jeton : (statut, en-têtes en minuscules, corps JSON ou None)."""
    demande = urllib.request.Request(f"{pile.passerelle}{chemin}", method="GET", headers={"Accept": "application/json"})  # noqa: S310 - adresses locales de la pile
    try:
        with urllib.request.urlopen(demande, timeout=15) as reponse:  # noqa: S310 - adresses locales de la pile
            statut, en_tetes, texte = reponse.status, dict(reponse.headers.items()), reponse.read()
    except urllib.error.HTTPError as erreur:
        statut, en_tetes, texte = erreur.code, dict(erreur.headers.items()), erreur.read()
        erreur.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}, None
    try:
        corps = json.loads(texte) if texte else None
    except ValueError:
        corps = None
    return statut, {nom.lower(): valeur for nom, valeur in en_tetes.items()}, corps


VERDICTS = {"LIBRE": "Libre", "RALENTI": "Ralenti", "BLOQUE": "Bloqué", "INCOMPLET": "Information incomplète", "INDISPONIBLE": "Information indisponible"}


def verdict_attendu(etats: list[str]) -> str:
    """Le titre que l'application doit afficher pour un trajet dont les tronçons ont ces états (`UNKNOWN` si le tronçon est absent).

    Même règle que `citizen/src/verdict.ts` (ADR-031, D2) : le pire état l'emporte ; fluide partout = Libre ; fluide là où l'on mesure avec
    un tronçon sans mesure = incomplet ; aucune mesure = indisponible. Un test compare les titres à ceux du fichier TypeScript."""
    if "CONGESTED" in etats:
        return VERDICTS["BLOQUE"]
    if "SLOW" in etats:
        return VERDICTS["RALENTI"]
    if etats and all(e == "FREE_FLOW" for e in etats):
        return VERDICTS["LIBRE"]
    if "FREE_FLOW" not in etats:
        return VERDICTS["INDISPONIBLE"]
    return VERDICTS["INCOMPLET"]


def etats_publics(pile: parcours.Pile, tronconts: list[str]) -> list[str]:
    """L'état de ces tronçons dans `GET /api/v1/public/congestion` (ce que le citoyen reçoit) ; `UNKNOWN` pour un tronçon absent."""
    statut, _, corps = lire_public(pile, "/api/v1/public/congestion")
    _exiger(statut == 200 and isinstance(corps, dict), f"GET /api/v1/public/congestion : HTTP {statut}")
    par_id = {i["road_segment_id"]: i["state"] for i in corps["items"]}  # type: ignore[index]
    return [par_id.get(t, "UNKNOWN") for t in tronconts]


def _jeton(c: Contexte) -> str:
    """Le compte jetable du parcours (créé par N1 s'il n'a pas été joué) ; supprimé en fin de parcours par `executer`."""
    if not c.jeton:
        parcours.n1_compte_et_jeton(c)
    return c.jeton


def _troncons(c: Contexte) -> list[str]:
    return [t for _, _, t in flux.capteurs(c.notes["carrefour"])]


def _refermer(c: Contexte) -> None:
    """Minutes fluides : le retour à la normale referme les alertes d'essai (l'état public ne garde rien d'ouvert)."""
    c.pile.envoyer(flux.mesures_du_run(c.notes["run"], c.notes["carrefour"], c.notes["debut"], FLUIDES, len(CONGESTIONNEES)))


def _npm(c: Contexte) -> str:
    npm = shutil.which("npm")
    _exiger(npm is not None and shutil.which("node") is not None, "navigateur non vérifié : Node.js 22 ou plus et npm sont nécessaires")
    _exiger((CITOYEN / "node_modules").is_dir(), "navigateur non vérifié : lancer `npm ci` dans citizen/ (Chromium de Playwright aussi)")
    construit = subprocess.run([npm, "run", "build"], cwd=CITOYEN, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=180)
    _exiger(construit.returncode == 0, "la version construite de l'application citoyenne échoue : " + construit.stdout[-200:].replace("\n", " | "))
    return npm


def _environnement(c: Contexte, mode: str, capture: str, capture_panne: str = "") -> dict[str, str]:
    tronconts = [a["troncon"] for a in c.notes["alertes"]][:2]  # deux tronçons du carrefour de l'essai : « le trajet du citoyen »
    c.notes["trajet"] = tronconts
    c.notes["attendu"] = verdict_attendu(etats_publics(c.pile, tronconts))
    return {**os.environ, "MODE": mode, "TRONCONS": json.dumps(tronconts), "NOM": "Parcours CIT-07", "ATTENDU": c.notes["attendu"],
            "CAPTURE": capture, "CAPTURE_PANNE": capture_panne, "DELAI_S": str(DELAI_NAVIGATEUR_S), "API_TARGET": c.pile.passerelle,
            "PORT_APERCU": os.environ.get("PORT_APERCU_PARCOURS", "5178")}


class Navigateur:
    """Le script Playwright de l'application citoyenne : ses comptes rendus JSON arrivent dans une file, on lui écrit « arret », « reprise »."""

    def __init__(self, c: Contexte, mode: str, capture: str, capture_panne: str = "") -> None:
        self.processus = subprocess.Popen(["node", "scripts/parcours-usager.mjs"], cwd=CITOYEN, env=_environnement(c, mode, capture, capture_panne), text=True,
                                          encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.evenements: queue.Queue[dict] = queue.Queue()
        self.vus: dict[str, dict] = {}
        threading.Thread(target=self._lire, daemon=True).start()

    def _lire(self) -> None:
        for ligne in self.processus.stdout or []:
            try:
                evenement = json.loads(ligne)
            except ValueError:
                continue
            self.vus[evenement.get("evenement", "?")] = evenement
            self.evenements.put(evenement)

    def attendre(self, nom: str, delai_s: float) -> dict:
        """Le prochain compte rendu `nom` ; une erreur du script, ou un compte rendu « pas ok », est un échec du cas."""
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            try:
                evenement = self.evenements.get(timeout=0.5)
            except queue.Empty:
                if self.processus.poll() is not None and self.evenements.empty():
                    break
                continue
            if evenement.get("evenement") == "erreur":
                raise Echec("navigateur : " + str(evenement.get("message")))
            if evenement.get("evenement") == nom:
                return evenement
        raise Echec(f"navigateur : pas de compte rendu « {nom} » après {delai_s:g} s")

    def dire(self, ordre: str) -> None:
        assert self.processus.stdin is not None
        self.processus.stdin.write(ordre + "\n")
        self.processus.stdin.flush()

    def fermer(self) -> None:
        if self.processus.poll() is None:
            self.processus.terminate()
        try:
            self.processus.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.processus.kill()


# --------------------------------------------------------------------------- les cas
def u1_mesures(c: Contexte) -> str:
    c.notes["run"] = flux.nouveau_run("cit07")
    c.notes["debut"] = flux.debut_pour(len(CONGESTIONNEES) + len(FLUIDES))
    c.notes["carrefour"] = citoyen_delai.choisir_carrefour(c.pile, c.notes["debut"])
    c.nettoyages.append(lambda: _refermer(c))
    mesures = flux.mesures_du_run(c.notes["run"], c.notes["carrefour"], c.notes["debut"], CONGESTIONNEES, 0)
    statuts = Counter(c.pile.envoyer(mesures))
    _exiger(statuts == Counter({"ACCEPTED": len(mesures)}), f"statuts de la collecte : {dict(statuts)}")
    return (f"{len(mesures)} mesures simulées de INT_{c.notes['carrefour']:02d} ({len(CONGESTIONNEES)} minutes congestionnées) acceptées (202), "
            f"run {c.notes['run']}")


def u2_indicateur(c: Contexte) -> str:
    jeton = _jeton(c)
    attendus = flux.etats_attendus(CONGESTIONNEES)
    tronconts = _troncons(c)

    def etats() -> dict[str, list[str]] | None:
        statut, corps = c.pile.indicateurs(c.notes["run"], jeton)
        if statut != 200 or not corps:
            return None
        par_troncon: dict[str, list[tuple[str, str]]] = {}
        for item in corps["items"]:
            par_troncon.setdefault(item["road_segment_id"], []).append((item["window_start"], item["congestion_state"]))
        lus = {t: [etat for _, etat in sorted(valeurs)] for t, valeurs in par_troncon.items()}
        return lus if all(len(lus.get(t, [])) >= len(attendus) for t in tronconts) else None

    lus = flux.attendre(etats, ATTENTE_INDICATEURS_S, 3, "les indicateurs des quatre tronçons n'arrivent pas")
    for troncon in tronconts:
        _exiger(lus[troncon][:len(attendus)] == attendus,  # type: ignore[index]
                f"{troncon} : états {lus[troncon][:len(attendus)]} au lieu de {attendus}")  # type: ignore[index]
    return (f"GET /api/v1/indicators (jeton viewer) : 4 tronçons × {len(attendus)} minutes, états {' → '.join(attendus)} sur chacun, "
            "égaux à ceux de la règle de seuils (classificateur du traitement)")


def u3_alerte(c: Contexte) -> str:
    run = c.notes["run"]
    trouvees = flux.attendre(lambda: (lambda a: a if len(a) >= 4 else None)(flux.alertes(c.pile, run)), ATTENTE_ALERTES_S, 2,
                             "les quatre alertes ne sont pas créées")
    _exiger(len(trouvees) == 4 and sorted(a["troncon"] for a in trouvees) == sorted(_troncons(c)),  # type: ignore[arg-type,union-attr]
            "les alertes ne couvrent pas exactement les quatre tronçons")
    _exiger(all(a["regle"] == "congestion.persistante" and a["kind"] == "CONGESTION" and a["gravite"] == "WARNING" and a["etat"] in ("CREATED", "NOTIFIED")
                for a in trouvees), "règle, type, gravité ou état inattendus")  # type: ignore[union-attr]
    c.notes["alertes"] = [{"alert_id": a["alert_id"], "troncon": a["troncon"]} for a in trouvees]  # type: ignore[union-attr]

    def publiques() -> dict | None:
        statut, h, corps = lire_public(c.pile, "/api/v1/public/alerts")
        if statut != 200 or not isinstance(corps, dict):
            return None
        par_id = {i["alert_id"]: i for i in corps["items"]}
        if not all(a["alert_id"] in par_id for a in c.notes["alertes"]):
            return None
        return {"en_tetes": h, "items": [par_id[a["alert_id"]] for a in c.notes["alertes"]]}

    lues = flux.attendre(publiques, 30, 1, "les alertes ne sont pas dans l'API publique")
    for item in lues["items"]:  # type: ignore[index]
        _exiger(set(item) == CHAMPS_PUBLICS, f"champs publics : {sorted(set(item) ^ CHAMPS_PUBLICS)} en trop ou en moins")
        _exiger(item["simulated"] is True and item["severity"] == "WARNING" and item["intersection_id"] == f"INT_{c.notes['carrefour']:02d}",
                "alerte publique : donnée non simulée, gravité ou carrefour inattendus")
    _exiger(lues["en_tetes"].get("cache-control") == "public, max-age=5", f"Cache-Control : {lues['en_tetes'].get('cache-control')}")  # type: ignore[index]
    return ("4 alertes `congestion.persistante` (WARNING, une par tronçon) créées par le service ; GET /api/v1/public/alerts, sans jeton : "
            "les 4 alertes avec exactement les six champs publics, `simulated` vrai, `Cache-Control: public, max-age=5`")


def u4_affichage(c: Contexte) -> str:
    _npm(c)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    navigateur = Navigateur(c, "affichage", str(CAPTURES / "CIT-07-parcours-usager-affichage.png"))
    try:
        rapport = navigateur.attendre("affichage", DELAI_NAVIGATEUR_S + 60)
    finally:
        navigateur.fermer()
    _exiger(rapport.get("ok") is True, "affichage citoyen : " + json.dumps({k: v for k, v in rapport.items() if k != "evenement"}, ensure_ascii=False)[:400])
    return (f"Chromium (390 × 844) : première visite avec {rapport['trajets_proposes']} trajets proposés et rien de gardé ; le citoyen ajoute son trajet "
            f"({', '.join(c.notes['trajet'])}) et lit « {rapport['verdict_attendu']} » avec sa phrase de décision (l'état public de ces tronçons, par la règle) ; "
            "« Me prévenir » est gardé après rechargement, une seule clé sur l'appareil, aucun cookie, aucun code à l'écran ; bandeau « Données simulées » présent")


def u5_service_indisponible(c: Contexte) -> str:
    _npm(c)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    navigateur = Navigateur(c, "indisponible", str(CAPTURES / "CIT-07-parcours-usager-avant-panne.png"), str(CAPTURES / "CIT-07-parcours-usager-panne.png"))
    arrete = False

    def relancer() -> None:
        nonlocal arrete
        if arrete:
            c.pile.docker("start", SERVICE_CIRCULATION)
            fin = time.monotonic() + ATTENTE_REPRISE_S
            while time.monotonic() < fin:
                c.pile.docker("exec", "-T", "passerelle", "nginx", "-s", "reload")  # la passerelle résout les services au démarrage
                if lire_public(c.pile, "/api/v1/public/congestion")[0] == 200:
                    break
                time.sleep(3)
            arrete = False

    c.nettoyages.append(relancer)  # le service est relancé même si ce cas plante
    try:
        navigateur.attendre("pret", DELAI_NAVIGATEUR_S + 60)
        sortie = c.pile.docker("stop", SERVICE_CIRCULATION)
        _exiger(sortie.returncode == 0, f"arrêt du service {SERVICE_CIRCULATION} impossible : {sortie.stderr.strip()[:150]}")
        arrete = True
        statut, h, corps = lire_public(c.pile, "/api/v1/public/congestion")
        _exiger(statut == 503 and isinstance(corps, dict) and corps.get("code") == "UPSTREAM_UNAVAILABLE" and h.get("cache-control") == "no-store",
                f"l'API publique devrait répondre 503 UPSTREAM_UNAVAILABLE sans cache : HTTP {statut}")
        navigateur.dire("arret")
        ouverte = navigateur.attendre("panne_page_ouverte", DELAI_NAVIGATEUR_S + 30)
        _exiger(ouverte.get("ok") is True, f"page ouverte pendant la panne : {ouverte}")
        neuve = navigateur.attendre("panne_page_neuve", DELAI_NAVIGATEUR_S + 30)
        _exiger(neuve.get("ok") is True, f"page neuve pendant la panne : {neuve}")
        navigateur.attendre("attente_reprise", 10)
        relancer()
        _exiger(lire_public(c.pile, "/api/v1/public/congestion")[0] == 200, f"l'API publique ne répond pas 200 {ATTENTE_REPRISE_S} s après le redémarrage")
        navigateur.dire("reprise")
        reprise = navigateur.attendre("reprise", DELAI_NAVIGATEUR_S + 30)
        _exiger(reprise.get("ok") is True, f"après la reprise : {reprise}")
    finally:
        navigateur.fermer()
        relancer()
    return (f"service `{SERVICE_CIRCULATION}` arrêté : l'API publique répond 503 sans détail ni cache ; page ouverte : le trajet reste et « Mise à jour impossible… "
            "dernière information connue » ; page neuve : « momentanément indisponible », bouton « Réessayer », aucun mot technique ; "
            "service relancé : tout se rétablit")


# --------------------------------------------------------------------------- orchestration
CAS_USAGER: tuple[tuple[str, str, Callable[[Contexte], str]], ...] = (
    ("U1", "Usager : mesures congestionnées envoyées", u1_mesures),
    ("U2", "Usager : l'indicateur annonce la congestion", u2_indicateur),
    ("U3", "Usager : l'alerte est créée et publique", u3_alerte),
    ("U4", "Usager : « Mes trajets » dans un navigateur", u4_affichage),
    ("U5", "Usager : service de circulation indisponible", u5_service_indisponible),
)
# U5 a besoin d'alertes ouvertes : il suit la même chaîne (un échec de U1 à U3 le rend « non joué »).
CHAINES = (parcours.NOMINAUX, ("U1", "U2", "U3", "U4"), ("U1", "U2", "U3", "U5"))


def tous_les_cas() -> tuple[tuple[str, str, Callable[[Contexte], str]], ...]:
    """Les cas de `dev.py parcours` : le nominal (N1 à N6), l'usager (U1 à U5), puis les échecs (E1 à E3, dont l'arrêt de PostgreSQL en dernier)."""
    nominaux = tuple(cas for cas in parcours.CAS if cas[0].startswith("N"))
    echecs = tuple(cas for cas in parcours.CAS if cas[0].startswith("E"))
    return nominaux + CAS_USAGER + echecs
