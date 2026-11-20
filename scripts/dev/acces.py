"""Matrice d'accès rôles × ressources et essais d'autorisation et de refus (CLD-18).

`ops/matrice-acces.json` dit, comme une politique IAM, qui peut faire quoi. Ce module compare cette déclaration à ce que la pile
applique **réellement**, par des essais sur les vrais composants :

| Ressource | Qui contrôle | Essais |
|---|---|---|
| API (27 routes des contrats) | La passerelle (rôles `viewer` < `operator` < `admin`), puis chaque service | Chaque route avec chaque sujet (anonyme et trois rôles) : refus 401 ou 403 attendu ou accès attendu |
| PostgreSQL | Un compte de connexion par service | Catalogue complet (tables × privilèges), puis un essai autorisé et un refusé par compte, connecté en tant que ce compte |
| MongoDB | Un utilisateur et un rôle par service | Privilèges de chaque utilisateur contre la matrice, puis un essai autorisé et un refusé par utilisateur |
| Kafka, point d'entrée de la collecte | Rien en local | Écarts connus : constatés et listés, jamais comptés comme des succès |

Aucun essai ne modifie de donnée : les chemins visent des identifiants inexistants, les corps sont vides, les écritures de base
sont des `UPDATE … WHERE false` ou des suppressions d'un identifiant absent. Bibliothèque standard seulement. Les mots de passe sont
lus dans l'environnement des conteneurs ou tirés au hasard (comptes jetables) : jamais affichés.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRICE = ROOT / "ops" / "matrice-acces.json"
ROUTES = ROOT / "gateway" / "routes.json"
TOPICS = ROOT / "contracts" / "topics.json"
SUJETS_API = ("anonyme", "viewer", "operator", "admin")
PRIVILEGES_PG = ("SELECT", "INSERT", "UPDATE", "DELETE")
METHODES_DE_LECTURE = ("GET", "HEAD")
PAUSE_S = 0.07  # la passerelle limite à 20 requêtes par seconde : on reste en dessous
ID_INCONNU = "essai-inconnu"


@dataclass
class Essai:
    """Un essai : ce que la matrice prévoit et ce que la pile a fait."""

    famille: str
    sujet: str
    ressource: str
    operation: str
    attendu: bool  # vrai : accès accordé
    obtenu: bool | None  # None : l'essai n'a pas pu être joué
    detail: str

    @property
    def ok(self) -> bool:
        return self.obtenu is not None and self.obtenu == self.attendu


@dataclass
class Ecart:
    """Un contrôle prévu et absent : constaté, pas un échec du banc."""

    id: str
    libelle: str
    preuve: str


class Erreur(Exception):
    pass


# --------------------------------------------------------------------------- la matrice déclarée
def charger(chemin: Path = MATRICE) -> dict:
    matrice = json.loads(Path(chemin).read_text(encoding="utf-8"))
    roles = matrice["api"]["roles"]
    for ressource in matrice["api"]["ressources"]:
        for cle in ("lecture", "action"):
            if ressource[cle] is not None and ressource[cle] not in roles:
                raise Erreur(f"ressource {ressource['id']} : rôle inconnu {ressource[cle]!r}")
    for compte, droits in matrice["postgres"]["schemas"].items():
        for service, privileges in droits.items():
            if service not in matrice["postgres"]["comptes"] or not set(privileges) <= set(PRIVILEGES_PG):
                raise Erreur(f"schéma {compte} : compte ou privilège inconnu pour {service}")
    for utilisateur, definition in matrice["mongo"]["utilisateurs"].items():
        if not set(definition["droits"]) <= set(matrice["mongo"]["collections"]):
            raise Erreur(f"{utilisateur} : collection hors de la liste déclarée")
    return matrice


def rang(role: str | None, roles: list[str]) -> int:
    """Rang d'un rôle : -1 pour l'anonyme, 0 pour le plus faible."""
    return -1 if role in (None, "anonyme") else roles.index(role)


def acces_attendu(matrice: dict, sujet: str, methode: str, chemin: str) -> tuple[bool, str | None, str]:
    """(accès accordé ?, rôle exigé par la matrice, id de la ressource) pour un sujet sur une route."""
    api = matrice["api"]
    if chemin in api["publiques"]:
        return True, None, "public"
    for ressource in api["ressources"]:
        if any(chemin == p or chemin.startswith(p + "/") for p in ressource["chemins"]):
            exige = ressource["lecture"] if methode in METHODES_DE_LECTURE else ressource["action"]
            if exige is None:
                raise Erreur(f"{methode} {chemin} : la matrice ne prévoit aucune action sur {ressource['id']}")
            return rang(sujet, api["roles"]) >= rang(exige, api["roles"]), exige, ressource["id"]
    raise Erreur(f"{methode} {chemin} : route absente de la matrice")


def chemin_concret(motif: str) -> str:
    """`^/api/v1/alerts/[^/]+/resolve$` devient `/api/v1/alerts/essai-inconnu/resolve` (un identifiant qui n'existe pas)."""
    return motif.strip("^$").replace("\\", "").replace("[^/]+", ID_INCONNU)


def chemin_declare(motif: str) -> str:
    """Le chemin sans identifiant, pour retrouver la ressource : `/api/v1/alerts/[^/]+/resolve` donne `/api/v1/alerts`."""
    return re.split(r"/\[\^/\]\+", motif.strip("^$").replace("\\", ""))[0]


def routes_du_contrat(chemin: Path = ROUTES) -> list[dict]:
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


def verifier_la_matrice_contre_les_contrats(matrice: dict, routes: list[dict]) -> list[str]:
    """Les rôles exigés par les contrats OpenAPI (routes.json, généré) doivent être ceux de la matrice : sinon un des deux ment."""
    ecarts = []
    for route in routes:
        chemin = chemin_declare(route["pattern"])
        _, exige, ressource = acces_attendu(matrice, "admin", route["method"], chemin)
        if exige != route["role"]:
            ecarts.append(f"{route['method']} {chemin} : matrice {exige}, contrats {route['role']}")
    return ecarts


# --------------------------------------------------------------------------- la pile
class Pile:
    def __init__(self, env: dict[str, str], racine: Path = ROOT) -> None:
        self.env, self.racine = env, racine
        self.passerelle = f"http://127.0.0.1:{env.get('GATEWAY_PORT', '8000')}"
        self.ports = {"traitement": env.get("TRAITEMENT_PORT", "8002"), "alerte": env.get("ALERTE_PORT", "8003"),
                      "reponse": env.get("REPONSE_PORT", "8004"), "collecte": env.get("COLLECTE_PORT", "8001")}

    def appel_conclusif(self, methode: str, url: str, jeton: str | None = None, corps: bytes | None = None, delai: float = 15,
                        hors_passerelle: bool = False) -> int:
        """Un appel ; s'il n'est pas concluant (réseau, 429, 5xx d'un service), un second essai après une courte attente."""
        statut = self.appel(methode, url, jeton, corps, delai)
        if classer_http(statut, hors_passerelle) is None:
            time.sleep(1.5)
            statut = self.appel(methode, url, jeton, corps, delai)
        return statut

    def appel(self, methode: str, url: str, jeton: str | None = None, corps: bytes | None = None, delai: float = 15) -> int:
        entetes = {"Content-Type": "application/json"}
        if jeton:
            entetes["Authorization"] = f"Bearer {jeton}"
        requete = urllib.request.Request(url, data=corps, method=methode, headers=entetes)  # noqa: S310 - adresses locales
        for _ in range(4):
            try:
                with urllib.request.urlopen(requete, timeout=delai) as reponse:  # noqa: S310
                    return reponse.status
            except urllib.error.HTTPError as erreur:
                erreur.close()
                if erreur.code != 429:
                    return erreur.code
                time.sleep(1.5)
            except (urllib.error.URLError, TimeoutError, OSError):
                return 0
        return 429

    def docker(self, *args: str, entree: str | None = None, delai: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", *args], cwd=self.racine, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", input=entree, check=False, timeout=delai)

    def psql(self, sql: str, compte: str | None = None, variable: str = "") -> subprocess.CompletedProcess:
        """Une requête SQL ; avec `compte`, la connexion se fait en tant que ce compte, mot de passe lu dans l'environnement du conteneur."""
        if compte:
            commande = f'PGPASSWORD="${variable}" psql -h 127.0.0.1 -U {compte} -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1'
        else:
            commande = 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1'
        return self.docker("exec", "-T", "postgres", "sh", "-c", commande, entree=sql)

    def mongosh(self, script: str, utilisateur: str | None = None, variable: str = "") -> subprocess.CompletedProcess:
        if utilisateur:
            commande = f'mongosh --quiet -u {utilisateur} -p "${variable}" --authenticationDatabase "$MONGO_DB" "$MONGO_DB" --eval "$(cat)"'
        else:
            commande = 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_DB" --eval "$(cat)"'
        return self.docker("exec", "-T", "mongo", "sh", "-c", commande, entree=script)

    def creer_compte(self, nom: str, role: str, mot_de_passe: str) -> None:
        sortie = self.docker("exec", "-T", "traitement", "python", "-m", "app.cli", "create-user", nom, "--role", role,
                             entree=f"{mot_de_passe}\n{mot_de_passe}\n")
        if sortie.returncode or "Compte créé" not in sortie.stdout:
            raise Erreur(f"création du compte {role} refusée : {sortie.stdout.strip()[-120:]}")

    def supprimer_compte(self, nom: str) -> None:
        self.psql(f"DELETE FROM app.users WHERE username = '{nom}';")

    def jeton(self, nom: str, mot_de_passe: str) -> str:
        requete = urllib.request.Request(f"{self.passerelle}/api/v1/auth/login", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"username": nom, "password": mot_de_passe}).encode())  # noqa: S310
        try:
            with urllib.request.urlopen(requete, timeout=15) as reponse:  # noqa: S310
                return json.load(reponse)["access_token"]
        except (urllib.error.URLError, KeyError, ValueError) as erreur:
            raise Erreur(f"connexion de {nom} impossible ({erreur.__class__.__name__})") from erreur


