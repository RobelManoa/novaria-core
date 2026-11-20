"""Retour de version en local : l'équivalent Compose du rollback d'ECS (CLD-16, ADR-021, ADR-025).

Sur AWS, un retour de version remet en service la **révision précédente de la définition de tâche** ECS (donc l'image dont
l'étiquette est le SHA du commit). En local, le même geste : chaque révision d'un service est une **image étiquetée par le SHA du
commit** (`novaria-local/<service>:<sha12>`, construite depuis les sources de ce commit), et Compose remet en service l'étiquette
précédente. `deploy.yml` fait la même vérification sur AWS : la révision renvoyée par `/health` est celle qu'on a demandée.

Ce que fait un retour : il change le **code** de un à quatre services (`collecte`, `traitement`, `alerte`, `reponse`, avec les
conteneurs qui partagent leur image). Ce qu'il ne fait jamais : toucher aux volumes, aux bases, à Kafka, aux migrations. Aucune
commande de ce module ne supprime de conteneur ni de volume : `up -d --no-build --no-deps --force-recreate` seulement.

Bibliothèque standard seulement. Docker, Git et le réseau sont appelés par des fonctions que les tests remplacent.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess, run

ROOT = Path(__file__).resolve().parents[2]
DOSSIER = ROOT / "var" / "rollback"
PREFIXE_IMAGE = "novaria-local"
SHA = re.compile(r"^[0-9a-f]{40}$")

# service applicatif -> conteneurs Compose qui partagent son image ; port publié (variable de .env, valeur par défaut)
SERVICES: dict[str, dict] = {
    "collecte": {"conteneurs": ("collecte",), "port": ("COLLECTE_PORT", "8001")},
    "traitement": {"conteneurs": ("traitement", "traitement-flux", "traitement-pipeline"), "port": ("TRAITEMENT_PORT", "8002")},
    "alerte": {"conteneurs": ("alerte", "alerte-worker"), "port": ("ALERTE_PORT", "8003")},
    "reponse": {"conteneurs": ("reponse",), "port": ("REPONSE_PORT", "8004")},
}
ATTENTE_SANTE_S = 120


class ErreurRollback(Exception):
    """Un retour de version refusé ou échoué ; le message dit quoi faire, la pile n'est pas modifiée au-delà de ce qu'il dit."""


def image(service: str, sha: str) -> str:
    return f"{PREFIXE_IMAGE}/{service}:{sha[:12]}"


@dataclass
class Moteur:
    """Les appels extérieurs (Git, Docker, HTTP, horloge) : remplacés dans les tests."""

    racine: Path = ROOT
    dossier: Path = DOSSIER
    env: dict[str, str] | None = None
    executer: Callable[..., CompletedProcess] = run
    lire_sante: Callable[[str], str | None] | None = None
    horloge: Callable[[], float] = time.time
    dormir: Callable[[float], None] = time.sleep

    # -- Git et Docker
    def _lancer(self, commande: list[str], **options) -> CompletedProcess:
        return self.executer(commande, cwd=self.racine, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, **options)

    def resoudre(self, reference: str) -> str:
        """Le SHA complet d'une référence Git (branche, étiquette, abréviation) ; refuse tout ce qui n'est pas un commit."""
        if not reference or reference.startswith("-"):
            raise ErreurRollback(f"référence Git invalide : « {reference} »")
        sortie = self._lancer(["git", "rev-parse", "--verify", "--quiet", f"{reference}^{{commit}}"])
        sha = sortie.stdout.strip()
        if sortie.returncode != 0 or not SHA.match(sha):
            raise ErreurRollback(f"référence Git introuvable : « {reference} » (git fetch ?)")
        return sha

    def image_presente(self, service: str, sha: str) -> bool:
        return self._lancer(["docker", "image", "inspect", image(service, sha)]).returncode == 0

    def construire(self, service: str, sha: str) -> str:
        """Construit l'image d'un service depuis les sources **de ce commit** (git archive), étiquetée par son SHA."""
        if service not in SERVICES:
            raise ErreurRollback(f"service inconnu : « {service} » (possibles : {', '.join(SERVICES)})")
        if self.image_presente(service, sha):
            return f"image déjà construite : {image(service, sha)}"
        archive = self.executer(["git", "archive", "--format=tar", sha, f"services/{service}"], cwd=self.racine, capture_output=True, check=False)
        if archive.returncode != 0:
            raise ErreurRollback(f"git archive a échoué pour {service} à {sha[:12]} : le dossier existait-il à cette révision ?")
        source = self.dossier / "sources" / sha[:12]
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(source, filter="data")  # noqa: S202 - archive produite par Git, filtre « data » : pas de chemin hors du dossier
        sortie = self._lancer(["docker", "build", "--build-arg", f"GIT_SHA={sha}", "-t", image(service, sha), str(source / "services" / service)], timeout=1200)
        if sortie.returncode != 0:
            raise ErreurRollback(f"docker build a échoué pour {service} :\n{sortie.stderr.strip()[-600:]}")
        return f"image construite : {image(service, sha)}"

    # -- état
    def etat(self) -> dict:
        try:
            return json.loads((self.dossier / "etat.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _ecrire_etat(self, etat: dict) -> None:
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / "etat.json").write_text(json.dumps(etat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    # -- déploiement
    def surcharge(self, revisions: dict[str, str]) -> str:
        """Fichier Compose qui fixe l'image et la révision annoncée de chaque conteneur concerné (rien d'autre)."""
        lignes = ["# Généré par scripts/dev/rollback.py : image et révision de chaque conteneur (ne pas modifier, ne pas commiter).", "services:"]
        for service, sha in revisions.items():
            for conteneur in SERVICES[service]["conteneurs"]:
                lignes += [f"  {conteneur}:", f"    image: {image(service, sha)}", "    environment:", f"      GIT_SHA: {sha}"]
        return "\n".join(lignes) + "\n"

    def _port(self, service: str) -> str:
        variable, defaut = ("GATEWAY_PORT", "8000") if service == "passerelle" else SERVICES[service]["port"]
        return (self.env or {}).get(variable, defaut)

    def sante(self, service: str) -> str | None:
        """La révision que le service dit exécuter (`/api/v1/health`), `None` s'il ne répond pas."""
        if self.lire_sante is not None:
            return self.lire_sante(service)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port(service)}/api/v1/health", timeout=3) as reponse:  # noqa: S310 - adresse locale
                return json.loads(reponse.read()).get("revision")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None

    def recharger_passerelle(self) -> None:
        """La passerelle (nginx) résout `traitement`, `alerte`… **une fois, au démarrage** : un conteneur recréé change d'adresse et
        la passerelle répond 503 vers l'ancienne. `nginx -s reload` relit les adresses sans couper les requêtes en cours."""
        sortie = self._lancer(["docker", "compose", "exec", "-T", "passerelle", "nginx", "-s", "reload"], timeout=60)
        if sortie.returncode != 0:
            raise ErreurRollback("la passerelle n'a pas relu les adresses des services (503 probables) : docker compose exec -T passerelle nginx -s reload")

    def attendre_revision(self, service: str, sha: str) -> None:
        fin = self.horloge() + ATTENTE_SANTE_S
        vue = None
        while self.horloge() < fin:
            vue = self.sante(service)
            if vue == sha:
                return
            self.dormir(2)
        raise ErreurRollback(f"{service} annonce la révision « {vue} » au lieu de « {sha[:12]} » après {ATTENTE_SANTE_S} s : l'état enregistré n'est pas modifié")

    def deployer(self, revisions: dict[str, str], action: str = "deploiement") -> list[str]:
        """Remet en service la révision demandée de chaque service, puis **vérifie** la révision annoncée par `/health`."""
        for service, sha in revisions.items():
            if service not in SERVICES:
                raise ErreurRollback(f"service inconnu : « {service} »")
            if not SHA.match(sha):
                raise ErreurRollback(f"révision invalide pour {service} : « {sha} »")
            if not self.image_presente(service, sha):
                raise ErreurRollback(f"{image(service, sha)} n'existe pas : la construire d'abord (dev.py rollback construire --ref {sha[:12]})")
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / "compose.revisions.yml").write_text(self.surcharge(revisions), encoding="utf-8", newline="\n")
        conteneurs = [c for s in revisions for c in SERVICES[s]["conteneurs"]]
        commande = ["docker", "compose", "-f", "docker-compose.yml", "-f", str(self.dossier / "compose.revisions.yml"),
                    "up", "-d", "--no-build", "--no-deps", "--force-recreate", *conteneurs]
        sortie = self._lancer(commande, timeout=600)
        if sortie.returncode != 0:
            raise ErreurRollback(f"docker compose up a échoué :\n{sortie.stderr.strip()[-600:]}")
        try:
            for service, sha in revisions.items():
                self.attendre_revision(service, sha)
            self.recharger_passerelle()
            if "traitement" in revisions:  # la passerelle route /api/v1/health vers le traitement : elle doit annoncer la même révision
                self.attendre_revision("passerelle", revisions["traitement"])
        except ErreurRollback as erreur:
            raise self._reprendre(erreur, revisions, action) from None
        etat, maintenant = self.etat(), datetime.fromtimestamp(self.horloge(), UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        messages = []
        for service, sha in revisions.items():
            ancien = etat.get(service, {})
            if ancien.get("en_service") == sha:
                messages.append(f"{service} : déjà en service à {sha[:12]}")
                continue
            etat[service] = {"en_service": sha, "precedente": ancien.get("en_service"),
                             "historique": [*ancien.get("historique", []), {"revision": sha, "action": action, "le": maintenant}][-20:]}
            messages.append(f"{service} : {sha[:12]} en service (précédente : {(ancien.get('en_service') or 'aucune')[:12]})")
        self._ecrire_etat(etat)
        return messages

    def _reprendre(self, erreur: ErreurRollback, revisions: dict[str, str], action: str) -> ErreurRollback:
        """Une révision qui ne répond pas comme annoncé : on remet **seul** celle qui tournait avant (comme le disjoncteur d'ECS)."""
        etat = self.etat()
        anciens = {s: etat[s]["en_service"] for s in revisions if etat.get(s, {}).get("en_service") and etat[s]["en_service"] != revisions[s]}
        if not anciens or action == "reprise":
            return erreur
        try:
            self.deployer(anciens, action="reprise")
        except ErreurRollback as seconde:
            return ErreurRollback(f"{erreur}\nLa reprise automatique de {', '.join(f'{s} {r[:12]}' for s, r in anciens.items())} a échoué aussi : {seconde}")
        return ErreurRollback(f"{erreur}\nReprise automatique : {', '.join(f'{s} {r[:12]}' for s, r in anciens.items())} remis en service.")

    def retour(self, services: list[str]) -> list[str]:
        """Rollback : remet en service, pour chaque service, la révision qui précédait celle d'aujourd'hui."""
        etat = self.etat()
        cibles = {}
        for service in services:
            if service not in SERVICES:
                raise ErreurRollback(f"service inconnu : « {service} »")
            precedente = etat.get(service, {}).get("precedente")
            if not precedente:
                raise ErreurRollback(f"{service} : aucune révision précédente enregistrée (rien n'a été déployé avant celle-ci avec dev.py rollback)")
            cibles[service] = precedente
        return self.deployer(cibles, action="retour")


# --------------------------------------------------------------------------- l'essai : ancienne, nouvelle, retour
def essai(moteur: Moteur, pile, ancienne: str, nouvelle: str, services: list[str], afficher: Callable[[str], None] = print) -> list[tuple[str, bool, str]]:
    """Joue un retour de version sur la pile qui tourne et dit, étape par étape, ce qui est prouvé.

    1. les deux révisions sont construites ; 2. l'ancienne est mise en service ; 3. la nouvelle la remplace ; 4. une mesure est
    écrite pendant que la nouvelle tourne ; 5. le retour remet l'ancienne en service ; 6. la mesure écrite par la nouvelle
    révision est toujours là : un retour de code ne rend pas les données.
    """
    import flux_complet as fc

    etapes: list[tuple[str, bool, str]] = []

    def noter(nom: str, ok: bool, detail: str) -> None:
        etapes.append((nom, ok, detail))
        afficher(f"[{'OK' if ok else 'ÉCHEC'}] {nom} : {detail}")

    sha_a, sha_b = moteur.resoudre(ancienne), moteur.resoudre(nouvelle)
    if sha_a == sha_b:
        raise ErreurRollback("l'ancienne et la nouvelle révision sont le même commit : il n'y a rien à rétablir")
    for sha in (sha_a, sha_b):
        for service in services:
            afficher(moteur.construire(service, sha))
    noter("révisions construites", True, f"ancienne {sha_a[:12]}, nouvelle {sha_b[:12]}, services {', '.join(services)}")
    moteur.deployer({s: sha_a for s in services}, action="essai : ancienne révision")
    noter("ancienne révision en service", all(moteur.sante(s) == sha_a for s in services), "/health annonce " + sha_a[:12])
    moteur.deployer({s: sha_b for s in services}, action="essai : nouvelle révision")
    noter("nouvelle révision en service", all(moteur.sante(s) == sha_b for s in services), "/health annonce " + sha_b[:12])
    run, debut = fc.nouveau_run("cld16"), fc.debut_pour(1)
    document = fc.mesure(run, 1, "SENSOR_001", "ROAD_001", debut + timedelta(seconds=10), fc.FLUIDE)
    statut, _ = pile.appel("POST", f"{pile.collecte}/api/v1/measurements", document)
    ecrite = statut == 202 and _compter(pile, document["id"]) == 1
    noter("écriture pendant la nouvelle révision", ecrite, f"mesure {document['id']} : HTTP {statut}, 1 copie dans raw_events" if ecrite else f"HTTP {statut}")
    moteur.retour(services)
    noter("retour : l'ancienne révision est de nouveau en service", all(moteur.sante(s) == sha_a for s in services), "/health annonce " + sha_a[:12])
    apres = _compter(pile, document["id"])
    noter("les données ne sont pas revenues en arrière", apres == 1, f"la mesure écrite par la nouvelle révision est toujours dans raw_events ({apres} copie)")
    return etapes


def _compter(pile, identifiant: str) -> int:
    return int(pile.mongo(f'db.raw_events.countDocuments({{"id": "{identifiant}"}})').split()[-1])
