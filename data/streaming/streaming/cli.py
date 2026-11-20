"""Commandes du prototype de flux temps réel (DAT-09) : `python scripts/dev/dev.py flux-proto <commande>`.

    build      construit l'image Flink (Flink 1.20 et ses deux connecteurs, épinglés par empreinte)
    up         démarre Kafka, MongoDB, Flink, crée les sujets, le compte et la collection d'écriture
    job        envoie le job SQL (sql/agregats.sql) à Flink
    produire   joue le simulateur MS-07 sur le sujet iot.raw
    verifier   compare les agrégats de MongoDB au recalcul par lots
    demo       tout, dans un projet Compose jetable, avec ports libres, puis démontage
    down       arrête le projet (avec --volumes : efface aussi les données)

Bibliothèque standard seulement ; Docker est la seule exigence. Les secrets ne passent jamais par un argument de commande : ils
passent par l'environnement du processus, ou par l'entrée standard (le SQL rendu).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import mongo, recalcul, simulateur, sql, verifier

RACINE = simulateur.RACINE
DOSSIER = RACINE / "data" / "streaming"
FICHIER_SQL = DOSSIER / "sql" / "agregats.sql"
ENV_FILE = RACINE / ".env"
IMAGE = "novaria-flink-proto:1.20.5"
PROJET_PAR_DEFAUT = "novaria-flux"
SUJET = "iot.raw"
SERVICES = ("kafka", "mongo", "flink-jobmanager", "flink-taskmanager")
KAFKA_BIN = "/opt/kafka/bin"
SEPARATEUR = "|"
# Le client SQL est une JVM de plus dans le conteneur du JobManager : son tas est borné (la machine virtuelle de Docker Desktop
# n'a souvent que 3 Go ; sans cela le client prend un quart de la mémoire et tout s'arrête).
JVM_CLIENT = "-Xmx256m"
# Le script arrive sur l'entrée standard et se lit comme un fichier : avec `--file`, mongosh n'affiche ni invite ni écho du script, et
# sa sortie ne contient que ce que le script imprime. Compte administrateur : variables du conteneur MongoDB, jamais dans le dépôt.
MONGOSH_ADMIN = ('mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" '
                 "--authenticationDatabase admin --file /dev/stdin")


class ErreurFlux(RuntimeError):
    pass


def lire_env(chemin: Path = ENV_FILE) -> dict[str, str]:
    """`.env` du dépôt (KEY=VALEUR, # pour un commentaire) ; vide s'il n'existe pas."""
    valeurs: dict[str, str] = {}
    if not chemin.exists():
        return valeurs
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, _, valeur = ligne.partition("=")
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def port_libre() -> int:
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return sonde.getsockname()[1]


@dataclass
class Configuration:
    projet: str = PROJET_PAR_DEFAUT
    ports: dict[str, str] = field(default_factory=dict)
    mot_de_passe: str = ""  # celui du compte d'écriture de Flink : en mémoire, passé par l'environnement des commandes

    def environnement(self) -> dict[str, str]:
        env = {**os.environ, "COMPOSE_PROJECT_NAME": self.projet, **self.ports}
        if self.mot_de_passe:
            env[mongo.VARIABLE_MOT_DE_PASSE] = self.mot_de_passe
        return env


def commande_compose(*arguments: str) -> list[str]:
    """`docker compose` avec le fichier de la racine et celui du prototype."""
    return ["docker", "compose", "-f", "docker-compose.yml", "-f", "data/streaming/compose.yml", *arguments]


def executer(configuration: Configuration, arguments: list[str], *, entree: bytes | str | None = None, capturer: bool = True,
             controle: bool = True) -> subprocess.CompletedProcess:
    donnees = entree.encode("utf-8") if isinstance(entree, str) else entree
    resultat = subprocess.run(arguments, cwd=RACINE, env=configuration.environnement(), input=donnees, capture_output=capturer, check=False)
    if controle and resultat.returncode != 0:
        detail = (resultat.stderr or b"").decode("utf-8", "replace")[-600:] if capturer else ""
        raise ErreurFlux(f"échec ({resultat.returncode}) : {' '.join(arguments[:6])} …\n{detail}")
    return resultat


def texte(resultat: subprocess.CompletedProcess) -> str:
    return (resultat.stdout or b"").decode("utf-8", "replace")


def preparer_mot_de_passe(configuration: Configuration, ecrire_dans_env: bool) -> None:
    """Le mot de passe du compte d'écriture : l'environnement, puis `.env`, sinon un nouveau (écrit dans `.env` si on le garde)."""
    existant = os.environ.get(mongo.VARIABLE_MOT_DE_PASSE) or lire_env().get(mongo.VARIABLE_MOT_DE_PASSE)
    if existant:
        configuration.mot_de_passe = existant
        return
    configuration.mot_de_passe = secrets.token_urlsafe(24)
    if ecrire_dans_env:
        with ENV_FILE.open("a", encoding="utf-8", newline="\n") as fichier:
            fichier.write(f"\n# Compte d'écriture du prototype de flux (DAT-09), généré par `dev.py flux-proto up`.\n"
                          f"{mongo.VARIABLE_MOT_DE_PASSE}={configuration.mot_de_passe}\n")


def construire(configuration: Configuration) -> None:
    executer(configuration, ["docker", "build", "-t", IMAGE, str(DOSSIER)], capturer=False)


def demarrer(configuration: Configuration) -> None:
    if not ENV_FILE.exists():
        raise ErreurFlux("`.env` est absent : python scripts/dev/dev.py init-env")
    executer(configuration, commande_compose("up", "-d", "--wait", *SERVICES), capturer=False)
    # Les sujets du bus (iot.raw…) sont créés par la tâche kafka-init, qui s'arrête ensuite.
    executer(configuration, commande_compose("up", "--exit-code-from", "kafka-init", "kafka-init"))
    resultat = executer(
        configuration,
        commande_compose("exec", "-T", "-e", mongo.VARIABLE_MOT_DE_PASSE, "mongo", "sh", "-c",
                         MONGOSH_ADMIN),
        entree=mongo.SCRIPT_PREPARATION,
    )
    if "PRET" not in texte(resultat):
        raise ErreurFlux(f"la préparation de MongoDB n'a pas abouti : {texte(resultat)[-300:]}")


def valeurs_du_job(configuration: Configuration, groupe: str) -> dict[str, str]:
    env = lire_env()
    base = env.get("MONGO_DB") or os.environ.get("MONGO_DB") or "novaria"
    uri = f"mongodb://{mongo.UTILISATEUR}:{configuration.mot_de_passe}@mongo:27017/{base}?authSource={base}"
    return {"KAFKA_SERVEURS": "kafka:9092", "SUJET": SUJET, "GROUPE": groupe, "MONGO_URI": uri, "MONGO_BASE": base,
            "MONGO_COLLECTION": mongo.COLLECTION}


def soumettre(configuration: Configuration, groupe: str = "flink-agregats") -> None:
    """Envoie le job : le SQL rendu (avec l'adresse de MongoDB et son mot de passe) part sur l'entrée standard du client SQL."""
    rendu = sql.rendre(sql.lire(FICHIER_SQL), valeurs_du_job(configuration, groupe))
    resultat = executer(
        configuration,
        commande_compose("exec", "-T", "-e", f"JVM_ARGS={JVM_CLIENT}", "flink-jobmanager", "/opt/flink/bin/sql-client.sh", "-f", "/dev/stdin"),
        entree=rendu, controle=False,
    )
    sortie = texte(resultat) + (resultat.stderr or b"").decode("utf-8", "replace")
    if resultat.returncode != 0 or "[ERROR]" in sortie:
        masque = sortie.replace(configuration.mot_de_passe, "***") if configuration.mot_de_passe else sortie
        raise ErreurFlux(f"Flink a refusé le job :\n{masque[-1200:]}")


def etat_des_jobs(configuration: Configuration) -> list[dict]:
    resultat = executer(configuration, commande_compose("exec", "-T", "flink-jobmanager", "curl", "-fsS", "http://localhost:8081/jobs/overview"))
    return json.loads(texte(resultat))["jobs"]


def attendre_job(configuration: Configuration, delai_s: int = 90) -> dict:
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        jobs = [job for job in etat_des_jobs(configuration) if job["state"] == "RUNNING"]
        if jobs:
            return jobs[0]
        time.sleep(2)
    raise ErreurFlux("aucun job Flink en cours d'exécution après l'envoi")


def produire(configuration: Configuration, essai: simulateur.Essai, debit: float = 0.0) -> int:
    """Publie les messages de l'essai sur iot.raw (clé = carrefour, comme la collecte). Rend le nombre de messages."""
    lot = simulateur.messages(essai)
    producteur = subprocess.Popen(
        commande_compose("exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-console-producer.sh", "--bootstrap-server", "localhost:9092", "--topic", SUJET,
                         "--reader-property", "parse.key=true", "--reader-property", f"key.separator={SEPARATEUR}"),
        cwd=RACINE, env=configuration.environnement(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    assert producteur.stdin is not None
    for message in lot:
        producteur.stdin.write(simulateur.ligne_kafka(message, SEPARATEUR))
        if debit > 0:
            time.sleep(1.0 / debit)
    producteur.stdin.close()
    erreurs = producteur.stderr.read().decode("utf-8", "replace") if producteur.stderr else ""
    if producteur.wait() != 0:
        raise ErreurFlux(f"le producteur Kafka a échoué : {erreurs[-400:]}")
    return len(lot)


def ressources(configuration: Configuration) -> list[str]:
    """Mémoire utilisée par chaque conteneur du projet, à l'instant de l'appel (docker stats, sans suivi)."""
    identifiants = texte(executer(configuration, commande_compose("ps", "-q"))).split()
    if not identifiants:
        return []
    sortie = texte(executer(configuration, ["docker", "stats", "--no-stream", "--format", "{{.Name}} : {{.MemUsage}}", *identifiants]))
    return sorted(ligne.strip() for ligne in sortie.splitlines() if ligne.strip())


def lire_agregats(configuration: Configuration) -> list[dict]:
    resultat = executer(
        configuration,
        commande_compose("exec", "-T", "mongo", "sh", "-c",
                         MONGOSH_ADMIN),
        entree=mongo.SCRIPT_LECTURE,
    )
    return mongo.lire_documents(texte(resultat))


def attendre_agregats(configuration: Configuration, minimum: int, delai_s: int = 90) -> list[dict]:
    """Relit MongoDB jusqu'à ce qu'il y ait au moins `minimum` documents, ou jusqu'au délai."""
    limite = time.monotonic() + delai_s
    documents: list[dict] = []
    while time.monotonic() < limite:
        documents = lire_agregats(configuration)
        if len(documents) >= minimum:
            return documents
        time.sleep(3)
    return documents


def controler(configuration: Configuration, essai: simulateur.Essai, documents: list[dict] | None = None) -> verifier.Rapport:
    lot = simulateur.messages(essai)
    attendus = recalcul.agreger(lot)
    fermees = recalcul.fenetres_fermees(attendus, recalcul.instant_du_filigrane(lot))
    return verifier.comparer(documents if documents is not None else lire_agregats(configuration), attendus, fermees)


def afficher(rapport: verifier.Rapport) -> None:
    print(f"documents dans MongoDB : {rapport.documents}")
    print(f"fenêtres fermées attendues (recalcul par lots) : {rapport.attendus} ; égales : {rapport.egales}")
    print(f"fenêtres encore ouvertes à la fin (normal en temps d'événement) : {rapport.ouvertes}")
    for titre, lignes in (("ÉCARTS DE VALEUR", rapport.ecarts), ("FENÊTRES MANQUANTES", rapport.manquantes), ("FENÊTRES EN TROP", rapport.en_trop)):
        if lignes:
            print(f"{titre} ({len(lignes)}) :")
            for ligne in lignes[:15]:
                print(f"  - {ligne}")
    print("CONFORME : le flux égale le recalcul." if rapport.conforme else "NON CONFORME : le flux diffère du recalcul.")


def arreter(configuration: Configuration, volumes: bool) -> None:
    executer(configuration, commande_compose("down", "--remove-orphans", *(["--volumes"] if volumes else [])), capturer=False)


def essai_depuis(arguments: argparse.Namespace) -> simulateur.Essai:
    return simulateur.Essai(scenario=arguments.scenario, graine=arguments.graine, debut=arguments.debut, duree=arguments.duree,
                            run_id=arguments.run_id, anomalies=tuple(arguments.anomalie))


def configuration_depuis(arguments: argparse.Namespace, *, jetable: bool = False) -> Configuration:
    env = lire_env()
    if jetable:
        configuration = Configuration(
            projet=f"novaria-flux-{secrets.token_hex(3)}",
            ports={"KAFKA_PORT": str(port_libre()), "MONGO_PORT": str(port_libre()), "FLINK_PORT": str(port_libre())},
        )
    else:
        configuration = Configuration(projet=arguments.projet, ports={
            "KAFKA_PORT": env.get("KAFKA_PORT") or "9094", "MONGO_PORT": env.get("MONGO_PORT") or "27017",
            "FLINK_PORT": os.environ.get("FLINK_PORT") or env.get("FLINK_PORT") or "8081"})
    preparer_mot_de_passe(configuration, ecrire_dans_env=not jetable)
    return configuration


def commande_demo(arguments: argparse.Namespace) -> int:
    """Démonstration complète : projet jetable, essai, vérification, démontage (sauf --garder)."""
    configuration = configuration_depuis(arguments, jetable=True)
    essai = essai_depuis(arguments)
    code = 1
    try:
        print(f"Projet Compose jetable : {configuration.projet} (ports {configuration.ports})")
        demarrer(configuration)
        soumettre(configuration, groupe=f"flink-{configuration.projet}")
        job = attendre_job(configuration)
        print(f"Job Flink : {job['name']} ({job['state']})")
        debut_publication = time.monotonic()
        envoyes = produire(configuration, essai, arguments.debit)
        fin_publication = time.monotonic()
        lot = simulateur.messages(essai)
        attendus = recalcul.fenetres_fermees(recalcul.agreger(lot), recalcul.instant_du_filigrane(lot))
        print(f"{envoyes} messages publiés sur {SUJET} en {fin_publication - debut_publication:.1f} s")
        documents = attendre_agregats(configuration, len(attendus), arguments.delai)
        print(f"agrégats visibles dans MongoDB {time.monotonic() - fin_publication:.1f} s après la fin de la publication")
        if documents:
            exemple = min(documents, key=lambda d: json.dumps(d["_id"], sort_keys=True, default=str))
            print("exemple de document : " + json.dumps(exemple, ensure_ascii=False, sort_keys=True, default=str))
        for ligne in ressources(configuration):
            print(f"mémoire : {ligne}")
        rapport = controler(configuration, essai, documents)
        afficher(rapport)
        code = 0 if rapport.conforme else 1
    except ErreurFlux as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
    finally:
        if not arguments.garder:
            arreter(configuration, volumes=True)
            print(f"Projet {configuration.projet} supprimé.")
    return code


def construire_analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(prog="flux-proto", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analyseur.add_argument("--projet", default=PROJET_PAR_DEFAUT, help=f"nom du projet Compose (défaut {PROJET_PAR_DEFAUT})")
    sous = analyseur.add_subparsers(dest="commande", required=True)

    def essai(parseur: argparse.ArgumentParser) -> None:
        defaut = simulateur.Essai()
        parseur.add_argument("--scenario", default=defaut.scenario)
        parseur.add_argument("--graine", type=int, default=defaut.graine)
        parseur.add_argument("--debut", default=defaut.debut, help="début UTC du run, ex. 2026-10-20T08:00:00Z")
        parseur.add_argument("--duree", default=defaut.duree, help="durée simulée (ex. 12m)")
        parseur.add_argument("--run-id", default=defaut.run_id)
        parseur.add_argument("--anomalie", action="append", default=[], metavar="SPEC", help="anomalie du simulateur (voir simulator/README.md, section 6)")

    sous.add_parser("build", help="construit l'image Flink")
    sous.add_parser("up", help="démarre Kafka, MongoDB et Flink, prépare MongoDB")
    sous.add_parser("job", help="envoie le job SQL à Flink")
    produire_p = sous.add_parser("produire", help="joue le simulateur sur iot.raw")
    essai(produire_p)
    produire_p.add_argument("--debit", type=float, default=0.0, help="messages par seconde (0 : sans frein)")
    verifier_p = sous.add_parser("verifier", help="compare MongoDB au recalcul par lots")
    essai(verifier_p)
    demo = sous.add_parser("demo", help="démonstration complète dans un projet jetable")
    essai(demo)
    demo.add_argument("--debit", type=float, default=0.0)
    demo.add_argument("--delai", type=int, default=120, help="secondes d'attente des agrégats")
    demo.add_argument("--garder", action="store_true", help="ne démonte pas le projet à la fin")
    bas = sous.add_parser("down", help="arrête le projet")
    bas.add_argument("--volumes", action="store_true", help="efface aussi les données (Kafka, MongoDB, points de contrôle)")
    return analyseur


def main(argv: list[str] | None = None) -> int:
    arguments = construire_analyseur().parse_args(argv)
    try:
        if arguments.commande == "demo":
            return commande_demo(arguments)
        configuration = configuration_depuis(arguments)
        if arguments.commande == "build":
            construire(configuration)
        elif arguments.commande == "up":
            demarrer(configuration)
            print(f"Prêt : Flink http://127.0.0.1:{configuration.ports['FLINK_PORT']} ; ensuite :  flux-proto job, puis produire.")
        elif arguments.commande == "job":
            soumettre(configuration)
            print(f"Job envoyé : {attendre_job(configuration)['name']} en cours.")
        elif arguments.commande == "produire":
            print(f"{produire(configuration, essai_depuis(arguments), arguments.debit)} messages publiés sur {SUJET}")
        elif arguments.commande == "verifier":
            rapport = controler(configuration, essai_depuis(arguments))
            afficher(rapport)
            return 0 if rapport.conforme else 1
        elif arguments.commande == "down":
            arreter(configuration, arguments.volumes)
        return 0
    except (ErreurFlux, sql.ErreurSql, RuntimeError) as erreur:
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
