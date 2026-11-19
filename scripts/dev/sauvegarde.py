"""Sauvegarde planifiée et restauration vérifiée de PostgreSQL et de MongoDB (CLD-15).

Trois idées, chacune testée :

1. **Conserver par paliers** (`a_conserver`) : tout ce qui date de moins de 24 h, puis une sauvegarde par jour pendant 7 jours,
   une par semaine pendant 4 semaines, une par mois pendant 3 mois. La plus récente n'est jamais supprimée.
2. **Un manifeste par sauvegarde** : empreinte SHA-256 du fichier et, pour chaque table ou collection, le nombre de lignes et
   une somme de contrôle de leur contenu, relevés **avant et après** la sauvegarde (si la base a bougé entre les deux, la
   sauvegarde n'est pas vérifiable : elle est refusée et refaite). Plus la structure (index, droits, validateurs).
3. **Restaurer dans un projet Docker isolé** (`compose.restauration.yml`) : deux serveurs neufs, réseau interne, aucun port,
   mots de passe tirés au hasard. La restauration y est comparée au manifeste (totaux identiques) puis essayée comme le ferait
   un service : lecture par le rôle de lecture, refus d'un document invalide par le validateur de MongoDB.

La logique est ici ; `dev.py sauvegarde`, `restauration`, `sauvegarde-liste` et `sauvegarde-planifier` ne font que l'appeler.
Bibliothèque standard seulement. Les mots de passe de l'environnement isolé ne sont ni affichés ni écrits.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ISOLE = "compose.restauration.yml"
BASE_RESTAUREE = "novaria_restauree"
SCHEMAS_PG = ("app", "dwh", "alertes", "ops")
POLITIQUE = {"recentes_h": 24, "jours": 7, "semaines": 4, "mois": 3}
NOM_FICHIER = re.compile(r"^(?P<base>[A-Za-z0-9]+)_(?P<ts>\d{8}T\d{6}Z)\.(?P<extension>dump|archive\.gz)$")
SOUS_DOSSIER = {"postgres": "postgres", "mongo": "mongo"}
EXTENSION = {"postgres": ".dump", "mongo": ".archive.gz"}
SERVICE_SAUVEGARDE = {"postgres": "backup-postgres", "mongo": "backup-mongo"}
VERSION_MANIFESTE = 1


class Echec(Exception):
    """Une vérification n'est pas satisfaite ; le message est la preuve de l'échec."""


@dataclass
class Resultat:
    cas: str
    titre: str
    ok: bool
    preuve: str
    duree_s: float = 0.0


# --------------------------------------------------------------------------- conservation par paliers
def horodatage_du_fichier(nom: str) -> datetime | None:
    trouve = NOM_FICHIER.match(nom)
    return None if not trouve else datetime.strptime(trouve["ts"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def a_conserver(sauvegardes: dict[str, datetime], maintenant: datetime, politique: dict[str, int] | None = None) -> set[str]:
    """Les noms à garder. Paliers : récentes (toutes), puis la dernière de chaque jour, semaine ISO et mois dans leur fenêtre."""
    politique = {**POLITIQUE, **(politique or {})}
    ordre = sorted(sauvegardes.items(), key=lambda element: element[1], reverse=True)
    gardees: set[str] = {nom for nom, instant in ordre[:1]}  # la plus récente est toujours gardée
    gardees |= {nom for nom, instant in ordre if instant >= maintenant - timedelta(hours=politique["recentes_h"])}
    paliers = (
        (lambda t: t.date(), maintenant.date() - timedelta(days=politique["jours"] - 1), lambda t: t.date()),
        (lambda t: t.isocalendar()[:2], maintenant - timedelta(weeks=politique["semaines"]), lambda t: t),
        (lambda t: (t.year, t.month), maintenant - timedelta(days=31 * politique["mois"]), lambda t: t),
    )
    for cle, debut, comparable in paliers:
        vus: set = set()
        for nom, instant in ordre:  # du plus récent au plus ancien : le premier rencontré d'un groupe est le dernier du groupe
            if comparable(instant) >= debut and cle(instant) not in vus:
                vus.add(cle(instant))
                gardees.add(nom)
    return gardees


def lister(base: str, dossier: Path) -> dict[str, datetime]:
    sous = Path(dossier) / SOUS_DOSSIER[base]
    if not sous.is_dir():
        return {}
    return {f.name: t for f in sous.iterdir() if f.name.endswith(EXTENSION[base]) and (t := horodatage_du_fichier(f.name))}


def supprimer(base: str, dossier: Path, nom: str) -> None:
    sous = Path(dossier) / SOUS_DOSSIER[base]
    for fichier in (sous / nom, sous / f"{nom}.counts", sous / f"{nom}.manifest.json"):
        fichier.unlink(missing_ok=True)


def appliquer_la_conservation(base: str, dossier: Path, maintenant: datetime, politique: dict[str, int] | None = None,
                              simuler: bool = False) -> list[str]:
    existantes = lister(base, dossier)
    supprimees = sorted(set(existantes) - a_conserver(existantes, maintenant, politique))
    if not simuler:
        for nom in supprimees:
            supprimer(base, dossier, nom)
    return supprimees


# --------------------------------------------------------------------------- manifeste
def empreinte(fichier: Path) -> str:
    condensat = hashlib.sha256()
    with open(fichier, "rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


def chemin_manifeste(fichier: Path) -> Path:
    return fichier.with_name(fichier.name + ".manifest.json")


def ecrire_manifeste(fichier: Path, base: str, releve: dict, instant: datetime) -> dict:
    manifeste = {"version": VERSION_MANIFESTE, "base": base, "fichier": fichier.name, "taille": fichier.stat().st_size,
                 "sha256": empreinte(fichier), "cree_le": instant.strftime("%Y-%m-%dT%H:%M:%SZ"), "releve": releve}
    cible = chemin_manifeste(fichier)
    temporaire = cible.with_name(cible.name + ".part")
    temporaire.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporaire.replace(cible)
    return manifeste


def lire_manifeste(fichier: Path) -> dict:
    chemin = chemin_manifeste(fichier)
    if not chemin.is_file():
        raise Echec(f"manifeste absent : {chemin.name} (sauvegarde faite sans `dev.py sauvegarde` : totaux invérifiables)")
    return json.loads(chemin.read_text(encoding="utf-8"))


def derniere_sauvegarde(base: str, dossier: Path) -> Path | None:
    existantes = lister(base, dossier)
    return None if not existantes else Path(dossier) / SOUS_DOSSIER[base] / max(existantes, key=existantes.get)


# --------------------------------------------------------------------------- comparaison des relevés
def comparer(attendu: dict, restaure: dict) -> list[str]:
    """Les écarts entre le relevé de la sauvegarde et celui de la restauration, nommés un par un (vide = identiques)."""
    ecarts: list[str] = []
    for rubrique in ("tables", "collections"):
        a, r = attendu.get(rubrique, {}), restaure.get(rubrique, {})
        for nom in sorted(set(a) | set(r)):
            if nom not in r:
                ecarts.append(f"{nom} : absente de la restauration")
            elif nom not in a:
                ecarts.append(f"{nom} : absente de la sauvegarde")
            else:
                if a[nom]["lignes"] != r[nom]["lignes"]:
                    ecarts.append(f"{nom} : {a[nom]['lignes']} lignes à la sauvegarde, {r[nom]['lignes']} restaurées")
                if a[nom]["controle"] != r[nom]["controle"]:
                    ecarts.append(f"{nom} : contenu différent (somme de contrôle {a[nom]['controle']} contre {r[nom]['controle']})")
                for cle in ("index", "validateur"):
                    if a[nom].get(cle) != r[nom].get(cle):
                        ecarts.append(f"{nom} : {cle} différent")
    for cle in ("totaux", "indexes", "vues", "droits", "contraintes_non_validees"):
        if attendu.get(cle) != restaure.get(cle):
            ecarts.append(f"{cle} : {json.dumps(attendu.get(cle), ensure_ascii=False)[:160]} contre {json.dumps(restaure.get(cle), ensure_ascii=False)[:160]}")
    return ecarts


def memes_donnees(a: dict, b: dict) -> bool:
    """Deux relevés prennent-ils la même photo des données (lignes et sommes de contrôle) ? Utilisé avant et après la sauvegarde."""
    return all(a.get(rubrique) == b.get(rubrique) for rubrique in ("tables", "collections", "totaux"))


# --------------------------------------------------------------------------- relevés (SQL et JavaScript lus par les serveurs)
SQL_RELEVE = """
SET timezone TO 'UTC';
SET extra_float_digits TO 3;
SELECT 'T|' || t.table_schema || '.' || t.table_name || '|' || (xpath('/row/n/text()', x))[1]::text || '|' || (xpath('/row/c/text()', x))[1]::text
FROM information_schema.tables t,
     LATERAL query_to_xml(format('SELECT count(*) AS n, coalesce(sum(hashtextextended(r::text, 0)::numeric), 0) AS c FROM %I.%I r', t.table_schema, t.table_name), false, true, '') x