def classer_http(statut: int, hors_passerelle: bool = False) -> bool | None:
    """Vrai : la requête a atteint le service (accès accordé) ; faux : refusée ; None : essai raté (réseau, limitation de débit)."""
    if statut in (401, 403) or (hors_passerelle and statut == 404):
        return False
    return None if statut in (0, 429) or statut >= 502 else True


# --------------------------------------------------------------------------- API : toutes les routes, tous les sujets
def essais_api(pile: Pile, matrice: dict, jetons: dict[str, str], routes: list[dict], pause: Callable[[float], None] = time.sleep) -> list[Essai]:
    essais = []
    for route in routes:
        chemin = chemin_concret(route["pattern"])
        for sujet in SUJETS_API:
            attendu, exige, ressource = acces_attendu(matrice, sujet, route["method"], chemin_declare(route["pattern"]))
            statut = pile.appel_conclusif(route["method"], f"{pile.passerelle}{chemin}", jetons.get(sujet),
                                None if route["method"] in METHODES_DE_LECTURE else b"{}", delai=4 if "stream" in chemin else 15)
            essais.append(Essai("api", sujet, ressource, f"{route['method']} {chemin_declare(route['pattern'])}{'/…' if chemin != chemin_declare(route['pattern']) else ''}",
                                attendu, classer_http(statut), f"HTTP {statut}, rôle exigé : {exige or 'aucun'}"))
            pause(PAUSE_S)
    # Le dépôt des mesures n'est pas exposé par la passerelle : refusé (404) pour tous, administrateur compris.
    for sujet in SUJETS_API:
        statut = pile.appel_conclusif("POST", f"{pile.passerelle}/api/v1/measurements", jetons.get(sujet), b"{}", hors_passerelle=True)
        essais.append(Essai("api", sujet, "mesures (dépôt interne)", "POST /api/v1/measurements", False, classer_http(statut, hors_passerelle=True),
                            f"HTTP {statut} : la passerelle ne l'expose pas"))
        pause(PAUSE_S)
    return essais


