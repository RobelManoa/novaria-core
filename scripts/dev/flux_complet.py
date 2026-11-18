"""Test de bout en bout du flux complet sur la pile locale (MS-15) : du capteur simulé à la commande de feux, et les cas d'échec.

La logique est ici ; `dev.py flux-complet` ne fait que l'appeler. Bibliothèque standard seulement. Réutilise `parcours.py`
(CLD-13 : adresses de la pile, appels HTTP, `docker compose`, `psql`, `mongosh`) ; chaque cas est une fonction qui rend la
preuve de ce qu'elle a **observé** et lève `Echec` quand l'observation diffère de l'attendu.

| Cas | Ce qu'il prouve |
|---|---|
| N1 à N7 | des mesures de congestion de 4 capteurs d'un carrefour traversent collecte, flux, pipeline (fenêtres), alerte, recommandation, |
|         | contrôleur de feux ; l'alerte se résout au retour à la normale ; un opérateur commande les feux (et une commande dangereuse est refusée) |
| F1 | message illisible, hors contrat ou déjà reçu : refusé ou ignoré, jamais compté deux fois, rien n'entre dans le flux |
| F2 | service arrêté (`alerte-worker`) : le reste de la chaîne continue ; au redémarrage les alertes arrivent, sans perte ni doublon |
| F3 | broker indisponible (Kafka) : la collecte refuse (503) au lieu de perdre ; au retour, le renvoi donne exactement les mêmes fenêtres |
| F4 | indicateurs en retard (flux arrêté) : rien n'est calculé pendant l'arrêt, tout est rattrapé ensuite, sans perte ni doublon |
| F5 | mode dégradé des feux : sans recommandation, plan fixe après le silence maximal ; la recommandation suivante rend le mode automatique |
| F6 | redémarrage du service des feux : plan fixe au démarrage, aucune recommandation rejouée, celle reçue pendant l'arrêt est appliquée |

Aucune valeur n'est simulée côté serveur. Seules les **mesures** sont fabriquées (provenance `SIMULATED`, scénario `ms15-flux-complet`).
Chaque cas utilise son propre `run_id`, donc ses propres fenêtres et alertes, et finit par quelques minutes fluides : les alertes
se résolvent seules et la commande peut être rejouée sans nettoyer la base.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import parcours
from parcours import Echec, Resultat, _exiger, debut_de_minute_passee, horodatage

ROOT = parcours.ROOT
APPROCHES = ("N", "E", "S", "W")
INTERVALLE_S = 10
MESURES_PAR_MINUTE = 6
SCENARIO = "ms15-flux-complet"
VITESSE_LIMITE_KMH = 50.0  # INT_01 à INT_04 : 50 km/h (réseau v0)
# Une minute « congestionnée » : 3 véhicules par mesure, 9 km/h (ratio 0,18), occupation 0,7, file de 150 m. Une minute « fluide » : 45 km/h.
CONGESTION = {"vehicules": 3, "vitesse": 9.0, "occupation": 0.7, "file": 150.0}
FLUIDE = {"vehicules": 3, "vitesse": 45.0, "occupation": 0.1, "file": 0.0}
PLAN_NOMINAL = (True, True, True, True, False, False, False, False)  # 4 minutes congestionnées puis 4 fluides (l'hystérésis sort après 3)
ATTENTE_FENETRES_S = 150
ATTENTE_REPRISE_S = 240
SILENCE_MAX_S = 180  # `MAX_SILENCE_S` du service des feux (feux.md, section 5)
MARGE_SILENCE_S = 45


# --------------------------------------------------------------------------- les mesures
def capteurs(carrefour: int) -> list[tuple[str, str, str]]:
    """(approche, capteur, tronçon) de INT_0<n> : les capteurs et tronçons sont numérotés de 4 en 4 dans le réseau v0."""
    return [(a, f"SENSOR_{4 * (carrefour - 1) + i + 1:03d}", f"ROAD_{4 * (carrefour - 1) + i + 1:03d}") for i, a in enumerate(APPROCHES)]


def mesure(run: str, carrefour: int, capteur: str, troncon: str, fin: datetime, valeurs: dict) -> dict:
    millis = int(fin.timestamp()) * 1000
    return {
        "id": f"{run}:{capteur}:{millis}", "source": f"simulateur/{run}", "type": "novaria.iot.measurement.v1", "time": horodatage(fin),
        "subject": f"INT_{carrefour:02d}", "schema_version": "1.0", "correlation_id": f"corr-{millis}", "domain": "iot",
        "data": {
            "sensor_id": capteur, "road_segment_id": troncon, "intersection_id": f"INT_{carrefour:02d}", "interval_s": INTERVALLE_S,
            "vehicle_count": valeurs["vehicules"], "average_speed_kmh": valeurs["vitesse"], "occupancy_rate": valeurs["occupation"],
            "queue_length_m": valeurs["file"], "quality": {"status": "VALID"},
            "provenance": {"source_type": "SIMULATED", "run_id": run, "scenario_id": SCENARIO, "seed": 15},
        },
    }


def mesures_du_run(run: str, carrefour: int, debut: datetime, plan: tuple[bool, ...], premiere_minute: int = 0) -> list[dict]:
    """Six mesures par capteur et par minute, dans l'ordre du temps ; `plan[m]` vrai = minute congestionnée."""
    sortie = []
    for m, congestionnee in enumerate(plan, start=premiere_minute):
        for i in range(MESURES_PAR_MINUTE):
            fin = debut + timedelta(minutes=m, seconds=(i + 1) * INTERVALLE_S)
            sortie += [mesure(run, carrefour, c, t, fin, CONGESTION if congestionnee else FLUIDE) for _, c, t in capteurs(carrefour)]
    return sortie


