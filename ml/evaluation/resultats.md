# Résultats de la comparaison (IA-03)

Fichier **généré** par `python3 scripts/dev/dev.py ml-train rapport` à partir de `selection.json` et de `resultat-test.json` : ne pas l'écrire à la main. Le choix argumenté est dans [comparaison.md](comparaison.md).

> **Données simulées.** Un modèle entraîné sur le simulateur apprend le simulateur : ces résultats prouvent la chaîne, pas la précision en conditions réelles.

## 1. Traçabilité

| Champ | Valeur |
|---|---|
| Jeu | `novaria-congestion-v1`, empreinte `5fc6f1832bd9f02dcf86de0e56dfbafb0854b57041819e6452820325c195c19e` |
| Graine | 42 |
| Révision du code | `880fa90b7fbc048714e663a1a43cb1c28a4eb8fd` (code modifié, non commité) |
| Versions | python 3.14.4, scikit-learn 1.9.1, numpy 2.5.4, scipy 1.18.1 |

## 2. Validation : réglage et choix

Au plus 12 réglages par candidat, mesurés sur la validation. Un réglage est éligible si ses fausses alertes restent sous 0,10 par tronçon et par jour (A5) ; sinon sa variante avec confirmation sur 2 fenêtres est jugée. Le réglage retenu a le meilleur F1 macro de validation parmi les éligibles. Entre candidats : meilleur F1 macro de validation, le plus simple à moins de 0,002. La validation croisée groupée par run ne choisit rien.

### 2.1 Réglage retenu de chaque candidat, sur la validation

| | F1 macro | Rappel CONGESTED | Précision CONGESTED | Délai médian / max (min) | Épisodes manqués | Fausses alertes par tronçon et jour |
|---|---|---|---|---|---|---|
| Règle de seuils (référence) | 0,975 | 0,971 | 0,960 | 1 / 1 | 0 / 9 | 0,07 |
| Régression logistique multiclasse (variables centrées et réduites) (confirmation sur 2 fenêtres) | 0,984 | 0,971 | 0,988 | 1 / 2 | 0 / 9 | 0,07 |

| Candidat | Réglage retenu | Variante | Éligibles (brut) | Éligibles (confirmé) | Réglages essayés | Reproductible |
|---|---|---|---|---|---|---|
| Régression logistique multiclasse (variables centrées et réduites) | {"C": 10.0, "class_weight": "balanced"} | confirmation sur 2 fenêtres | 0 / 8 | 8 / 8 | 8 | oui |
| HistGradientBoostingClassifier | – | – | 0 / 8 | 0 / 8 | 8 | – |

### 2.2 Tous les réglages essayés (brut)

| Candidat | Réglage | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour | Éligible |
|---|---|---|---|---|---|
| logistique | {"C": 0.01, "class_weight": null} | 0,989 | 0,968 | 0,21 | non |
| logistique | {"C": 0.01, "class_weight": "balanced"} | 0,993 | 0,985 | 0,29 | non |
| logistique | {"C": 0.1, "class_weight": null} | 0,995 | 0,983 | 0,14 | non |
| logistique | {"C": 0.1, "class_weight": "balanced"} | 0,994 | 0,984 | 0,36 | non |
| logistique | {"C": 1.0, "class_weight": null} | 0,994 | 0,981 | 0,14 | non |
| logistique | {"C": 1.0, "class_weight": "balanced"} | 0,993 | 0,981 | 0,36 | non |
| logistique | {"C": 10.0, "class_weight": null} | 0,994 | 0,981 | 0,21 | non |
| logistique | {"C": 10.0, "class_weight": "balanced"} | 0,994 | 0,983 | 0,29 | non |
| gradient | {"learning_rate": 0.05, "max_leaf_nodes": 15, "class_weight": null} | 0,994 | 0,988 | 0,14 | non |
| gradient | {"learning_rate": 0.05, "max_leaf_nodes": 15, "class_weight": "balanced"} | 0,992 | 0,984 | 0,21 | non |
| gradient | {"learning_rate": 0.05, "max_leaf_nodes": 31, "class_weight": null} | 0,994 | 0,988 | 0,14 | non |
| gradient | {"learning_rate": 0.05, "max_leaf_nodes": 31, "class_weight": "balanced"} | 0,992 | 0,984 | 0,14 | non |
| gradient | {"learning_rate": 0.1, "max_leaf_nodes": 15, "class_weight": null} | 0,994 | 0,988 | 0,14 | non |
| gradient | {"learning_rate": 0.1, "max_leaf_nodes": 15, "class_weight": "balanced"} | 0,992 | 0,984 | 0,14 | non |
| gradient | {"learning_rate": 0.1, "max_leaf_nodes": 31, "class_weight": null} | 0,994 | 0,988 | 0,14 | non |
| gradient | {"learning_rate": 0.1, "max_leaf_nodes": 31, "class_weight": "balanced"} | 0,992 | 0,984 | 0,14 | non |

