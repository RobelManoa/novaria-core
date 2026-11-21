"""Parcours de bout en bout sur la pile locale (CLD-13) : donnée brute, entrepôt, API, tableau de bord, et trois cas d'échec.

La logique est ici ; `dev.py parcours` ne fait que l'appeler. Bibliothèque standard seulement. Chaque cas est une
fonction qui rend un `Resultat` (identifiant, verdict, preuve) ; un cas qui lève une exception est un échec, jamais un arrêt.

| Cas | Ce qu'il prouve |
|---|---|
| N1 à N6 | une mesure brute reçue par la collecte devient, par le flux puis le pipeline, une ligne de l'entrepôt ; l'API la lit |
|         | avec les valeurs recalculées ici depuis les mesures ; le front-end la sert par son proxy ; un navigateur l'affiche |
| E1 | une mesure hors contrat est refusée à l'entrée (422) et tracée ; une mesure datée du futur est refusée par le flux |
| E2 | un jeton expiré, mal signé ou absent est refusé (401) ; le même jeton non expiré est accepté ; le navigateur ferme la session |
| E3 | PostgreSQL arrêté : l'API répond 503 sans détail, la collecte continue, et les mesures reçues pendant la panne |
|    | arrivent dans l'entrepôt après le redémarrage (rien n'est perdu) |
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPTEUR = "SENSOR_001"
TRONCON = "ROAD_001"
CARREFOUR = "INT_01"
INTERVALLE_S = 10
MESURES_PAR_MINUTE = 6
ATTENTE_ENTREPOT_S = 150  # fermeture de la fenêtre (15 s sans message) + flux + pipeline, avec marge
ATTENTE_REPRISE_S = 240  # redémarrage de PostgreSQL, puis des deux services d'écriture
ROLE = "viewer"


@dataclass
class Resultat:
    cas: str
    titre: str
    ok: bool
    preuve: str
    duree_s: float = 0.0


class Echec(Exception):
    """Une vérification du parcours n'est pas satisfaite ; le message est la preuve de l'échec."""


# --------------------------------------------------------------------------- mesures et valeurs attendues
def horodatage(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def debut_de_minute_passee(maintenant: datetime, recul_s: int = 150) -> datetime:
    """Le début de la dernière minute entière terminée depuis au moins `recul_s` secondes."""
    seconde = int((maintenant - timedelta(seconds=recul_s)).timestamp()) // 60 * 60
    return datetime.fromtimestamp(seconde, UTC)


def mesure(run_id: str, fin: datetime, vehicules: int, vitesse: float | None, occupation: float, file_m: float) -> dict:
    """Une mesure `novaria.iot.measurement.v1` conforme au contrat, de provenance simulée, pour le capteur de référence."""
    millis = int(fin.timestamp()) * 1000  # l'identifiant porte l'instant à la seconde près, comme le contrat l'exige
    return {
        "id": f"{run_id}:{CAPTEUR}:{millis}",
        "source": f"simulateur/{run_id}",
        "type": "novaria.iot.measurement.v1",
        "time": horodatage(fin),
        "subject": CARREFOUR,
        "schema_version": "1.0",
        "correlation_id": f"corr-{millis}",
        "domain": "iot",
        "data": {
            "sensor_id": CAPTEUR,
            "road_segment_id": TRONCON,
            "intersection_id": CARREFOUR,
            "interval_s": INTERVALLE_S,
            "vehicle_count": vehicules,
            "average_speed_kmh": vitesse,
            "occupancy_rate": occupation,
            "queue_length_m": file_m,
            "quality": {"status": "VALID"},
            "provenance": {"source_type": "SIMULATED", "run_id": run_id, "scenario_id": "cld13-parcours", "seed": 13},
        },
    }


def minute_nominale(run_id: str, debut: datetime) -> list[dict]:
    """Six mesures de dix secondes qui couvrent [debut, debut + 60 s[ : valeurs fixes, choisies pour que l'arrondi compte."""
    vehicules = (4, 6, 5, 3, 7, 5)
    vitesses = (31.5, 28.0, 30.5, 33.0, 29.5, 30.0)
    occupations = (0.21, 0.25, 0.24, 0.20, 0.28, 0.26)
    files = (12.0, 18.5, 15.0, 9.5, 22.0, 17.0)
    return [
        mesure(run_id, debut + timedelta(seconds=(i + 1) * INTERVALLE_S), vehicules[i], vitesses[i], occupations[i], files[i])
        for i in range(MESURES_PAR_MINUTE)
    ]


def arrondir(valeur: Decimal, decimales: int) -> Decimal:
    """Moitié vers le haut, comme le flux et PostgreSQL (docs/03-donnees/entrepot.md, section 3.1)."""
    return valeur.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def indicateur_attendu(mesures: list[dict]) -> dict[str, str]:
    """Les champs de l'indicateur d'une minute, recalculés ici depuis les mesures brutes (formules de flux.md, section 5.1)."""
    donnees = [m["data"] for m in mesures]
    total = sum(d["vehicle_count"] for d in donnees)
    pondere = sum(Decimal(str(d["average_speed_kmh"])) * d["vehicle_count"] for d in donnees)
    occupation = sum(Decimal(str(d["occupancy_rate"])) for d in donnees) / len(donnees)
    return {
        "vehicle_count": str(total),
        "flow_veh_per_min": str(arrondir(Decimal(total), 2)),
        "average_speed_kmh": str(arrondir(pondere / total, 1)),
        "occupancy_rate": str(arrondir(occupation, 3)),
        "max_queue_length_m": str(arrondir(max(Decimal(str(d["queue_length_m"])) for d in donnees), 1)),
        "sample_count": str(len(donnees)),
        "expected_sample_count": str(MESURES_PAR_MINUTE),
    }


def meme_nombre(a: object, b: object) -> bool:
    return Decimal(str(a)) == Decimal(str(b))


def ecarts(attendu: dict[str, str], lu: dict) -> list[str]:
    """Les champs où la valeur lue (API ou entrepôt) diffère de la valeur recalculée."""
    return [f"{champ} : attendu {valeur}, lu {lu.get(champ)}" for champ, valeur in attendu.items()
            if lu.get(champ) is None or not meme_nombre(valeur, lu[champ])]


# --------------------------------------------------------------------------- jetons
def _base64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def jeton(secret: str, sujet: str, role: str, expire: datetime, emis: datetime | None = None) -> str:
    """Un jeton HS256 aux revendications de l'API (`sub`, `role`, `iat`, `exp`) : les mêmes que `app/core/security.py`."""
    emis = emis or expire - timedelta(minutes=30)
    entete = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    charge = _base64url(json.dumps({"sub": sujet, "role": role, "iat": int(emis.timestamp()), "exp": int(expire.timestamp())},
                                   separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{entete}.{charge}".encode(), hashlib.sha256).digest()
    return f"{entete}.{charge}.{_base64url(signature)}"


def mal_signe(valeur: str) -> str:
    """Le même jeton, dont le premier caractère de la signature est remplacé : la charge reste valide, pas la signature.

    Le dernier caractère d'une signature de 32 octets en base64url ne porte que 4 bits utiles : le changer pourrait donner
    les mêmes octets, donc une signature encore valable. Le premier caractère porte 6 bits : le changer change les octets.
    """
    corps, _, signature = valeur.rpartition(".")
    remplacement = "A" if signature[0] != "A" else "B"
    return f"{corps}.{remplacement}{signature[1:]}"


# --------------------------------------------------------------------------- la pile : HTTP, Docker, bases
class Pile:
    """Adresses et accès de la pile locale ; `env` est le contenu de `.env` (jamais affiché)."""

    def __init__(self, env: dict[str, str], racine: Path = ROOT) -> None:
        self.env = env
        self.racine = racine
        self.passerelle = f"http://127.0.0.1:{env.get('GATEWAY_PORT', '8000')}"
        self.collecte = f"http://127.0.0.1:{env.get('COLLECTE_PORT', '8001')}"
        self.frontend = f"http://127.0.0.1:{env.get('FRONTEND_PORT', '8080')}"

    def appel(self, methode: str, url: str, corps: object | None = None, jeton_acces: str | None = None,
              brut: bytes | None = None) -> tuple[int, dict | None]:
        donnees = brut if brut is not None else (None if corps is None else json.dumps(corps).encode())
        entetes = {"Content-Type": "application/json"}
        if jeton_acces:
            entetes["Authorization"] = f"Bearer {jeton_acces}"
        requete = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)  # noqa: S310 - adresses locales
        try:
            with urllib.request.urlopen(requete, timeout=20) as reponse:  # noqa: S310 - adresses locales de la pile
                statut, texte = reponse.status, reponse.read()
        except urllib.error.HTTPError as erreur:
            statut, texte = erreur.code, erreur.read()
        except (urllib.error.URLError, TimeoutError, OSError) as erreur:
            return 0, {"erreur_reseau": str(erreur.__class__.__name__)}
        try:
            return statut, json.loads(texte) if texte else None
        except ValueError:
            return statut, None

    def docker(self, *args: str, entree: str | None = None, delai: int = 180) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", *args], cwd=self.racine, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", input=entree, check=False, timeout=delai)

    def psql(self, requete: str) -> list[list[str]]:
        sortie = self.docker("exec", "-T", "postgres", "sh", "-c",
                             'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1', entree=requete)
        if sortie.returncode:
            raise Echec(f"psql a échoué : {sortie.stderr.strip()[:200]}")
        return [ligne.split("|") for ligne in sortie.stdout.splitlines() if ligne]

    def mongo(self, expression: str) -> str:
        sortie = self.docker("exec", "-T", "mongo", "sh", "-c",
                             'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
                             '--authenticationDatabase admin "$MONGO_DB" --eval "$0"', expression)
        if sortie.returncode:
            raise Echec(f"mongosh a échoué : {sortie.stderr.strip()[:200]}")
        return sortie.stdout.strip()

    def creer_compte(self, nom: str, mot_de_passe: str) -> str:
        """Crée le compte par la commande de l'application (le mot de passe passe par l'entrée standard, pas par la ligne de commande)."""
        sortie = self.docker("exec", "-T", "traitement", "python", "-m", "app.cli", "create-user", nom, "--role", ROLE,
                             entree=f"{mot_de_passe}\n{mot_de_passe}\n")
        if sortie.returncode or "Compte créé" not in sortie.stdout:
            raise Echec(f"création du compte refusée : {sortie.stdout.strip()[-120:]}")
        return sortie.stdout.rsplit("identifiant", 1)[-1].strip(" .\n")

    def supprimer_compte(self, nom: str) -> None:
        self.psql(f"DELETE FROM app.users WHERE username = '{nom}';")

    def connexion(self, nom: str, mot_de_passe: str) -> str:
        statut, corps = self.appel("POST", f"{self.passerelle}/api/v1/auth/login", {"username": nom, "password": mot_de_passe})
        if statut != 200 or not corps or "access_token" not in corps:
            raise Echec(f"connexion : HTTP {statut}")
        return corps["access_token"]

    def envoyer(self, mesures: list[dict]) -> list[str]:
        """Publie chaque mesure sur la collecte ; rend le statut de chacune (`ACCEPTED`, `DUPLICATE`)."""
        statuts = []
        for document in mesures:
            statut, corps = self.appel("POST", f"{self.collecte}/api/v1/measurements", document)
            if statut != 202 or not corps:
                raise Echec(f"collecte : HTTP {statut} pour {document['id']}")
            statuts.append(corps.get("status", "?"))
        return statuts

    def ligne_entrepot(self, run_id: str, debut: datetime) -> dict | None:
        lignes = self.psql(
            "SELECT f.vehicle_count, f.flow_veh_per_min, f.average_speed_kmh, f.occupancy_rate, f.max_queue_length_m, "
            "f.sample_count, f.expected_sample_count, f.congestion_state FROM dwh.fact_traffic_window f "
            f"WHERE f.run_id = '{run_id}' AND f.window_size_s = 60 AND f.window_start = '{horodatage(debut)}';")
        if not lignes:
            return None
        noms = ("vehicle_count", "flow_veh_per_min", "average_speed_kmh", "occupancy_rate", "max_queue_length_m",
                "sample_count", "expected_sample_count", "congestion_state")
        return dict(zip(noms, lignes[0], strict=True))

    def attendre_entrepot(self, run_id: str, debut: datetime, delai_s: int) -> dict:
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            ligne = self.ligne_entrepot(run_id, debut)
            if ligne:
                return ligne
            time.sleep(5)
        raise Echec(f"aucune ligne dans dwh.fact_traffic_window après {delai_s} s (run {run_id})")

    def indicateurs(self, run_id: str, jeton_acces: str, base: str | None = None) -> tuple[int, dict | None]:
        return self.appel("GET", f"{base or self.passerelle}/api/v1/indicators?run_id={run_id}&window_size_s=60&limit=20",
                          jeton_acces=jeton_acces)


# --------------------------------------------------------------------------- le contexte partagé par les cas
@dataclass
class Contexte:
    pile: Pile
    run_id: str
    debut: datetime
    nom: str = ""
    mot_de_passe: str = ""
    identifiant: str = ""
    jeton: str = ""
    mesures: list[dict] | None = None
    ligne: dict | None = None
    indicateur: dict | None = None


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise Echec(message)



# --------------------------------------------------------------------------- le navigateur (Playwright, front-end construit)
SPECIFICATION = "e2e/parcours-bout-en-bout.e2e.ts"


def francais(valeur: str) -> str:
    """« 1234.5 » devient « 1 234,5 » : espace entre les milliers, virgule décimale (l'écran du tableau de bord)."""
    entier, _, decimales = valeur.partition(".")
    groupe = f"{int(entier):,}".replace(",", " ")
    return groupe if not decimales else f"{groupe},{decimales}"


def nombre_affiche(valeur: str, decimales: int) -> str:
    """Un nombre de l'API tel que le tableau de bord l'écrit : un nombre fixe de décimales (`formatNumber` du front-end)."""
    return francais(format(arrondir(Decimal(valeur), decimales), "f"))


def lancer_navigateur(c: "Contexte", filtre: str, extra: dict[str, str]) -> str:
    """Joue la spécification Playwright (filtre `-g`) contre le front-end de la pile ; rend la dernière ligne du compte rendu."""
    dossier = c.pile.racine / "frontend"
    lanceur = dossier / "node_modules" / "@playwright" / "test" / "cli.js"
    _exiger(shutil.which("node") is not None and lanceur.is_file(),
            "navigateur non vérifié : Node et « npm ci » dans frontend/ sont nécessaires (Chrome aussi)")
    environnement = {**os.environ, "E2E_BASE_URL": c.pile.frontend, "E2E_USER": c.nom, "E2E_PASSWORD": c.mot_de_passe, **extra}
    sortie = subprocess.run(["node", str(lanceur), "test", SPECIFICATION, "-g", filtre, "--reporter=line"], cwd=dossier, env=environnement,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=240)
    resume = [ligne.strip() for ligne in sortie.stdout.splitlines() if ligne.strip()]
    _exiger(sortie.returncode == 0, "navigateur : " + " | ".join(resume[-4:])[:400])
    _exiger(not any("skipped" in ligne for ligne in resume[-3:]), "navigateur : le test a été ignoré (variables manquantes)")
    return resume[-1] if resume else "ok"


# --------------------------------------------------------------------------- parcours nominal
def n1_compte_et_jeton(c: Contexte) -> str:
    c.nom = f"parcours-{secrets.token_hex(3)}"
    c.mot_de_passe = secrets.token_urlsafe(18)
    c.identifiant = c.pile.creer_compte(c.nom, c.mot_de_passe)
    c.jeton = c.pile.connexion(c.nom, c.mot_de_passe)
    return f"compte {c.nom} ({ROLE}) créé, connexion par la passerelle : jeton reçu"


def n2_donnee_brute(c: Contexte) -> str:
    c.mesures = minute_nominale(c.run_id, c.debut)
    statuts = c.pile.envoyer(c.mesures)
    _exiger(statuts == ["ACCEPTED"] * MESURES_PAR_MINUTE, f"statuts de la collecte : {statuts}")
    nombre = c.pile.mongo(f'db.raw_events.countDocuments({{"data.provenance.run_id": "{c.run_id}"}})')
    _exiger(nombre.endswith(str(MESURES_PAR_MINUTE)), f"copie brute dans MongoDB : {nombre} document(s)")
    return (f"{MESURES_PAR_MINUTE} mesures de {horodatage(c.debut)} acceptées (202 ACCEPTED), "
            f"{nombre} copie(s) dans raw_events, run {c.run_id}")


def n3_entrepot(c: Contexte) -> str:
    c.ligne = c.pile.attendre_entrepot(c.run_id, c.debut, ATTENTE_ENTREPOT_S)
    problemes = ecarts(indicateur_attendu(c.mesures or []), c.ligne)
    _exiger(not problemes, "entrepôt différent du recalcul : " + " ; ".join(problemes))
    return (f"1 ligne dans dwh.fact_traffic_window : {c.ligne['vehicle_count']} véhicules, "
            f"{c.ligne['average_speed_kmh']} km/h, état {c.ligne['congestion_state']}, égale au recalcul des 6 mesures")


def n4_api(c: Contexte) -> str:
    statut, corps = c.pile.indicateurs(c.run_id, c.jeton)
    _exiger(statut == 200 and corps is not None, f"GET /api/v1/indicators : HTTP {statut}")
    items = [i for i in corps["items"] if i["window_start"] == horodatage(c.debut)]
    _exiger(len(items) == 1, f"{len(items)} indicateur(s) pour la fenêtre {horodatage(c.debut)}, 1 attendu")
    c.indicateur = items[0]
    problemes = ecarts(indicateur_attendu(c.mesures or []), c.indicateur)
    _exiger(not problemes, "API différente du recalcul : " + " ; ".join(problemes))
    _exiger(c.indicateur["provenance"]["run_id"] == c.run_id and c.indicateur["provenance"]["source_type"] == "SIMULATED",
            "provenance absente ou changée")
    return f"GET /api/v1/indicators par la passerelle : 200, 1 indicateur, mêmes valeurs que l'entrepôt, provenance SIMULATED"


def n5_proxy_du_frontend(c: Contexte) -> str:
    statut, corps = c.pile.indicateurs(c.run_id, c.jeton, c.pile.frontend)
    _exiger(statut == 200 and corps is not None, f"proxy du front-end : HTTP {statut}")
    _exiger(any(i["indicator_id"] == (c.indicateur or {}).get("indicator_id") for i in corps["items"]),
            "le front-end ne sert pas le même indicateur que la passerelle")
    return "le front-end (nginx, port du tableau de bord) sert le même indicateur : le navigateur le lira par ce chemin"


def n6_navigateur(c: Contexte) -> str:
    indicateur = c.indicateur or {}
    attendu = {
        "run_id": c.run_id,
        "vitesse": f"{nombre_affiche(str(indicateur['average_speed_kmh']), 1)} km/h",
        "vehicules": nombre_affiche(str(indicateur["vehicle_count"]), 0),
        "debit": f"{nombre_affiche(str(indicateur['flow_veh_per_min']), 1)} véh/min",
        "troncon": indicateur["road_segment_id"],
    }
    compte_rendu = lancer_navigateur(c, "affiche la minute", {"E2E_ATTENDU": json.dumps(attendu)})
    return (f"Chrome, front-end sur {c.pile.frontend} : connexion puis écran « exécution {c.run_id} », "
            f"{attendu['vitesse']}, {attendu['vehicules']} véhicules, {attendu['debit']}, tronçon {attendu['troncon']} ({compte_rendu})")


# --------------------------------------------------------------------------- cas d'échec
def e1_donnee_invalide(c: Contexte) -> str:
    refus_avant = int(c.pile.mongo("db.rejects.countDocuments({})") or 0)
    invalide = mesure(c.run_id, c.debut + timedelta(seconds=5 * INTERVALLE_S), -3, 31.0, 0.2, 10.0)
    invalide["id"] = f"{c.run_id}:{CAPTEUR}:invalide"
    statut, corps = c.pile.appel("POST", f"{c.pile.collecte}/api/v1/measurements", invalide)
    _exiger(statut == 422 and corps is not None and corps.get("code") == "VALIDATION_ERROR",
            f"mesure hors contrat : HTTP {statut}, code {(corps or {}).get('code')}")
    absente = c.pile.mongo(f'db.raw_events.countDocuments({{"id": "{invalide["id"]}"}})')
    _exiger(absente.endswith("0"), f"la mesure invalide est dans raw_events : {absente}")
    refus_apres = int(c.pile.mongo("db.rejects.countDocuments({})") or 0)
    _exiger(refus_apres > refus_avant, f"aucun rejet tracé dans MongoDB (avant {refus_avant}, après {refus_apres})")
    futur = mesure(c.run_id, datetime.now(UTC) + timedelta(hours=1), 5, 30.0, 0.2, 10.0)
    _exiger(c.pile.envoyer([futur]) == ["ACCEPTED"], "la mesure du futur est conforme au contrat : la collecte l'accepte")
    delai = time.monotonic() + 60
    while time.monotonic() < delai and int(c.pile.mongo("db.rejects.countDocuments({})") or 0) <= refus_apres:
        time.sleep(3)
    _exiger(int(c.pile.mongo("db.rejects.countDocuments({})") or 0) > refus_apres, "le flux n'a pas refusé la mesure du futur")
    lignes = c.pile.psql(f"SELECT count(*) FROM dwh.fact_traffic_window WHERE run_id = '{c.run_id}' AND window_start > now();")
    _exiger(lignes == [["0"]], f"une fenêtre du futur est dans l'entrepôt : {lignes}")
    return (f"hors contrat : 422 VALIDATION_ERROR, absente de raw_events, rejet tracé (rejects {refus_avant} à {refus_apres}) ; "
            "datée du futur : acceptée par la collecte, refusée par le flux (rejet tracé), aucune ligne dans l'entrepôt")


def e2_jeton_expire(c: Contexte) -> str:
    secret = c.pile.env.get("JWT_SECRET", "")
    _exiger(len(secret) >= 32, "JWT_SECRET absent de .env")
    maintenant = datetime.now(UTC)
    url = f"{c.pile.passerelle}/api/v1/indicators?limit=1"
    constats = []
    for nom, valeur, attendu in (
        ("expiré depuis 1 min", jeton(secret, c.identifiant, ROLE, maintenant - timedelta(minutes=1)), 401),
        ("signature altérée", mal_signe(jeton(secret, c.identifiant, ROLE, maintenant + timedelta(minutes=10))), 401),
        ("absent", None, 401),
        ("valide, expire dans 10 min (témoin)", jeton(secret, c.identifiant, ROLE, maintenant + timedelta(minutes=10)), 200),
    ):
        statut, corps = c.pile.appel("GET", url, jeton_acces=valeur)
        _exiger(statut == attendu, f"jeton {nom} : HTTP {statut}, {attendu} attendu")
        if attendu == 401:
            _exiger("Traceback" not in json.dumps(corps) and secret not in json.dumps(corps), f"réponse bavarde pour le jeton {nom}")
        constats.append(f"{nom} : {statut}")
    direct = f"http://127.0.0.1:{c.pile.env.get('TRAITEMENT_PORT', '8002')}/api/v1/indicators?limit=1"
    statut, _ = c.pile.appel("GET", direct, jeton_acces=jeton(secret, c.identifiant, ROLE, maintenant - timedelta(minutes=1)))
    _exiger(statut == 401, f"jeton expiré, directement sur le service : HTTP {statut}")
    expire = jeton(secret, c.identifiant, ROLE, maintenant - timedelta(minutes=1))
    navigateur = lancer_navigateur(c, "jeton expiré", {"E2E_TOKEN_EXPIRE": expire})
    return ("passerelle : " + " ; ".join(constats) + " ; jeton expiré directement sur le service : 401 ; "
            f"navigateur : retour à la connexion, session effacée, aucune donnée ({navigateur})")


def e3_base_indisponible(c: Contexte) -> str:
    pile = c.pile
    debut2 = c.debut - timedelta(minutes=2)
    run2 = f"{c.run_id}-b"
    mesures2 = minute_nominale(run2, debut2)
    constats = []
    pile.docker("stop", "postgres")
    try:
        statut, corps = pile.appel("GET", f"{pile.passerelle}/api/v1/indicators?limit=1", jeton_acces=c.jeton)
        texte = json.dumps(corps)
        _exiger(statut == 503 and (corps or {}).get("code") == "UPSTREAM_UNAVAILABLE", f"API sans base : HTTP {statut}, {texte[:120]}")
        _exiger(not any(mot in texte.lower() for mot in ("svc_", "password", "postgresql", "traceback")), "la réponse 503 donne des détails techniques")
        constats.append("API : 503 UPSTREAM_UNAVAILABLE sans détail")
        statuts = pile.envoyer(mesures2)
        _exiger(statuts == ["ACCEPTED"] * MESURES_PAR_MINUTE, f"collecte pendant la panne : {statuts}")
        constats.append("collecte pendant la panne : 6 mesures acceptées (elle ne dépend pas de PostgreSQL)")
    finally:
        pile.docker("start", "postgres")
    _attendre_api(pile, c.jeton)
    constats.append("PostgreSQL redémarré : l'API répond de nouveau 200")
    ligne = pile.attendre_entrepot(run2, debut2, ATTENTE_REPRISE_S)
    problemes = ecarts(indicateur_attendu(mesures2), ligne)
    _exiger(not problemes, "entrepôt après la reprise différent du recalcul : " + " ; ".join(problemes))
    constats.append("les mesures reçues pendant la panne sont dans l'entrepôt, égales au recalcul (rien perdu)")
    return " ; ".join(constats)


def _attendre_api(pile: Pile, jeton_acces: str) -> None:
    fin = time.monotonic() + ATTENTE_REPRISE_S
    while time.monotonic() < fin:
        if pile.appel("GET", f"{pile.passerelle}/api/v1/indicators?limit=1", jeton_acces=jeton_acces)[0] == 200:
            return
        time.sleep(3)
    raise Echec(f"l'API ne répond pas 200 {ATTENTE_REPRISE_S} s après le redémarrage de PostgreSQL")


# --------------------------------------------------------------------------- orchestration
CAS: tuple[tuple[str, str, Callable[[Contexte], str]], ...] = (
    ("N1", "Compte et jeton", n1_compte_et_jeton),
    ("N2", "Donnée brute : collecte, bus, copie MongoDB", n2_donnee_brute),
    ("N3", "Entrepôt : le flux et le pipeline écrivent la fenêtre", n3_entrepot),
    ("N4", "API : lecture par la passerelle, valeurs recalculées", n4_api),
    ("N5", "Tableau de bord : le front-end sert la même donnée", n5_proxy_du_frontend),
    ("N6", "Tableau de bord : un navigateur affiche la donnée", n6_navigateur),
    ("E1", "Donnée invalide", e1_donnee_invalide),
    ("E2", "Jeton expiré", e2_jeton_expire),
    ("E3", "Base indisponible", e3_base_indisponible),
)
NOMINAUX = ("N1", "N2", "N3", "N4", "N5", "N6")


def executer(pile: Pile, ids: tuple[str, ...] | None = None, afficher: Callable[[Resultat], None] = lambda r: None,
             maintenant: datetime | None = None) -> list[Resultat]:
    """Joue les cas dans l'ordre. Un cas dont un prérequis a échoué est signalé « non joué », pas ignoré."""
    maintenant = maintenant or datetime.now(UTC)
    choisis = [cas for cas in CAS if ids is None or cas[0] in ids]
    contexte = Contexte(pile, f"cld13-{secrets.token_hex(3)}", debut_de_minute_passee(maintenant))
    resultats: list[Resultat] = []
    nominal_ok = True
    try:
        for identifiant, titre, fonction in choisis:
            if identifiant in NOMINAUX[1:] and not nominal_ok:
                resultat = Resultat(identifiant, titre, False, "non joué : une étape précédente du parcours nominal a échoué")
            else:
                resultat = _jouer(identifiant, titre, fonction, contexte)
            if identifiant in NOMINAUX and not resultat.ok:
                nominal_ok = False
            resultats.append(resultat)
            afficher(resultat)
    finally:
        if contexte.nom:
            try:
                pile.supprimer_compte(contexte.nom)
            except Echec:
                pass
    return resultats


def _jouer(identifiant: str, titre: str, fonction: Callable[[Contexte], str], contexte: Contexte) -> Resultat:
    debut = time.monotonic()
    try:
        ok, preuve = True, fonction(contexte)
    except Echec as erreur:
        ok, preuve = False, str(erreur)
    except Exception as erreur:  # noqa: BLE001 - un cas qui plante est un échec du cas, la suite est quand même jouée
        ok, preuve = False, f"exception {erreur.__class__.__name__} : {erreur}"
    return Resultat(identifiant, titre, ok, preuve, round(time.monotonic() - debut, 1))


def ligne(resultat: Resultat) -> str:
    duree = f" ({resultat.duree_s:g} s)" if resultat.duree_s else ""
    return f"[{'OK' if resultat.ok else 'ÉCHEC'}] {resultat.cas}  {resultat.titre}{duree} : {resultat.preuve}"
