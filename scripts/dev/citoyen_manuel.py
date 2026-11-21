"""Essai à la main de l'application citoyenne (CIT-07) : vous créez des alertes simulées, vous les regardez, vous les refermez.

Les autres commandes (`citoyen delai`, `parcours`) referment leurs alertes en quelques secondes : trop court pour un essai humain. Celle-ci
attend vos touches :

  1. elle choisit un carrefour libre et vous donne ses 4 tronçons : ouvrez l'application, cochez le consentement, suivez l'un d'eux ;
  2. [Entrée] : elle envoie des mesures simulées congestionnées ; les 4 alertes naissent, la page les affiche en moins de 10 s et notifie
     (de façon simulée) le tronçon suivi ;
  3. [Entrée] : elle envoie des minutes fluides, les alertes se referment, la page les retire.

Ctrl+C à tout moment : les alertes déjà créées sont refermées avant de quitter. Les mesures sont simulées (run `cit07m-…`).
"""

import sys
import time

import citoyen_delai as delai
import flux_complet as flux
from parcours import Echec


def executer(entree=input, sortie=print) -> int:
    pile = flux.Pile(delai.lire_env())
    if not pile.sante():
        raise Echec("la pile ne répond pas : lancer d'abord `dev.py up`")
    run, debut = flux.nouveau_run("cit07m"), flux.debut_pour(len(delai.CONGESTIONNEES) + len(delai.FLUIDES))
    carrefour = delai.choisir_carrefour(pile, debut)
    contexte = flux.Contexte(pile=pile)
    troncons = [t for _, _, t in flux.capteurs(carrefour)]
    sortie(f"Carrefour INT_{carrefour:02d} (run {run}). Tronçons : {', '.join(troncons)}.")
    sortie("1. Ouvrez l'application (http://127.0.0.1:5174), cochez « J'ai compris et j'accepte », puis « Suivre ce tronçon » sur l'un de ces tronçons")
    sortie("   (ils apparaissent dans « Par carrefour » ; la liste d'alertes n'en montre pas encore).")
    envoyees = False
    try:
        entree("   Prêt ? Entrée pour créer les alertes… ")
        flux.envoyer_run(contexte, run, carrefour, debut, delai.CONGESTIONNEES, 0)
        envoyees = True
        fin = time.monotonic() + delai.ATTENTE_ALERTES_S
        trouvees: dict = {}
        while time.monotonic() < fin and len(trouvees) < 4:
            trouvees = delai.creations(pile, run)
            time.sleep(1)
        if len(trouvees) < 4:
            raise Echec(f"{len(trouvees)} alerte(s) créée(s) sur 4 attendues après {delai.ATTENTE_ALERTES_S} s")
        sortie(f"2. {len(trouvees)} alertes créées par le service : {', '.join(sorted(t for t, _ in trouvees.values()))}.")
        sortie("   Regardez la page : elles doivent apparaître seules en moins de 10 s, et le tronçon suivi doit afficher « Notification simulée » en haut.")
        entree("   Entrée pour refermer les alertes… ")
    except (KeyboardInterrupt, EOFError):
        sortie("\nInterrompu.")
    finally:
        if envoyees:
            flux.envoyer_run(contexte, run, carrefour, debut, delai.FLUIDES, len(delai.CONGESTIONNEES))
            sortie("3. Minutes fluides envoyées : les alertes se referment ; la page les retire à la lecture suivante (5 s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(executer())
    except Echec as erreur:
        print(f"ÉCHEC : {erreur}", file=sys.stderr)
        sys.exit(1)