WHERE t.table_type = 'BASE TABLE' AND t.table_schema IN ('app', 'dwh', 'alertes', 'ops') ORDER BY 1;
SELECT 'I|' || schemaname || '.' || indexname FROM pg_indexes WHERE schemaname IN ('app', 'dwh', 'alertes', 'ops') ORDER BY 1;
SELECT 'V|' || v.schemaname || '.' || v.viewname || '|' || (xpath('/row/n/text()', x))[1]::text
FROM pg_views v, LATERAL query_to_xml(format('SELECT count(*) AS n FROM %I.%I', v.schemaname, v.viewname), false, true, '') x
WHERE v.schemaname IN ('app', 'dwh', 'alertes', 'ops') ORDER BY 1;
SELECT 'D|' || coalesce(md5(string_agg(r.rolname || ':' || n.nspname || '.' || c.relname || ':' || a.privilege_type, ',' ORDER BY r.rolname COLLATE "C", n.nspname COLLATE "C", c.relname COLLATE "C", a.privilege_type COLLATE "C")), '')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(c.relacl) a JOIN pg_roles r ON r.oid = a.grantee
WHERE n.nspname IN ('app', 'dwh', 'alertes', 'ops') AND c.relkind IN ('r', 'v', 'm', 'S') AND a.grantee <> c.relowner AND r.rolname LIKE 'svc\\_%';
SELECT 'C|' || count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE NOT c.convalidated AND n.nspname IN ('app', 'dwh', 'alertes', 'ops');
SELECT 'S|fenetres|' || count(*) || '|' || coalesce(sum(vehicle_count), 0) || '|' || count(DISTINCT run_id) FROM dwh.fact_traffic_window;
SELECT 'S|comptes|' || count(*) FROM app.users;
SELECT 'S|migrations|' || count(*) FROM ops.schema_migrations;
SHOW server_version;
"""

JS_RELEVE = """
const h = (s) => { let x = 5381; for (let i = 0; i < s.length; i++) { x = ((x << 5) + x + s.charCodeAt(i)) | 0; } return x; };
const sortie = { collections: {}, totaux: {} };
db.getCollectionNames().sort().forEach((n) => {
  let lignes = 0, somme = 0n;
  db.getCollection(n).find().forEach((d) => { lignes++; somme += BigInt(h(EJSON.stringify(d))); });
  const info = db.getCollectionInfos({ name: n })[0] || {};
  const index = db.getCollection(n).getIndexes().map((i) => ({ nom: i.name, cle: i.key, ttl: i.expireAfterSeconds === undefined ? null : i.expireAfterSeconds }));
  index.sort((a, b) => (a.nom < b.nom ? -1 : 1));
  sortie.collections[n] = { lignes, controle: somme.toString(), index, validateur: h(EJSON.stringify((info.options || {}).validator || {})) };
});
const brut = db.raw_events.aggregate([{ $group: { _id: null, n: { $sum: 1 }, vehicules: { $sum: "$data.vehicle_count" } } }]).toArray()[0] || { n: 0, vehicules: 0 };
sortie.totaux = { raw_events: [brut.n, Number(brut.vehicules)], rejets: db.rejects.countDocuments({}) };
sortie.serveur = db.version();
print(EJSON.stringify(sortie));
"""


def lire_releve_pg(texte: str) -> dict:
    """Transforme la sortie de `SQL_RELEVE` (lignes `T|`, `I|`, `V|`, `D|`, `C|`, `S|`) en relevé."""
    releve: dict = {"tables": {}, "indexes": [], "vues": {}, "droits": "", "contraintes_non_validees": 0, "totaux": {}}
    for ligne in texte.splitlines():
        etiquette, _, reste = ligne.partition("|")
        if etiquette == "T":
            nom, lignes, controle = reste.split("|")
            releve["tables"][nom] = {"lignes": int(lignes), "controle": controle}
        elif etiquette == "I":
            releve["indexes"].append(reste)
        elif etiquette == "V":
            nom, lignes = reste.split("|")
            releve["vues"][nom] = int(lignes)
        elif etiquette == "D":
            releve["droits"] = reste
        elif etiquette == "C":
            releve["contraintes_non_validees"] = int(reste)
        elif etiquette == "S":
            nom, _, valeurs = reste.partition("|")
            releve["totaux"][nom] = [int(v) for v in valeurs.split("|")]
        elif re.fullmatch(r"\d+(\.\d+)*( \(.*\))?", ligne.strip()):
            releve["serveur"] = ligne.strip()
    return releve


def lire_releve_mongo(texte: str) -> dict:
    """La dernière ligne JSON de la sortie de `JS_RELEVE` (mongosh peut écrire des avertissements avant)."""
    for ligne in reversed(texte.strip().splitlines()):
        if ligne.startswith("{"):
            return json.loads(ligne)
    raise Echec(f"relevé MongoDB illisible : {texte.strip()[-200:]}")


# --------------------------------------------------------------------------- les serveurs : pile de travail ou environnement isolé
class Serveurs:
    """Docker Compose sur un projet : `prefixe` vide pour la pile de travail, `-p … -f …` pour l'environnement isolé."""

    def __init__(self, racine: Path = ROOT, prefixe: tuple[str, ...] = (), service_pg: str = "postgres", service_mongo: str = "mongo",
                 environnement: dict[str, str] | None = None) -> None:
        self.racine, self.prefixe, self.service_pg, self.service_mongo = racine, prefixe, service_pg, service_mongo
        self.environnement = environnement

    def compose(self, *args: str, entree: str | None = None, delai: int = 600, verifier: bool = False) -> subprocess.CompletedProcess:
        import os

        env = None if self.environnement is None else {**os.environ, **self.environnement}
        sortie = subprocess.run(["docker", "compose", *self.prefixe, *args], cwd=self.racine, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", input=entree, check=False, timeout=delai, env=env)
        if verifier and sortie.returncode:
            raise Echec(f"docker compose {' '.join(args[:3])} : {(sortie.stderr or sortie.stdout).strip()[-300:]}")
        return sortie

    def psql(self, sql: str, base: str = '"$POSTGRES_DB"', utilisateur: str = '"$POSTGRES_USER"', delai: int = 300) -> str:
        sortie = self.compose("exec", "-T", self.service_pg, "sh", "-c", f'psql -q -U {utilisateur} -d {base} -At -F "|" -v ON_ERROR_STOP=1',
                              entree=sql, delai=delai)
        if sortie.returncode:
            raise Echec(f"psql : {(sortie.stderr or sortie.stdout).strip()[-300:]}")
        return sortie.stdout

    def mongosh(self, script: str, delai: int = 600) -> str:
        sortie = self.compose("exec", "-T", self.service_mongo, "sh", "-c",
                              'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "$MONGO_DB" --eval "$(cat)"',
                              entree=script, delai=delai)
        if sortie.returncode:
            raise Echec(f"mongosh : {(sortie.stderr or sortie.stdout).strip()[-300:]}")
        return sortie.stdout

    def releve(self, base: str, base_pg: str = '"$POSTGRES_DB"') -> dict:
        if base == "postgres":
            return lire_releve_pg(self.psql(SQL_RELEVE, base=base_pg))
        return lire_releve_mongo(self.mongosh(JS_RELEVE))


# --------------------------------------------------------------------------- sauvegarder
def lancer_la_sauvegarde(serveurs: Serveurs, base: str) -> str:
    """Appelle le script de sauvegarde du dépôt (sans rotation par nombre) ; rend le nom du fichier créé."""
    sortie = serveurs.compose("--profile", "ops", "run", "--rm", "-e", "BACKUP_KEEP=0", SERVICE_SAUVEGARDE[base], "backup", verifier=True)
    trouve = re.search(r"Sauvegarde créée : (\S+)", sortie.stdout)
    if not trouve:
        raise Echec(f"sauvegarde {base} : nom du fichier introuvable dans la sortie : {sortie.stdout.strip()[-200:]}")
    return trouve.group(1)


def sauvegarder_une_base(serveurs: Serveurs, base: str, dossier: Path, tentatives: int = 3, afficher: Callable[[str], None] = print,
                         maintenant: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict:
    """Sauvegarde, écrit le manifeste. Relevé avant et après : si la base a bougé, la sauvegarde est refaite (refusée au bout de `tentatives`)."""
    for essai in range(1, tentatives + 1):
        avant = serveurs.releve(base)
        nom = lancer_la_sauvegarde(serveurs, base)
        apres = serveurs.releve(base)
        fichier = Path(dossier) / SOUS_DOSSIER[base] / nom
        if memes_donnees(avant, apres):
            manifeste = ecrire_manifeste(fichier, base, avant, maintenant())
            afficher(f"  {base} : {nom} ({manifeste['taille']} octets, {len(avant.get('tables') or avant.get('collections'))} "
                     f"{'tables' if base == 'postgres' else 'collections'} relevées, empreinte {manifeste['sha256'][:12]}…)")
            return manifeste
        supprimer(base, dossier, nom)
        afficher(f"  {base} : la base a changé pendant la sauvegarde (essai {essai}/{tentatives}), sauvegarde refusée et refaite")
    raise Echec(f"{base} : la base change trop vite pour produire une sauvegarde vérifiable ({tentatives} essais)")


def sauvegarder(serveurs: Serveurs, dossier: Path = ROOT / "backups", politique: dict[str, int] | None = None,
                afficher: Callable[[str], None] = print, maintenant: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict:
    """Un cycle : sauvegarde des deux bases avec manifeste, puis conservation par paliers."""
    afficher("Sauvegarde :")
    manifestes = {base: sauvegarder_une_base(serveurs, base, dossier, afficher=afficher, maintenant=maintenant) for base in ("postgres", "mongo")}
    supprimees = {base: appliquer_la_conservation(base, dossier, maintenant(), politique) for base in ("postgres", "mongo")}
    for base, noms in supprimees.items():
        for nom in noms:
            afficher(f"  {base} : ancienne sauvegarde supprimée par la politique de conservation : {nom}")
    return {"manifestes": manifestes, "supprimees": supprimees}


# --------------------------------------------------------------------------- restaurer dans l'environnement isolé
class EnvironnementIsole:
    """Un projet Compose jetable : créé à l'entrée, supprimé avec ses volumes à la sortie, même après une erreur."""

    def __init__(self, racine: Path = ROOT, nom_base_mongo: str = "novaria", administrateur_pg: str = "novaria_admin") -> None:
        # Le rôle administrateur porte le même NOM que celui de la pile de travail (pas son mot de passe) : une sauvegarde
        # PostgreSQL cite ce rôle dans ses droits par défaut, et pg_restore échoue s'il n'existe pas.
        self.racine = racine
        self.projet = f"novaria-restauration-{secrets.token_hex(3)}"
        self.environnement = {
            "R_POSTGRES_USER": administrateur_pg, "R_POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            "R_POSTGRES_DB": "novaria", "R_PG_PASSWORD": secrets.token_urlsafe(24),
            "R_MONGO_ROOT_USER": "admin_restauration", "R_MONGO_ROOT_PASSWORD": secrets.token_urlsafe(24),
            "R_MONGO_DB": nom_base_mongo, "R_MONGO_PASSWORD": secrets.token_urlsafe(24),
        }
        self.serveurs = Serveurs(racine, ("-p", self.projet, "-f", COMPOSE_ISOLE), "postgres-restauration", "mongo-restauration", self.environnement)

    def __enter__(self) -> EnvironnementIsole:
        try:
            self.serveurs.compose("up", "-d", "--wait", "--wait-timeout", "180", verifier=True, delai=400)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self.serveurs.compose("down", "-v", "--remove-orphans", delai=180)

    def isolation(self) -> dict:
        """Ce qui prouve l'isolement : réseau interne, aucun port publié, projet distinct de la pile de travail."""
        reseau = subprocess.run(["docker", "network", "inspect", f"{self.projet}_isolee", "--format", "{{.Internal}}"], capture_output=True, text=True,
                                check=False, timeout=60).stdout.strip()
        conteneurs = self.serveurs.compose("ps", "--format", "json").stdout.strip().splitlines()
        ports = [p for ligne in conteneurs for p in (json.loads(ligne).get("Publishers") or []) if p.get("PublishedPort")]
        return {"projet": self.projet, "reseau_interne": reseau == "true", "ports_publies": len(ports), "conteneurs": len(conteneurs)}

    def restaurer(self, base: str, fichier: Path) -> None:
        if base == "postgres":
            self.serveurs.psql(f"CREATE DATABASE {BASE_RESTAUREE};", base="postgres", utilisateur='"$POSTGRES_USER"')
            sortie = self.serveurs.compose("exec", "-T", self.serveurs.service_pg, "sh", "-c",
                                           f'pg_restore --no-owner --exit-on-error -U "$POSTGRES_USER" -d {BASE_RESTAUREE} /backups/postgres/{fichier.name}')
        else:
            # Base vidée d'abord : seules les collections, validateurs et index de la SAUVEGARDE doivent s'y retrouver, pas ceux que
            # le script d'initialisation du dépôt (peut-être plus récent que la pile sauvegardée) y a créés.
            self.serveurs.mongosh("db.dropDatabase()")
            sortie = self.serveurs.compose("exec", "-T", self.serveurs.service_mongo, "sh", "-c",
                                           'mongorestore -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin '
                                           f'--archive=/backups/mongo/{fichier.name} --gzip --quiet --drop --nsInclude "$MONGO_DB.*"')
        if sortie.returncode:
            raise Echec(f"la restauration de {fichier.name} a échoué : {(sortie.stderr or sortie.stdout).strip()[-300:]}")

    def releve(self, base: str) -> dict:
        return self.serveurs.releve(base, base_pg=BASE_RESTAUREE)

    def essais_d_usage_pg(self) -> list[str]:
        """Ce qu'un service ferait : se connecter avec le rôle de lecture et lire la vue de l'API, sans pouvoir y écrire."""
        constats = []
        lecture = self.serveurs.compose("exec", "-T", self.serveurs.service_pg, "sh", "-c",
                                        f'PGPASSWORD="$PG_PASSWORD_LECTURE" psql -q -h 127.0.0.1 -U svc_lecture -d {BASE_RESTAUREE} -At -c "SELECT count(*) FROM dwh.v_indicator"')
        if lecture.returncode or not lecture.stdout.strip().isdigit():
            raise Echec(f"le rôle de lecture ne lit pas dwh.v_indicator : {(lecture.stderr or lecture.stdout).strip()[-200:]}")
        constats.append(f"svc_lecture lit dwh.v_indicator ({lecture.stdout.strip()} lignes)")
        ecriture = self.serveurs.compose("exec", "-T", self.serveurs.service_pg, "sh", "-c",
                                         f'PGPASSWORD="$PG_PASSWORD_LECTURE" psql -q -h 127.0.0.1 -U svc_lecture -d {BASE_RESTAUREE} -At -c "DELETE FROM dwh.fact_traffic_window"')
        if ecriture.returncode == 0:
            raise Echec("le rôle de lecture a pu écrire dans l'entrepôt : droits mal restaurés")
        constats.append("svc_lecture ne peut pas écrire (droits restaurés)")
        return constats

    def essais_d_usage_mongo(self) -> list[str]:
        script = ("try { db.raw_events.insertOne({ invalide: true }); print('ACCEPTE'); } catch (e) { print('REFUSE ' + e.code); }\n"
                  "print('LU ' + db.raw_events.find().limit(1).toArray().length);\n")
        sortie = self.serveurs.mongosh(script)
        if "REFUSE 121" not in sortie:
            raise Echec(f"le validateur de raw_events n'a pas refusé un document invalide : {sortie.strip()[-120:]}")
        return ["le validateur de raw_events refuse un document invalide (code 121)",
                "un document se lit" if "LU 1" in sortie else "collection vide : aucun document à lire"]


def verifier_le_fichier(base: str, fichier: Path) -> dict:
    """Empreinte du fichier comparée à celle du manifeste : détecte une altération entre la sauvegarde et la restauration."""
    if not fichier.is_file():
        raise Echec(f"fichier introuvable : {fichier.name}")
    manifeste = lire_manifeste(fichier)
    if manifeste.get("version") != VERSION_MANIFESTE or manifeste.get("base") != base:
        raise Echec(f"manifeste de {fichier.name} : version ou base inattendue")
    if (reelle := empreinte(fichier)) != manifeste["sha256"]:
        raise Echec(f"{fichier.name} a changé depuis la sauvegarde : empreinte {reelle[:12]}… au lieu de {manifeste['sha256'][:12]}…")
    return manifeste


def verifier_la_restauration(isole: EnvironnementIsole, base: str, fichier: Path, manifeste: dict) -> str:
    isole.restaurer(base, fichier)
    restaure = isole.releve(base)
    ecarts = comparer(manifeste["releve"], restaure)
    if ecarts:
        raise Echec("totaux différents : " + " ; ".join(ecarts[:4]) + (f" (+{len(ecarts) - 4} autres)" if len(ecarts) > 4 else ""))
    usage = isole.essais_d_usage_pg() if base == "postgres" else isole.essais_d_usage_mongo()
    unite = "tables" if base == "postgres" else "collections"
    lignes = sum(t["lignes"] for t in (restaure.get("tables") or restaure.get("collections")).values())
    return (f"{len(restaure.get('tables') or restaure.get('collections'))} {unite} et {lignes} lignes restaurées, lignes et sommes de contrôle "
            f"identiques au manifeste ; {'; '.join(usage)}")


def restaurer_et_verifier(serveurs_travail: Serveurs | None = None, dossier: Path = ROOT / "backups", racine: Path = ROOT,
                          fichiers: dict[str, Path] | None = None, nom_base_mongo: str = "novaria", administrateur_pg: str = "novaria_admin",
                          afficher: Callable[[Resultat], None] = lambda r: None) -> list[Resultat]:
    """Restaure les sauvegardes choisies (les dernières par défaut) dans un projet isolé et en vérifie les totaux."""
    resultats: list[Resultat] = []

    def jouer(cas: str, titre: str, action: Callable[[], str]) -> bool:
        debut = time.monotonic()
        try:
            ok, preuve = True, action()
        except Echec as erreur:
            ok, preuve = False, str(erreur)
        except Exception as erreur:  # noqa: BLE001 - un cas qui plante est un échec du cas
            ok, preuve = False, f"exception {erreur.__class__.__name__} : {erreur}"
        resultat = Resultat(cas, titre, ok, preuve, round(time.monotonic() - debut, 1))
        resultats.append(resultat)
        afficher(resultat)
        return ok

    choisis = {}
    for base in ("postgres", "mongo"):
        fichier = (fichiers or {}).get(base) or derniere_sauvegarde(base, dossier)
        choisis[base] = fichier
    manifestes: dict[str, dict] = {}
    sain = True
    for base, num in (("postgres", "R1"), ("mongo", "R2")):
        def empreinte_ok(base=base) -> str:
            if choisis[base] is None:
                raise Echec(f"aucune sauvegarde {base} dans {dossier} : lancer `dev.py sauvegarde`")
            manifestes[base] = verifier_le_fichier(base, choisis[base])
            m = manifestes[base]
            return f"{choisis[base].name} : {m['taille']} octets, empreinte {m['sha256'][:12]}… conforme au manifeste du {m['cree_le']}"
        sain &= jouer(num, f"Empreinte du fichier {base}", empreinte_ok)
    if not sain:
        return resultats
    isole = EnvironnementIsole(racine, nom_base_mongo, administrateur_pg)
    try:
        with isole:
            jouer("R3", "Environnement isolé", lambda: _constat_isolement(isole))
            jouer("R4", "Restauration PostgreSQL et contrôle des totaux", lambda: verifier_la_restauration(isole, "postgres", choisis["postgres"], manifestes["postgres"]))
            jouer("R5", "Restauration MongoDB et contrôle des totaux", lambda: verifier_la_restauration(isole, "mongo", choisis["mongo"], manifestes["mongo"]))
    except Echec as erreur:
        resultat = Resultat("R3", "Environnement isolé", False, str(erreur))
        resultats.append(resultat)
        afficher(resultat)
    return resultats


def _constat_isolement(isole: EnvironnementIsole) -> str:
    constat = isole.isolation()
    if not constat["reseau_interne"] or constat["ports_publies"] or constat["conteneurs"] < 2:
        raise Echec(f"isolement non prouvé : {constat}")
    return (f"projet {constat['projet']} : {constat['conteneurs']} conteneurs neufs, réseau interne (sans accès extérieur), "
            f"{constat['ports_publies']} port publié, mots de passe tirés au hasard, supprimé à la fin")



# --------------------------------------------------------------------------- contrôles négatifs : le banc sait dire « non »
def _copie_alteree(base: str, dossier: Path, suffixe: str, modifier_octet: bool, modifier_manifeste: Callable[[dict], None] | None = None) -> Path:
    """Une copie de la dernière sauvegarde, datée de 1999 (hors de portée de `derniere_sauvegarde`), avec son manifeste."""
    source = derniere_sauvegarde(base, dossier)
    if source is None:
        raise Echec(f"aucune sauvegarde {base} à copier")
    nom = f"novaria_1999010{suffixe}T000000Z{EXTENSION[base]}"
    copie = source.with_name(nom)
    contenu = bytearray(source.read_bytes())
    if modifier_octet:
        contenu[len(contenu) // 2] ^= 0xFF
    copie.write_bytes(bytes(contenu))
    manifeste = lire_manifeste(source)
    manifeste["fichier"] = nom
    if modifier_manifeste:
        modifier_manifeste(manifeste)
    chemin_manifeste(copie).write_text(json.dumps(manifeste, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
    return copie


def controles_negatifs(dossier: Path = ROOT / "backups", racine: Path = ROOT, nom_base_mongo: str = "novaria", administrateur_pg: str = "novaria_admin",
                       afficher: Callable[[Resultat], None] = lambda r: None) -> list[Resultat]:
    """Prouve que la vérification échoue quand elle le doit. Un cas est « OK » quand la panne injectée a été **détectée**."""
    resultats: list[Resultat] = []
    copies: list[tuple[str, Path]] = []

    def jouer(cas: str, titre: str, action: Callable[[], str]) -> None:
        debut = time.monotonic()
        try:
            ok, preuve = True, action()
        except Echec as erreur:
            ok, preuve = False, f"NON DÉTECTÉ ou autre erreur : {erreur}"
        resultat = Resultat(cas, titre, ok, preuve, round(time.monotonic() - debut, 1))
        resultats.append(resultat)
        afficher(resultat)

    def fichier_altere() -> str:
        copie = _copie_alteree("postgres", dossier, "1", modifier_octet=True)
        copies.append(("postgres", copie))
        try:
            verifier_le_fichier("postgres", copie)
        except Echec as erreur:
            return f"un octet changé dans la copie : {erreur}"
        raise Echec("un fichier altéré a été accepté")

    def total_altere(base: str, suffixe: str, titre: str) -> Callable[[], str]:
        def action() -> str:
            def fausser(manifeste: dict) -> None:
                rubrique = "tables" if base == "postgres" else "collections"
                nom = next(n for n, v in manifeste["releve"][rubrique].items() if v["lignes"] > 0)
                manifeste["releve"][rubrique][nom]["lignes"] += 1
                manifeste["_fausse_table"] = nom
            copie = _copie_alteree(base, dossier, suffixe, modifier_octet=False, modifier_manifeste=fausser)
            copies.append((base, copie))
            manifeste = verifier_le_fichier(base, copie)  # le fichier, lui, est intact : l'empreinte passe
            with EnvironnementIsole(racine, nom_base_mongo, administrateur_pg) as isole:
                try:
                    verifier_la_restauration(isole, base, copie, manifeste)
                except Echec as erreur:
                    return f"{titre} : {erreur}"
            raise Echec("un total faux a été accepté")
        return action

    try:
        jouer("N1", "Fichier PostgreSQL altéré d'un octet", fichier_altere)
        jouer("N2", "Total PostgreSQL faux dans le manifeste", total_altere("postgres", "2", "un total de plus dans le manifeste"))
        jouer("N3", "Total MongoDB faux dans le manifeste", total_altere("mongo", "3", "un total de plus dans le manifeste"))
    finally:
        for base, copie in copies:
            supprimer(base, dossier, copie.name)
    return resultats

# --------------------------------------------------------------------------- planification
def prochain_creneau(maintenant: datetime, heure: str) -> datetime:
    """La prochaine occurrence de HH:MM (heure du poste) strictement après `maintenant`."""
    h, m = (int(x) for x in heure.split(":"))
    candidat = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    return candidat if candidat > maintenant else candidat + timedelta(days=1)


def doit_rattraper(base_derniere: dict[str, datetime | None], maintenant: datetime, age_max_h: int = 24) -> bool:
    """Vrai si une des deux bases n'a aucune sauvegarde de moins de `age_max_h` heures (poste éteint au créneau)."""
    return any(t is None or maintenant - t > timedelta(hours=age_max_h) for t in base_derniere.values())


def planifier(cycle: Callable[[], None], heure: str = "02:00", toutes_les_s: int | None = None, executions: int | None = None,
              sans_rattrapage: bool = False, derniere: Callable[[], dict[str, datetime | None]] = lambda: {},
              horloge: Callable[[], datetime] = lambda: datetime.now().astimezone(), dormir: Callable[[float], None] = time.sleep,
              afficher: Callable[[str], None] = print) -> int:
    """Attend le créneau, lance `cycle`, recommence. Une erreur est journalisée et n'arrête pas le planificateur. Rend le nombre de cycles réussis."""
    reussis = lances = 0

    def lancer(motif: str) -> None:
        nonlocal reussis, lances
        lances += 1
        afficher(f"[{horloge().strftime('%Y-%m-%d %H:%M:%S')}] sauvegarde planifiée ({motif})")
        try:
            cycle()
            reussis += 1
        except Exception as erreur:  # noqa: BLE001 - le planificateur ne doit pas mourir
            afficher(f"  ÉCHEC : {erreur.__class__.__name__} : {erreur}")

    if not sans_rattrapage and toutes_les_s is None and doit_rattraper(derniere(), horloge()):
        lancer("rattrapage : aucune sauvegarde de moins de 24 h")
    while executions is None or lances < executions:
        if toutes_les_s is not None:
            dormir(toutes_les_s)
        else:
            attente = (prochain_creneau(horloge(), heure) - horloge()).total_seconds()
            afficher(f"prochaine sauvegarde à {heure} (dans {int(attente // 3600)} h {int(attente % 3600 // 60)} min)")
            dormir(max(attente, 0))
        lancer("créneau")
    return reussis


def ligne(resultat: Resultat) -> str:
    duree = f" ({resultat.duree_s:g} s)" if resultat.duree_s else ""
    return f"[{'OK' if resultat.ok else 'ÉCHEC'}] {resultat.cas}  {resultat.titre}{duree} : {resultat.preuve}"
