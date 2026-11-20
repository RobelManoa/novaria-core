"""Délai d'apparition d'une alerte chez le citoyen (CIT-05) : mesuré sur la pile locale réelle, dans un vrai navigateur.

Critère d'acceptation : « Une alerte créée par le service apparaît chez le citoyen en moins de 10 secondes. »

Ce qui est mesuré, de bout en bout :
  1. l'application citoyenne construite est ouverte dans Chromium (écran de téléphone), derrière la passerelle réelle ;
  2. des mesures de congestion (simulées, un carrefour, un run neuf) sont envoyées à la collecte ; la chaîne les traite ;
  3. le service des alertes crée les alertes : l'instant de création est lu dans PostgreSQL, dans l'événement `...-created` de
     `alertes.outbox_event` (`created_at`, horloge de la base). Les dates de `alert` et de `alert_history` sont celles des MESURES
     (ici dans le passé) : elles ne servent pas à mesurer un délai ;
  4. l'instant où chaque alerte apparaît à l'écran est noté par la page elle-même (`citizen/scripts/delai-alerte.mjs`) ;
  5. délai = apparition à l'écran − création dans la base. Succès si le plus long des délais est sous 10 secondes.

L'application relit les alertes toutes les 5 s : le délai dépend de l'instant de la création dans ce tour (0 à 5 s) ; un décalage
aléatoire avant l'envoi répartit la mesure sur le tour. Les deux horloges sont celles du même poste (la base, le navigateur) : aucune dérive à corriger. Le critère ne dit pas « jamais plus » :
la mesure d'une exécution n'est pas une garantie ; l'intervalle de lecture (5 s) borne seulement la part due à l'application.

Lancement : python3 scripts/dev/dev.py citoyen delai  (Windows : py -3 scripts/dev/dev.py citoyen delai). La pile doit tourner.
Les mesures envoyées sont simulées, d'un carrefour libre (INT_06, sinon INT_05…), sur un run à nom neuf. Les minutes congestionnées sont envoyées d'abord :
l'alerte reste ouverte le temps de la mesure ; les minutes fluides suivent ensuite, et les alertes se résolvent seules.
(Avec des minutes passées envoyées d'un coup, l'alerte naît et se résout en moins d'une seconde : le citoyen ne la verrait jamais.)
"""

import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import flux_complet as flux
from parcours import Echec

RACINE = Path(__file__).resolve().parents[2]
CITOYEN = RACINE / "citizen"
CAPTURE = RACINE / "docs" / "Capture d'ecran" / "CIT-05-alerte-creee-par-le-service-reelle.png"
SEUIL_S = 10.0
CARREFOURS = (6, 5, 4, 3, 2)
ATTENTE_ALERTES_S = 150
CONGESTIONNEES = (True,) * 4
FLUIDES = (False,) * 4


def lire_env() -> dict[str, str]:
    """Le contenu de `.env` (jamais affiché)."""
    valeurs: dict[str, str] = {}
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, _, valeur = ligne.partition("=")
            valeurs[cle.strip()] = valeur.strip().strip("'\"")
    return valeurs


def creations(pile: flux.Pile, run: str) -> dict[str, tuple[str, float]]:
    """{alert_id: (tronçon, instant de création en ms depuis l'époque)} des alertes de ce run."""
    lignes = pile.psql(
        "SELECT a.alert_id, a.road_segment_id, round(extract(epoch FROM o.created_at) * 1000) "
        "FROM alertes.alert a JOIN alertes.outbox_event o ON o.event_id = 'alerte-' || a.alert_id || '-created' "
        f"WHERE a.run_id = '{run}' ORDER BY 2;")
    return {ligne[0]: (ligne[1], float(ligne[2])) for ligne in lignes}


def mesurer(pile: flux.Pile, run: str, vues: dict[str, float], delai_s: int = ATTENTE_ALERTES_S) -> list[dict]:
    """Attend que les 4 alertes du run soient créées et vues à l'écran ; rend un résultat par alerte."""
    fin = time.monotonic() + delai_s
    while time.monotonic() < fin:
        trouvees = creations(pile, run)
        if len(trouvees) >= 4 and all(identifiant in vues for identifiant in trouvees):
            break
        time.sleep(1)
    trouvees = creations(pile, run)
    return [{"alert_id": identifiant, "troncon": troncon, "creee_ms": cree, "vue_ms": vues.get(identifiant),
             "delai_s": None if identifiant not in vues else (vues[identifiant] - cree) / 1000}
            for identifiant, (troncon, cree) in trouvees.items()]


