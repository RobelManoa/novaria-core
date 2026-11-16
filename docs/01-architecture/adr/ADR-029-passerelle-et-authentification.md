# ADR-029 — Passerelle d'API : le jeton et le rôle sont contrôlés avant tout service

| Champ | Valeur |
|---|---|
| Date | 12/11/2026 |
| Statut | Proposée : à valider par les deux membres |
| Décideurs | Daddy Luciano, Manoa Robel |
| Validation du professeur | Non demandée |
| Issues liées | MS-13 (#132), BE-03, BE-08, MS-06, MS-11, MS-12 |
| Compétences BC05 | Architecture, Sécurité applicative |
| S'appuie sur | [ADR-008](ADR-008-microservices.md), [ADR-012](ADR-012-validation-contrats-zod.md) |
| Réponse au | point ouvert n° 2 des [diagrammes C4](../c4/README.md) (« Qui valide le jeton ? ») |

## 1. Problème

Chaque service validait seul le jeton (BE-03 dans `traitement`, copie dans `alerte` et `reponse`) : trois contrôles écrits trois fois, un service oublié laisse passer, et la clé de signature se répand. Le critère de MS-13 : **un appel sans jeton valide est refusé pour tous les services.**

## 2. Forces de décision

| Critère | Poids |
|---|---|
| Aucune route sans contrôle, même oubliée dans un service | Fort |
| Rôles décidés à partir des contrats (source de vérité) | Fort |
| Pas de dépendance d'un service à un autre pour authentifier | Fort |
| Tenir en local avec Docker Compose, sans compte cloud | Fort |
| Peu de code à maintenir | Moyen |

## 3. Options comparées

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| A. Chaque service contrôle seul (état actuel) | Aucun point commun | Un contrôle par service à tenir identique ; l'oubli est silencieux | Insuffisante seule |
| B. nginx `auth_request` vers l'API métier | Pas de clé à la passerelle ; compte relu en base | Toute requête dépend de `traitement` : s'il tombe, la commande des feux devient inaccessible (ADR-008 : la réponse survit aux pannes des autres) | Écartée |
| C. Traefik + greffon JWT tiers | Rôles par middleware | Greffon hors dépôt à auditer ; autre technologie que le front-end | Écartée |
| D. nginx + njs : vérification HS256 locale, table de rôles générée depuis les contrats | Aucune dépendance de service ; une table unique ; même nginx que le front-end | La passerelle détient la clé ; ne relit pas le compte | **Retenue** |

## 4. Choix

1. La **passerelle vérifie** le jeton (HS256 fixé, revendications obligatoires, expiration) **et le rôle** avant d'envoyer la requête. Mécanisme : nginx avec njs (`gateway/auth.js`), appelé par `auth_request`.
2. Les **routes, méthodes et rôles sont générés depuis les contrats OpenAPI** (`scripts/dev/gateway_routes.py`) : une route absente des contrats n'existe pas (404) ; un test échoue si les fichiers générés ne sont pas à jour.
3. Les services **gardent** leur contrôle (défense en profondeur) : un accès direct à un service reste refusé sans jeton. `traitement` relit en plus le compte à chaque requête.
4. **Limitation de débit, CORS et en-têtes de sécurité** sont posés par la passerelle, qui efface ceux des services : une seule source. La limite de la connexion (BE-08) reste aussi dans le service.
5. **Secrets hors du code** : `JWT_SECRET` n'existe que dans l'environnement du conteneur ; une clé absente, courte ou d'exemple hors local fait refuser toute route protégée (503), jamais accepter.

## 5. Conséquences

| Conséquence | Mesure |
|---|---|
| La passerelle détient la clé HS256 : qui la connaît émet un jeton | Même exposition que dans `alerte` et `reponse` ; clé asymétrique à prévoir si la passerelle est le seul point de contrôle |
| La passerelle ne relit pas le compte : un compte désactivé passe jusqu'à l'expiration du jeton (30 min) | `traitement` le refuse ; pour `alerte` et `reponse`, même limite qu'avant MS-13 |
| Une seule instance du contrôle à prouver | `gateway/tests/test_gateway.py` essaie chaque route des contrats sur la vraie passerelle ; 42 mutations de `auth.js` détectées |
| Un nouveau service ou une nouvelle route doit être dans un contrat avec son rôle | `gateway_routes.py` refuse une route protégée sans `x-required-role` |
| Image nginx avec njs (variante non « slim ») | Épinglée dans `docker-compose.yml`, vérifiée par `test_compose.py` |

## 6. Repli

Si njs pose problème : option B (`auth_request` vers `traitement`), au prix de la dépendance décrite ci-dessus ; `routes.json` reste la table des rôles.
