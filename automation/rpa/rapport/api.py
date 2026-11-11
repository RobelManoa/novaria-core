"""Appels à l'API de Novaria Core : connexion puis lecture des indicateurs (compte en lecture seule).

Le robot ne fait que lire (ADR-019) : deux appels `GET` et la connexion. Le mot de passe et le jeton ne
sont jamais écrits dans un message d'erreur ni dans un journal.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

TIMEOUT_S = 30
PAGE = 500
MAX_PAGES = 200  # 100 000 fenêtres : au-delà, le rapport le dit au lieu de s'allonger sans fin


class ErreurApi(Exception):
    """Un appel a échoué ; le message ne contient ni mot de passe ni jeton."""


@dataclass(frozen=True)
class Indicateurs:
    lignes: list[dict]
    tronque: bool


Requete = Callable[[urllib.request.Request], tuple[int, bytes]]


def _envoyer(requete: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(requete, timeout=TIMEOUT_S) as reponse:  # noqa: S310 : http(s) vérifié
            return reponse.status, reponse.read()
    except urllib.error.HTTPError as erreur:
        return erreur.code, erreur.read()
    except (urllib.error.URLError, TimeoutError, OSError) as erreur:
        raise ErreurApi(f"API injoignable : {type(erreur).__name__}") from erreur


def _verifier_base(base: str) -> str:
    adresse = urllib.parse.urlsplit(base)
    if adresse.scheme not in ("http", "https") or not adresse.hostname:
        raise ErreurApi("l'adresse de l'API doit commencer par http:// ou https:// et nommer un hôte")
    return base.rstrip("/")


def _json(statut: int, corps: bytes, action: str) -> dict:
    try:
        contenu = json.loads(corps)
    except ValueError:
        contenu = {}
    if statut != 200:
        code = contenu.get("code", "?") if isinstance(contenu, dict) else "?"
        raise ErreurApi(f"{action} : réponse {statut} ({code})")
    if not isinstance(contenu, dict):
        raise ErreurApi(f"{action} : réponse inattendue")
    return contenu


def se_connecter(
    base: str, utilisateur: str, mot_de_passe: str, envoyer: Requete | None = None
) -> str:
    envoyer = envoyer or _envoyer
    base = _verifier_base(base)
    requete = urllib.request.Request(  # noqa: S310
        f"{base}/api/v1/auth/login",
        data=json.dumps({"username": utilisateur, "password": mot_de_passe}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    statut, corps = envoyer(requete)
    jeton = _json(statut, corps, "connexion").get("access_token")
    if not isinstance(jeton, str) or not jeton:
        raise ErreurApi("connexion : pas de jeton dans la réponse")
    return jeton


def lire_indicateurs(
    base: str, jeton: str, debut: str, fin: str, *, fenetre_s: int = 300, envoyer: Requete | None = None
) -> Indicateurs:
    """Toutes les fenêtres de la période (pages de 500, curseur), du plus récent au plus ancien."""
    envoyer = envoyer or _envoyer
    base = _verifier_base(base)
    lignes: list[dict] = []
    curseur = None
    for _ in range(MAX_PAGES):
        parametres = {"from": debut, "to": fin, "window_size_s": fenetre_s, "limit": PAGE}
        if curseur:
            parametres["cursor"] = curseur
        requete = urllib.request.Request(  # noqa: S310
            f"{base}/api/v1/indicators?{urllib.parse.urlencode(parametres)}",
            headers={"Authorization": f"Bearer {jeton}"},
        )
        statut, corps = envoyer(requete)
        page = _json(statut, corps, "lecture des indicateurs")
        lignes += page.get("items", [])
        curseur = page.get("next_cursor")
        if not curseur:
            return Indicateurs(lignes, tronque=False)
    return Indicateurs(lignes, tronque=True)