def essais_services_directs(pile: Pile, jetons: dict[str, str], pause: Callable[[float], None] = time.sleep) -> list[Essai]:
    """Défense en profondeur : chaque service contrôle lui-même le jeton, sans la passerelle (qui n'est qu'une première porte)."""
    cas = (("traitement", "GET", "/api/v1/indicators", "viewer", "GET /api/v1/users", "/api/v1/users", "viewer"),
           ("alerte", "GET", "/api/v1/alerts", "viewer", "POST /api/v1/alerts/…/acknowledge", f"/api/v1/alerts/{ID_INCONNU}/acknowledge", "viewer"),
           ("reponse", "GET", "/api/v1/signals", "viewer", "POST /api/v1/signals/…/commands", f"/api/v1/signals/{ID_INCONNU}/commands", "viewer"))
    essais = []
    for service, methode, chemin, sujet, operation, chemin_refuse, _ in cas:
        base = f"http://127.0.0.1:{pile.ports[service]}"
        for libelle, jeton, appel_methode, appel_chemin, attendu, texte in (
            (f"anonyme sur {methode} {chemin}", None, methode, chemin, False, "sans jeton"),
            (f"{sujet} sur {methode} {chemin}", jetons[sujet], methode, chemin, True, "jeton viewer, lecture"),
            (f"{sujet} sur {operation}", jetons[sujet], "GET" if "users" in operation else "POST", chemin_refuse, False, "jeton viewer, rôle trop faible"),
        ):
            statut = pile.appel_conclusif(appel_methode, f"{base}{appel_chemin}", jeton, None if appel_methode == "GET" else b"{}")
            essais.append(Essai("service direct", "anonyme" if jeton is None else sujet, service, libelle, attendu, classer_http(statut), f"HTTP {statut}, {texte}"))
            pause(PAUSE_S)
    return essais


