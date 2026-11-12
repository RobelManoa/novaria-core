# Rapport des tests du front-end (FE-08, #76)

Mesures du 12/11/2026, sur Windows 11, Node 24.14, Edge 157. Rédigé à la main à partir des sorties de `npm test` et de `npm run e2e` ; à refaire quand les chiffres changent.

## Résultat

| Critère de l'issue | Résultat |
|---|---|
| Tests de composants (Vitest + Testing Library) | **403 tests dans 42 fichiers, tous réussis** (389 avant FE-08 : +14, ci-dessous) |
| Un parcours Playwright : connexion → tableau de bord | **3 tests réussis** en 25 s dans Edge (`e2e/connexion-tableau-de-bord.spec.ts`) |
| Couverture ≥ 70 % | **98,96 % des instructions, 94,28 % des branches, 99,19 % des fonctions, 99,56 % des lignes** ; `npm test` échoue sous 70 % (`vite.config.ts`) |
| Le parcours de bout en bout passe en CI | **Non vérifié.** Il passe en local. L'étape de CI est écrite dans un commit séparé (`ci.yml`) qui demande l'accord écrit des deux membres (CLAUDE.md, §6) ; tant qu'elle n'est pas fusionnée et exécutée sur GitHub, le critère n'est pas atteint |

## Parcours de bout en bout

Un vrai navigateur ouvre l'application **construite** (`npm run build`, servie par `vite preview`). **Seule l'API est simulée** (`e2e/support.ts`) : routeur, session, client d'API, mise en page et CSS sont réels. Les réponses du tableau de bord sont les **réponses réelles de l'API enregistrées** (`tests/fixtures/dashboard-api.json`, produites par `scripts/dev/dashboard_fixture.py`), les mêmes que celles des tests de composants. Ce n'est donc pas un essai contre le service, la passerelle et les bases : il prouve le front-end, pas la chaîne complète.

Le premier test déroule, avec une étape par ligne :

1. sans session, `/` renvoie à la connexion et aucune donnée n'est demandée ;
2. un mauvais mot de passe est refusé (message en français, champ vidé, aucune session) ;
3. les bons identifiants ouvrent le tableau de bord, le compte et le rôle s'affichent ;
4. le jeton est gardé dans `sessionStorage` seulement (jamais `localStorage`) et part en `Authorization: Bearer` dans chaque appel de données ;
5. les fenêtres d'une minute sont vides : l'écran le dit et propose les 5 minutes ;
6. les cartes (vitesse, véhicules, débit, tronçons congestionnés), le nombre de lignes du détail, l'origine « données simulées » et l'exécution sont **égaux aux valeurs de l'API**, écrites sans le code de l'application ;
7. changer la période puis la zone relit l'API, l'écran passe aux valeurs de « 6 h, INT_02 » ;
8. la navigation mène à « Alertes » (focus sur le titre) sans nouvelle connexion ;
9. un rechargement garde la session ;
10. se déconnecter efface la session et referme les pages protégées.

Deux autres tests : une session refusée par le serveur renvoie à la connexion sans afficher de données ; une panne de l'API (503) est dite avec sa référence, puis « Réessayer » relit les données.

**Le parcours détecte-t-il un défaut ?** Éprouvé en cassant le code exprès, puis restauré :

| Défaut injecté | Résultat |
|---|---|
| La vitesse moyenne affichée avec 2 décimales au lieu d'une | échec : attendu « 28,6 km/h », reçu « 28,61 km/h » |
| Route protégée qui laisse passer sans session | échec de 2 tests sur 3 : pas de renvoi vers `/connexion` |

Une 3ᵉ vérification : l'étape 7 passe par « 6 h, tout le réseau », que l'API n'a jamais enregistré (un filtre intermédiaire). Le simulateur répond 503 et le test **dit explicitement** que cette seule lecture est attendue ; toute autre lecture non enregistrée fait échouer le test.

## Couverture

Mesurée sur `src/` seulement (`coverage.include`) : sans cela, un fichier qu'aucun test n'importe n'apparaîtrait dans la mesure. Les types générés (`src/types/api/`) sont exclus.

| | Avant FE-08 | Après |
|---|---|---|
| Instructions | 98,30 % | **98,96 %** |
| Branches | 93,39 % | **94,28 %** |
| Fonctions | 97,84 % | **99,19 %** |
| Lignes | 98,91 % | **99,56 %** |

Le chiffre de 96,46 % relevé avant d'avoir restreint la mesure à `src/` comptait des fichiers de `scripts/` et de `tests/` : il n'était pas comparable. Les fichiers les moins couverts avant les ajouts : `apiMetier.ts` (71 %), `reponse.ts` (80 %), `FilterBar.tsx` (80 %), `AuthContext.ts` (83 %), `ApiStatus.tsx` (92 %).

## Tests ajoutés

| Fichier | Ce qu'il prouve |
|---|---|
| `tests/features/dashboard/FilterBar.test.tsx` (8) | formulaire nommé, chaque liste libellée, filtres reflétés, zone inconnue conservée et triée, chaque changement émet les bons filtres (nombre, pas texte ; zone vers `null`), Entrée ne recharge pas la page |
| `tests/features/auth/useAuth.test.tsx` (2) | `useAuth` hors fournisseur échoue en le disant ; libellé français de chaque rôle |
| `tests/features/api-status/ApiStatus.test.tsx` (+1) | réseau coupé : « API injoignable » avec la phrase de l'erreur |
| `tests/services/endpoints.test.ts` (+3) | `createUser`, `updateUser`, `sendSignalCommand` : méthode, chemin et corps JSON |

Les 389 tests existants couvraient déjà les composants (`tests/components/`, `tests/features/*`, `tests/hooks/`, `tests/app/`, `tests/services/`), les points de rupture, les jetons de design, le parcours de connexion en routeur mémoire, les graphiques et, depuis FE-07, l'accessibilité.

## Limites

- **La CI n'a pas exécuté le parcours** (voir plus haut) ; ce rapport ne prouve que l'exécution locale.
- API simulée : rien ne prouve ici que le service réel répond comme l'enregistrement ; l'enregistrement date du 31/10/2026.
- Un seul navigateur (Edge, moteur Chromium) ; la CI utiliserait Chromium de Playwright. Ni Firefox ni Safari.
- Le parcours n'essaie pas un téléphone, la page des prévisions, celle des rapports ni les actions sur les alertes ; ces pages ont leurs tests de composants.
- La couverture mesure les lignes exécutées, pas la qualité des assertions : d'où les mutations ci-dessus, faites à la main sur deux défauts seulement.
- Constat : sur ce poste (0,6 Go de mémoire libre), la suite complète dépasse des délais avec les réglages par défaut ; tout passe avec `--maxWorkers=2 --testTimeout=30000`.
- Playwright 1.52 se bloquait sous Node 24 (même `--list`) : version 1.64.1 retenue, ainsi que pour `playwright-core` (utilisé par l'audit FE-07).

## Reproduire

```bash
cd frontend
npm ci
npm test                                   # Vitest, couverture, seuil de 70 %
npm run build
E2E_CHANNEL=msedge npm run e2e             # ou sans E2E_CHANNEL après : npx playwright install chromium
```

`npm run e2e` écrit le rapport HTML dans `e2e-report/` (ignoré par Git) et, en cas d'échec, une capture et une trace dans `test-results/`.
