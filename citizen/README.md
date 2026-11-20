# Application citoyenne (PoC)

L'état de la circulation en ville, **sans compte, en lecture seule**, pensé pour un téléphone. Décision : [ADR-030](../docs/01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md) ; mode d'emploi et preuves : [application-citoyenne.md](../docs/08-exploitation/application-citoyenne.md).

> **Données simulées.** Tout ce que l'application montre vient du simulateur du dépôt ; elle le dit en permanence à l'écran.

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Lancer (la pile doit tourner : `dev.py up`) | `python3 scripts/dev/dev.py citoyen` ou `make citoyen` | `py -3 scripts/dev/dev.py citoyen` |
| Version construite | `python3 scripts/dev/dev.py citoyen apercu` | `py -3 scripts/dev/dev.py citoyen apercu` |
| Tests, couverture, lint | `python3 scripts/dev/dev.py citoyen test` puis `cd citizen && npm run lint` | idem avec `py -3` |
| Captures sur écran de téléphone | `python3 scripts/dev/dev.py citoyen captures` | `py -3 scripts/dev/dev.py citoyen captures` |

Adresse : `http://127.0.0.1:5174` (liée à `127.0.0.1` : rien n'est joignable depuis le réseau).

## Ce qu'il y a dedans

| Dossier ou fichier | Rôle |
|---|---|
| `src/api.ts` | **Le seul appel réseau** : `GET /api/v1/public/congestion`, sans jeton ni cookie, réponse vérifiée champ par champ |
| `src/useCongestion.ts` | Lecture, puis relecture toutes les 15 secondes (arrêtée quand la page est cachée) ; une erreur garde les dernières données |
| `src/labels.ts`, `src/messages.ts` | Les mots de l'écran : « Fluide », « Ralenti », « Congestionné », jamais un code technique |
| `src/components/` | État (mot + forme, jamais la couleur seule), carte d'un tronçon, résumé, avis |
| `src/styles.css` | Mobile d'abord, thème clair et sombre, contrastes vérifiés par un test |
| `tests/` | Vitest : API, écrans et états, contrastes WCAG, audit axe-core de chaque état |
| `scripts/captures.mjs` | Les captures de `docs/Capture d'ecran/CIT-04-*.png` |

## Règles qui font échouer le lint ou les tests

- Aucun `fetch` hors de `src/api.ts` ; aucune route autre que la route publique.
- Aucun `localStorage`, `sessionStorage`, `indexedDB`, cookie ni en-tête `Authorization` : l'application ne garde rien sur l'appareil.
- Les valeurs (états, côtés, champs) sont comparées au contrat par `scripts/dev/test_application_citoyenne.py`.
