# Gabarit de prompt pour une issue

Ce gabarit sert à démarrer une session Claude Code sur une issue. `CLAUDE.md` (racine du dépôt) fournit déjà les conventions : le prompt n'a besoin que de l'issue, du système et de la limite du travail.

## 1. Gabarit à copier

```text
Système : <Linux (Ubuntu) | Windows PowerShell>
Issue : <ID> (<lien ou numéro>)
But en une phrase : <ce qui doit exister à la fin>
Ce que tu fais : <liste courte des tâches de l'issue concernées>
Ce que tu ne fais pas : <hors périmètre : autres issues, CI, AWS, protection de branche>
Fichiers à lire d'abord : <chemins>
Preuve attendue : <sortie de commande, test, capture>

Avant de modifier un fichier, donne ton plan en 5 lignes maximum et attends mon accord.
```

## 2. Exemple rempli : LOC-01 (Daddy, Windows)

```text
Système : Windows PowerShell
Issue : LOC-01 (PostgreSQL local sous Windows)
But en une phrase : db-up et db-check donnent 9 lignes [OK] pour PostgreSQL sur mon poste.
Ce que tu fais : me guider pas à pas dans docs/08-exploitation/poste-de-travail.md, corriger la documentation si une étape échoue.
Ce que tu ne fais pas : MongoDB (LOC-02), CI, AWS, protection de branche.
Fichiers à lire d'abord : docs/08-exploitation/poste-de-travail.md, docs/03-donnees/base-de-donnees-locale.md
Preuve attendue : sortie de db-check, sans mot de passe.

Avant de modifier un fichier, donne ton plan en 5 lignes maximum et attends mon accord.
```

## 3. Contrôle de la réponse

| Vérification | Pourquoi |
|---|---|
| Les commandes sont dans la variante de mon système | Une commande bash ne marche pas dans PowerShell |
| La branche s'appelle `feature/<ID>-titre` | Convention du dépôt |
| Aucun secret n'apparaît dans la réponse, les fichiers ou les messages de commit | Dépôt public |
| Aucune ressource AWS (Amazon Web Services), aucun changement de CI (Continuous Integration, intégration continue) ni de protection de branche | ADR-023 et `CLAUDE.md` |
| Chaque affirmation technique est testée ou marquée « non vérifié » | Honnêteté devant le jury |
| L'usage est noté dans `docs/ia/journal-usage-ia.md` | Déclaration d'usage de l'IA (intelligence artificielle) |

## 4. Si la réponse ne convient pas

1. Dire précisément ce qui manque (« la commande PowerShell pour activer l'environnement Python »).
2. Redonner le fichier ou l'extrait concerné plutôt que de le décrire.
3. Si la réponse contredit `CLAUDE.md` ou un ADR (Architecture Decision Record, enregistrement de décision d'architecture), citer le passage.
4. Corriger le gabarit (pull request) quand le même défaut revient.
