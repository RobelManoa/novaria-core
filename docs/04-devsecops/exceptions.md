# Politique de vulnérabilités et exceptions de sécurité

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 20/10/2026
Issue de suivi : CLD-23
Statut : proposition à valider par les deux membres (relecture de la pull request)

Ce document fixe trois règles : dans quel délai une faille est corrigée, qui accepte une exception, et pendant combien de temps. Il liste aussi les exceptions actives.

Abréviations : CI (Continuous Integration, intégration continue), UTC (temps universel coordonné).

## 1. Principe

| Élément | Règle |
|---|---|
| Seuil bloquant | Une faille de gravité **high** ou **critical** fait échouer le contrôle `snyk` ou `docker` de la CI ; la pull request ne peut pas être fusionnée |
| Corriger d'abord | Une faille avec correctif publié se corrige : mise à jour de la dépendance, de l'image de base ou des paquets système (`apt-get upgrade`, `apk upgrade`) |
| Exception en dernier recours | Une exception n'existe que si **aucun correctif n'est publié** ou si le faux positif est démontré |
| Jamais d'exception | Pour un secret détecté par `gitleaks` : le secret est révoqué et remplacé, quelle que soit la gravité |
| Seuil non abaissé | Aucune exception ne passe par une baisse du seuil, l'option `--exclude-base-image-vulns`, une commande forcée en succès ou `continue-on-error` |

## 2. Délais de correction

Le délai court à partir de la date où la faille est connue du binôme (échec de la CI ou du scan hebdomadaire) et où un correctif est publié.

| Gravité | Correctif publié | Aucun correctif publié |
|---|---|---|
| critical | Corrigée avant la fusion, ou sous **7 jours** si découverte par le scan hebdomadaire | Exception de 30 jours au plus, avec ligne dans le registre des risques |
| high | Corrigée avant la fusion, ou sous **14 jours** si découverte par le scan hebdomadaire | Exception de 30 jours au plus, avec ligne dans le registre des risques |
| medium, low | Traitée avec les mises à jour mensuelles de Dependabot (une pull request groupée) | Surveillée, sans exception |

## 3. Qui décide d'une exception

| Étape | Qui |
|---|---|
| Proposer | La personne qui rencontre la faille : une pull request qui modifie `.snyk`, ce document et le registre des risques |
| Décider | L'**autre membre** du binôme, en approuvant la pull request (relecture croisée) ; la session qui a écrit la modification ne l'approuve pas |
| Responsable de l'exception | Manoa Robel (équipe cloud et livraison, issue CLD-23) |
| Information du professeur | Les exceptions actives figurent dans ce document et dans le registre des risques, consultables à chaque jalon |

## 4. Durée maximale

| Règle | Valeur |
|---|---|
| Durée d'une exception | **30 jours** au plus à partir de la date de création |
| Expiration | Toujours **avant le 10/12/2026**, date de la soutenance : la dernière expiration autorisée est le **09/12/2026** |
| Renouvellement | Possible après une nouvelle vérification : correctif publié ou non, avec une nouvelle ligne datée ; sans nouvelle vérification, l'exception expire |
| À l'expiration | Snyk ignore de nouveau l'exception : si la faille persiste, la CI échoue |

## 5. Contenu obligatoire d'une exception

Chaque exception de `.snyk` a ces quatre éléments, vérifiés par un test (section 8) :

| Élément | Où |
|---|---|
| Identifiant Snyk | Clé dans `.snyk`, ligne du tableau de la section 6 |
| Raison (`reason`) | `.snyk`, avec la référence de ce document |
| Expiration (`expires`) | `.snyk` et tableau de la section 6 |
| Entrée au registre des risques | Ligne R10 de `docs/07-gestion/registre-risques.md`, qui cite l'identifiant |

## 6. Exceptions actives

| Identifiant Snyk | Composant | Image | Raison | Créée le | Expiration | Registre |
|---|---|---|---|---|---|---|
| SNYK-DEBIAN13-ZLIB-19520500 | zlib1g (Out-of-bounds Write) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-10-17 | 2026-11-15 | R10 |
| SNYK-DEBIAN13-ATTR-17678182 | libattr1 (Link Following) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-10-17 | 2026-11-15 | R10 |
| SNYK-DEBIAN13-ACL-17677866 | libacl1 (Link Following) | backend (python:3.12-slim, Debian 13) | Aucun correctif publié par Debian à la date de création | 2026-10-17 | 2026-11-15 | R10 |

## 7. Scan hebdomadaire

| Élément | Valeur |
|---|---|
| Déclencheur | `schedule` dans `.github/workflows/ci.yml` : chaque **lundi à 06:00 UTC** |
| Branche | `main` : GitHub n'exécute un scan planifié que depuis la branche par défaut. Tant que ce fichier n'est pas fusionné dans `main`, le scan ne tourne pas |
| Jobs exécutés | `snyk` (dépendances) et `docker` (construction des images et analyse Snyk). Les autres jobs sont réservés aux pull requests et aux pushes |
| But | Détecter une nouvelle faille d'une image de base ou d'une dépendance sans attendre une pull request |
| Si le scan échoue | La personne responsable (Manoa Robel) ouvre une issue, applique le délai de la section 2 et, sans correctif publié, ajoute une exception selon les sections 3 à 5 |
| Vérification | Onglet Actions de GitHub, workflow CI, événement `schedule` |

## 8. Contrôle automatique

Le test `scripts/dev/test_exceptions.py` vérifie que chaque exception de `.snyk` :

- a une raison et une expiration ;
- expire avant le 10/12/2026 et au plus 30 jours après sa création ;
- figure dans le tableau de la section 6 avec la même expiration ;
- est citée dans le registre des risques.

| Linux (bash) | Windows (PowerShell) |
|---|---|
| `python3 -m unittest discover -s scripts/dev` | `py -3 -m unittest discover -s scripts/dev` |

## 9. Revue et suppression

| Moment | Action |
|---|---|
| Avant l'expiration | Reconstruire l'image backend (la ligne `apt-get upgrade` du Dockerfile récupère les correctifs publiés) et relancer l'analyse |
| Faille corrigée | Supprimer l'exception de `.snyk` et sa ligne du tableau de la section 6, puis noter la fermeture (date, version corrigée) dans la ligne R10 du registre des risques |
| Faille toujours sans correctif | Renouveler selon la section 4 |
| Fin de projet | Aucune exception ne doit rester active après le 09/12/2026 |