# --------------------------------------------------------------------------- PostgreSQL
SQL_CATALOGUE = """
SELECT 'P|' || r.rolname || '|' || n.nspname || '|' || p.priv || '|' || count(*) FILTER (WHERE has_table_privilege(r.rolname, c.oid, p.priv)) || '|' || count(*)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN (VALUES %(valeurs)s) r(rolname)
CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) p(priv)
WHERE n.nspname IN ('app', 'dwh', 'alertes', 'ops') AND c.relkind IN ('r', 'v', 'm')
GROUP BY r.rolname, n.nspname, p.priv ORDER BY 1;
SELECT 'A|' || rolname || '|' || rolsuper || '|' || rolcreatedb || '|' || rolcreaterole || '|' || rolbypassrls || '|' || rolcanlogin FROM pg_roles WHERE rolname IN (%(liste)s);
SELECT 'C|' || r.rolname || '|' || n.nspname || '|' || has_schema_privilege(r.rolname, n.oid, 'CREATE')
FROM pg_namespace n CROSS JOIN (VALUES %(valeurs)s) r(rolname) WHERE n.nspname IN ('app', 'dwh', 'alertes', 'ops') ORDER BY 1;
"""


def lire_catalogue_pg(texte: str) -> dict:
    catalogue: dict = {"privileges": {}, "administration": {}, "creation": {}}
    for ligne in texte.splitlines():
        etiquette, _, reste = ligne.partition("|")
        champs = reste.split("|")
        if etiquette == "P":
            compte, schema, privilege, avec, total = champs
            catalogue["privileges"][(compte, schema, privilege)] = (int(avec), int(total))
        elif etiquette == "A":
            catalogue["administration"][champs[0]] = [v == "true" or v == "t" for v in champs[1:]]
        elif etiquette == "C":
            catalogue["creation"][(champs[0], champs[1])] = champs[2] in ("t", "true")
    return catalogue


