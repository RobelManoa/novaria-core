# CI de l'application citoyenne : état et proposition

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano et Manoa Robel (relecture croisée)
Dernière mise à jour : 21/11/2026
Issue de suivi : CIT-07 (#275), quatrième tâche : « CI verte sur les deux postes (Linux et Windows) »
Statut : **proposition, non appliquée** : modifier les contrôles de la CI demande l'accord écrit des deux membres (`CLAUDE.md`, section 6)

Abréviations : **CI** (Continuous Integration, intégration continue), **YAML** (format des fichiers de workflow GitHub), **SAST** (Static Application Security Testing, analyse du code source).

## 1. Constat du 21/11/2026

| Contrôle | Lancé par la CI ? | Détail |
|---|---|---|
| Tests, lint, format et build de `citizen/` | **Non** | `ci.yml` ne cite pas `citizen/` : le job `frontend` ne lit que `frontend/` |
| Tests de `scripts/dev` (dont `test_application_citoyenne.py`, `test_parcours_usager.py`) | **Non** | Aucun job ne lance `unittest` sur ce dossier ; le décompte de CLAUDE.md (environ 1000 tests) vient des postes |
| Tests de la passerelle (`gateway/tests`) | Non | Déjà noté dans `gateway/README.md` |
| Poste Windows | **Aucun** | Tous les jobs sont `ubuntu-latest` |
| Snyk (dépendances, code), SonarQube, gitleaks | Oui, sur tout le dépôt ou ses dossiers listés dans `docs/04-devsecops/exceptions.md`, section 15.5 | `sonar.sources` de `sonar-project.properties` vaut `services,frontend/src,frontend/tests,data,ml` : **`citizen/` n'est pas analysé par SonarCloud** (vérifié le 21/11/2026). Snyk Code (SAST) couvre tout le dépôt, sur `main` seulement |

Conséquence : la CI d'une pull request qui ne touche que `citizen/` peut être **verte sans avoir lancé un seul de ses 184 tests**. La CI verte ne prouve donc rien sur l'application citoyenne aujourd'hui ; les preuves de CIT-04 à CIT-07 sont des sorties de commandes lancées sur un poste.

## 2. Proposition : un job `citoyen`, sur Linux et sur Windows

Ce que le job lancerait : exactement les commandes de `dev.py citoyen` (installer, lint, format, tests avec seuils de couverture, build), plus les tests Python qui ne demandent ni Docker ni navigateur.

```yaml
  # Application citoyenne (CIT-04 à CIT-07) : lint, format, tests (couverture avec seuils), build ; puis les tests Python qui la concernent.
  # Aucun réseau extérieur, aucune pile : l'API est un faux serveur (citizen/tests/parcours.test.tsx).
  citoyen:
    if: ${{ github.event_name != 'schedule' }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with: { node-version: "22", cache: npm, cache-dependency-path: "citizen/package-lock.json" }
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - name: Installer
        working-directory: citizen
        run: npm ci
      - { name: Lint, working-directory: citizen, run: npm run lint }
      - { name: Format, working-directory: citizen, run: npm run format:check }
      - { name: Tests, working-directory: citizen, run: npm test }
      - { name: Build, working-directory: citizen, run: npm run build }
      - name: Tests Python de l'application citoyenne (sans Docker ni navigateur)
        run: python -m unittest discover -s scripts/dev -p "test_application_citoyenne.py"
      - name: Tests Python du parcours usager et des essais d'abus (faux, sans Docker)
        run: |
          python -m unittest discover -s scripts/dev -p "test_parcours_usager.py"
          python -m unittest discover -s scripts/dev -p "test_acces_abus_public.py"
```

| Point | Décision à prendre |
|---|---|
| Ajouter ce job | Oui ou non, à deux. Il ajoute un contrôle, il n'en retire aucun ; il reste une modification de la CI |
| `windows-latest` | Donne enfin un poste Windows à la CI. **Non essayé** : `npm ci` et les tests Vitest tournent sous Windows en principe, mais rien n'est vérifié ici. Les tests Python lisent des fichiers avec `Path` (portable) ; `test_application_citoyenne.py` lance `git` (présent sur le runner) |
| Fichier de verrouillage | `citizen/package-lock.json` est suivi par Git (vérifié le 21/11/2026) : `npm ci` et `cache: npm` fonctionnent |
| Nom du job | `citoyen` : n'est pas un contrôle obligatoire de `main` tant que la protection de `main` ne le liste pas ; **ne pas toucher à la protection de `main`** sans accord écrit |
| Les 184 tests en CI | Ils deviendraient les premiers contrôles de `citizen/` rejoués à chaque pull request |
| Le parcours complet (`dev.py parcours`) | Reste hors CI (treize conteneurs et Chromium) : voir `tests-integration.md`, sections 7 et 10.5 |

## 3. Ce qui est fait en attendant

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Lancer à la main ce que le job lancerait | `cd citizen && npm ci && npm run lint && npm run format:check && npm test && npm run build` | `cd citizen; npm ci; npm run lint; npm run format:check; npm test; npm run build` (vérifier le code de sortie de chaque commande ; PowerShell 7 accepte `&&`) |
| Tests Python correspondants | `python3 -m unittest discover -s scripts/dev -p "test_application_citoyenne.py"` | `py -3 -m unittest discover -s scripts/dev -p "test_application_citoyenne.py"` |

Les sorties de ces commandes, jointes à l'issue ou à la pull request, sont la preuve tant que le job n'existe pas.
