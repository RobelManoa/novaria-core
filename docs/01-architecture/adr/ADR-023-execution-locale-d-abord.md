# ADR-023 — Exécution locale d'abord : AWS documenté et préparé, non exécuté

| Champ | Valeur |
|---|---|
| Date | 20/10/2026 |
| Statut | Acceptée : instruction du professeur transmise **oralement** par Manoa Robel ; confirmation écrite à obtenir (voir section 7) |
| Décideurs | Manoa Robel, Daddy Luciano, d'après la consigne du professeur |
| Validation du professeur | Donnée oralement le 20/10/2026 ; à consigner par écrit dans `docs/07-gestion/decisions-professeur.md` |
| Issues liées | GES-06, GES-09, CLD-01, CLD-09 à CLD-12, CLD-14 à CLD-18, CLD-21, LOC-01 à LOC-06, DAT-06, DAT-08, DAT-09, IA-04, IA-05, IA-06, BE-08, MS-16, MS-17 |
| Compétences BC05 | Architectures de données décisionnelles, Documentation |
| Remplace en partie | [ADR-003](ADR-003-aws-ecs-fargate-docker.md), [ADR-007](ADR-007-compte-aws.md) (la décision d'exécuter sur AWS est suspendue) |
| Complété par | [ADR-024](ADR-024-bases-de-donnees-locales.md), [ADR-025](ADR-025-equivalents-locaux-des-services-aws.md), [ADR-026](ADR-026-postes-de-travail-windows-et-linux.md) |

## 1. Problème

Les ADR (Architecture Decision Record, enregistrement de décision d'architecture) du 17/10/2026 supposaient un déploiement sur AWS (Amazon Web Services) : ECS (Elastic Container Service) Fargate, RDS (Relational Database Service), MSK (Managed Streaming for Apache Kafka), SageMaker, CloudWatch. Le professeur indique que **le projet peut tourner sur `localhost` pour le moment, mais pas sur des services AWS**. Sans décision écrite, le planning garde des tâches impossibles à exécuter et la documentation promet ce que le projet ne fera pas.

## 2. Forces de décision

| Critère | Poids |
|---|---|
| Respect de la consigne du professeur | Fort |
| Aucune dépense, aucun compte, aucun secret cloud | Fort |
| Conserver le travail de conception AWS déjà fait (documents, Terraform, ADR) | Fort |
| Un parcours de bout en bout démontrable le 10/12/2026 | Fort |
| Pouvoir reprendre AWS si l'autorisation arrive plus tard | Moyen |

## 3. Options comparées

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| A. Poursuivre le plan AWS | Compétence cloud démontrée par un déploiement | Contraire à la consigne ; coût et risque | Écartée |
| **B. Exécuter en local, garder AWS documenté et validé statiquement** | Respecte la consigne ; rien n'est perdu ; reprise possible | Les compétences cloud se démontrent par le code et les documents, pas par un déploiement | **Retenue** |
| C. Supprimer toute trace d'AWS | Dépôt plus simple | Perte du travail fait ; contredit la consigne de garder les documents | Écartée |

Réserve la plus forte contre B : le bloc BC05 mentionne des architectures cloud ; sans déploiement réel, la démonstration repose sur la documentation et le code Terraform. Parade : chaque service AWS a un **équivalent local documenté** ([ADR-025](ADR-025-equivalents-locaux-des-services-aws.md)) et le code AWS se valide sans compte.

## 4. Choix

```mermaid
flowchart LR
    subgraph LOCAL["Exécuté : localhost"]
        DC[Docker Compose]
        PG[(PostgreSQL)]
        MG[(MongoDB)]
        KF[Kafka local]
        APP[Backend, frontend,<br/>microservices]
    end
    subgraph AWS["Documenté et validé statiquement, non exécuté"]
        TF[Terraform]
        ECS[ECS Fargate]
        RDS[RDS]
        MSK[MSK]
        DOC[docs/05-cloud-aws]
    end
    DC --> PG & MG & KF & APP
    TF -. "fmt, validate,<br/>tflint, Snyk IaC" .-> CHK{{Contrôles sans compte}}
    DOC -. "équivalences" .-> LOCAL
```

| N° | Règle |
|---|---|
| 1 | Tout s'exécute sur `localhost` avec Docker Compose : `python3 scripts/dev/dev.py up` (Linux) ou `py -3 scripts/dev/dev.py up` (Windows). |
| 2 | **Aucune ressource AWS n'est créée** : pas de compte ouvert pour le projet, pas d'identifiant AWS dans le dépôt, dans GitHub Actions ni dans une conversation. |
| 3 | Les documents AWS (`docs/05-cloud-aws`, ADR 003, 006, 007, 020, 021, 022) et le code Terraform sont **conservés**. Ils portent la mention « cible documentée, non exécutée ». |
| 4 | Le code Terraform se contrôle sans compte : `terraform fmt -check`, `terraform init -backend=false` puis `terraform validate`, `tflint`, analyse Snyk IaC. Le `terraform plan` exige des identifiants : il n'est **pas** exécuté. Aujourd'hui, ces contrôles statiques sont dans le job `plan` de `terraform.yml`, qui ne démarre pas sans `AWS_ROLE_ARN` : ils se lancent donc **à la main** en attendant un job CI (Continuous Integration, intégration continue) sans identifiants (issue LOC-06, à approuver puisqu'elle touche la CI). |
| 5 | Les workflows `deploy.yml` et `terraform.yml` restent **inactifs** : ils ne démarrent que si la variable `AWS_ROLE_ARN` existe ; cette variable n'est pas créée. |
| 6 | Le chiffrage (GES-09) devient un **coût projeté**, calculé sur l'inventaire prévu et étiqueté « non déployé ». |
| 7 | Chaque composant qui dépendait d'un service AWS a un équivalent local ([ADR-025](ADR-025-equivalents-locaux-des-services-aws.md)) et un adaptateur remplaçable ([ADR-010](ADR-010-architecture-hexagonale.md)). |
| 8 | Reprise d'AWS : uniquement sur **autorisation écrite** du professeur, puis décision de l'[ADR-007](ADR-007-compte-aws.md) (compte, plafond, budget d'alerte). |

### Effet sur le planning

| Issue | Traitement |
|---|---|
| CLD-01 (compte AWS) | Partie compte reportée ; reste la rédaction de la procédure |
| CLD-09 (OIDC), CLD-10 (réseau), CLD-11 (MongoDB sur ECS), CLD-12 (ECS), CLD-14, CLD-15, CLD-16, CLD-17, CLD-18, CLD-21 | **Différées** : étiquette `aws:differe`, documents conservés |
| DAT-06 (Glue), DAT-08 (EMR), DAT-09 (MSK), IA-04 (S3), IA-05 (SageMaker), IA-06 (CloudWatch), BE-08 (Secrets Manager), MS-16 (CloudWatch), MS-17 | **Réorientées** vers l'équivalent local |
| GES-09 | Coût projeté, rien n'est créé |
| GES-14 (démonstration) | Plan A : démonstration locale |
| LOC-01 à LOC-06 | **Nouvelles** : bases locales, sauvegarde, Kafka local, équivalents locaux, contrôles Terraform sans compte |

Les corps des issues ne sont pas effacés : un commentaire d'amendement et l'étiquette expliquent le changement.

## 5. Conséquences

**Positives**

- Zéro dépense, zéro secret cloud, zéro compte à protéger.
- Le temps libéré par les tâches AWS (installation, réseau, droits) va au parcours de bout en bout et à la qualité des données.
- La démonstration ne dépend ni d'internet ni d'un service tiers.

**Compromis acceptés**

- Aucune preuve de déploiement cloud réel : la compétence se démontre par le code, les contrôles statiques et les documents.
- Écarts possibles entre le local et AWS (versions, réseau, droits) : consignés dans le registre des risques (R6).
- Les performances mesurées en local ne valent pas celles d'un service géré.

**Risques et parades**

| Risque | Parade |
|---|---|
| Écart entre local et AWS que personne ne voit | Adaptateurs et variables de configuration ; tableau d'équivalences ([ADR-025](ADR-025-equivalents-locaux-des-services-aws.md)) ; risque R6 suivi à chaque jalon |
| Instruction orale mal comprise ou oubliée | Confirmation écrite demandée ; consignée dans le registre des demandes (risque R7) |
| Documents AWS qui se périment | Mention de statut en tête de chaque document ; relecture si le projet reprend AWS |
| Dérive : une ressource AWS créée par erreur | Aucune clé AWS dans le dépôt ni dans GitHub ; workflow de déploiement inactif |

## 6. Plan de repli

Si le professeur autorise AWS plus tard : décider selon l'[ADR-007](ADR-007-compte-aws.md), rouvrir dans cet ordre CLD-01, CLD-09, CLD-10, CLD-12, CLD-11, puis les services de données ; les adaptateurs de l'[ADR-025](ADR-025-equivalents-locaux-des-services-aws.md) évitent de réécrire les services.

## 7. Vérification

| Contrôle | Preuve |
|---|---|
| Le parcours tourne en local | `dev.py up`, `dev.py db-check` |
| Aucune ressource AWS | Pas de variable `AWS_*` dans GitHub ; `deploy.yml` et `terraform.yml` sans exécution |
| Le code Terraform reste valide | Contrôles statiques lancés à la main (LOC-06), puis en CI si le job sans identifiants est approuvé |
| L'instruction est tracée | Ligne dans `docs/07-gestion/decisions-professeur.md` et dans le registre des demandes ; **demande de confirmation écrite** envoyée au professeur |

## 8. Conditions de réexamen

- Le professeur autorise un usage d'AWS (même limité à une démonstration).
- Le professeur exige une preuve de déploiement cloud pour valider une compétence.
- Un écart local/AWS bloque une fonction.
