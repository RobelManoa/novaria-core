# Prévision de vitesse : résultats (IA-10)

Fichier **généré** par `python3 scripts/dev/dev.py ml-prevision evaluer` (ne pas modifier à la main) ; le choix argumenté et la limite de validité sont dans [`prevision-comparaison.md`](prevision-comparaison.md).

## Données et découpage

- METR-LA : 34272 pas de 5 minutes, 207 capteurs, 8,1 % de mesures manquantes (vitesse 0 dans le fichier). Fiche : [PROVENANCE.md](../../data/datasets/metr-la/PROVENANCE.md).
- Découpage dans l'ordre du temps (70 % / 15 % / 15 %), délai de garde de 30 minutes (12 pas écartés) :

| Partie | Pas | Début | Fin |
|---|---|---|---|
| Apprentissage | 23973 | 2012-03-01 00:55 | 2012-05-23 06:35 |
| Validation | 5135 | 2012-05-23 07:10 | 2012-06-10 03:00 |
| Test | 5141 | 2012-06-10 03:35 | 2012-06-27 23:55 |

Exemples d'apprentissage : 1654137 (un instant sur 3, 207 capteurs). Unité : miles par heure (mph) ; 1 mph = 1,609 km/h.

## Test sur METR-LA : MAE / RMSE (mph)

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 2,78 / 4,59 | 3,46 / 6,37 | 4,14 / 7,97 |
| Moyenne glissante (1 h) | 3,40 / 6,49 | 3,87 / 7,55 | 4,49 / 8,81 |
| Naïf saisonnier (veille) | 5,88 / 11,26 | 5,88 / 11,26 | 5,88 / 11,26 |
| Ridge | 2,63 / 4,38 | 3,35 / 6,03 | 4,19 / 7,48 |
| HistGradientBoosting | 2,42 / 4,11 | 3,12 / 5,70 | 3,81 / 6,94 |

## Meilleur modèle contre les références

Écart de MAE entre le meilleur modèle (choisi sur la validation) et chaque référence, avec l'intervalle à 95 % par rééchantillonnage de journées. Négatif : le modèle fait mieux.

| Horizon | Meilleur modèle | Contre | Écart de MAE (mph) | Intervalle à 95 % | Bat la référence ? |
|---|---|---|---|---|---|
| 5 min | HistGradientBoosting | Persistance | -0,366 | [-0,384 ; -0,344] | oui |
| 5 min | HistGradientBoosting | Moyenne glissante (1 h) | -0,979 | [-1,109 ; -0,831] | oui |
| 5 min | HistGradientBoosting | Naïf saisonnier (veille) | -3,465 | [-4,031 ; -2,938] | oui |
| 15 min | HistGradientBoosting | Persistance | -0,333 | [-0,358 ; -0,305] | oui |
| 15 min | HistGradientBoosting | Moyenne glissante (1 h) | -0,744 | [-0,863 ; -0,606] | oui |
| 15 min | HistGradientBoosting | Naïf saisonnier (veille) | -2,762 | [-3,334 ; -2,205] | oui |
| 30 min | HistGradientBoosting | Persistance | -0,333 | [-0,371 ; -0,294] | oui |
| 30 min | HistGradientBoosting | Moyenne glissante (1 h) | -0,679 | [-0,816 ; -0,527] | oui |
| 30 min | HistGradientBoosting | Naïf saisonnier (veille) | -2,074 | [-2,678 ; -1,471] | oui |

## Réglages choisis sur la validation

| Horizon | Modèle | Réglage | MAE validation (mph) |
|---|---|---|---|
| 5 min | Ridge | alpha = 0.1 | 2,568 |
| 5 min | HistGradientBoosting | max_leaf_nodes = 63, max_iter = 400, learning_rate = 0.05 | 2,356 |
| 15 min | Ridge | alpha = 0.1 | 3,257 |
| 15 min | HistGradientBoosting | max_leaf_nodes = 63, max_iter = 400, learning_rate = 0.05 | 3,016 |
| 30 min | Ridge | alpha = 0.1 | 4,069 |
| 30 min | HistGradientBoosting | max_leaf_nodes = 63, max_iter = 400, learning_rate = 0.05 | 3,668 |

## Run simulé : MAE / RMSE (mph), modèles appris sur METR-LA, sans réapprentissage

Trois runs de 6 h (ia10-calme-s401, ia10-pointe-s402, ia10-incident-s403), exemples réunis. Vitesses du simulateur converties de km/h en mph. **Limite de validité : voir [`prevision-comparaison.md`](prevision-comparaison.md).**

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 0,74 / 1,42 | 1,07 / 2,47 | 1,57 / 3,54 |
| Moyenne glissante (1 h) | 1,38 / 3,09 | 1,70 / 3,80 | 2,20 / 4,75 |
| Naïf saisonnier (veille) | non applicable | non applicable | non applicable |
| Ridge | 1,30 / 1,85 | 3,01 / 3,68 | 5,28 / 6,02 |
| HistGradientBoosting | 0,96 / 1,58 | 2,50 / 3,37 | 4,82 / 5,86 |
| Exemples mesurés | 4320 | 4176 | 3960 |
| Vitesse réelle moyenne (mph) | 22,7 | 22,6 | 22,5 |

Biais moyen, prévision − réel (mph) : négatif, le modèle prévoit une vitesse plus basse que la réalité.

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 0,00 | 0,00 | -0,01 |
| Ridge | 1,09 | 2,66 | 4,85 |
| HistGradientBoosting | 0,54 | 1,93 | 4,06 |

## Biais du modèle sur METR-LA (test), pour comparaison

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 0,00 | 0,00 | 0,01 |
| Ridge | -0,00 | 0,02 | 0,03 |
| HistGradientBoosting | 0,03 | 0,09 | 0,14 |
