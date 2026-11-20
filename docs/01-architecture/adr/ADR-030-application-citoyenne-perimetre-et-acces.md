# ADR-030 — Application citoyenne : un usager sans compte, en lecture seule, par des routes publiques à liste blanche

| Champ | Valeur |
|---|---|
| Date | 20/11/2026 |
| Statut | Proposée : à valider par les deux membres |
| Décideurs | Daddy Luciano, Manoa Robel |
| Validation du professeur | À demander (demande C-08 du [registre](../../07-gestion/registre-des-demandes.md)) |
| Issues liées | CIT-01 (#269, cette décision), CIT-02 à CIT-08 (jalon M6) ; demandes C-03 et C-08 |
| Compétences BC05 | Architecture, Sécurité applicative |
| S'appuie sur | [ADR-008](ADR-008-microservices.md), [ADR-027](ADR-027-jeux-de-donnees-et-provenance.md), [ADR-028](ADR-028-etats-de-congestion-et-alertes.md), [ADR-029](ADR-029-passerelle-et-authentification.md) |
| Précise | La demande C-03 : « alertes envoyées aux usagers et consultables sur le tableau de bord » |

Abréviations : **PoC** (Proof of Concept, démonstration de faisabilité), **API** (Application Programming Interface, interface de programmation), **JWT** (JSON Web Token, jeton signé), **CORS** (Cross-Origin Resource Sharing, partage entre origines), **DTO** (Data Transfer Object, objet qui décrit exactement ce qui sort d'une API), **SSE** (Server-Sent Events, flux du serveur vers le navigateur), **RGPD** (Règlement général sur la protection des données), **CI** (Continuous Integration, intégration continue).

## 1. Problème

La demande C-03 promet des alertes « envoyées aux usagers ». Aujourd'hui, le seul écran est le **tableau de bord de l'équipe** : il exige un compte, montre des indicateurs détaillés (comptages, vitesses, identifiants de carrefours), les feux et leur commande manuelle. Un citoyen n'a rien à y faire, et **ne doit rien y voir de ce qu'il montre**. Il faut décider, avant d'écrire du code :

1. **qui** est l'usager ;
2. **ce que l'application lui montre en v1**, et ce qu'elle ne montrera pas ;
3. **comment il y accède** : sans compte, ou avec un rôle ;
4. **ce qu'il ne voit jamais**.

Contexte : le projet est un **PoC** (démonstration de faisabilité), exécuté en local ([ADR-023](ADR-023-execution-locale-d-abord.md)), avec des données simulées ([ADR-027](ADR-027-jeux-de-donnees-et-provenance.md)). La soutenance est le 10/12/2026 et le jalon M6 se termine le 08/12/2026.

## 2. Forces de décision

| Critère | Poids |
|---|---|
| Aucune donnée interne ni personnelle ne sort vers le public, même par oubli d'un champ | Fort |
| Un citoyen consulte **sans compte** (demande de l'issue CIT-01) | Fort |
| Tenir en M6 : peu de code, pas de nouveau service, pas de nouveau droit de base | Fort |
| Réutiliser la passerelle et les contrats (ADR-029), pas un second mécanisme | Moyen |
| Lisible sur téléphone, accessible, en français | Moyen |
| Dire que la donnée est simulée ([ADR-027](ADR-027-jeux-de-donnees-et-provenance.md)) | Fort |

## 3. Options comparées

### 3.1 Accès

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| A. **Routes publiques en lecture seule**, sans jeton, sous `/api/v1/public/`, derrière la passerelle | Aucun compte ; surface minuscule et explicite ; mécanisme déjà employé (`security: []` dans le contrat pour `/health` et `/auth/login`) | Première surface sans jeton : abus de débit et fuite de champ à prévenir | **Retenue** |
| B. Rôle `citizen` avec compte et mot de passe | Identité connue, abonnements côté serveur possibles | Inscription, mots de passe et données personnelles à gérer ; contredit « sans compte obligatoire » ; hors de portée d'un PoC en M6 | Écartée pour la v1 (réexamen si des notifications réelles sont voulues) |
| C. Rôle `viewer` partagé par tous les citoyens (jeton d'invité dans le front) | Aucune route nouvelle | Un secret dans le navigateur de tout le monde ; le jeton donne **toutes** les routes `viewer` (indicateurs détaillés, feux) | Écartée |
| D. Réutiliser les routes `viewer` existantes, sans jeton | Aucun code | Expose les données internes ; casse ADR-029 | Écartée |

### 3.2 Qui sert les routes publiques

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| E. Un cinquième service « public » | Isolation totale | Contredit les quatre services d'[ADR-008](ADR-008-microservices.md) ; un compte de base et un déploiement de plus ; risque R11 (complexité) | Écartée |
| F. **Chaque service sert la part qu'il possède** : `traitement` l'état par tronçon (il lit déjà l'entrepôt avec un compte en lecture seule), `alerte` les alertes en cours (son schéma) | Aucun droit de base nouveau ; aucun service nouveau | Deux routes dans deux services, un contrat chacune | **Retenue** |

### 3.3 Application

| Option | Verdict |
|---|---|
| React Native (application native) | **Écartée** : PoC, un second outil de construction, aucun besoin de l'appareil (pas de notification réelle) |
| **React avec Vite, dans une application distincte du tableau de bord**, pensée pour téléphone | **Retenue** : même outillage que `frontend/`, rien de partagé avec l'authentification de l'équipe |
| Une page publique dans le tableau de bord existant | Écartée : une erreur de route donnerait accès à l'écran de l'équipe |

## 4. Choix

### 4.1 L'usager

Un **citoyen qui se déplace** dans la ville : il consulte l'état de la circulation et voit les alertes de congestion en cours. Il n'est **pas** l'opérateur (qui accuse réception et commande les feux), ni l'administrateur, ni l'observateur de l'équipe. Il est **anonyme** : l'application ne sait rien de lui.

### 4.2 Périmètre de la v1

| Inclus | Précision |
|---|---|
| **Lecture seule** | Aucune écriture, aucune action sur le réseau |
| **État de congestion par tronçon** | Un état parmi trois (ADR-028), dit en français : `FREE_FLOW` → « Fluide », `SLOW` → « Ralenti », `CONGESTED` → « Congestionné ». Le tronçon est désigné par son identifiant public (`road_segment_id`), son carrefour (`intersection_id`) et son côté (`approach`). Heure de la dernière mise à jour |
| **Alertes en cours** | Seulement le type `CONGESTION`, dans les états non résolus ; tronçon, gravité (`INFO`, `WARNING`, `CRITICAL`, dite en français), heure d'ouverture |
| **Mention « Données simulées »** | Toujours visible quand la provenance est `SIMULATED` (ADR-027, EXG-NFR-13) |
| **Rafraîchissement** | Interrogation régulière (de l'ordre de 5 à 10 secondes), pas de flux SSE : `/api/v1/events/stream` reste réservé aux comptes |
| **Suivi d'un tronçon** | Enregistré **dans le navigateur seulement**. Quand une alerte naît sur un tronçon suivi, l'application l'affiche (« notification simulée ») : aucun courriel, SMS ni notification poussée, aucun canal réel. Le consentement est affiché |
| **Langue et accessibilité** | Français ; cibles WCAG 2.1 AA, comme le tableau de bord (EXG-NFR-15) |

**Hors v1** (noté dans le registre, exclusion X-07) : compte citoyen, notifications réelles, géolocalisation de l'usager, itinéraires, prévisions, historique, application native.

### 4.3 L'accès : option A

1. Deux routes, **`GET` seulement** : `GET /api/v1/public/congestion` (`traitement`) et `GET /api/v1/public/alerts` (`alerte`). Elles sont déclarées dans les contrats OpenAPI avec `security: []` ; la table de la passerelle est **générée** (ADR-029) : une route publique n'existe que si un contrat la déclare. Toute autre route sous `/api/v1/public/` répond 404 ; toute méthode autre que `GET` est refusée.
2. **Pas de jeton, pas de cookie, pas de compte.** Un jeton d'équipe envoyé à une route publique n'est ni lu ni utile : il ne donne **rien de plus** que l'anonyme.
3. **Chaque réponse est un DTO écrit pour le public**, avec une **liste blanche** de champs (section 4.4). Le modèle interne n'est jamais sérialisé tel quel : un champ ajouté demain au modèle n'apparaît pas dehors.
4. **Limitation de débit propre aux routes publiques** (zone distincte de la passerelle, valeur fixée par CIT-02), en-tête `Cache-Control` court, **CORS limité à l'origine de l'application citoyenne**, sans `Access-Control-Allow-Credentials`, erreurs sans détail interne.
5. **Aucune donnée personnelle n'est demandée ni enregistrée par l'application** (pas de formulaire, pas de compte, pas d'identifiant de visiteur). Le journal technique de la passerelle garde l'adresse du client : à réduire pour les routes publiques (CIT-06) ; cette décision n'a pas reçu d'analyse juridique (RGPD) : un PoC simulé n'est pas une mise en production.

### 4.4 Ce que l'usager ne voit jamais

| Jamais exposé | Pourquoi | Champ ou route concernée |
|---|---|---|
| **Données brutes** des capteurs | Ce sont des mesures internes, pas une information au public | `raw_events`, `POST /api/v1/measurements`, comptages (`vehicle_count`, `flow_veh_per_min`), vitesses (`average_speed_kmh`, `speed_ratio`), `sample_count` |
| **Capteurs** | Leur identité et leur emplacement n'ont pas à être publics ; un capteur muet est un souci d'exploitation | `sensor_id`, alertes `SENSOR_FAULT` |
| **Commandes et état des feux** | Aucune commande ne se prépare depuis une route publique | `/api/v1/signals`, `/api/v1/signals/*/commands`, recommandations |
| **Nom de l'opérateur** | Donnée personnelle | `acknowledged_by` |
| **Cause d'une alerte, règle, épisode, historique** | La cause est toujours `UNKNOWN` (une baisse de vitesse ne prouve pas un accident, ADR-028) ; le reste est interne | `cause`, `rule_id`, `episode_id`, `resolution`, historique |
| **Provenance interne** | Seule la mention « simulée » est utile | `run_id`, `scenario_id`, `seed`, `classifier_version` |
| **Comptes, règles d'alerte, rapports, prévisions, journal d'audit** | Réservés à l'équipe | `/api/v1/users`, `/api/v1/alert-rules`, `/api/v1/reports`, `/api/v1/forecasts` |

**Champs publics, et seulement eux.** Congestion : `road_segment_id`, `intersection_id`, `approach`, `state`, `updated_at`, `simulated`. Alerte : `alert_id`, `road_segment_id`, `intersection_id`, `severity`, `opened_at`, `simulated`. Un test compare l'ensemble des champs de chaque réponse à cette liste (CIT-02, CIT-06).

### 4.5 L'application

Application **React avec Vite et TypeScript**, dans un dossier à part du tableau de bord, **conçue pour téléphone** (lecture seule, sans graphique), qui n'embarque aucun secret et n'appelle que les deux routes publiques. Son dossier, son conteneur et son port sont décidés par CIT-04.

### 4.6 Qualité et livraison pendant le développement

Le code citoyen est développé sur une **branche de travail temporaire** (`dev-citoyen`), qui tient lieu de `main` pendant le développement. Pendant ce temps, les contrôles SonarQube et Snyk ne bloquent pas cette branche (la protection de `main` ne la couvre pas). **Cette décision ne change aucun contrôle de la CI** (CLAUDE.md, point 6 : toute modification demande l'accord écrit des deux membres) :

- les contrôles continuent de s'exécuter sur les pull requests ; leurs résultats sont **lus et consignés**, pas masqués ;
- **avant toute fusion de la branche dans `main`**, ces contrôles doivent passer, ou une exception documentée (`docs/04-devsecops/exceptions.md`, avec raison et date d'expiration) doit être acceptée par les deux membres ;
- la tâche CIT-06 (« Scan Snyk et gitleaks verts sur le nouveau code ») reste dans le backlog et sera tenue ou amendée explicitement.

## 5. Conséquences

| Conséquence | Mesure |
|---|---|
| Première surface publique du projet : un champ oublié ou un abus de débit | DTO à liste blanche et test d'égalité des champs ; zone de débit dédiée ; matrice d'accès étendue (`dev.py acces`) avec un essai autorisé et un refusé (CIT-02, CIT-06) ; risque R13 |
| Une alerte et un état sont servis par deux services | L'application interroge deux routes ; si l'une est indisponible, elle le dit et garde l'autre (cas d'échec CE-30) |
| Pas de compte : aucun abonnement serveur, donc aucune vraie notification | Limite assumée du PoC ; réexamen si une notification réelle devient un objectif |
| Jalon M6 court (8 jours avant la soutenance) | Périmètre minimal, aucun nouveau service ni droit de base ; risque R14 |
| Le tableau de bord de l'équipe et l'application citoyenne divergent | Aucun composant d'authentification partagé ; vocabulaire public défini ici |

## 6. Repli

Si les routes publiques posent problème en M6 : l'application citoyenne lit des **instantanés générés** par un script (fichier JSON d'état et d'alertes, produit à partir de l'API avec un compte `viewer` côté poste, sans exposer la passerelle). On perd le rafraîchissement direct, pas le périmètre.

## 7. Vérification

- `contracts/openapi/` contient les deux routes publiques (`security: []`) ; `gateway_routes.py` génère leur entrée ; **toute autre route sous `/api/v1/public/` répond 404** (CIT-02).
- Un test compare les champs de chaque réponse publique à la liste de la section 4.4 ; un champ de plus fait échouer le test (CIT-02, CIT-03).
- Un jeton d'équipe, une écriture, une route interne et un dépassement de débit **échouent tous sur une route publique** (matrice d'accès, CIT-06).
- Un citoyen voit l'état de la circulation sur téléphone **sans se connecter**, avec « Données simulées » (CIT-04).
- Une alerte créée par le service apparaît dans l'application en moins de 10 secondes (CIT-05).

## 8. Conditions de réexamen

| Condition | Effet |
|---|---|
| Le professeur ou le binôme veut de vraies notifications | Réexaminer l'option B (rôle `citizen`) et le consentement ; analyse RGPD |
| Une donnée réelle remplace la simulée | Revoir ce que le public peut voir et la mention de provenance |
| Une fuite de champ ou un abus est observé | Fermer la route (404) avant de corriger ; revoir la liste blanche |
| Le projet quitte `localhost` | TLS, authentification de la passerelle et journalisation à revoir (revue de sécurité) |

## 9. À mettre à jour ensuite (hors de cette décision)

Diagramme de contexte C4 (« Usager → Novaria Core » passe de « via le tableau de bord » à « via l'application citoyenne »), dictionnaire de données et contrats : CIT-02 et CIT-08.
