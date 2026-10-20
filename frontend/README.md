# Frontend (React + Vite + TypeScript)

Tableau de bord web de Novaria Core : React 19, Vite 6, TypeScript 5.7, Vitest 3. L'interface est en français et doit rester utilisable sur un téléphone (360 px de large) comme sur un ordinateur (1280 px et plus).

```bash
npm ci
npm run dev        # http://localhost:5173 (proxy /api vers le backend, port 8000)
npm test           # vitest + couverture (coverage/lcov.info)
npm run lint && npm run format:check
npm run build      # contrôle de types puis construction
```

Formater : `npx prettier --write src`.

## Arborescence de `src/`

| Dossier | Rôle |
|---|---|
| `app/` | Assemblage : `App.tsx`, `router.tsx` (tableau de routes exporté), `bootstrap.tsx` (montage), `AppShell/` (mise en page) |
| `pages/` | Une page par route (`DashboardPage`, `AlertsPage`, `TrafficLightsPage`, `ForecastsPage`, `ReportsPage`, `NotFoundPage`) |
| `features/` | Fonctionnalités : `navigation/` (entrées du menu), `theme/` (thème et sélecteur), `api-status/` (état de l'API) |
| `components/` | Composants génériques sans logique métier (`PageHeader`, `SkipLink`, `IconButton`, `Container`, `VisuallyHidden`, `ComingSoon`) |
| `hooks/` | `useMediaQuery`, `useDisclosure`, `useEscapeKey`, `useFocusTrap`, `useScrollLock` |
| `services/` | Appels à l'API |
| `styles/` | `tokens.css` (jetons), `global.css` (base), `breakpoints.ts` (points de rupture) |
| `types/` | Types partagés |

Les tests sont dans `tests/`, avec la même arborescence que `src/`. L'alias `@/` désigne `src/` (déclaré dans `vite.config.ts` et `tsconfig.json`).

## Règles de dépendance

Un dossier n'importe jamais un dossier « plus haut » dans cet ordre : `components` ← `features` ← `pages` ← `app`.

| Dossier | N'importe pas |
|---|---|
| `components/` | `features/`, `pages/`, `app/` |
| `features/` | `pages/`, `app/` |
| `hooks/`, `services/`, `types/` | `components/`, `features/`, `pages/`, `app/` |

ESLint impose ces règles (`no-restricted-imports` dans `eslint.config.js`) : une importation interdite fait échouer `npm run lint`. `tests/architecture/dependency-rules.test.ts` vérifie la règle sur des cas autorisés et interdits.

## Jetons de design et thème

Tout style passe par les variables CSS de `src/styles/tokens.css` : couleurs sémantiques (`--color-bg`, `--color-text`, `--color-primary`, `--color-danger`…), espacements (`--space-1` à `--space-8`, échelle de 4 px), typographie (polices du système, `--text-xs` à `--text-3xl`), rayons, ombres, `--tap-min` (zone tactile de 44 px) et niveaux de superposition. Un composant n'écrit aucune couleur ni taille en dur (un test le vérifie).

Le thème a trois modes : Clair, Sombre et Système (par défaut). L'attribut `data-theme` de `<html>` vaut `light` ou `dark` ; absent, il suit la préférence du système. Le choix est mémorisé dans `localStorage` (accès protégés : l'application fonctionne sans stockage) et appliqué avant le premier rendu. Les contrastes de chaque paire texte/fond respectent WCAG AA dans les deux thèmes (test dans `tests/styles/tokens.test.ts`).

## Points de rupture

Mobile d'abord, avec `min-width` : **40rem** (tablette) et **64rem** (ordinateur). Au-dessus de 64rem, la navigation est une barre latérale ; en dessous, c'est un tiroir. Les variables CSS ne fonctionnent pas dans les requêtes média : les valeurs sont écrites dans `tokens.css` (commentaire) et dans `breakpoints.ts`, et un test vérifie qu'elles restent identiques. N'utilisez pas d'autre valeur de `min-width` dans une feuille de style de composant.

## Ajouter une page et une entrée de menu

1. Créer `src/pages/MaPage.tsx` avec un `PageHeader` (titre et phrase d'introduction).
2. Ajouter la route dans `src/app/router.tsx` : `{ path: "ma-page", element: <MaPage />, handle: handle("Ma page") }`. Le titre sert à `document.title` et au repère de la page.
3. Ajouter l'entrée dans `src/features/navigation/entries.ts` : `{ path: "/ma-page", label: "Ma page" }`. Un test vérifie que chaque entrée correspond à une route titrée.
4. Ajouter un test dans `tests/app/navigation.test.tsx` si la page a un comportement propre.

## Vérifier avant une pull request

```bash
npm ci && npm run lint && npm run format:check && npm test && npm run build
```

Le job `frontend` de la CI exécute ces mêmes commandes. Pour le conteneur : `docker build -t novaria-frontend:test frontend`, puis lancer l'image avec le service `backend` accessible (par exemple `docker compose up --build`) ; `nginx.conf` renvoie toute route inconnue vers `index.html`, donc un rechargement direct de `/alertes` fonctionne.

## Décisions

- **Routeur** : `react-router` 7 (`createBrowserRouter` dans l'application, `createMemoryRouter` dans les tests). Les routes sont un tableau exporté pour être testées sans navigateur. `RouterProvider` est importé depuis `react-router` et non depuis `react-router/dom` : ce sous-chemin charge une seconde copie du routeur dans Vitest et casse les contextes ; la seule fonction perdue est `flushSync` pour les transitions de vue, inutilisée ici.
- **Styles** : CSS Modules (`*.module.css`) pour les composants et variables CSS pour les jetons, sans bibliothèque de composants ni de styles.
- **Thème** : un attribut `data-theme` sur `<html>` et deux jeux de variables, plutôt qu'une classe par composant. Le jeu sombre existe deux fois (choix explicite et préférence du système) car le CSS n'a pas de moyen de le partager ; un test vérifie qu'ils restent identiques.
- **Tiroir mobile** : l'élément `inert` rend le fond non interactif ; un piège à focus minimal garde le clavier dans le tiroir, sans bibliothèque.