def comparer_catalogue_pg(matrice: dict, catalogue: dict) -> list[Essai]:
    """Chaque (compte, schéma, privilège) : tous les objets du schéma ou aucun, selon la matrice. Un droit partiel est un écart."""
    essais = []
    declare = matrice["postgres"]["schemas"]
    for compte in matrice["postgres"]["comptes"]:
        for schema, droits in declare.items():
            for privilege in PRIVILEGES_PG:
                attendu = privilege in droits.get(compte, [])
                avec, total = catalogue["privileges"].get((compte, schema, privilege), (0, 0))
                obtenu = None if total == 0 else (avec == total if avec in (0, total) else None)
                detail = f"{avec} table(s) sur {total}" + (" : droit partiel" if avec not in (0, total) else "")
                essais.append(Essai("postgres (catalogue)", compte, f"{schema}.*", privilege, attendu, obtenu, detail))
    for compte in matrice["postgres"]["comptes"]:
        drapeaux = catalogue["administration"].get(compte)
        essais.append(Essai("postgres (catalogue)", compte, "administration", "SUPERUSER, CREATEDB, CREATEROLE, BYPASSRLS", False,
                            None if drapeaux is None else any(drapeaux[:4]), "aucun droit d'administration" if drapeaux and not any(drapeaux[:4]) else f"drapeaux {drapeaux}"))
        for schema in declare:
            attendu = compte == "svc_app" and schema == "app"
            essais.append(Essai("postgres (catalogue)", compte, f"{schema}", "CREATE (objets)", attendu, catalogue["creation"].get((compte, schema)), "droit de créer dans le schéma"))
    return essais


def objet_cible(requete: str) -> str:
    """La table ou la vue visée par une requête d'essai (`dwh.v_indicator`)."""
    trouve = re.search(r"\b(?:app|dwh|alertes|ops)\.\w+", requete)
    return trouve.group(0) if trouve else "?"


def essais_postgres(pile: Pile, matrice: dict) -> list[Essai]:
    comptes = list(matrice["postgres"]["comptes"])
    sql = SQL_CATALOGUE.replace("%(valeurs)s", ", ".join(f"('{c}')" for c in comptes)).replace("%(liste)s", ", ".join(f"'{c}'" for c in comptes))
    sortie = pile.psql(sql)
    if sortie.returncode:
        raise Erreur(f"catalogue PostgreSQL illisible : {(sortie.stderr or sortie.stdout).strip()[-200:]}")
    essais = comparer_catalogue_pg(matrice, lire_catalogue_pg(sortie.stdout))
    variables = {"svc_app": "PG_PASSWORD_APP", "svc_traitement": "PG_PASSWORD_TRAITEMENT", "svc_alerte": "PG_PASSWORD_ALERTE", "svc_lecture": "PG_PASSWORD_LECTURE"}
    for compte, requetes in matrice["postgres"]["essais"].items():
        for cle, attendu in (("autorise", True), ("refuse", False)):
            execution = pile.psql(requetes[cle] + ";", compte=compte, variable=variables[compte])
            refuse = "permission denied" in execution.stderr
            obtenu = (not refuse) if (execution.returncode == 0 or refuse) else None
            detail = "permission denied" if refuse else ("exécutée" if execution.returncode == 0 else f"autre erreur : {execution.stderr.strip()[-90:]}")
            essais.append(Essai("postgres (essai réel)", compte, objet_cible(requetes[cle]), requetes[cle][:70], attendu, obtenu, detail))
    return essais


# --------------------------------------------------------------------------- MongoDB
JS_CATALOGUE = """
const sortie = { utilisateurs: {}, collections: db.getCollectionNames().filter((n) => !n.startsWith('system.')).sort() };
%(utilisateurs)s.forEach((u) => {
  const info = db.runCommand({ usersInfo: u, showPrivileges: true }).users[0];
  const droits = {};
  (info ? info.inheritedPrivileges : []).forEach((p) => { droits[p.resource.collection] = (droits[p.resource.collection] || []).concat(p.actions).sort(); });
  sortie.utilisateurs[u] = droits;
});
print(EJSON.stringify(sortie));
"""