def fenetre_attendue(congestionnee: bool) -> dict[str, float]:
    """Ce qu'une fenêtre d'une minute doit contenir : 6 mesures identiques, véhicules additionnés, le reste constant."""
    v = CONGESTION if congestionnee else FLUIDE
    return {"vehicle_count": float(v["vehicules"] * MESURES_PAR_MINUTE), "average_speed_kmh": v["vitesse"], "occupancy_rate": v["occupation"],
            "max_queue_length_m": v["file"], "sample_count": float(MESURES_PAR_MINUTE)}


def etats_attendus(plan: tuple[bool, ...]) -> list[str]:
    """L'état annoncé à chaque minute par la règle de seuils et son hystérésis (ADR-028), calculé avec **le classificateur du traitement**."""
    sys.path.insert(0, str(ROOT / "services" / "traitement"))
    from app.flux.classifier import Hysteresis, Observation, advance
    from app.flux.rules import DEFAULT_THRESHOLDS

    etat, sortie = Hysteresis(), []
    for m, congestionnee in enumerate(plan):
        valeurs = CONGESTION if congestionnee else FLUIDE
        etat = advance(etat, Observation(m * 60_000, 1.0, valeurs["vitesse"] / VITESSE_LIMITE_KMH, valeurs["vehicules"] * MESURES_PAR_MINUTE), DEFAULT_THRESHOLDS)
        sortie.append("FREE_FLOW" if etat.state == "UNKNOWN" else etat.state)
    return sortie


# --------------------------------------------------------------------------- la pile, avec ce que MS-15 ajoute à celle de CLD-13
class Pile(parcours.Pile):
    def creer_compte_role(self, nom: str, mot_de_passe: str, role: str) -> None:
        sortie = self.docker("exec", "-T", "traitement", "python", "-m", "app.cli", "create-user", nom, "--role", role,
                             entree=f"{mot_de_passe}\n{mot_de_passe}\n")
        if sortie.returncode or "Compte créé" not in sortie.stdout:
            raise Echec(f"création du compte refusée : {sortie.stdout.strip()[-120:]}")

    def sujet(self, sujet: str, delai_ms: int = 6000) -> list[dict]:
        """Tous les messages d'un sujet Kafka, du début (outil de Kafka dans son conteneur)."""
        lu = self.docker("exec", "-T", "kafka", "/opt/kafka/bin/kafka-console-consumer.sh", "--bootstrap-server", "kafka:9092", "--topic", sujet,
                         "--from-beginning", "--timeout-ms", str(delai_ms), delai=120)
        sortie = []
        for ligne in lu.stdout.splitlines():
            try:
                sortie.append(json.loads(ligne))
            except ValueError:
                continue  # ligne de journal de l'outil, pas un message
        return sortie

    def signal(self, jeton_acces: str, carrefour: int) -> dict | None:
        statut, corps = self.appel("GET", f"{self.passerelle}/api/v1/signals/INT_{carrefour:02d}", jeton_acces=jeton_acces)
        return corps if statut == 200 else None

    def sante(self) -> bool:
        """La collecte et la passerelle répondent (la chaîne est prête à recevoir des mesures)."""
        return self.appel("GET", f"{self.collecte}/api/v1/health")[0] == 200 and self.appel("GET", f"{self.passerelle}/api/v1/health")[0] == 200


@dataclass
class Contexte:
    pile: Pile
    nom: str = ""
    mot_de_passe: str = ""
    jeton: str = ""
    notes: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- aides
def attendre(condition: Callable[[], object], delai_s: float, pas_s: float = 3.0, message: str = "condition non atteinte") -> object:
    """Rend la première valeur « vraie » de `condition`, ou lève `Echec` après `delai_s`."""
    fin = time.monotonic() + delai_s
    while True:
        valeur = condition()
        if valeur:
            return valeur
        if time.monotonic() >= fin:
            raise Echec(f"{message} (après {delai_s:g} s)")
        time.sleep(pas_s)


def nouveau_run(prefixe: str = "ms15") -> str:
    return f"{prefixe}-{secrets.token_hex(3)}"


def debut_pour(minutes: int, maintenant: datetime | None = None) -> datetime:
    """Début d'une plage de `minutes` minutes dont la fin est passée depuis au moins 150 s."""
    return debut_de_minute_passee(maintenant or datetime.now(UTC), 150 + (minutes - 1) * 60)


def compter(pile: Pile, requete: str) -> int:
    lignes = pile.psql(requete)
    return int(lignes[0][0]) if lignes else 0


def fenetres(pile: Pile, run: str) -> list[dict]:
    lignes = pile.psql(
        "SELECT s.road_segment_id, to_char(f.window_start AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI'), f.vehicle_count, f.average_speed_kmh, "
        "f.occupancy_rate, f.max_queue_length_m, f.sample_count, f.congestion_state FROM dwh.fact_traffic_window f "
        "JOIN dwh.dim_road_segment s ON s.road_segment_key = f.road_segment_key "
        f"WHERE f.run_id = '{run}' AND f.window_size_s = 60 ORDER BY 1, 2;")
    noms = ("troncon", "minute", "vehicle_count", "average_speed_kmh", "occupancy_rate", "max_queue_length_m", "sample_count", "etat")
    return [dict(zip(noms, ligne, strict=True)) for ligne in lignes]


def alertes(pile: Pile, run: str) -> list[dict]:
    lignes = pile.psql("SELECT road_segment_id, rule_id, kind, severity, state, coalesce(resolution, ''), alert_id FROM alertes.alert "
                       f"WHERE run_id = '{run}' ORDER BY 1;")
    return [dict(zip(("troncon", "regle", "kind", "gravite", "etat", "resolution", "alert_id"), ligne, strict=True)) for ligne in lignes]


