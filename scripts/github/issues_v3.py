"""Backlog v3 (20/10/2026) : exécution locale d'abord, congestion avant prévision, travail à deux.

Ce module ajoute au backlog :
  - 13 issues nouvelles (NEW_IDS) : LOC-01 à LOC-06, DAT-10, IA-08 à IA-11, GES-19, DOC-11 ;
  - des amendements (AMENDMENTS) sur des issues existantes, appliqués en mémoire par `apply_amendments`.

Il ne contacte pas GitHub : c'est `sync_backlog.py` qui crée, commente et étiquette.
Décisions : docs/01-architecture/adr/ADR-023 à ADR-028 ; registre des demandes C-05 à C-07.
"""
from __future__ import annotations

import issues_data
from issues_data import I

ADR023 = "docs/01-architecture/adr/ADR-023-execution-locale-d-abord.md"
ADR025 = "docs/01-architecture/adr/ADR-025-equivalents-locaux-des-services-aws.md"
DEV = "`python3 scripts/dev/dev.py` (Linux) ou `py -3 scripts/dev/dev.py` (Windows)"

# --------------------------------------------------------------------------------------------------
# Issues nouvelles
# --------------------------------------------------------------------------------------------------
NEW_ISSUES = [
    # ------------------------------------------------------------ M1 : démarrage du binôme
    I("LOC-01", "PostgreSQL local : démarrage, migrations et droits vérifiés sur Windows", 1, "cloud", "D", "tache", "P0",
      ["Suivre `docs/08-exploitation/poste-de-travail.md` : `check-tools` puis `init-env`",
       "Lancer `db-up` puis `db-check` : les 9 lignes `postgres` doivent être [OK]",
       "Ouvrir `psql` et lire `ops.schema_migrations` : 5 migrations appliquées",
       "Se connecter avec le compte `svc_app` depuis un script Python (adresse lue dans `.env`, jamais copiée dans le dépôt)",
       "Noter le résultat dans l'issue et corriger la documentation par pull request si une étape a échoué"],
      "Les 9 contrôles PostgreSQL de `db-check` sont [OK] sous Windows, et la documentation est corrigée si nécessaire.",
      "Sortie de `db-check` (sans secret) collée dans l'issue", bc05=["architectures", "documentation"], deps=["GES-04"]),
    I("LOC-02", "MongoDB local : premier démarrage sous Docker, validateurs, index et rôles vérifiés", 1, "cloud", "M", "tache", "P0",
      ["Lancer `db-up` puis `db-check` : les 12 lignes `mongo` doivent être [OK] (premier essai réel sous Docker : le script d'initialisation n'a été vérifié qu'en simulation)",
       "Corriger `db/mongo/init/01-collections-et-utilisateurs.js` si une étape échoue",
       "Insérer `contracts/events/examples/mesure-valide.json` dans `raw_events` avec le compte `svc_collecte` (dates converties en type date) : accepté ; puis un document sans `provenance` : refusé",
       "Vérifier l'index de durée de vie de `raw_events` (14 jours) avec `getIndexes()`"],
      "Les 12 contrôles MongoDB sont [OK] ; un document conforme est accepté et un document non conforme est refusé.",
      "Sortie de `db-check` et des deux insertions", bc05=["architectures", "documentation"], deps=["GES-04"]),
    I("DAT-10", "Valider le dictionnaire de données et les contrats d'événements v0", 1, "data", "DM", "decision", "P0",
      ["Relecture croisée de `docs/03-donnees/dictionnaire-de-donnees.md` et de `contracts/events/` (enveloppe, mesure, indicateur, alerte)",
       "Lancer les tests des contrats : `make test-contracts` (Linux) ou `py -3 -m unittest discover -s contracts/tests` (Windows) après `pip install jsonschema referencing`",
       "Lister les questions à poser au professeur : seuils d'hystérésis, retard autorisé, jours fériés, jeu réel avec comptages",
       "Corriger par pull request ; marquer le contrat v0 une fois les deux approbations données"],
      "Les deux membres ont relu et approuvé ; les tests des contrats passent sur les deux postes.",
      "Pull request approuvée par les deux membres", bc05=["documentation", "decisionnel", "etl"], deps=["GES-04"]),
    I("GES-19", "CLAUDE.md et gabarit de prompt par issue : travailler à deux avec Claude", 1, "gestion", "DM", "tache", "P1",
      ["Relire `CLAUDE.md` (racine du dépôt) et `docs/ia/prompt-modele-issue.md`",
       "Daddy : essai sous Windows avec le gabarit et l'identifiant de LOC-01 ; vérifier que Claude donne les commandes PowerShell et respecte les conventions de branche, de commit et de pull request",
       "Consigner chaque usage significatif dans `docs/ia/journal-usage-ia.md` (but, prompt, vérification)",
       "Ajuster le gabarit après l'essai (pull request)"],
      "Avec le même gabarit, chaque membre obtient une réponse conforme aux conventions et aux commandes de son système.",
      "Journal d'usage de l'IA mis à jour", bc05=["documentation"], deps=["DOC-02"]),
    I("LOC-04", "Kafka local (mode KRaft) dans Docker Compose et création des sujets", 1, "cloud", "M", "tache", "P0",
      ["Ajouter le service `kafka` (image officielle, mode KRaft, port publié sur 127.0.0.1) avec sonde de santé dans `docker-compose.yml`",
       "Script de création des sujets `iot.raw`, `traffic.indicators`, `traffic.recommendations`, `alerts.events`, `signal.status`, `errors.dlq` (clé de partition : `intersection_id`) et commande `dev.py kafka-topics`",
       "Aller-retour : publier `mesure-valide.json`, le relire et le valider avec `contracts/validate_events.py`",
       "Documenter les commandes sous Linux et sous Windows"],
      "Un événement publié sur `iot.raw` est relu et conforme au contrat ; les 6 sujets existent. Si l'ADR-009 retient un bus léger, l'issue s'adapte.",
      "Sortie de `dev.py kafka-topics` et de l'aller-retour", bc05=["flux"], deps=["MS-02", "LOC-01"]),
    # ------------------------------------------------------------ M2
    I("LOC-03", "Sauvegarde et restauration locales vérifiées sur les deux bases et les deux postes", 2, "cloud", "DM", "test", "P1",
      ["`backup` puis `restore-check` : deux fois OK sur Linux et sur Windows",
       "Simuler un sinistre (table vidée, collection supprimée) puis `restore` ; vérifier comptages et droits avec `db-check`",
       "Transférer des sauvegardes d'un poste à l'autre et restaurer",
       "Compléter `docs/08-exploitation/sauvegarde-restauration-locale.md` avec les constats MongoDB (restauration jamais exécutée à ce jour)"],
      "Chaque base est restaurée depuis une sauvegarde et les comptages sont identiques, sur les deux postes.",
      "Sorties de `restore-check` et de `restore`", bc05=["architectures", "documentation"], deps=["LOC-01", "LOC-02"]),
    I("LOC-06", "Contrôles Terraform sans compte : lancement manuel et proposition d'un job de CI", 2, "cloud", "M", "securite", "P1",
      ["Lancer `terraform fmt -check -recursive`, `terraform init -backend=false`, `terraform validate` et `tflint` sur `infra/terraform/envs/*` et corriger",
       "Lancer l'analyse Snyk IaC sur `infra/`",
       "Proposer un job de CI sans identifiants AWS dans une pull request séparée, **à approuver avant fusion** puisqu'elle modifie les contrôles de la CI"],
      "Les quatre contrôles passent sans identifiant AWS ; la proposition de job est décrite et attend l'accord du binôme.",
      "Sorties des contrôles et pull request de proposition", bc05=["architectures"], deps=["CLD-05"]),
    # ------------------------------------------------------------ M3
    I("IA-08", "Jeu d'entraînement v1 : export des runs du simulateur avec vérité terrain et fiche de provenance", 3, "ia", "M", "tache", "P0",
      ["Catalogue de scénarios : journée calme, heure de pointe, incident ponctuel, capteur muet, messages en retard et en doublon",
       "Calculer `label_state` (FREE_FLOW, SLOW, CONGESTED) à partir de l'état voulu par le scénario, pas de la règle de seuils",
       "Exporter en Parquet les colonnes du dictionnaire de données (section 9) ; découpage par run et par scénario",
       "Écrire `data/datasets/<jeu>/PROVENANCE.md` et enregistrer l'empreinte SHA-256",
       "Tests : deux exécutions avec la même graine donnent la même empreinte ; aucun `run_id` commun entre entraînement et test"],
      "Un jeu v1 reproductible existe, avec sa fiche de provenance, et le test de non-recouvrement des runs est vert.",
      "data/datasets/ (fiche), ml/tests/", bc05=["ml", "etl", "documentation"], deps=["MS-07", "DAT-10"]),
    I("LOC-05", "Équivalents locaux des services AWS : port de stockage d'objets et test d'absence de SDK AWS", 3, "cloud", "D", "tache", "P1",
      ["Définir le port `ObjectStore` (écrire, lire, lister) dans le backend et son adaptateur local sur `var/` (`STORAGE_BACKEND=local`)",
       "Test qui échoue si `boto3` ou un autre SDK AWS est importé dans `backend/` ou `ml/`",
       "Relire la table d'équivalences de l'ADR-025 et corriger les écarts constatés"],
      "Le stockage des modèles et des jeux de données passe par le port ; le test d'absence de SDK AWS est vert.",
      "backend/tests/", bc05=["architectures"], deps=["LOC-01"]),
    # ------------------------------------------------------------ M4
    I("IA-09", "Détection d'anomalies : règles robustes et comparaison avec Isolation Forest", 4, "ia", "M", "tache", "P1",
      ["Règles : écart à la médiane glissante, plateau suspect, capteur muet, chute de débit inexpliquée",
       "Isolation Forest en comparaison sur les mêmes variables",
       "Évaluer sur les anomalies injectées par le simulateur : rappel, précision, délai de détection",
       "Tableau comparatif et choix argumenté"],
      "Chaque anomalie injectée est détectée par les règles dans un délai mesuré ; le tableau compare règles et modèle.",
      "ml/evaluation/", bc05=["ml"], deps=["IA-08"]),
    I("IA-10", "Prévision de vitesse sur METR-LA : références, modèles et test sur un run simulé", 4, "ia", "M", "tache", "P1",
      ["Vérifier la licence du jeu, écrire sa fiche de provenance, script de téléchargement avec contrôle de l'empreinte (le jeu n'est pas versionné dans le dépôt public)",
       "Références : persistance, moyenne glissante, naïf saisonnier ; modèles : Ridge, HistGradientBoosting",
       "Évaluation par horizon (5, 15, 30 minutes) avec MAE et RMSE, découpage dans l'ordre du temps",
       "Tester la chaîne sur un run simulé et documenter la limite de validité"],
      "Le meilleur modèle bat les références par horizon, ou l'écart est documenté ; la limite de validité est écrite.",
      "ml/evaluation/ et fiche de provenance", bc05=["ml"], deps=["IA-03"]),
    I("IA-11", "Prototype SUMO (conditionnel) : simulation microscopique d'un carrefour", 4, "ia", "M", "prototype", "P2",
      ["Décision de lancement après IA-03 : générateur v0 livré et testé, temps disponible ; sinon consigner la décision de ne pas lancer",
       "Installer SUMO sous Docker et modéliser un carrefour à feux",
       "Exporter un run au format des événements v0 (`contracts/events/`)",
       "Comparer le comportement au générateur v0 et documenter ce que le prototype démontre et ne démontre pas"],
      "Un run SUMO est rejoué par le pipeline, ou la décision de ne pas lancer le prototype est consignée avec sa raison.",
      "docs/06-ia-mlops/prototype-sumo.md", bc05=["ml"], deps=["IA-08", "IA-03"]),
    I("DOC-11", "Relecture croisée des ADR 023 à 028 et de la table d'équivalences locales/AWS", 4, "docs", "DM", "tache", "P2",
      ["Relire les ADR 023 à 028 et corriger les écarts avec ce qui a réellement été construit",
       "Mettre à jour la table d'équivalences de l'ADR-025 et le risque R6",
       "Vérifier que chaque document technique donne les commandes Linux et Windows"],
      "Les ADR décrivent le système tel qu'il est, et chaque document technique a ses deux variantes.",
      "Pull request de relecture", bc05=["documentation"], deps=["LOC-05"]),
]