def comparer_catalogue_mongo(matrice: dict, catalogue: dict) -> list[Essai]:
    essais = []
    declare = matrice["mongo"]
    for utilisateur, definition in declare["utilisateurs"].items():
        reel = catalogue["utilisateurs"].get(utilisateur, {})
        for collection in declare["collections"]:
            for action in ("find", "insert", "update", "remove"):
                attendu = action in definition["droits"].get(collection, [])
                essais.append(Essai("mongo (catalogue)", utilisateur, collection, action, attendu, action in reel.get(collection, []),
                                    f"droits réels : {', '.join(reel.get(collection, [])) or 'aucun'}"))
    inconnues = sorted(set(catalogue["collections"]) - set(declare["collections"]))
    if inconnues:
        essais.append(Essai("mongo (catalogue)", "—", ", ".join(inconnues), "collection absente de la matrice", False, True, "à ajouter à ops/matrice-acces.json"))
    return essais


def essais_mongo(pile: Pile, matrice: dict) -> list[Essai]:
    utilisateurs = json.dumps(list(matrice["mongo"]["utilisateurs"]))
    sortie = pile.mongosh(JS_CATALOGUE.replace("%(utilisateurs)s", utilisateurs))
    ligne = next((x for x in reversed(sortie.stdout.splitlines()) if x.startswith("{")), None)
    if sortie.returncode or ligne is None:
        raise Erreur(f"catalogue MongoDB illisible : {(sortie.stderr or sortie.stdout).strip()[-200:]}")
    essais = comparer_catalogue_mongo(matrice, json.loads(ligne))
    for utilisateur, requetes in matrice["mongo"]["essais"].items():
        variable = matrice["mongo"]["utilisateurs"][utilisateur]["variable"]
        for cle, attendu in (("autorise", True), ("refuse", False)):
            script = f"try {{ {requetes[cle]}; print('RESULTAT OK'); }} catch (e) {{ print('RESULTAT ERR ' + e.codeName); }}"
            execution = pile.mongosh(script, utilisateur=utilisateur, variable=variable)
            texte = execution.stdout
            refuse = "RESULTAT ERR Unauthorized" in texte
            obtenu = (not refuse) if ("RESULTAT OK" in texte or refuse) else None
            essais.append(Essai("mongo (essai réel)", utilisateur, requetes[cle].split(".")[1], requetes[cle][:70], attendu, obtenu,
                                "Unauthorized" if refuse else ("exécutée" if "RESULTAT OK" in texte else f"autre résultat : {texte.strip()[-90:]}")))
    return essais


# --------------------------------------------------------------------------- écarts connus
def ecarts_connus(pile: Pile, matrice: dict) -> list[Ecart]:
    ecarts = []
    sujets = json.loads(TOPICS.read_text(encoding="utf-8"))["topics"]
    declares = sum(len(t["producers"]) + len(t["consumers"]) for t in sujets.values())
    acl = pile.docker("exec", "-T", "kafka", "sh", "-c", "/opt/kafka/bin/kafka-acls.sh --bootstrap-server kafka:9092 --list 2>&1 | tail -3")
    texte = acl.stdout.strip().replace("\n", " ")
    ecarts.append(Ecart("kafka", f"Kafka : {len(sujets)} sujets, {declares} droits de production ou de consommation déclarés dans contracts/topics.json, aucun appliqué",
                        f"`kafka-acls --list` : {texte[:200] or 'aucune sortie'}"))
    for entree in matrice["points_d_entree_sans_controle"]:
        statut = pile.appel(entree["methode"], f"http://127.0.0.1:{pile.ports['collecte']}{entree['chemin']}", None, b"{}")
        ecarts.append(Ecart(entree["id"], entree["libelle"] + " : accessible sans jeton depuis le poste",
                            f"{entree['methode']} sans jeton : HTTP {statut} ({'validation du corps atteinte : aucun contrôle d’accès devant' if statut in (400, 422) else 'inattendu'})"))
    return ecarts


