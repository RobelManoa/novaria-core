# Ressources persistantes protégées et second plan Terraform (CLD-17)

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 19/11/2026
Issue de suivi : CLD-17 (#90), dépend de CLD-11 (différée)
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation de l'issue : « le plan indique 0 changement ». **Atteint sur un émulateur d'API AWS local et ouvert (Moto), pas sur AWS** : le vrai second plan compare le code à de vraies ressources, donc exige un compte, et le projet n'en crée aucun ([ADR-023](../01-architecture/adr/ADR-023-execution-locale-d-abord.md) ; l'issue reste **différée** côté AWS). Le **même code** Terraform est appliqué à l'émulateur, puis le plan est rejoué : « No changes » (section 3). Ce document documente aussi les ressources persistantes, dont les protections ont été ajoutées au code, et dit ce que l'émulateur ne prouve pas.

Abréviations : **ECR** (Elastic Container Registry, dépôt d'images), **Moto** (émulateur d'API AWS, licence Apache-2.0), **IaC** (Infrastructure as Code, infrastructure décrite par du code), **CI** (Continuous Integration, intégration continue), **état** (le fichier où Terraform note ce qu'il a créé).

## 1. En bref

| Tâche de l'issue | État | Où |
|---|---|---|
| Rejouer `terraform plan` après l'application | **Fait sur l'émulateur local Moto** : `apply` puis plan = `No changes` (code 0), pour `dev` et `demo`, et le contrôle **sait échouer** (une dérive est vue : 1 changement). **Non fait sur AWS** : aucun compte (ADR-023) | Section 3, [`emulateur-dev.txt`](sorties-terraform/emulateur-dev.txt), [`emulateur-demo.txt`](sorties-terraform/emulateur-demo.txt) |
| Documenter les ressources persistantes protégées | **Fait**, et les protections sont **ajoutées au code** (elles n'existaient pas) puis prouvées sur un vrai état de l'émulateur | Sections 2 et 4 |
| Critère « le plan indique 0 changement » | **Atteint sur l'émulateur**, non sur AWS | Sections 3 et 5 |
| Preuve « sortie du plan » | Six sorties versionnées, chacune dit ce qu'elle ne prouve pas | Section 3 |

**Pourquoi Moto.** Licence Apache-2.0, projet de 2013 qui publie toujours (version 5.2.5 du 27/10/2026), image Docker officielle, ECR et CloudWatch Logs gérés. **LocalStack n'est plus un choix stable** : depuis le 23/03/2026 son image exige un compte et un jeton et l'édition communautaire n'est plus entretenue ([annonce de LocalStack](https://blog.localstack.cloud/the-road-ahead-for-localstack/)). Floci (MIT) est trop récent (mars 2026) pour être jugé stable.

## 2. Les ressources persistantes

Une ressource est **persistante** quand sa destruction fait perdre des données qu'on ne recrée pas en relançant `terraform apply`.

| Ressource Terraform | Ce qu'elle garde | Protection dans `dev` | Dans `demo` | Où |
|---|---|---|---|---|
| `aws_ecr_repository` | les images déployées (une étiquette = une révision) | `prevent_destroy = true` : `terraform destroy` échoue ; `force_delete = false` : même sans Terraform, AWS refuse de supprimer un dépôt qui contient des images ; étiquettes **immuables** ; analyse à la poussée | jetable : `force_delete = true`, sans `prevent_destroy` (détruit après chaque séance, CLD-21) | `modules/ecr`, bloc `protected` ou `disposable` selon `protected` |
| `aws_cloudwatch_log_group` | les journaux d'un service | `skip_destroy = true` : à la destruction, le groupe sort de l'état mais **les journaux restent** ; conservation de 14 jours | `skip_destroy = false` : supprimé, conservation de 7 jours | `modules/observability` |
| `aws_ecr_lifecycle_policy` | une règle de conservation (les 20 dernières images), pas de données | sans objet : elle se recrée | idem | `modules/ecr` |

**Prévues par l'[ADR-020](../01-architecture/adr/ADR-020-terraform.md), absentes du code** (CLD-10 et CLD-11, différées) : pas de protection écrite aujourd'hui, la règle à appliquer au moment de les écrire est la suivante.

| Ressource prévue | Règle à écrire avec elle |
|---|---|
| Base PostgreSQL (RDS) | protection contre la suppression activée, copie finale obligatoire à la destruction, `prevent_destroy` |
| MongoDB (sur ECS, volume) | volume séparé de la tâche, `prevent_destroy` sur le volume |
| État Terraform distant (bucket S3) | versions conservées, chiffrement, `prevent_destroy`, aucune destruction par le même code qu'il décrit |
| Paramètres et secrets (SSM, Secrets Manager) | `prevent_destroy` ; la valeur n'entre jamais dans le dépôt |

Un test (`scripts/dev/test_terraform_plan_hors_ligne.py`) **échoue** si le code Terraform contient une ressource de ce genre que ce document ne décrit pas : on ne peut pas en ajouter une sans la protéger ni l'écrire ici.

## 3. Ce qui est prouvé

### 3.1 Sur l'émulateur local : `dev.py terraform-emulateur`

Le **même code** (`infra/terraform/envs/<env>`) est appliqué à Moto, dans un conteneur Terraform. Seule une copie jetable reçoit un fichier qui redirige les adresses d'API vers `http://moto:5000`. Garanties vérifiées par des tests :

- l'émulateur et Terraform tournent sur un réseau Docker **interne** : aucune route vers Internet, donc aucun appel possible vers le vrai AWS ; un premier essai l'a montré utilement : le fournisseur tentait d'atteindre `iam.amazonaws.com`, ce qui a bloqué l'exécution au lieu de sortir ;
- seule l'étape `init` (fournisseur) utilise le réseau normal ;
- identifiants **factices**, aucune variable `AWS_*` dans les conteneurs, aucun port publié ;
- l'émulateur tourne sans droits (`--user 65534`, `--cap-drop ALL`, système de fichiers en lecture seule), image fixée par son **empreinte**.

| Étape (identique pour `dev` et `demo`) | Résultat observé le 19/11/2026 |
|---|---|
| `apply` | `Apply complete! Resources: 15 added, 0 changed, 0 destroyed.` |
| **Second plan** | **`No changes. Your infrastructure matches the configuration.`**, code de sortie 0 |
| Dérive : un groupe de journaux est modifié hors Terraform (30 jours) | le plan voit **1 changement** (`~ retention_in_days = 30 -> 14`), code 2 : **le contrôle sait échouer** |
| `apply` de correction, puis second plan | `0 added, 1 changed`, puis de nouveau `No changes` |
| `dev` : `terraform destroy` | **refusé** : `Instance cannot be destroyed … lifecycle.prevent_destroy`, sur un **vrai état** |
| `dev` : destruction des journaux seuls | `5 destroyed` côté Terraform, et **les 5 groupes existent toujours dans l'émulateur** (`skip_destroy`) |
| `demo` : `terraform destroy` | `Destroy complete! Resources: 15 destroyed.`, les groupes ont disparu de l'émulateur |

**Ce que cela prouve** : le code est **idempotent** (l'application suivie du plan ne donne aucun changement), il détecte une dérive, et ses protections jouent sur un vrai état. **Ce que cela ne prouve pas** : le comportement du vrai AWS (quotas, droits, valeurs refusées par le service, dérives que l'émulateur ne reproduit pas).

### 3.2 Hors ligne, sans émulateur : `dev.py terraform-plan-hors-ligne`

Terraform dans un conteneur, sur une copie jetable, fournisseur AWS à identifiants factices et sans appel d'API. Utile quand même : il ne dépend pas de l'émulateur.

| Fichier | Ce que Terraform dit | Ce que cela prouve | Ce que cela ne prouve pas |
|---|---|---|---|
| `plan-dev-hors-ligne.txt` | `Plan: 15 to add, 0 to change, 0 to destroy.` (5 dépôts protégés, 5 politiques, 5 groupes de journaux avec `skip_destroy = true`) | la configuration `dev` est cohérente | aucun état : pas un plan à 0 changement |
| `plan-demo-hors-ligne.txt` | `Plan: 15 to add …` (dépôts `force_delete = true`, journaux `skip_destroy = false`) | `demo` est bien jetable | idem |
| `destruction-protegee.txt` | `Error: Instance cannot be destroyed` | `destroy` refuse un dépôt protégé | l'état est **fictif** (compte `000000000000`) : remplacé par la preuve 3.1 sur un vrai état |
| `bascule-variable.txt` | le même refus avec `protected = false` | **basculer la variable ne lève pas la protection** : il faut changer le code | idem |

## 4. Comment la protection se comporte

| Situation | Effet |
|---|---|
| `terraform destroy` ou un plan qui détruit un dépôt de `dev` | **refusé** par Terraform (`prevent_destroy`), avant tout appel à AWS |
| `protected = false` sur l'appel du module | **toujours refusé** tant que le bloc `protected` existe dans le module (section 3, `bascule-variable.txt`) |
| Supprimer le dépôt à la main dans la console AWS | **non empêché** par Terraform ; mais un dépôt qui contient des images ne se supprime pas (`force_delete = false`) |
| Retirer le bloc `protected` du code, ou `terraform state rm` | lève la protection : c'est un changement de code, donc une **pull request relue** ; `main` est protégée (CLAUDE.md, point 4) |
| `terraform destroy -target=…` | contourne la limite de portée seulement si on retire la protection ; non essayé |
| `terraform destroy` de `demo` | **autorisé** : environnement jetable, dépôts détruits même pleins (CLD-21) |
| Journaux avec `skip_destroy = true` | le groupe sort de l'état et les journaux restent chez AWS. Comportement décrit par la documentation du fournisseur ; **non vérifié**, il faudrait un `apply` |

**Conséquence pour CLD-21** (nettoyage après la soutenance) : si un jour `dev` est créé sur AWS, il ne se détruit pas d'un seul `terraform destroy`. Il faut une pull request qui retire la protection, puis la destruction, après avoir sauvegardé les images utiles. `demo` se détruit sans cette étape.

## 5. Reprendre CLD-17 sur le vrai AWS, sur autorisation écrite

Conditions : accord écrit des deux membres, compte AWS ouvert avec son budget d'alerte et l'authentification à deux facteurs ([ADR-007](../01-architecture/adr/ADR-007-compte-aws.md)), CLD-10 et CLD-11 réalisées. Les variables `AWS_ROLE_ARN` et `AWS_REGION` ne se créent **pas** pour cela (elles activeraient `deploy.yml` et `terraform.yml`). Le second plan se rejoue ensuite avec un jeton de courte durée, jamais une clé longue.

| Étape | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Appliquer (premier passage) | `cd infra/terraform/envs/dev && terraform apply` | `cd infra\terraform\envs\dev; terraform apply` |
| Rejouer le plan (code de sortie 0 = aucun changement, 2 = des changements) | `terraform plan -detailed-exitcode -lock-timeout=60s \| tee plan-second.txt ; echo $?` | `terraform plan -detailed-exitcode -lock-timeout=60s \| Tee-Object plan-second.txt ; $LASTEXITCODE` |
| Garder la preuve | copier `plan-second.txt` dans `docs/05-cloud-aws/sorties-terraform/` avec son en-tête (commande, date, code de sortie) | idem |

Critère satisfait **sur AWS** seulement si la sortie contient `No changes. Your infrastructure matches the configuration.` et que le code de sortie est 0. Les sorties de la section 3 (émulateur, état fictif) ne le remplacent pas ; elles montrent que le code est prêt pour ce passage.

## 6. Rejouer les preuves

Prérequis : Docker. Les images de Terraform (`hashicorp/terraform:1.17.0`) et le cache du fournisseur sont ceux de `terraform-check` ([contrôles sans compte](controles-terraform-sans-compte.md)) ; l'émulateur est l'image `motoserver/moto` (environ 100 Mo à télécharger, 560 Mo décompressée), tirée une fois.

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| **Apply puis second plan sur l'émulateur** (`dev`, protégé) | `python3 scripts/dev/dev.py terraform-emulateur` | `py -3 scripts/dev/dev.py terraform-emulateur` |
| Idem pour `demo` (jetable), avec compte rendu écrit | `python3 scripts/dev/dev.py terraform-emulateur --env demo --sortie compte-rendu.txt` | `py -3 scripts/dev/dev.py terraform-emulateur --env demo --sortie compte-rendu.txt` |
| Premier plan hors ligne de `dev` | `python3 scripts/dev/dev.py terraform-plan-hors-ligne` | `py -3 scripts/dev/dev.py terraform-plan-hors-ligne` |
| Refus de destruction (état fictif) | `python3 scripts/dev/dev.py terraform-plan-hors-ligne --mode destruction-protegee` | `py -3 scripts/dev/dev.py terraform-plan-hors-ligne --mode destruction-protegee` |
| Les autres contrôles (format, validation, tflint) | `python3 scripts/dev/dev.py terraform-check --sans-snyk` | `py -3 scripts/dev/dev.py terraform-check --sans-snyk` |
| Tests, sans Docker | `python3 -m unittest discover -s scripts/dev -p "test_terraform_*.py"` | `py -3 -m unittest discover -s scripts/dev -p "test_terraform_*.py"` |

`terraform-emulateur` dure environ une minute par environnement et rend 0 quand **chaque** étape a donné ce qu'on attend (le second plan à 0 changement, la dérive vue, la destruction refusée ou réussie selon l'environnement). Le réseau et l'émulateur sont supprimés même après une erreur.

## 7. Choix à valider, écarts et limites

| Point | État |
|---|---|
| Ajouter les protections au code (`prevent_destroy`, `skip_destroy`) alors que rien n'est déployé | Décidé le 19/11/2026 par Manoa Robel ; **à relire par Daddy Luciano** (le code `infra/` change) |
| `protected` vaut vrai par défaut : un nouvel environnement est protégé tant qu'on ne dit pas le contraire | Choix de prudence, à valider |
| Deux blocs `aws_ecr_repository` (`protected` et `disposable`) au lieu d'un | Terraform ne rend pas `prevent_destroy` conditionnel ; la duplication est le prix de la protection |
| Contrôles exécutés après la modification | `fmt`, `init`, `validate` (dev et demo) et `tflint` : **réussis** le 19/11/2026. **Snyk IaC non lancé** (pas de jeton sur ce poste) : le job `snyk` de la CI le jouera sur la pull request |
| Les preuves 3.1 viennent d'un **émulateur** ; les sorties 3.2 d'un état vide ou fictif | Dit dans chaque fichier et ci-dessus ; seul un passage sur AWS prouve le comportement du vrai service |
| Refus d'AWS de supprimer un dépôt qui contient des images (`force_delete = false`) | Non vérifié : Moto ne reproduit pas ce refus, il faudrait AWS. La protection de Terraform (`prevent_destroy`) est, elle, prouvée |
| `skip_destroy` des journaux | **Vérifié sur l'émulateur** (les groupes restent après la destruction côté Terraform) ; comportement de CloudWatch non vérifié |
| Reformulation de l'énoncé #90 (remplacer « plan à 0 changement » par ce qui est faisable sans compte) | À décider à deux ; non faite ([remplacer AWS en local](remplacer-aws-en-local.md), section 7) |
| Option « Terraform avec le fournisseur Docker » | Écartée : elle prouvait la méthode, pas ce code ; l'émulateur applique le code réel |
| Moto reste un émulateur : il ne couvre pas tous les services de l'ADR-020 (réseau, RDS, MSK, ECS) | À réévaluer quand CLD-10 et CLD-11 seront écrites ; le script s'étend en ajoutant les adresses de ces services |
| Commandes Windows | Non vérifiées |
