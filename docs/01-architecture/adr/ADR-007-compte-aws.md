# ADR-007 — Compte AWS (Amazon Web Services), plafond de dépense et plan B

| Champ | Valeur |
|---|---|
| Date | 17/10/2026 |
| Statut | **Différée le 20/10/2026** ([ADR-023](ADR-023-execution-locale-d-abord.md)) : l'option D (pas de compte AWS) s'applique tant que le professeur n'autorise pas de services AWS. Les champs de la section 4 restent vides ; la date du 24/10/2026 n'est plus une porte. |
| Décideurs | Daddy Luciano, Manoa Robel, avec le professeur pour le plafond (point 4 de GES-06) |
| Validation du professeur | Requise **si le projet reprend AWS** |
| Issues liées | GES-18, GES-06, CLD-01, CLD-09, GES-09, CLD-21 |
| Compétences BC05 | Architectures de données décisionnelles, Documentation |
| Conditionne | [ADR-003](ADR-003-aws-ecs-fargate-docker.md), [ADR-009](ADR-009-bus-evenements.md), [ADR-011](ADR-011-temps-reel-et-batch.md), [ADR-016](ADR-016-big-data.md), [ADR-017](ADR-017-mlops-mlsecops.md), [ADR-022](ADR-022-hebergement-mongodb.md) |

> **Mise à jour du 20/10/2026 ([ADR-023](ADR-023-execution-locale-d-abord.md)).** L'ouverture du compte, le plafond et le budget d'alerte ne sont plus à décider pour l'instant. Le contenu de cette ADR sert si l'autorisation arrive.

## 1. Problème

Le dépôt n'a pas encore de compte AWS. Plusieurs décisions d'architecture supposent des services facturés (bus Kafka géré, Flink géré, Spark sur EMR (Elastic MapReduce), entraînement sur SageMaker). Sans compte, sans moyen de paiement et sans plafond convenu, ces choix restent théoriques et le planning cloud (M1 à M4) glisse.

Trois décisions sont à prendre : **qui ouvre le compte et avec quel moyen de paiement**, **quel plafond de dépense**, **quel plan B si le compte n'existe pas à temps**.

## 2. Forces de décision

- Aucune estimation financière inventée : le chiffrage repose sur l'inventaire réel des ressources (GES-09).
- AWS Budgets envoie des alertes mais ne coupe pas la dépense : le plafond est une **discipline opérationnelle** (alertes, arrêt, destruction), pas un blocage technique.
- Un compte sans protection (authentification à deux facteurs, budget d'alerte) ne reçoit aucune ressource.
- Le 10/12/2026 reste la date de soutenance.

## 3. Options

| Option | Description | Avantages | Inconvénients |
|---|---|---|---|
| A. Compte AWS personnel d'un membre | Un membre ouvre un compte avec sa carte | Liberté totale de services | Risque financier personnel, responsabilité d'un seul |
| B. Compte fourni par l'établissement (programme pédagogique AWS, bac à sable) | Pas de frais personnels | Services et durées souvent restreints, rôles IAM (Identity and Access Management) limités : OIDC (OpenID Connect) et Terraform complets possiblement impossibles | À vérifier auprès du professeur |
| C. Crédits offerts aux nouveaux comptes | Réduit la dépense | Conditions et durée variables, à lire sur le site AWS à la date d'ouverture | Ne dispense pas du budget d'alerte |
| D. Pas de compte AWS (plan B) | Démonstration locale | Aucun coût ni risque | Les compétences cloud sont démontrées par le code Terraform et le plan, pas par un déploiement réel |

Les options A, B et C se combinent. L'option D est le plan B de toute façon.

## 4. Décision (à compléter)

| Question | Réponse | Date | Décideur |
|---|---|---|---|
| Qui ouvre le compte ? |  |  |  |
| Moyen de paiement |  |  |  |
| Plafond de dépense mensuel (montant et devise) |  |  | Professeur |
| Seuils d'alerte | 50 %, 80 %, 100 % du plafond (proposition) |  |  |
| Date limite d'ouverture | 24/10/2026 (proposition) |  |  |
| Option retenue (A, B, C, D) |  |  |  |

Règles posées dès maintenant, quelle que soit l'option :

1. Authentification à deux facteurs (MFA, Multi-Factor Authentication) sur l'utilisateur racine, qui ne sert qu'à l'ouverture du compte.
2. Budget d'alerte créé **avant** la première ressource.
3. Accès quotidien par IAM Identity Center ou un rôle, jamais par clé d'accès longue durée ; GitHub s'authentifie par OIDC (OpenID Connect, CLD-09).
4. Étiquette `projet=novaria` sur toute ressource.
5. Destruction (`terraform destroy`) après chaque séance d'essai de composants facturés à l'heure.

## 5. Conséquences selon le scénario

| Composant | Compte disponible (A, B, C) | Plan B (D) |
|---|---|---|
| Services applicatifs | ECS (Elastic Container Service) Fargate ([ADR-003](ADR-003-aws-ecs-fargate-docker.md)) | Docker Compose local (`dev.py up`) |
| Bus d'événements | Amazon MSK (Managed Streaming for Apache Kafka) ou conteneur sur ECS, selon le chiffrage | Kafka en conteneur local |
| Traitement de flux | Service géré Flink ou conteneur | Flink en conteneur local |
| Big Data | EMR Serverless ou Spark local | Spark local en conteneur |
| Entraînement du modèle | SageMaker ou entraînement local | Entraînement local, mêmes scripts |
| Terraform | `plan` et `apply` | `fmt`, `validate`, `tflint` et analyse Snyk IaC (le `plan` exige des identifiants AWS, voir [ADR-020](ADR-020-terraform.md)) |
| Chiffrage | Coûts réels de l'inventaire | Coûts calculés sur l'inventaire prévu, étiquetés « non déployé » |

Si l'option B s'avère trop restreinte pour OIDC ou Terraform, les issues CLD-09 à CLD-12, MS-17 et IA-05 se replanifient (jalons M2 à M4).

## 6. Risques et parades

| Risque | Parade |
|---|---|
| Facture inattendue | Budget d'alerte, destruction après essai, revue de la facturation à chaque jalon |
| Dépendance à un seul membre pour le compte | Au moins un second utilisateur IAM avec droits limités |
| Décision tardive | Date limite du 24/10/2026 ; passé ce délai, plan B appliqué et planning cloud replanifié |

## 7. Vérification

- Capture du budget d'alerte et de la MFA active (sans valeur secrète).
- Décision, date limite et plan B écrits dans cet ADR et dans `docs/07-gestion/decisions-professeur.md`.

## 8. Conditions de réexamen

- Le compte est ouvert en cours de projet (passer du plan B au déploiement).
- Les alertes montrent une dépense hors trajectoire.