# --------------------------------------------------------------------------- orchestration
def executer(pile: Pile, matrice: dict | None = None, routes: list[dict] | None = None, afficher: Callable[[str], None] = print,
             pause: Callable[[float], None] = time.sleep) -> tuple[list[Essai], list[Ecart], list[str]]:
    """Joue tous les essais. Rend (essais, écarts connus, incohérences entre la matrice et les contrats)."""
    matrice = matrice or charger()
    routes = routes or routes_du_contrat()
    incoherences = verifier_la_matrice_contre_les_contrats(matrice, routes)
    comptes: dict[str, tuple[str, str]] = {}
    essais: list[Essai] = []
    try:
        for role in matrice["api"]["roles"]:
            nom, mot_de_passe = f"acces-{role}-{secrets.token_hex(3)}", secrets.token_urlsafe(18)
            pile.creer_compte(nom, role, mot_de_passe)
            comptes[role] = (nom, mot_de_passe)
        jetons = {role: pile.jeton(nom, mot_de_passe) for role, (nom, mot_de_passe) in comptes.items()}
        afficher(f"API : {len(routes)} routes × 4 sujets, par la passerelle…")
        essais += essais_api(pile, matrice, jetons, routes, pause)
        afficher("API : un essai direct sur chaque service…")
        essais += essais_services_directs(pile, jetons, pause)
        afficher("PostgreSQL : catalogue des droits et essais réels…")
        essais += essais_postgres(pile, matrice)
        afficher("MongoDB : droits des utilisateurs et essais réels…")
        essais += essais_mongo(pile, matrice)
        ecarts = ecarts_connus(pile, matrice)
    finally:
        for nom, _ in comptes.values():
            try:
                pile.supprimer_compte(nom)
            except Exception:  # noqa: BLE001 - le nettoyage ne masque pas l'erreur d'origine
                pass
    return essais, ecarts, incoherences


def accord_interdit(essais: list[Essai]) -> list[Essai]:
    """Le cas grave : un accès que la matrice interdit et que la pile a ACCORDÉ. Le critère de CLD-18 est que cette liste soit vide."""
    return [e for e in essais if not e.attendu and e.obtenu is True]


def refus_inattendu(essais: list[Essai]) -> list[Essai]:
    """L'inverse, moins grave (disponibilité, pas sécurité) : un accès prévu par la matrice et refusé ou non concluant."""
    return [e for e in essais if e.attendu and not e.ok]


def resume_par_famille(essais: list[Essai]) -> list[tuple[str, int, int, int, int]]:
    """(famille, accès attendus et obtenus, accès attendus, refus attendus et obtenus, refus attendus)."""
    lignes = []
    for famille in dict.fromkeys(e.famille for e in essais):
        groupe = [e for e in essais if e.famille == famille]
        autorises = [e for e in groupe if e.attendu]
        refuses = [e for e in groupe if not e.attendu]
        lignes.append((famille, sum(e.ok for e in autorises), len(autorises), sum(e.ok for e in refuses), len(refuses)))
    return lignes


def exemples_par_sujet(essais: list[Essai], familles: tuple[str, ...], exemples: dict[str, dict[str, str]] | None = None
                       ) -> dict[str, tuple[Essai | None, Essai | None]]:
    """Pour chaque sujet : un essai autorisé et un essai refusé. Ceux que la matrice nomme (`api.exemples`) quand ils existent, sinon les premiers."""
    sujets: dict[str, tuple[Essai | None, Essai | None]] = {}
    for essai in essais:
        if not essai.famille.startswith(familles):
            continue
        autorise, refuse = sujets.get(essai.sujet, (None, None))
        voulu = (exemples or {}).get(essai.sujet, {}).get("autorise" if essai.attendu else "refuse")
        choisi = voulu is None or essai.operation == voulu
        if essai.attendu and autorise is None and choisi:
            autorise = essai
        if not essai.attendu and refuse is None and choisi:
            refuse = essai
        sujets[essai.sujet] = (autorise, refuse)
    return sujets