NEW_IDS = [i["id"] for i in NEW_ISSUES]

# --------------------------------------------------------------------------------------------------
# Amendements d'issues existantes
#   note        : commentaire publié sur l'issue (texte lisible, sans lien relatif)
#   labels      : étiquettes ajoutées
#   title       : nouveau titre (le préfixe [ID] est conservé par le script)
#   replace     : {ancienne tâche exacte: nouvelle tâche}      add : tâches ajoutées     drop : tâches retirées
#   done, proof : nouveaux critère et preuve
#   deps_add, deps_remove : dépendances
# --------------------------------------------------------------------------------------------------
DIFFERE = "aws:differe"
REORIENTE = "local:reoriente"
MAJ = "v3:amende"


def _differe(why: str) -> dict:
    return dict(labels=[DIFFERE, MAJ], note=(
        f"**Différée** (consigne du professeur : exécution sur localhost, pas sur les services AWS). {why} "
        f"Le contenu de l'issue reste valable pour une reprise sur autorisation écrite. Voir `{ADR023}`."))


AMENDMENTS: dict[str, dict] = {
    # ------------------------------------------------------------ AWS différé
    "CLD-09": _differe("Le rôle OIDC et le budget d'alerte n'ont pas lieu d'être sans compte AWS ; ne créer ni la variable `AWS_ROLE_ARN` ni la variable `AWS_REGION` : elles activeraient `deploy.yml` et `terraform.yml`."),
    "CLD-10": _differe("`terraform plan` exige des identifiants AWS ; seuls `fmt`, `validate` et `tflint` s'exécutent (voir LOC-06)."),
    "CLD-11": _differe("Aucune ressource AWS n'est créée ; bases locales dans LOC-01 et LOC-02, équivalences dans l'ADR-025."),
    "CLD-12": _differe("Pas de déploiement automatique ; la révision est visible en local (`/api/v1/health` renvoie le SHA du commit construit par Docker Compose)."),
    "CLD-14": _differe("Pas de CloudWatch ; le diagnostic d'une panne se travaille avec les journaux JSON et les indicateurs locaux de MS-16."),
    "CLD-15": dict(labels=[DIFFERE, MAJ], note=(
        "**Remplacée en local par LOC-03** (sauvegarde et restauration vérifiées de PostgreSQL et MongoDB, scripts déjà écrits). "
        "La partie AWS (instantanés RDS, sauvegardes S3) reste documentée, non exécutée. Voir `docs/08-exploitation/sauvegarde-restauration-locale.md`."),
        deps_remove=["CLD-11"], deps_add=["LOC-03"]),
    "CLD-16": _differe("Le retour de version d'ECS ne se teste pas ; le retour de code local se fait par `git checkout` du tag puis `dev.py up`."),
    "CLD-17": _differe("Le second `terraform plan` exige des identifiants AWS."),
    "CLD-18": _differe("Pas d'IAM ; la matrice d'accès locale existe pour les bases (`db-check`, 21 contrôles positifs et négatifs)."),
    "CLD-21": _differe("Rien n'est créé sur AWS, donc rien à détruire ; conserver l'issue pour la reprise."),
    "MS-17": _differe("Le déploiement par service se fait en local avec `dev.py up` (MS-06) ; la version AWS reste documentée."),
    "GES-18": dict(labels=[DIFFERE, MAJ], note=(
        f"**Différée** : la décision d'ouverture du compte AWS n'est plus à prendre pour l'instant (ADR-007 différée par l'ADR-023). Le plan B est appliqué. "
        "La date limite du 24/10/2026 est levée. Correction du texte : sans compte, `terraform plan` ne s'exécute pas (il exige des identifiants) ; seuls `fmt`, `validate` et `tflint` s'exécutent."),
        replace={
            "Choisir qui ouvre le compte AWS et avec quel moyen de paiement ; date limite : 24/10/2026":
                "Différé : choisir qui ouvre le compte AWS et avec quel moyen de paiement, si le professeur autorise AWS",
            "Si le compte n'est pas ouvert à la date limite : plan B documenté (démonstration locale avec `make up`, Terraform écrit et validé avec `terraform plan`, sans déploiement)":
                "Plan B appliqué : démonstration locale (`dev.py up`), Terraform écrit et contrôlé sans compte (`fmt`, `validate`, `tflint`), ni `plan` ni déploiement",
        },
        done="La décision est différée par l'ADR-023 ; le plan B est appliqué et documenté ; les issues cloud sont différées ou réorientées.",
        proof="docs/01-architecture/adr/ADR-007-compte-aws.md et ADR-023"),
    "CLD-01": dict(labels=[REORIENTE, MAJ], note=(
        "**Réorientée** : la partie AWS (compte, authentification à deux facteurs de l'utilisateur racine, budget d'alerte) est différée. "
        "Restent SonarQube Cloud et Snyk, nécessaires à la CI (secrets `SONAR_TOKEN` et `SNYK_TOKEN`)."),
        replace={"AWS : compte, MFA sur l'utilisateur racine, budget d'alerte, utilisateur d'administration via IAM Identity Center":
                 "AWS : différé (aucun compte tant que le professeur n'autorise pas AWS) ; rédiger seulement la procédure d'ouverture dans docs/05-cloud-aws/"}),
    "GES-09": dict(labels=[REORIENTE, MAJ], note=(
        "**Réorientée** : le chiffrage devient un **coût projeté** calculé sur l'inventaire prévu et étiqueté « non déployé ». Aucune ressource n'est créée."),
        replace={"Inventaire des ressources utilisées": "Inventaire des ressources prévues (cible AWS documentée, non déployée)",
                 "Coût de chaque prototype (Spark, Flink, Kafka)": "Coût projeté de chaque prototype (Spark, Flink, Kafka) s'il tournait sur AWS"},
        done="Chaque montant cite sa source de tarif et sa durée, et porte la mention « projeté, non déployé ».",
        deps_remove=["CLD-11"]),
    "DAT-06": dict(labels=[REORIENTE, MAJ], note=(
        "**Réorientée** : AWS Glue n'est pas exécuté. L'ETL tourne en local (Python) ; l'équivalent Glue est documenté. Le rejeu idempotent remplace la comparaison avec Glue."),
        replace={"Créer le job Glue avec Terraform": "Documenter l'équivalent Glue (job, planification) sans l'exécuter",
                 "Planifier l'exécution": "Planifier l'exécution locale (cron sous Linux, Planificateur de tâches sous Windows, ou commande de `dev.py`)",
                 "Comparer les résultats avec l'exécution locale": "Rejouer le chargement : les totaux sont identiques (clé d'idempotence de `fact_traffic_window`)"},
        done="Le rejeu du chargement produit les mêmes totaux ; l'équivalent Glue est documenté.",
        title="ETL planifié en local (équivalent d'AWS Glue documenté)", deps_remove=["CLD-11"]),
    "DAT-08": dict(labels=[REORIENTE, MAJ], note=(
        "**Réorientée** : PySpark en mode local (`local[*]`), sans cluster Amazon EMR."),
        replace={"Documenter les limites et arrêter le cluster après l'essai": "Documenter les limites (exécution locale, pas de cluster) et l'équivalent EMR non exécuté"},
        title="Prototype Big Data : PySpark en mode local (Amazon EMR documenté)", deps_remove=["CLD-11"]),
    "DAT-09": dict(labels=[REORIENTE, MAJ], note=(
        "**Réorientée** : Kafka tourne en local (LOC-04) ; Amazon MSK est documenté, non exécuté."),
        replace={"Arrêter MSK après l'essai": "Documenter l'équivalent Amazon MSK (non exécuté)"},
        title="Prototype flux temps réel : Kafka local et Flink (Amazon MSK documenté)", deps_remove=["CLD-11"], deps_add=["LOC-04"]),
    "IA-04": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : les modèles sont stockés dans le dossier local `var/models/` derrière le port `ObjectStore` (LOC-05) ; S3 est documenté, non exécuté.",
        replace={"Stocker les modèles versionnés dans S3": "Stocker les modèles versionnés dans `var/models/` (port `ObjectStore` local ; S3 documenté)"}),
    "IA-05": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : entraînement local (scikit-learn) ; SageMaker documenté, non exécuté. Plus de dépendance au rôle OIDC (CLD-09).",
        replace={"Entraînement sur Amazon SageMaker": "Entraînement local (scikit-learn) ; équivalent SageMaker documenté, non exécuté"},
        deps_remove=["CLD-09"]),
    "IA-06": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : l'alerte de dérive est locale (journal et point `/metrics`), pas une alarme CloudWatch.",
        replace={"Alarme CloudWatch": "Alerte locale : entrée de journal et indicateur exposé sur `/metrics`"},
        done="La dérive simulée déclenche l'alerte locale.", proof="Capture de l'alerte (journal ou /metrics)"),
    "BE-08": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : les secrets viennent des variables d'environnement (`.env` généré par `dev.py init-env`, ignoré par Git). AWS Secrets Manager est documenté, non exécuté.",
        replace={"Secrets lus depuis AWS Secrets Manager": "Secrets lus depuis les variables d'environnement (`.env` généré, jamais versionné) ; Secrets Manager documenté"},
        title="Sécurité applicative : CORS, en-têtes, limitation de débit, secrets d'environnement", deps_remove=["CLD-11"]),
    "MS-16": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : pas de tableau CloudWatch ; tableau local (journaux JSON et point `/metrics`).",
        replace={"Tableau CloudWatch : débit, retard de consommation, erreurs par service (reprend CLD-14)":
                 "Tableau local (journaux JSON et point `/metrics`) : débit, retard de consommation, erreurs par service"}),
    "GES-14": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : la démonstration locale est le plan A (plus un plan B de repli).",
        replace={"Plan B si AWS est indisponible (démo locale avec `make up`)": "Démonstration locale (plan A) avec `dev.py up` sur les deux systèmes ; plan B : captures et enregistrement vidéo du parcours"}),
    "CLD-20": dict(labels=[REORIENTE, MAJ], note="**Dépendance corrigée** : le modèle de pipeline ne dépend pas du déploiement AWS (CLD-12 différée) mais de la CI (CLD-03).",
        deps_remove=["CLD-12"], deps_add=["CLD-03"]),
    "DOC-06": dict(labels=[REORIENTE, MAJ], note="**Réorientée** : les procédures sont locales (démarrage, diagnostic par journaux, sauvegarde et restauration). Les procédures AWS (CLD-14, CLD-16) sont différées.",
        deps_remove=["CLD-14", "CLD-16"], deps_add=["LOC-03"]),
    "GES-13": dict(labels=[REORIENTE, MAJ], note="**Précision** : la vérification du tag se fait en local.",
        replace={"Vérifier le déploiement de ce tag": "Vérifier que `dev.py up` à ce tag démarre l'ensemble sur les deux systèmes"}),
    "DOC-03": dict(labels=[MAJ], note="**Précision** : AWS figure dans les vues comme cible documentée ; le conteneur d'exécution réel est Docker Compose local.",
        replace={"Contexte : utilisateurs, sources de données urbaines, AWS": "Contexte : utilisateurs, sources de données urbaines ; AWS en cible documentée"}),
    # ------------------------------------------------------------ Postes Windows et Linux
    "GES-04": dict(labels=[MAJ], note=(
        "**Mise à jour** : `make` n'existe pas nativement sous Windows. Le lanceur commun est `scripts/dev/dev.py` (Linux et Windows) ; `make` reste un raccourci Linux. "
        "Voir `docs/08-exploitation/poste-de-travail.md`."),
        title="Préparer les postes de travail (Docker, Python 3.12, Node 22, gh) : Linux et Windows",
        replace={"Cloner le dépôt, copier `.env.example` vers `.env`, lancer `make up`":
                 "Cloner le dépôt, lancer `check-tools`, `init-env` (mots de passe aléatoires dans `.env`) puis `db-up` avec `python3 scripts/dev/dev.py` (Linux) ou `py -3 scripts/dev/dev.py` (Windows)"},
        done="`check-tools` ne signale rien de manquant et `db-up` démarre PostgreSQL et MongoDB sur les deux postes.",
        proof="Sortie de `check-tools` et de `ps` des deux postes"),
    "CLD-07": dict(labels=[MAJ], note="**Mise à jour** : le démarrage se documente avec `dev.py` (Linux et Windows), `make` en raccourci Linux.",
        replace={"Documenter `make up` dans le README": "Documenter le démarrage (`dev.py up`, Linux et Windows) dans le README"}),
    "MS-06": dict(labels=[MAJ], note=(
        "**Mise à jour** : les bases sont déjà fournies par LOC-01 et LOC-02 (rôles par service, migrations) ; le broker vient de LOC-04. Le lanceur est `dev.py up` (`make` en raccourci Linux)."),
        replace={"Ajouter le broker, PostgreSQL, MongoDB, les 4 services, le simulateur, la passerelle et le frontend":
                 "Ajouter à `docker-compose.yml` (bases déjà présentes, broker de LOC-04) les 4 services, le simulateur, la passerelle et le frontend",
                 "`make up` démarre tout, `make down` nettoie ; variables dans `.env.example`":
                 "`dev.py up` démarre tout, `dev.py down` nettoie (`make` en raccourci Linux) ; variables dans `.env.example`"},
        done="`dev.py up` démarre l'ensemble sur les deux systèmes et chaque /health répond.",
        deps_add=["LOC-01", "LOC-02", "LOC-04"]),
    # ------------------------------------------------------------ Données et contrats
    "GES-06": dict(labels=[MAJ], note=(
        "**Ajouts** : obtenir la **confirmation écrite** de la consigne « localhost, pas AWS » (donnée oralement le 20/10/2026, risque R7), "
        "et faire valider l'ordre congestion puis prévision ainsi que le jeu de données (générateur Python, METR-LA, jeu de l'UCI)."),
        replace={"Taux journalier, devise et plafond de dépense AWS": "Taux journalier et devise (le plafond AWS est sans objet tant que l'exécution reste locale)"},
        add=["Confirmation écrite de la consigne d'exécution sur localhost (ADR-023, registre des demandes C-05)",
             "Ordre congestion puis prévision, label = vérité terrain, jeux de données (ADR-015, ADR-027)"],
        done="Les décisions sont consignées avec la date et le décideur, et la consigne localhost est confirmée par écrit."),
    "DAT-02": dict(labels=[MAJ], note=(
        "**Avancement** : le schéma est écrit sous forme de migrations (`db/postgres/migrations`, 5 fichiers) et le dictionnaire de données est rédigé. "
        "Reste la relecture croisée (DAT-10) et la vérification sur Windows (LOC-01)."),
        replace={"Schéma `app` (métier) et schéma `dwh` (tables de faits et dimensions)":
                 "Schémas `app`, `dwh`, `alertes`, `ops` : migrations SQL de `db/postgres/migrations`, relues et vérifiées sur Windows",
                 "Dictionnaire de données": "Dictionnaire de données `docs/03-donnees/dictionnaire-de-donnees.md` relu et complété (DAT-10)"},
        proof="db/postgres/migrations/ et docs/03-donnees/"),
    "DAT-07": dict(labels=[MAJ], note="**Ajout** : des indicateurs propres à la congestion.",
        add=["Indicateurs de congestion : part du temps en état CONGESTED par tronçon, durée moyenne des épisodes, délai de détection, alertes par jour"]),
    "MS-03": dict(labels=[MAJ], note=(
        "**Avancement** : les contrats d'événements v0 (enveloppe, mesure, indicateur, alerte) sont écrits dans `contracts/events/` avec 9 exemples, 35 cas invalides testés et `contracts/validate_events.py`. "
        "Reste à compléter les sujets restants, à générer ou aligner les modèles Pydantic et à décider avec le binôme si le test de conformité entre dans la CI (modification des contrôles : à approuver)."),
        add=["Reprendre les contrats v0 de `contracts/events/` et compléter `traffic.recommendations`, `signal.status` et `errors.dlq`",
             "Aligner les modèles Pydantic sur les schémas (test de conformité)"]),
    "MS-07": dict(labels=[MAJ], note=(
        "**Précisions** : le simulateur est la base du jeu d'entraînement (IA-08). Il émet des événements conformes à `contracts/events/iot-measurement.schema.json` "
        "avec `run_id`, `scenario_id` et `seed`, sur le réseau de démonstration de la migration 0005, et sait aussi écrire un run dans un fichier."),
        replace={"Modèle de carrefours (par exemple 6 carrefours de 4 capteurs) : comptage de véhicules, vitesse moyenne, taux d'occupation":
                 "Réseau fixe de la migration 0005 (6 carrefours, 24 tronçons, 24 capteurs, une mesure toutes les 10 s) : comptage, vitesse moyenne, taux d'occupation"},
        add=["Identifiant d'événement `<run_id>:<sensor_id>:<instant>` ; état de congestion voulu par le scénario conservé à part comme vérité terrain",
             "Mode fichier : écrire un run complet pour IA-08"]),
    "MS-09": dict(labels=[MAJ], note="**Précisions** : états de congestion avec hystérésis et épisodes (ADR-028) ; rejets de qualité selon les codes DQ-01 à DQ-10 du dictionnaire de données.",
        add=["Calculer l'état de congestion stabilisé (ADR-028) et ouvrir ou clore les épisodes dans `dwh.fact_congestion_episode`"]),
    "MS-11": dict(labels=[MAJ], note="**Précisions** : tables de la migration 0003 (`alertes.*`), une alerte par épisode (index unique partiel), motif outbox pour publier.",
        replace={"Cycle de vie d'une alerte : créée, notifiée, acquittée, résolue ; stockage dans PostgreSQL (schéma propre au service)":
                 "Cycle de vie d'une alerte : créée, notifiée, acquittée, résolue ; stockage dans le schéma `alertes` (migration 0003) et publication par la table `outbox_event`",
                 "Anti-bruit : regroupement et délai minimum entre deux alertes identiques":
                 "Anti-bruit : une alerte par épisode (index unique), délai minimum `min_gap_s` ; cause `UNKNOWN` par défaut"}),
    # ------------------------------------------------------------ IA : congestion d'abord
    "IA-01": dict(labels=[MAJ], note=(
        "**Cadrage modifié** (ADR-015 réécrite le 20/10/2026) : la cible est l'état de congestion, la prévision vient ensuite. "
        "Le label est la vérité terrain du simulateur (ADR-027) et les seuils d'hystérésis se fixent ici (ADR-028)."),
        replace={"Cible : prévision de mobilité à court terme": "Cible : état de congestion d'un tronçon (FREE_FLOW, SLOW, CONGESTED) ; la prévision de vitesse vient en second (IA-10)",
                 "Métrique et seuil d'acceptation": "Métriques : F1 macro, rappel de CONGESTED, délai de détection, fausses alertes par tronçon et par jour ; seuil d'acceptation fixé avant l'entraînement",
                 "Modèle de référence (moyenne glissante) à battre": "Référence à battre : règle de seuils avec hystérésis ; fixer définitivement les seuils de l'ADR-028 après un premier run"},
        add=["Label = vérité terrain du simulateur, jamais la sortie de la règle de seuils (ADR-027)"],
        deps_add=["IA-08"]),
    "IA-02": dict(labels=[MAJ], note="**Découpage modifié** : par run et par scénario (jamais par lignes tirées au hasard) ; dans l'ordre du temps pour la prévision.",
        replace={"Découpage entraînement / validation / test dans l'ordre du temps": "Découpage entraînement / validation / test par run et par scénario ; dans l'ordre du temps pour la prévision"},
        deps_add=["IA-08"]),
    "IA-03": dict(labels=[MAJ], note="**Modèles modifiés** : règle de seuils en référence, régression logistique et HistGradientBoosting en candidats pour la congestion (ADR-015).",
        replace={"Référence et 2 modèles candidats": "Référence (règle de seuils) et 2 modèles candidats (régression logistique, HistGradientBoosting)",
                 "Validation croisée temporelle": "Validation croisée groupée par run (temporelle pour la prévision, IA-10)"}),
}


