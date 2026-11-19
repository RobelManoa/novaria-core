# Détection d'anomalies : résultats (IA-09)

Fichier **généré** par `python3 scripts/dev/dev.py ml-anomalies` (ne pas modifier à la main) ; le choix argumenté est dans [`anomalies-comparaison.md`](anomalies-comparaison.md).

## Protocole

- Évaluation : 14 runs, 42 h de réseau simulé, 44 anomalies injectées (graines 301 et plus, distinctes de la validation et de l'apprentissage).
- Isolation Forest : 200 arbres, 256 mesures par arbre, graine 42, ajusté sur 207504 messages **non étiquetés** ; seuil de score -0,724 réglé sur la validation sans anomalie.
- Budget commun : au plus 1 fausse alerte par heure de réseau sur la validation sans anomalie (18 h). Obtenu : règles 0,11 par heure, Isolation Forest 0,83 par heure.
- Délai : secondes entre le premier message touché et la première alerte du bon capteur. Colonnes « médian / max ».
- Définitions du rappel, de la précision (par épisode d'alerte) et du délai : en tête de `ml/src/anomalies/evaluation.py`.

## Rappel et délai par type d'anomalie

| Anomalie | Source | Injectées | Règles : rappel | Règles : délai (s) | Isolation Forest : rappel | Isolation Forest : délai (s) |
|---|---|---|---|---|---|---|
| capteur muet | simulateur | 9 | 100 % (9/9) | 50 / 50 | 0 % (0/9) | — |
| message en retard | simulateur | 9 | 100 % (9/9) | 50 / 50 | 0 % (0/9) | — |
| doublon | simulateur | 9 | 100 % (9/9) | 3 / 3 | 0 % (0/9) | — |
| valeur aberrante | simulateur | 9 | 89 % (8/9) | 0 / 0 | 22 % (2/9) | 15 / 30 |
| capteur figé (plateau) | synthétique | 4 | 100 % (4/4) | 100 / 110 | 0 % (0/4) | — |
| chute de débit | synthétique | 4 | 75 % (3/4) | 70 / 90 | 0 % (0/4) | — |

## Précision et fausses alertes

| Détecteur | Précision (épisodes) | Épisodes vrais | Épisodes faux | Fausses alertes par heure |
|---|---|---|---|---|
| Règles | 92 % | 45 | 4 | 0,10 |
| Isolation Forest | 5 % | 2 | 40 | 0,95 |

## Isolation Forest sans seuil : aire sous la courbe ROC des scores

Mesure indépendante du seuil : 1 = les messages touchés ont toujours un score plus bas que les messages normaux, 0,5 = au hasard. « — » : aucun message n'existe pendant l'anomalie (capteur muet).

| Anomalie | AUC |
|---|---|
| message en retard | 0,757 |
| doublon | 0,811 |
| valeur aberrante | 0,996 |
| capteur figé (plateau) | 0,936 |
| chute de débit | 0,512 |
| capteur muet | — |

## Quelle règle donne la première alerte

| Anomalie | Première alerte des règles (nombre d'anomalies) |
|---|---|
| capteur muet | `capteur_muet` (9) |
| message en retard | `capteur_muet` (6), `livraison_en_retard` (3) |
| doublon | `doublon` (9) |
| valeur aberrante | `ecart_mediane` (8) |
| capteur figé (plateau) | `plateau` (4) |
| chute de débit | `chute_de_debit` (3) |

## Seuils des règles

| Paramètre | Valeur |
|---|---|
| `ecart_vitesse` | 6 |
| `ecart_debit` | 7,5 |
| `chute_debit` | 0,25 |
| `chute_vitesse_min` | 0,85 |
| `plateau` | 12 |
| `silence_s` | 60 |
| `retard_s` | 30 |