### 2.3 Validation croisée groupée par run (diagnostic : elle ne choisit rien)

Trois plis sur entraînement et validation : chaque pli met de côté un run de **chaque** scénario. Moyenne ± écart-type des trois plis.

| | F1 macro | Rappel CONGESTED | Fausses alertes par tronçon et jour |
|---|---|---|---|
| Régression logistique multiclasse (variables centrées et réduites) | 0,983 ± 0,006 | 0,981 ± 0,009 | 0,10 ± 0,11 |
| Règle de seuils sur les mêmes plis | 0,976 ± 0,003 | 0,975 ± 0,013 | 0,02 ± 0,04 |

### 2.4 Choix

Candidat retenu : **logistique**, confirmation sur 2 fenêtres, réglage {"C": 10.0, "class_weight": "balanced"}. Meilleur F1 macro de validation parmi les candidats éligibles (0.9843).

## 3. Test (lu une seule fois)

Lu le 2026-11-11T21:27:34+00:00 (UTC), après le choix : empreinte de `selection.json` `876c217f3faaa329083eacce172fd0f6a1213afe8c3122e5faecaf077c5b4d39`. Runs du test : ds1-calme-s14, ds1-incident-s34, ds1-pointe-s24.

| | F1 macro | Rappel CONGESTED | Précision CONGESTED | Délai médian / max (min) | Épisodes manqués | Fausses alertes par tronçon et jour |
|---|---|---|---|---|---|---|
| Règle de seuils (référence) | 0,968 | 0,979 | 0,941 | 1 / 1 | 0 / 9 | 0,07 |
| Régression logistique multiclasse (variables centrées et réduites) (confirmation sur 2 fenêtres) | 0,981 | 0,980 | 0,967 | 1 / 1 | 0 / 9 | 0,21 |

### 3.1 Conditions d'acceptation (cadrage ML, section 6)

| N° | Condition | Modèle | Exigé | Remplie |
|---|---|---|---|---|
| A1 | F1 macro ≥ référence + 0,01 | 0,9814 | ≥ 0.9781 | oui |
| A2 | rappel de CONGESTED ≥ référence + 0,01 | 0,9799 | ≥ 0.9885 | **non** |
| A3 | délai médian ≤ référence | 1,0000 | ≤ 1 min | oui |
| A4 | aucun épisode manqué | 0,0000 | 0 | oui |
| A5 | fausses alertes ≤ 0,10 par tronçon et par jour | 0,2143 | ≤ 0.1 | **non** |

**Décision : modèle rejeté.**

### 3.2 Matrice de confusion du modèle sur le test (ligne : état réel, colonne : état annoncé)

| | FREE_FLOW | SLOW | CONGESTED |
|---|---|---|---|
| FREE_FLOW | 17916 | 6 | 3 |
| SLOW | 0 | 1473 | 17 |
| CONGESTED | 0 | 8 | 737 |