# --------------------------------------------------------------------------------------------------
# Application en mémoire
# --------------------------------------------------------------------------------------------------
class AmendmentError(ValueError):
    """Un amendement ne correspond plus au backlog (tâche introuvable, identifiant inconnu)."""


def register_new_issues() -> None:
    """Ajoute les issues nouvelles à issues_data.ISSUES (une seule fois, même si importé deux fois)."""
    present = {i["id"] for i in issues_data.ISSUES}
    issues_data.ISSUES.extend(i for i in NEW_ISSUES if i["id"] not in present)


def apply_amendments(issues: list[dict]) -> set[str]:
    """Applique AMENDMENTS aux issues (modifie la liste en place) et rend les identifiants touchés."""
    by_id = {i["id"]: i for i in issues}
    touched = set()
    for issue_id, change in AMENDMENTS.items():
        if issue_id not in by_id:
            raise AmendmentError(f"{issue_id} : issue inconnue")
        issue = by_id[issue_id]
        tasks = list(issue["tasks"])
        for old in change.get("drop", []):
            if old not in tasks:
                raise AmendmentError(f"{issue_id} : tâche à retirer introuvable : {old[:60]}")
            tasks.remove(old)
        for old, new in change.get("replace", {}).items():
            if old not in tasks:
                raise AmendmentError(f"{issue_id} : tâche à remplacer introuvable : {old[:60]}")
            tasks[tasks.index(old)] = new
        tasks += [t for t in change.get("add", []) if t not in tasks]
        issue["tasks"] = tasks
        for key in ("title", "done", "proof"):
            if key in change:
                issue[key] = change[key]
        deps = [d for d in issue["deps"] if d not in change.get("deps_remove", [])]
        deps += [d for d in change.get("deps_add", []) if d not in deps]
        issue["deps"] = deps
        touched.add(issue_id)
    return touched


register_new_issues()