def verdict(resultats: list[dict], seuil_s: float = SEUIL_S) -> tuple[bool, str]:
    """Succès seulement si les 4 alertes attendues existent, sont toutes vues et si la plus lente est sous le seuil."""
    if len(resultats) < 4:
        return False, f"{len(resultats)} alerte(s) créée(s), 4 attendues"
    manquantes = [r["troncon"] for r in resultats if r["delai_s"] is None]
    if manquantes:
        return False, "jamais vue à l'écran : " + ", ".join(manquantes)
    pire = max(r["delai_s"] for r in resultats)
    if min(r["delai_s"] for r in resultats) < 0:
        return False, "délai négatif : les horloges ne concordent pas, mesure inutilisable"
    return pire < seuil_s, f"délai le plus long {pire:.1f} s pour un seuil de {seuil_s:g} s"


def choisir_carrefour(pile: flux.Pile, debut: datetime) -> int:
    """Le premier carrefour (de INT_06 à INT_02) dont les feux n'ont pas déjà reçu une recommandation plus récente que ces minutes.
    INT_01 est laissé au parcours nominal (`dev.py flux-complet`)."""
    refus = []
    for carrefour in CARREFOURS:
        try:
            flux.exiger_horloge(pile, carrefour, debut)
            return carrefour
        except Echec as erreur:
            refus.append(str(erreur))
    raise Echec("aucun carrefour libre pour ces minutes ; " + refus[0])


def executer() -> int:
    node = shutil.which("node")
    if node is None:
        raise Echec("node est absent (Node.js 22 ou plus)")
    pile = flux.Pile(lire_env())
    if not pile.sante():
        raise Echec("la pile ne répond pas : lancer d'abord `dev.py up`")
    contexte = flux.Contexte(pile=pile)
    run, debut = flux.nouveau_run("cit05"), flux.debut_pour(len(CONGESTIONNEES) + len(FLUIDES))
    carrefour = choisir_carrefour(pile, debut)
    print(f"Run {run}, carrefour INT_{carrefour:02d}, {len(CONGESTIONNEES)} minutes congestionnées, puis {len(FLUIDES)} fluides (mesures simulées).")
    CAPTURE.parent.mkdir(parents=True, exist_ok=True)
    observateur = subprocess.Popen([node, "scripts/delai-alerte.mjs"], cwd=CITOYEN, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                   env={**os.environ, "CAPTURE": str(CAPTURE), "ATTENTE_S": str(ATTENTE_ALERTES_S + 30)})
    vues: dict[str, float] = {}
    envoyees = False
    try:
        premiere = observateur.stdout.readline()
        if json.loads(premiere or "{}").get("evenement") != "pret":
            raise Echec(f"l'observateur n'est pas prêt : {premiere!r}")
        # L'application relit toutes les 5 s : sans décalage, l'alerte naîtrait toujours au même point du tour et le délai serait toujours
        # le même. Un décalage aléatoire (0 à 5 s) répartit la mesure sur le tour, comme des citoyens qui ouvrent la page à tout moment.
        decalage = random.uniform(0, 5)
        time.sleep(decalage)
        print(f"Application ouverte dans Chromium (liste d'alertes chargée). Décalage aléatoire {decalage:.1f} s, envoi des mesures…")
        flux.envoyer_run(contexte, run, carrefour, debut, CONGESTIONNEES, 0)
        envoyees = True
        def lire() -> None:
            for texte in observateur.stdout:
                try:
                    evenement = json.loads(texte)
                except ValueError:
                    continue
                if evenement.get("evenement") == "vue":
                    vues[evenement["alert_id"]] = float(evenement["vue_ms"])

        fil = threading.Thread(target=lire, daemon=True)
        fil.start()
        resultats = mesurer(pile, run, vues)
    finally:
        observateur.terminate()
        if envoyees:  # le retour à la normale ferme les alertes : l'état public ne garde pas d'alerte d'essai ouverte
            flux.envoyer_run(contexte, run, carrefour, debut, FLUIDES, len(CONGESTIONNEES))
    reussi, resume = verdict(resultats)
    print(f"\n{'Tronçon':<10} {'Créée (UTC)':<14} {'Délai jusqu'+chr(39)+'à l'+chr(39)+'écran'}")
    for r in sorted(resultats, key=lambda r: r["troncon"]):
        cree = datetime.fromtimestamp(r["creee_ms"] / 1000, UTC).strftime("%H:%M:%S.%f")[:-3]
        delai = "jamais vue" if r["delai_s"] is None else f"{r['delai_s']:.1f} s"
        print(f"{r['troncon']:<10} {cree:<14} {delai}")
    print(f"\n{'RÉUSSI' if reussi else 'ÉCHEC'} : {resume}.")
    if CAPTURE.exists():
        print(f"Capture : {CAPTURE.relative_to(RACINE).as_posix()}")
    return 0 if reussi else 1


if __name__ == "__main__":
    try:
        sys.exit(executer())
    except Echec as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
        sys.exit(1)