def recommandations(pile: Pile, run: str) -> list[dict]:
    return [e for e in pile.sujet("traffic.recommendations") if e.get("data", {}).get("provenance", {}).get("run_id") == run]


def audits_de_recommandations(pile: Pile, reference: str) -> int:
    return int(pile.mongo(f'db.audit_logs.countDocuments({{"action": "signal.recommendation", "details.reference_id": "{reference}"}})').split()[-1])


def derniere_recommandation(pile: Pile, carrefour: int) -> datetime | None:
    """L'instant de la recommandation la plus récente publiée pour ce carrefour (tous runs confondus), ou `None`."""
    instants = [datetime.strptime(e["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) for e in pile.sujet("traffic.recommendations")
                if e.get("data", {}).get("intersection_id") == f"INT_{carrefour:02d}"]
    return max(instants) if instants else None


def exiger_horloge(pile: Pile, carrefour: int, debut: datetime) -> None:
    """Le service des feux **ignore** une recommandation plus ancienne que la dernière qu'il a reçue pour un carrefour (feux.md, section 4) :
    un cas qui rejoue des minutes déjà dépassées ne verrait jamais ses feux changer. On le dit tout de suite plutôt que d'attendre en vain."""
    derniere = derniere_recommandation(pile, carrefour)
    if derniere and derniere >= debut + timedelta(minutes=1):
        attente = int((derniere - debut).total_seconds() // 60) + 1
        raise Echec(f"INT_{carrefour:02d} a déjà reçu une recommandation datée de {derniere:%H:%M} UTC, plus récente que les minutes de ce cas "
                    f"(à partir de {debut:%H:%M}) : le service des feux ignore les plus anciennes ; rejouer ce cas dans {attente} minute(s)")


def verifier_fenetres(trouvees: list[dict], plan: tuple[bool, ...], carrefour: int) -> list[str]:
    """Les écarts entre les fenêtres de l'entrepôt et ce qu'on attend des mesures envoyées (valeurs et états)."""
    problemes = []
    attendues = etats_attendus(plan)
    for _, _, troncon in capteurs(carrefour):
        propres = [f for f in trouvees if f["troncon"] == troncon]
        if len(propres) != len(plan):
            problemes.append(f"{troncon} : {len(propres)} fenêtres au lieu de {len(plan)}")
            continue
        for m, (f, congestionnee) in enumerate(zip(propres, plan, strict=True)):
            attendu = fenetre_attendue(congestionnee)
            for cle, valeur in attendu.items():
                if abs(float(f[cle]) - valeur) > 0.051:
                    problemes.append(f"{troncon} minute {m + 1} : {cle} = {f[cle]}, attendu {valeur:g}")
            if f["etat"] != attendues[m]:
                problemes.append(f"{troncon} minute {m + 1} : état {f['etat']}, attendu {attendues[m]}")
    return problemes[:8]


def attendre_pile_prete(pile: Pile, delai_s: int = ATTENTE_REPRISE_S) -> None:
    attendre(pile.sante, delai_s, 4, "la collecte et la passerelle ne répondent pas")


def attendre_fenetres(c: Contexte, run: str, attendues: int, delai_s: int = ATTENTE_FENETRES_S) -> list[dict]:
    return attendre(lambda: (lambda f: f if len(f) >= attendues else None)(fenetres(c.pile, run)), delai_s, 4,
                    f"moins de {attendues} fenêtres dans l'entrepôt pour {run}")  # type: ignore[return-value]


def compte(c: Contexte) -> None:
    """Crée (une fois) le compte jetable de rôle `operator` et ouvre une session."""
    if c.jeton:
        return
    c.nom, c.mot_de_passe = f"ms15-{secrets.token_hex(3)}", secrets.token_urlsafe(18)
    c.pile.creer_compte_role(c.nom, c.mot_de_passe, "operator")
    c.jeton = c.pile.connexion(c.nom, c.mot_de_passe)


def envoyer_run(c: Contexte, run: str, carrefour: int, debut: datetime, plan: tuple[bool, ...], premiere_minute: int = 0) -> list[dict]:
    mesures = mesures_du_run(run, carrefour, debut, plan, premiere_minute)
    statuts = Counter(c.pile.envoyer(mesures))
    _exiger(statuts == Counter({"ACCEPTED": len(mesures)}), f"statuts de la collecte : {dict(statuts)}")
    return mesures


# --------------------------------------------------------------------------- parcours nominal
def n1_compte(c: Contexte) -> str:
    compte(c)
    return f"compte {c.nom} (operator) créé par l'application, session ouverte par la passerelle : jeton reçu"


def n2_capteurs_et_collecte(c: Contexte) -> str:
    run, debut = nouveau_run(), debut_pour(len(PLAN_NOMINAL))
    exiger_horloge(c.pile, 1, debut)
    c.notes.update(run=run, debut=debut)
    mesures = envoyer_run(c, run, 1, debut, PLAN_NOMINAL)
    brutes = int(c.pile.mongo(f'db.raw_events.countDocuments({{"data.provenance.run_id": "{run}"}})').split()[-1])
    _exiger(brutes == len(mesures), f"copie brute dans MongoDB : {brutes} document(s) pour {len(mesures)} mesures")
    c.notes["mesures"] = len(mesures)
    return (f"{len(mesures)} mesures de 4 capteurs (INT_01, {len(PLAN_NOMINAL)} minutes, 4 congestionnées puis 4 fluides) acceptées (202 ACCEPTED), "
            f"{brutes} copies dans raw_events, run {run}")


def n3_traitement(c: Contexte) -> str:
    run, attendues = c.notes["run"], len(PLAN_NOMINAL) * 4
    trouvees = attendre_fenetres(c, run, attendues)
    _exiger(len(trouvees) == attendues, f"{len(trouvees)} fenêtres, {attendues} attendues")
    problemes = verifier_fenetres(trouvees, PLAN_NOMINAL, 1)
    _exiger(not problemes, "fenêtres différentes de l'attendu : " + " ; ".join(problemes))
    etats = Counter(f["etat"] for f in trouvees)
    return (f"{len(trouvees)} fenêtres d'une minute dans dwh.fact_traffic_window (4 tronçons × {len(PLAN_NOMINAL)} minutes), chacune de 6 mesures, "
            f"valeurs égales au recalcul, états égaux à ceux de la règle de seuils : {dict(etats)}")


def n4_alertes(c: Contexte) -> str:
    run = c.notes["run"]
    trouvees = attendre(lambda: (lambda a: a if len(a) >= 4 and all(x["etat"] == "RESOLVED" for x in a) else None)(alertes(c.pile, run)), 90, 4,
                        "les 4 alertes ne sont pas toutes créées puis résolues")
    _exiger(len(trouvees) == 4, f"{len(trouvees)} alertes, 4 attendues (une par approche)")  # type: ignore[arg-type]
    _exiger(sorted(a["troncon"] for a in trouvees) == [t for _, _, t in capteurs(1)], "les alertes ne couvrent pas exactement les 4 tronçons")  # type: ignore[union-attr]
    _exiger(all(a["regle"] == "congestion.persistante" and a["kind"] == "CONGESTION" and a["gravite"] == "WARNING" and a["resolution"] == "AUTO"
                for a in trouvees), "règle, type, gravité ou mode de résolution inattendus")  # type: ignore[union-attr]
    statut, corps = c.pile.appel("GET", f"{c.pile.passerelle}/api/v1/alerts?intersection_id=INT_01&limit=50", jeton_acces=c.jeton)
    _exiger(statut == 200 and corps is not None, f"GET /api/v1/alerts : HTTP {statut}")
    de_ce_run = [a for a in corps["items"] if a["provenance"]["run_id"] == run]  # type: ignore[index]
    _exiger(len(de_ce_run) == 4, f"l'API rend {len(de_ce_run)} alertes de ce run, 4 attendues")
    return ("4 alertes `congestion.persistante` (une par approche, aucun doublon), gravité WARNING, créées puis notifiées puis **résolues seules** "
            "au retour à la normale ; l'API les rend avec la même provenance")


def n5_recommandation(c: Contexte) -> str:
    run = c.notes["run"]
    trouvees = attendre(lambda: recommandations(c.pile, run) or None, 60, 5, "aucune recommandation de plan de feux sur traffic.recommendations")
    ids = [r["data"]["recommendation_id"] for r in trouvees]  # type: ignore[union-attr]
    _exiger(len(ids) == len(set(ids)), "une recommandation est publiée deux fois")
    for r in trouvees:  # type: ignore[union-attr]
        d = r["data"]
        _exiger(d["intersection_id"] == "INT_01" and d["method"]["kind"] == "WEBSTER_REFERENCE", "carrefour ou méthode inattendus")
        _exiger(30 <= d["cycle_s"] <= 120 and sum(p["duration_s"] for p in d["phases"]) == d["cycle_s"], f"plan incohérent : {d['phases']}")
        _exiger(all(10 <= p["duration_s"] <= 90 for p in d["phases"]), f"phase hors des bornes de sécurité : {d['phases']}")
    c.notes["recommandations"] = ids
    derniere = trouvees[-1]["data"]  # type: ignore[index]
    return (f"{len(ids)} recommandations `WEBSTER_REFERENCE` pour INT_01 (une par minute dégradée, identifiants distincts), plans sûrs "
            f"(cycle {derniere['cycle_s']} s, phases {[p['duration_s'] for p in derniere['phases']]} s)")


def n6_commande_de_feux(c: Contexte) -> str:
    ids = c.notes["recommandations"]
    etat = attendre(lambda: (lambda e: e if e and e["mode"] == "AUTOMATIC" and e["decision"]["reference_id"] in ids else None)(c.pile.signal(c.jeton, 1)),
                    60, 4, "les feux de INT_01 n'appliquent aucune recommandation du run")
    d = etat["decision"]  # type: ignore[index]
    _exiger(d["origin"] == "RECOMMENDATION" and d["outcome"] == "APPLIED", f"décision : {d}")
    evenements = [e for e in c.pile.sujet("signal.status") if e["id"] == f"reponse-recommendation-{d['reference_id']}"]
    _exiger(len(evenements) == 1, f"{len(evenements)} événement(s) signal.status pour cette recommandation, 1 attendu")
    journal = audits_de_recommandations(c.pile, d["reference_id"])
    _exiger(journal == 1, f"{journal} entrée(s) d'audit pour cette recommandation, 1 attendue")
    c.notes["reference"] = d["reference_id"]
    return (f"GET /api/v1/signals/INT_01 : mode AUTOMATIC, décision RECOMMENDATION appliquée (référence {d['reference_id'][:8]}…), "
            "un événement signal.status et une entrée d'audit, ni l'un ni l'autre en double")


def attendre_fenetre_de_commande(c: Contexte, carrefour: int) -> None:
    """Les garde-fous refusent de quitter une phase avant 10 s et pendant ses 4 dernières secondes (feux.md, section 3) : on attend le bon
    moment (phase en cours depuis 11 s au moins, et plus de 6 s à courir) pour que le test vise la règle voulue et pas le hasard de l'horloge."""
    def prete():
        e = c.pile.signal(c.jeton, carrefour)
        if not e:
            return False
        debut = datetime.strptime(e["phase_started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        fin = datetime.strptime(e["phase_ends_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        maintenant = datetime.now(UTC)
        return (maintenant - debut).total_seconds() >= 11 and (fin - maintenant).total_seconds() > 6
    attendre(prete, 60, 1, f"pas de fenêtre de commande sur INT_{carrefour:02d}")


def n7_commande_manuelle(c: Contexte) -> str:
    base = f"{c.pile.passerelle}/api/v1/signals/INT_01/commands"
    dangereuse = {"action": "SET_PHASE", "phase_id": "P1", "duration_s": 5, "reason": "essai MS-15 : durée trop courte"}
    attendre_fenetre_de_commande(c, 1)
    avant = c.pile.signal(c.jeton, 1)
    statut, corps = c.pile.appel("POST", base, dangereuse, c.jeton)
    _exiger(statut == 422 and (corps or {}).get("code") == "UNSAFE_COMMAND" and "PHASE_TOO_SHORT" in json.dumps(corps), f"commande dangereuse : HTTP {statut}, {str(corps)[:160]}")
    apres = c.pile.signal(c.jeton, 1)
    _exiger(apres["mode"] == avant["mode"] and apres["decision"] == avant["decision"], "l'état des feux a changé après une commande refusée")  # type: ignore[index]
    sure = {"action": "SET_PHASE", "phase_id": "P2", "duration_s": 30, "reason": "essai MS-15 : évacuation d'une file"}
    statut, corps = c.pile.appel("POST", base, sure, c.jeton)
    _exiger(statut == 202 and (corps or {}).get("status") == "APPLIED", f"commande sûre : HTTP {statut}, {str(corps)[:100]}")
    etat = c.pile.signal(c.jeton, 1)
    _exiger(etat["mode"] == "MANUAL" and etat["decision"]["origin"] == "MANUAL_COMMAND", f"après la commande : mode {etat['mode']}, décision {etat['decision']}")  # type: ignore[index]
    audit = int(c.pile.mongo('db.audit_logs.countDocuments({"action": "signal.command.SET_PHASE", "actor": {$exists: true}, '
                             '"details.reason": "essai MS-15 : évacuation d\'une file"})').split()[-1])
    _exiger(audit >= 1, "la commande n'est pas dans le journal d'audit")
    # Un refus transitoire (phase trop récente, dégagement) n'est pas une panne : on réessaie quelques secondes plus tard ; tout autre refus est un échec.
    attendre_fenetre_de_commande(c, 1)
    refus = []
    for _ in range(4):
        statut, corps = c.pile.appel("POST", base, {"action": "RESUME_AUTOMATIC", "reason": "essai MS-15 : fin de l'essai"}, c.jeton)
        if statut == 202:
            break
        texte = json.dumps(corps, ensure_ascii=False)
        motif = next((m for m in ("MIN_DURATION_NOT_ELAPSED", "CLEARANCE_IN_PROGRESS") if m in texte), None)
        _exiger(statut == 422 and motif, f"reprise automatique : HTTP {statut}, {texte[:160]}")
        refus.append(motif)
        time.sleep(6)
    _exiger(statut == 202, f"reprise automatique toujours refusée après {len(refus)} essais : {refus}")
    fin = c.pile.signal(c.jeton, 1)
    _exiger(fin["mode"] != "MANUAL", f"les feux restent en MANUAL après RESUME_AUTOMATIC : {fin['mode']}")  # type: ignore[index]
    reprise = f"RESUME_AUTOMATIC : 202, mode {fin['mode']}" if not refus else f"RESUME_AUTOMATIC : refusée {len(refus)} fois par un garde-fou ({refus[0]}), puis 202, mode {fin['mode']}"  # type: ignore[index]
    return ("commande dangereuse (phase de 5 s) : 422 UNSAFE_COMMAND, état des feux inchangé ; commande sûre (P2, 30 s) : 202 APPLIED, mode MANUAL, "
            f"journalisée avec son motif ; {reprise}")


# --------------------------------------------------------------------------- cas d'échec
def f1_message_invalide(c: Contexte) -> str:
    compte(c)
    run, debut = nouveau_run(), debut_pour(1)
    refus_avant = int(c.pile.mongo("db.rejects.countDocuments({})").split()[-1])
    constats = []
    # 1. illisible : pas du JSON
    statut, corps = c.pile.appel("POST", f"{c.pile.collecte}/api/v1/measurements", brut=b"{ceci n'est pas du json")
    _exiger(statut in (400, 422), f"message illisible : HTTP {statut}")
    constats.append(f"illisible : HTTP {statut}")
    # 2. hors contrat : nombre de véhicules négatif
    hors = mesure(run, 1, "SENSOR_001", "ROAD_001", debut + timedelta(seconds=10), CONGESTION | {"vehicules": -3})
    statut, corps = c.pile.appel("POST", f"{c.pile.collecte}/api/v1/measurements", hors)
    _exiger(statut == 422 and (corps or {}).get("code") == "VALIDATION_ERROR", f"hors contrat : HTTP {statut}, code {(corps or {}).get('code')}")
    constats.append("hors contrat : 422 VALIDATION_ERROR")
    _exiger(int(c.pile.mongo(f'db.raw_events.countDocuments({{"id": "{hors["id"]}"}})').split()[-1]) == 0, "la mesure invalide est dans raw_events")
    refus_apres = int(c.pile.mongo("db.rejects.countDocuments({})").split()[-1])
    _exiger(refus_apres > refus_avant, f"aucun rejet tracé (rejects {refus_avant} puis {refus_apres})")
    constats.append(f"rejet tracé dans MongoDB (rejects {refus_avant} à {refus_apres})")
    # 3. déjà reçue : un identifiant n'est jamais compté deux fois
    bonne = mesure(run, 1, "SENSOR_001", "ROAD_001", debut + timedelta(seconds=10), FLUIDE)
    premier, second = c.pile.envoyer([bonne]), c.pile.envoyer([bonne])
    _exiger(premier == ["ACCEPTED"] and second == ["DUPLICATE"], f"mesure envoyée deux fois : {premier} puis {second}")
    brutes = int(c.pile.mongo(f'db.raw_events.countDocuments({{"id": "{bonne["id"]}"}})').split()[-1])
    _exiger(brutes == 1, f"{brutes} copies de la mesure envoyée deux fois, 1 attendue")
    constats.append("mesure envoyée deux fois : ACCEPTED puis DUPLICATE, une seule copie")
    time.sleep(20)
    _exiger(compter(c.pile, f"SELECT count(*) FROM alertes.alert WHERE run_id = '{run}';") == 0, "une alerte a été créée par des messages invalides")
    return " ; ".join(constats) + " ; aucune alerte créée"


def f2_service_arrete(c: Contexte) -> str:
    compte(c)
    pile, run, debut = c.pile, nouveau_run(), debut_pour(len(PLAN_NOMINAL))
    constats = []
    pile.docker("stop", "alerte-worker")
    try:
        mesures = envoyer_run(c, run, 2, debut, PLAN_NOMINAL)
        attendues = len(PLAN_NOMINAL) * 4
        trouvees = attendre_fenetres(c, run, attendues)
        _exiger(not verifier_fenetres(trouvees, PLAN_NOMINAL, 2), "fenêtres différentes de l'attendu pendant l'arrêt")
        constats.append(f"alerte-worker arrêté : {len(mesures)} mesures acceptées et {attendues} fenêtres calculées (la chaîne continue)")
        time.sleep(25)
        _exiger(len(alertes(pile, run)) == 0, "des alertes existent alors que leur service est arrêté")
        constats.append("aucune alerte tant que le service est arrêté")
        statut, _ = pile.appel("GET", f"{pile.passerelle}/api/v1/alerts?limit=1", jeton_acces=c.jeton)
        _exiger(statut == 200, f"l'API des alertes (service `alerte`) ne répond plus : HTTP {statut}")
        constats.append("l'API des alertes répond toujours (200)")
    finally:
        pile.docker("start", "alerte-worker")
    trouvees = attendre(lambda: (lambda a: a if len(a) >= 4 and all(x["etat"] == "RESOLVED" for x in a) else None)(alertes(pile, run)), ATTENTE_REPRISE_S, 5,
                        "les alertes n'arrivent pas après le redémarrage")
    _exiger(len(trouvees) == 4 and len({a["troncon"] for a in trouvees}) == 4, f"{len(trouvees)} alertes, 4 attendues, une par tronçon")  # type: ignore[arg-type]
    constats.append("redémarrage : les 4 alertes arrivent, résolues, **sans perte et sans doublon** (une par tronçon, lues depuis les décalages enregistrés)")
    return " ; ".join(constats)


def f3_broker_indisponible(c: Contexte) -> str:
    pile, run, debut = c.pile, nouveau_run(), debut_pour(2)
    mesures = mesures_du_run(run, 3, debut, (True, True))
    constats = []
    pile.docker("stop", "kafka")
    try:
        statuts = [pile.appel("POST", f"{pile.collecte}/api/v1/measurements", m)[0] for m in mesures[:8]]
        _exiger(set(statuts) == {503}, f"collecte sans broker : {Counter(statuts)}")
        brutes = int(pile.mongo(f'db.raw_events.countDocuments({{"data.provenance.run_id": "{run}"}})').split()[-1])
        _exiger(brutes == 0, f"{brutes} copie(s) dans raw_events alors que la mesure n'est pas publiée")
        constats.append("Kafka arrêté : la collecte répond 503 à chaque mesure et n'en garde aucune copie (rien n'est « accepté » sans être publié)")
    finally:
        pile.docker("start", "kafka")
    attendre(lambda: pile.appel("POST", f"{pile.collecte}/api/v1/measurements", mesures[0])[0] == 202, ATTENTE_REPRISE_S, 5,
             "la collecte ne publie plus après le retour du broker")
    statuts = Counter(pile.envoyer(mesures))
    _exiger(statuts == Counter({"ACCEPTED": len(mesures) - 1, "DUPLICATE": 1}), f"renvoi des mesures : {dict(statuts)}")
    constats.append(f"retour du broker : le renvoi des {len(mesures)} mesures donne {len(mesures) - 1} ACCEPTED et 1 DUPLICATE (celle qui avait servi de sonde)")
    trouvees = attendre_fenetres(c, run, 8)
    vehicules = sum(int(float(f["vehicle_count"])) for f in trouvees)
    _exiger(len(trouvees) == 8 and vehicules == 8 * 18, f"{len(trouvees)} fenêtres, {vehicules} véhicules (8 fenêtres et 144 véhicules attendus)")
    brutes = int(pile.mongo(f'db.raw_events.countDocuments({{"data.provenance.run_id": "{run}"}})').split()[-1])
    _exiger(brutes == len(mesures), f"{brutes} copies dans raw_events, {len(mesures)} attendues")
    constats.append("8 fenêtres, 144 véhicules, 48 copies brutes : exactement ce qu'on attend, aucune mesure perdue ni comptée deux fois")
    return " ; ".join(constats)


def _feux_automatiques(c: Contexte, carrefour: int, run: str, debut: datetime) -> None:
    """Met les feux d'un carrefour en mode automatique avec quelques minutes congestionnées (préparation de F5 et F6)."""
    exiger_horloge(c.pile, carrefour, debut)
    envoyer_run(c, run, carrefour, debut, (True, True, True, True))
    attendre(lambda: (lambda e: e and e["mode"] == "AUTOMATIC")(c.pile.signal(c.jeton, carrefour)), 90, 4, f"les feux de INT_{carrefour:02d} ne passent pas en automatique")


def f4_indicateurs_en_retard(c: Contexte) -> str:
    """Flux arrêté : les indicateurs sont en retard, puis rattrapés. Garde les observations dans le contexte pour F5."""
    compte(c)
    pile, run = c.pile, nouveau_run()
    debut = debut_pour(len(PLAN_NOMINAL) + 4)
    _feux_automatiques(c, 4, run, debut)
    constats = ["avant l'arrêt : feux de INT_04 en AUTOMATIC"]
    fenetres_avant = len(fenetres(pile, run))
    pile.docker("stop", "traitement-flux")
    arret = time.monotonic()
    try:
        envoyer_run(c, run, 4, debut, PLAN_NOMINAL[4:], premiere_minute=4)
        time.sleep(30)
        pendant = len(fenetres(pile, run))
        _exiger(pendant == fenetres_avant, f"{pendant - fenetres_avant} fenêtre(s) calculée(s) alors que le flux est arrêté")
        constats.append(f"flux arrêté : 96 mesures de plus acceptées par la collecte, aucune fenêtre calculée ({pendant} avant et pendant l'arrêt)")
        degrade = attendre(lambda: (lambda e: e if e and e["mode"] == "DEGRADED_FIXED_PLAN" else None)(pile.signal(c.jeton, 4)), SILENCE_MAX_S + MARGE_SILENCE_S, 5,
                           "les feux ne reviennent pas au plan fixe")
        c.notes["delai_degrade_s"] = round(time.monotonic() - arret)
        c.notes["decision_degradee"] = degrade["decision"]  # type: ignore[index]
    finally:
        pile.docker("start", "traitement-flux")
    c.notes["f4_run"], c.notes["f4_debut"] = run, debut
    trouvees = attendre_fenetres(c, run, 8 * 4)
    _exiger(len(trouvees) == 32, f"{len(trouvees)} fenêtres après le rattrapage, 32 attendues")
    _exiger(not verifier_fenetres(trouvees, (True, True, True, True) + PLAN_NOMINAL[4:], 4), "fenêtres rattrapées différentes de l'attendu")
    doublons = [k for k, n in Counter((f["troncon"], f["minute"]) for f in trouvees).items() if n > 1]
    _exiger(not doublons, f"fenêtres en double : {doublons[:3]}")
    constats.append("redémarrage du flux : 32 fenêtres (4 tronçons × 8 minutes), valeurs et états égaux à l'attendu, **sans perte ni doublon**, les mesures reçues pendant l'arrêt comprises")
    return " ; ".join(constats)


def f5_mode_degrade_des_feux(c: Contexte) -> str:
    _exiger("decision_degradee" in c.notes, "F4 n'a pas observé le mode dégradé (cas non joué ou échoué)")
    d = c.notes["decision_degradee"]
    _exiger(d["origin"] == "FIXED_PLAN_FALLBACK" and d["outcome"] == "APPLIED", f"décision en mode dégradé : {d}")
    delai = c.notes["delai_degrade_s"]
    _exiger(SILENCE_MAX_S - 40 <= delai <= SILENCE_MAX_S + MARGE_SILENCE_S, f"retour au plan fixe après {delai} s, autour de {SILENCE_MAX_S} s attendu")
    evenements = [e for e in c.pile.sujet("signal.status") if e["subject"] == "INT_04" and (e["data"].get("decision") or {}).get("origin") == "FIXED_PLAN_FALLBACK"]
    _exiger(len(evenements) >= 1, "aucun signal.status de retour au plan fixe sur le bus")
    journal = int(c.pile.mongo('db.audit_logs.countDocuments({"action": "signal.fixed_plan_fallback", "details.intersection_id": "INT_04"})').split()[-1])
    _exiger(journal >= 1, "le retour au plan fixe n'est pas dans le journal d'audit")
    reprise = attendre(lambda: (lambda e: e if e and e["mode"] == "AUTOMATIC" and e["decision"]["origin"] == "RECOMMENDATION" else None)(c.pile.signal(c.jeton, 4)),
                       90, 4, "les feux ne reviennent pas en automatique avec les indicateurs rattrapés")
    return (f"sans recommandation depuis {delai} s (silence maximal {SILENCE_MAX_S} s) : DEGRADED_FIXED_PLAN, décision FIXED_PLAN_FALLBACK, annoncé sur signal.status et "
            f"journalisé ; avec les indicateurs rattrapés, les feux repassent seuls en AUTOMATIC (recommandation {reprise['decision']['reference_id'][:8]}…)")  # type: ignore[index]


def f6_redemarrage_des_feux(c: Contexte) -> str:
    compte(c)
    pile, run, run2 = c.pile, nouveau_run(), nouveau_run()
    debut = debut_pour(8)  # minutes 0 à 3 pour le premier lot, 4 à 7 pour celui qui arrive pendant l'arrêt : les feux ignorent les recommandations plus anciennes
    _feux_automatiques(c, 5, run, debut)
    avant = [r["data"]["recommendation_id"] for r in recommandations(pile, run)]
    _exiger(avant, "aucune recommandation avant l'arrêt")
    constats = [f"avant l'arrêt : {len(avant)} recommandation(s) publiée(s), feux de INT_05 en AUTOMATIC"]
    demarrages_avant = int(pile.mongo('db.audit_logs.countDocuments({"action": "signal.startup", "details.intersection_id": "INT_05"})').split()[-1])
    pile.docker("stop", "reponse")
    try:
        envoyer_run(c, run2, 5, debut, (True, True, True, True), premiere_minute=4)
        recues = attendre(lambda: recommandations(pile, run2) or None, 60, 5, "le traitement ne publie pas pendant l'arrêt des feux")
        constats.append(f"service des feux arrêté : le traitement publie {len(recues)} recommandation(s) du lot suivant (elles attendent sur le bus)")  # type: ignore[arg-type]
    finally:
        pile.docker("start", "reponse")
    attendre(lambda: pile.signal(c.jeton, 5), ATTENTE_REPRISE_S, 5, "l'API des feux ne répond pas après le redémarrage")
    attendre(lambda: (lambda e: e if e and e["decision"]["reference_id"] in {r["data"]["recommendation_id"] for r in recommandations(pile, run2)} else None)(
        pile.signal(c.jeton, 5)), 90, 4, "la recommandation reçue pendant l'arrêt n'est pas appliquée")
    constats.append("redémarrage : STARTUP au plan fixe, puis la recommandation arrivée pendant l'arrêt est appliquée (aucune perte)")
    rejouees = [r for r in avant if audits_de_recommandations(pile, r) > 1]
    _exiger(not rejouees, f"recommandations d'avant l'arrêt traitées plus d'une fois : {rejouees}")
    _exiger(audits_de_recommandations(pile, avant[-1]) == 1, "la dernière recommandation d'avant l'arrêt n'a pas son entrée d'audit")
    demarrages = int(pile.mongo('db.audit_logs.countDocuments({"action": "signal.startup", "details.intersection_id": "INT_05"})').split()[-1])
    _exiger(demarrages > demarrages_avant, f"aucune entrée signal.startup de plus pour INT_05 ({demarrages_avant} avant, {demarrages} après)")
    nouvelles = [r["data"]["recommendation_id"] for r in recommandations(pile, run2)]
    doubles = [r for r in nouvelles if audits_de_recommandations(pile, r) > 1]
    _exiger(not doubles, f"recommandations d'après l'arrêt appliquées plus d'une fois : {doubles}")
    constats.append(f"redémarrage journalisé (signal.startup) ; aucune des {len(avant)} recommandations d'avant ni des {len(nouvelles)} d'après n'a plus d'une entrée d'audit : rien n'est rejoué")
    return " ; ".join(constats)


# --------------------------------------------------------------------------- orchestration
CAS: tuple[tuple[str, str, Callable[[Contexte], str]], ...] = (
    ("N1", "Compte opérateur", n1_compte),
    ("N2", "Capteurs simulés et collecte", n2_capteurs_et_collecte),
    ("N3", "Traitement : fenêtres de l'entrepôt", n3_traitement),
    ("N4", "Alertes : créées puis résolues", n4_alertes),
    ("N5", "Recommandation de plan de feux", n5_recommandation),
    ("N6", "Commande de feux par la recommandation", n6_commande_de_feux),
    ("N7", "Commande manuelle d'un opérateur", n7_commande_manuelle),
    ("F1", "Message invalide", f1_message_invalide),
    ("F2", "Service arrêté (alerte-worker)", f2_service_arrete),
    ("F3", "Broker indisponible (Kafka)", f3_broker_indisponible),
    ("F4", "Indicateurs en retard (flux arrêté)", f4_indicateurs_en_retard),
    ("F5", "Mode dégradé des feux", f5_mode_degrade_des_feux),
    ("F6", "Redémarrage du service des feux", f6_redemarrage_des_feux),
)
NOMINAUX = ("N1", "N2", "N3", "N4", "N5", "N6", "N7")
DEPENDANCES = {"F5": "F4"}  # F5 lit ce que F4 a observé


def executer(pile: Pile, ids: tuple[str, ...] | None = None, afficher: Callable[[Resultat], None] = lambda r: None) -> list[Resultat]:
    """Joue les cas dans l'ordre. Un cas dont un prérequis a échoué est signalé « non joué », pas ignoré."""
    choisis = [cas for cas in CAS if ids is None or cas[0] in ids]
    contexte = Contexte(pile)
    resultats: list[Resultat] = []
    reussis: dict[str, bool] = {}
    nominal_ok = True
    try:
        attendre_pile_prete(pile, 60)
        for identifiant, titre, fonction in choisis:
            requis = DEPENDANCES.get(identifiant)
            if identifiant in NOMINAUX[1:] and not nominal_ok:
                resultat = Resultat(identifiant, titre, False, "non joué : une étape précédente du parcours nominal a échoué")
            elif requis and not reussis.get(requis, False) and requis in {c[0] for c in choisis}:
                resultat = Resultat(identifiant, titre, False, f"non joué : {requis} n'a pas réussi")
            else:
                resultat = parcours._jouer(identifiant, titre, fonction, contexte)
                if identifiant.startswith("F"):  # un cas d'échec qui a arrêté un service doit le laisser reparti : on attend la chaîne avant le suivant
                    try:
                        attendre_pile_prete(pile, ATTENTE_REPRISE_S)
                    except Echec as erreur:
                        resultat = Resultat(resultat.cas, resultat.titre, False, f"{resultat.preuve} | la pile ne répond plus après le cas : {erreur}", resultat.duree_s)
            if identifiant in NOMINAUX and not resultat.ok:
                nominal_ok = False
            reussis[identifiant] = resultat.ok
            resultats.append(resultat)
            afficher(resultat)
    finally:
        if contexte.nom:
            try:
                pile.supprimer_compte(contexte.nom)
            except Echec:
                pass
    return resultats


def ligne(resultat: Resultat) -> str:
    return parcours.ligne(resultat)

