"""Rédaction de la fiche de provenance `PROVENANCE.md` (ADR-027, section 4) à partir du manifeste du jeu.

Le texte est déterministe : il ne dépend que du manifeste (lui-même sans date ni chemin de machine).
"""

from jeu_entrainement import lignes
from jeu_entrainement.catalogue import ENSEMBLES

LIBELLES_ENSEMBLE = {"train": "entraînement", "validation": "validation", "test": "test"}
LIBELLES_SCENARIO = {"journee-calme": "journée calme", "heure-de-pointe": "heure de pointe", "incident-ponctuel": "incident ponctuel"}


def pourcent(partie: int, total: int) -> str:
    return "0 %" if total == 0 else f"{100 * partie / total:.1f} %".replace(".", ",")


def nombre(valeur: int) -> str:
    return f"{valeur:,}".replace(",", " ")


def rediger(m: dict) -> str:
    fichiers, runs, origine = m["fichiers"], m["runs"], m["origine"]
    total = sum(f["lignes"] for f in fichiers.values())
    anomalies_par_type = {}
    for run in runs:
        for texte in run["anomalies"]:
            anomalies_par_type.setdefault(texte.partition(":")[0], []).append(run["run_id"])
    sections = []
    ajouter = sections.append

    ajouter(f"""# Fiche de provenance du jeu `{m['dataset_id']}` (version {m['version']})

Issue : IA-08 · Décision : [ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), règles 1 à 8 · Fichier généré par `python3 ml/src/construire_jeu.py` : ne pas l'écrire à la main.

Abréviations : IA (intelligence artificielle), SHA-256 (Secure Hash Algorithm, empreinte de 256 bits), UTC (Temps universel coordonné).

> **Donnée simulée.** Tout ce jeu vient du simulateur du dépôt. Il ne décrit aucun trafic réel et ne doit jamais être présenté comme tel. Un modèle entraîné sur le simulateur apprend le simulateur : le résultat prouve la chaîne de bout en bout, pas la précision en conditions réelles.""")

    ajouter(f"""## 1. Identifiant et version

| Rubrique | Valeur |
|---|---|
| `dataset_id` | `{m['dataset_id']}` |
| Version | {m['version']} |
| Type de source (`source_type`) | `{origine['source_type']}` |
| Lignes | {nombre(total)} (une ligne par tronçon et par minute) |
| Colonnes | {len(m['colonnes'])} (dictionnaire de données, section 9) |
| Empreinte du jeu | `{m['empreinte_du_jeu']}` (section 9 de cette fiche) |""")

    ajouter(f"""## 2. Origine

| Rubrique | Valeur |
|---|---|
| Générateur | `{origine['generateur']}` version {origine['version_du_generateur']} (issue MS-07) |
| Constructeur du jeu | `ml/src/jeu_entrainement`, version {origine['version_du_constructeur']} |
| Agrégation en fenêtres | `{origine['moteur_de_fenetres']}` : le moteur du traitement en flux, rejoué sur les messages de chaque run, dans l'ordre de livraison |
| Vérité terrain | l'état de congestion **voulu par le scénario** (`verite-terrain` du simulateur), pas la règle de seuils de l'ADR-028 |
| Graines | {', '.join(str(r['seed']) for r in runs)} (une par run, toutes différentes) |
| Format | {origine['format']} |

Le jeu se **régénère** par sa graine : le dépôt garde le catalogue (`ml/src/jeu_entrainement/catalogue.py`), cette fiche et le manifeste, pas les fichiers Parquet ([ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), règle 6).""")

    ajouter("""## 3. Licence et conditions

| Rubrique | Valeur |
|---|---|
| Données | synthétiques, produites par le code du dépôt : aucune donnée de tiers, aucune licence de données à respecter |
| Redistribution | possible, puisque le jeu se régénère ; **la licence du dépôt n'est pas encore fixée** (aucun fichier `LICENSE`) : à décider avant toute publication |
| Données personnelles | aucune |""")

    lignes_scenarios = ["| Scénario | Runs | Plage horaire (UTC, 20/10/2026) | Durée | Ce que le scénario impose |", "|---|---|---|---|---|"]
    imposes = {
        "journee-calme": "tous les tronçons restent fluides",
        "heure-de-pointe": "les approches Nord et Ouest se saturent de 07:20 à 08:50, décalage de 0 à 12 minutes par tronçon",
        "incident-ponctuel": "incident sur ROAD_005 de 08:10 à 08:35, les autres approches du carrefour INT_02 ralentissent",
    }
    for scenario, libelle in LIBELLES_SCENARIO.items():
        ceux = [r for r in runs if r["scenario_id"] == scenario]
        if not ceux:
            continue
        debut = ceux[0]["debut"][11:16]
        heures = ceux[0]["duree_s"] // 3600
        fin = f"{(int(debut[:2]) + heures) % 24:02d}:{debut[3:]}"
        lignes_scenarios.append(f"| {libelle} (`{scenario}`) | {len(ceux)} | {debut} à {fin} | {heures} h | {imposes[scenario]} |")
    ajouter("## 4. Période et couverture\n\n" + "\n".join(lignes_scenarios) + """

Réseau fixe du simulateur : 6 carrefours, **24 tronçons d'approche**, un capteur par tronçon, une mesure toutes les 10 secondes. Pas de temps du jeu : **1 minute** (6 mesures attendues par fenêtre). Un seul jour simulé : le 20/10/2026.""")

    anomalies = "\n".join(
        f"| `{type_}` | {', '.join(f'`{r}`' for r in ids)} |"
        for type_, ids in sorted(anomalies_par_type.items())
    )
    ajouter(f"""### Catalogue des runs

Les trois scénarios sont combinés avec les trois anomalies de l'ADR-027 (règle 8), injectées sur un capteur à la fois :

| Anomalie injectée | Runs |
|---|---|
{anomalies}

| Run | Scénario | Graine | Ensemble | Anomalies | Lignes |
|---|---|---|---|---|---|
""" + "\n".join(
        f"| `{r['run_id']}` | {LIBELLES_SCENARIO.get(r['scenario_id'], r['scenario_id'])} | {r['seed']} | {LIBELLES_ENSEMBLE[r['ensemble']]} | {r['note']} | {nombre(r['lignes'])} |"
        for r in runs
    ))

    groupes = []
    for nom, colonnes in lignes.GROUPES.items():
        groupes.append(f"| {nom} | {', '.join(f'`{c.nom}`' for c in colonnes)} |")
    ajouter("""## 5. Variables et unités

Les colonnes et leurs définitions sont celles du [dictionnaire de données](../../../docs/03-donnees/dictionnaire-de-donnees.md), section 9 ; les mesures ont les définitions de la section 6 (même moteur de calcul, mêmes arrondis que l'entrepôt).

| Groupe | Colonnes |
|---|---|
""" + "\n".join(groupes) + """

Notes :
- `window_start` : début de la fenêtre, UTC, en microsecondes ; `flow_veh_per_min` : véhicules par minute ; `average_speed_kmh` : km/h ; `occupancy_rate` : de 0 à 1 ; `max_queue_length_m` : mètres ; `speed_ratio` : vitesse moyenne divisée par la vitesse fluide (0 à 9,999).
- Une valeur qui n'existe pas est **absente** (`null`) : route vide, début ou fin de run, historique pas encore disponible. Rien n'est inventé.
- `speed_ratio_lag1` à `lag5` et `flow_lag1` à `lag5` : la valeur des 1 à 5 minutes **précédentes** du même tronçon. `speed_ratio_ma5`, `speed_ratio_ma15`, `flow_ma5`, `flow_ma15` : moyenne des valeurs présentes des 5 ou 15 minutes précédentes. Aucune ne regarde la ligne elle-même ni l'avenir.
- `speed_ratio_h5` et `speed_ratio_h15` : le `speed_ratio` du même tronçon 5 et 15 minutes plus tard (réponses de la prévision).
- `label_state` : `FREE_FLOW`, `SLOW` ou `CONGESTED`, l'état voulu par le scénario pour cette minute (l'état le plus fréquent de ses 6 intervalles ; à égalité, le dernier).""")

    lignes_decoupage = ["| Ensemble | Fichier | Runs | Lignes | `FREE_FLOW` | `SLOW` | `CONGESTED` |", "|---|---|---|---|---|---|---|"]
    for ensemble in ENSEMBLES:
        fichier = fichiers[f"{ensemble}.parquet"]
        etats = fichier["etats"]
        lignes_decoupage.append(
            f"| {LIBELLES_ENSEMBLE[ensemble]} | `{ensemble}.parquet` | {len(fichier['runs'])} | {nombre(fichier['lignes'])} | "
            + " | ".join(f"{pourcent(etats.get(e, 0), fichier['lignes'])}" for e in lignes.ETATS) + " |"
        )
    ajouter("## 6. Découpage : par run et par scénario\n\n" + "\n".join(lignes_decoupage) + """

| Règle | Garantie |
|---|---|
| Par run | un `run_id` appartient à **un seul** ensemble ; une graine aussi (vérifié par `ml/tests/test_catalogue.py` et sur les fichiers écrits par `ml/tests/test_construire.py`) |
| Par scénario | chaque ensemble contient des runs de **chacun** des trois scénarios |
| Jamais par lignes | des minutes voisines d'un même run se ressemblent : un tirage au hasard ferait fuir le test vers l'entraînement |

Les parts d'états sont presque identiques d'un ensemble à l'autre : les runs d'un même scénario ont le même calendrier d'états (section 8), et chaque ensemble a les mêmes scénarios dans les mêmes proportions.""")

    qualite = ["| Run | Lignes | Fenêtres vides | Fenêtres incomplètes | Minutes à états mélangés | Messages livrés | Doublons écartés | Refusés (en retard) | Intervalles muets |", "|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        q, mo = r["qualite"], r["moteur"]
        qualite.append(f"| `{r['run_id']}` | {nombre(r['lignes'])} | {q['fenetres_vides']} | {q['fenetres_incompletes']} | {q['etats_melanges']} | {nombre(r['messages_livres'])} | {mo['duplicates']} | {mo['late']} | {r['capteur_muet_intervalles']} |")
    absents = ["| Ensemble | " + " | ".join(f"`{n}`" for n in ("average_speed_kmh", "speed_ratio", "speed_ratio_lag5", "speed_ratio_h15")) + " |", "|---|---|---|---|---|"]
    for ensemble in ENSEMBLES:
        fichier = fichiers[f"{ensemble}.parquet"]
        valeurs = fichier["valeurs_absentes"]
        absents.append(f"| {LIBELLES_ENSEMBLE[ensemble]} | " + " | ".join(pourcent(valeurs[n], fichier["lignes"]) for n in ("average_speed_kmh", "speed_ratio", "speed_ratio_lag5", "speed_ratio_h15")) + " |")
    ajouter("## 7. Qualité mesurée\n\n" + "\n".join(qualite) + """

Lecture : une **fenêtre vide** n'a reçu aucune mesure (capteur muet) ; une **fenêtre incomplète** en a reçu moins de 6 ; une **minute à états mélangés** contient des intervalles d'états voulus différents (le changement d'état tombe dans la minute). Un **doublon écarté** est une copie d'un message déjà reçu ; un message **refusé en retard** arrive après la fermeture de sa fenêtre (règle DQ-04 du traitement en flux) et n'entre pas dans le jeu.

Valeurs absentes (part des lignes) :

""" + "\n".join(absents))

    ajouter("""## 8. Limites

| Limite | Conséquence |
|---|---|
| Données simulées | un bon résultat prouve la chaîne, pas la précision réelle (ADR-027) |
| La graine ne change que le bruit, pas le calendrier des états | deux runs d'un même scénario ont la même suite d'états voulus : le test mesure la généralisation à un **autre bruit**, pas à un **scénario jamais vu**. Évaluer sur une situation nouvelle demande un quatrième scénario dans le simulateur |
| Un seul jour, un seul réseau de 24 tronçons | `iso_day_of_week`, `is_weekend` et `is_holiday` ne varient pas : ces colonnes ne portent aucune information dans la version 1 |
| `hour_of_day` suit le scénario | les plages horaires diffèrent d'un scénario à l'autre (section 4) : un modèle peut deviner le scénario par l'heure |
| Classes déséquilibrées | `CONGESTED` est rare (section 6) ; l'exactitude seule est trompeuse, utiliser le rappel et la précision par classe |
| Un capteur muet donne une fenêtre vide | la colonne ne distingue pas une route sans véhicule d'un capteur silencieux (la complétude n'est pas dans les colonnes du dictionnaire) |
| Retards et doublons jugés comme en production | un message très en retard est refusé : le jeu n'en garde que l'effet (fenêtre incomplète) |
| Réponses de prévision absentes en fin de run | les 5 ou 15 dernières minutes de chaque run n'ont pas de `speed_ratio_h5` ou `h15` |
| Écrivain Parquet maison | le format est validé en relecture avec `pyarrow` (outil d'essai, pas une dépendance) ; non vérifié avec d'autres lecteurs |
| Windows et macOS | non vérifiés : l'empreinte a été relevée sous Linux ; elle doit être la même ailleurs (calculs décimaux et flottants IEEE, aucun fichier compressé) |""")

    liste = "\n".join(f"| `{nom}` | `{f['sha256']}` | {nombre(f['octets'])} | {nombre(f['lignes'])} |" for nom, f in sorted(fichiers.items()))
    ajouter(f"""## 9. Empreinte

| Fichier | SHA-256 | Octets | Lignes |
|---|---|---|---|
{liste}

**Empreinte du jeu** : `{m['empreinte_du_jeu']}` = SHA-256 du texte « nom de fichier, espace, SHA-256 » (une ligne par fichier, triées par nom, fin de ligne LF).

La même empreinte est écrite dans `manifest.json`. L'enregistrement de l'empreinte dans MongoDB (`model_runs`, ADR-027 règle 5) se fait à l'entraînement d'un modèle (IA-04, IA-05) : un document par entraînement cite `dataset_id` et cette empreinte.

### Régénérer et vérifier

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Construire le jeu | `python3 ml/src/construire_jeu.py` | `py -3 ml/src/construire_jeu.py` |
| Comparer | `sha256sum data/datasets/{m['dataset_id']}/*.parquet` | `Get-FileHash data\\datasets\\{m['dataset_id']}\\*.parquet` |
| Lancer les tests | `python3 -m unittest discover -s ml/tests -t ml` | `py -3 -m unittest discover -s ml\\tests -t ml` |

Si un SHA-256 diffère de celui de la section ci-dessus, le jeu n'est pas celui de cette fiche : le code, le simulateur ou le catalogue a changé. Reconstruire, relire le diff de cette fiche, puis la commiter avec le code.
""")
    return "\n\n".join(sections)
