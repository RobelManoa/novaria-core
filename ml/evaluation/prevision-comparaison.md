# Prévision de vitesse : références, modèles et limite de validité (IA-10)

Dernière mise à jour : 18/11/2026 · Issue IA-10 (#154) · Exigence : EXG-IA-07 · Cadre : [ADR-015](../../docs/01-architecture/adr/ADR-015-modeles-ia.md), cas d'usage 3 · Chiffres : [prevision-resultats.md](prevision-resultats.md) (généré), `prevision.json` · Jeu : [fiche de provenance METR-LA](../../data/datasets/metr-la/PROVENANCE.md)

Abréviations : MAE (*Mean Absolute Error*, erreur absolue moyenne), RMSE (*Root Mean Square Error*, racine de l'erreur quadratique moyenne), mph (miles par heure ; 1 mph = 1,609 km/h), DCRNN (*Diffusion Convolutional Recurrent Neural Network*, réseau de neurones à graphe publié avec le jeu).

> **Deux jeux, deux verdicts.** Sur les vitesses réelles de METR-LA, le meilleur modèle bat les trois références aux trois horizons, mais de peu. Sur le run simulé, **les modèles appris sur METR-LA ne battent pas la persistance** : ils ne servent pas les données du projet. Cette limite est le résultat le plus important de ce document.

## 1. Résultat en une page

| Question | Réponse |
|---|---|
| Le meilleur modèle bat-il les références par horizon ? | **Oui sur METR-LA, aux 3 horizons** : HistGradientBoosting est meilleur que la persistance, la moyenne glissante et le naïf saisonnier, avec un intervalle à 95 % entièrement sous zéro |
| De combien ? | **Peu** : 0,37 mph de moins que la persistance à 5 min (13 %), 0,33 à 15 min (10 %), 0,33 à 30 min (8 %), soit environ 0,5 km/h |
| Ridge fait-il aussi bien ? | Non. Il bat la persistance à 5 et 15 min, **pas à 30 min** en MAE (4,19 contre 4,14), même s'il la bat en RMSE (7,48 contre 7,97) |
| Et sur le run simulé ? | **Non.** La persistance fait mieux que les deux modèles aux trois horizons ; à 30 min l'erreur du modèle est trois fois plus grande (4,82 contre 1,57 mph) |
| Le modèle peut-il servir l'API de prévision ? | **Non**, pas tel quel. La prévision servie reste la référence actuelle ([API de prévision](../../docs/03-donnees/api-previsions.md), section 3) ; il faudrait réapprendre sur des données du projet |

## 2. Protocole

- **Jeu** : METR-LA, 34 272 pas de 5 minutes, 207 capteurs, du 1er mars au 27 juin 2012, 8,1 % de mesures manquantes (non utilisées pour juger).
- **Découpage dans l'ordre du temps** (70 % / 15 % / 15 %) avec un **délai de garde de 30 minutes** : le passé apprend, le futur juge, et aucune réponse d'apprentissage ne tombe dans la validation. Apprentissage jusqu'au 23/05, validation du 23/05 au 10/06, **test du 10/06 au 27/06** (18 jours).
- **Horizons** : 5, 15 et 30 minutes. Un modèle par horizon, appris sur l'écart à la persistance.
- **Variables** : le passé du capteur (6 retards, moyennes, écart type, part de mesures manquantes) et l'heure ; **aucune variable n'identifie le capteur**, pour que le modèle puisse s'appliquer à un capteur jamais vu.
- **Réglages** : grilles courtes fixées d'avance (Ridge : 4 valeurs de `alpha` ; HistGradientBoosting : 3 combinaisons), choisies sur la **validation**. Le test sert ensuite à juger, sans retour.
- **Intervalle de confiance** : on rééchantillonne des **journées entières** (2 000 tirages, graine 42), car les erreurs d'un même jour ne sont pas indépendantes.
- **Run simulé** : 3 runs de 6 h (calme, pointe, incident), graines 401 à 403, vitesses du simulateur converties de km/h en mph, pas de 5 minutes, exemples réunis (environ 4 000 par horizon). **Les modèles ne sont pas réappris.**

## 3. Résultats sur METR-LA (test, MAE / RMSE en mph)

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 2,78 / 4,59 | 3,46 / 6,37 | 4,14 / 7,97 |
| Moyenne glissante (1 h) | 3,40 / 6,49 | 3,87 / 7,55 | 4,49 / 8,81 |
| Naïf saisonnier (veille) | 5,88 / 11,26 | 5,88 / 11,26 | 5,88 / 11,26 |
| Ridge | 2,63 / 4,38 | 3,35 / 6,03 | 4,19 / 7,48 |
| **HistGradientBoosting** | **2,42 / 4,11** | **3,12 / 5,70** | **3,81 / 6,94** |

Écart de MAE de HistGradientBoosting (intervalle à 95 %) : contre la persistance **−0,366** [−0,384 ; −0,344], **−0,333** [−0,358 ; −0,305], **−0,333** [−0,371 ; −0,294] ; contre la moyenne glissante −0,98, −0,74, −0,68 ; contre le naïf saisonnier −3,47, −2,76, −2,07. Tous les intervalles sont sous zéro : l'écart ne s'explique pas par le hasard des journées du test.

Lectures :

- **La persistance est une référence dure** : à 5 minutes la vitesse change peu, et le modèle ne la corrige que de 13 %.
- **Le naïf saisonnier est le pire** (5,88 mph à tout horizon, puisqu'il ne dépend pas de l'horizon). Cause **non analysée** ; piste : « la veille » est parfois un jour de week-end pour un jour de semaine.
- **La moyenne glissante d'une heure est moins bonne que la persistance** : elle lisse trop pour une vitesse qui change en quelques minutes.
- **Orientation, pas comparaison** : le dépôt DCRNN publie des MAE de 2,18, 2,67 et 3,08 mph à 5, 15 et 30 min ([tableau du dépôt](https://github.com/liyaguang/DCRNN)) avec un réseau de neurones à graphe, un découpage 70/10/20 et un protocole différent. Notre modèle est de 11 à 24 % moins bon, ce qui est attendu : il ne voit **aucun capteur voisin**. Ces chiffres ne sont pas à comparer terme à terme.

## 4. Résultats sur le run simulé (MAE / RMSE en mph, sans réapprentissage)

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| **Persistance** | **0,74 / 1,42** | **1,07 / 2,47** | **1,57 / 3,54** |
| Moyenne glissante (1 h) | 1,38 / 3,09 | 1,70 / 3,80 | 2,20 / 4,75 |
| Naïf saisonnier | non applicable | non applicable | non applicable |
| Ridge | 1,30 / 1,85 | 3,01 / 3,68 | 5,28 / 6,02 |
| HistGradientBoosting | 0,96 / 1,58 | 2,50 / 3,37 | 4,82 / 5,86 |
| Biais moyen de HistGradientBoosting (prévision − réel) | +0,54 | +1,93 | +4,06 |
| Biais moyen de Ridge | +1,09 | +2,66 | +4,85 |

- **La chaîne tourne** : le même code lit un run du simulateur, construit les mêmes variables et rend les mêmes métriques. C'est ce que prouve ce test.
- **Les modèles font pire que la persistance** et leur erreur grandit avec l'horizon. À 30 minutes, **4,06 mph des 4,82 mph de MAE sont du biais** : le modèle prévoit systématiquement une vitesse plus haute que la réalité. La persistance, elle, n'a aucun biais.
- **Hypothèse** (non testée) : appris sur des autoroutes où la vitesse libre est d'environ 58 mph, le modèle tire la prévision vers ce niveau ; le simulateur roule à 22,5 mph en moyenne (limites de 30 et 50 km/h). Une expérience de confirmation, par exemple retirer les variables horaires ou réapprendre sur le simulateur, n'a **pas** été faite.
- Le naïf saisonnier est « non applicable » : un run de 6 h n'a pas la journée de passé qu'il exige.

## 5. Limite de validité

| Ce que le résultat permet de dire | Ce qu'il ne permet pas de dire |
|---|---|
| Sur des **autoroutes de Los Angeles en 2012**, à 5, 15 et 30 minutes, un arbre de gradient sur le passé du capteur bat la persistance de 8 à 13 % | Que la prévision serait aussi bonne sur des **rues urbaines à feux**, une autre ville ou une autre année |
| La chaîne (lecture du jeu, découpage, références, modèles, métriques, test sur un run du projet) fonctionne et se rejoue | Qu'un modèle appris sur METR-LA **sert** les données du projet : le test simulé dit le contraire |
| Le gain est réel au sens statistique (intervalles sous zéro sur 18 jours) | Que le gain est **utile** : 0,3 mph (0,5 km/h) ne change aucune décision de signalisation à lui seul |

Précisions :

1. **Domaine** : 207 capteurs d'autoroute, mars à juin 2012, un seul découpage temporel (18 jours de test), aucune autre saison.
2. **Données simulées** : les vitesses du simulateur suivent des profils de scénario ; une bonne ou mauvaise prévision dessus prouve la chaîne, pas la précision réelle (ADR-015, ADR-027).
3. **Pas de voisinage** : un capteur est prévu seul, sans ses voisins ; un modèle à graphe ferait mieux (section 3).
4. **Un seul réglage court** par modèle, et un instant d'apprentissage sur trois (1,65 million d'exemples au lieu de 5 millions) ; d'autres réglages pourraient changer les chiffres, ce n'est pas vérifié.
5. **Jeu** : producteur et unité non confirmés, licence non établie, convention « 0 = manquant » reprise du dépôt qui diffuse le fichier ([fiche](../../data/datasets/metr-la/PROVENANCE.md)).
6. **Lecture du test** : la campagne complète a été exécutée deux fois, avec les mêmes réglages (la seconde pour ajouter le biais au rapport) ; un essai de mise au point sur 20 capteurs et 6 000 pas a aussi affiché des MAE de test ; **aucun réglage n'a été modifié après avoir vu un résultat de test**.
7. **Non vérifié sous Windows.** Aucun modèle n'est écrit sur le disque (pas de `pickle`) ; le fichier METR-LA n'est ni versionné ni utilisé par la CI.

## 6. Décision et suite

- **Critère d'acceptation** : « le meilleur modèle bat les références par horizon, ou l'écart est documenté » : **rempli sur METR-LA** (3 horizons sur 3) ; l'écart sur le run simulé est documenté ci-dessus. « La limite de validité est écrite » : section 5.
- **Statut de EXG-IA-07** : **Partiel**. Le modèle bat les références sur METR-LA, mais il n'est pas servi par l'API et il est testé sur un run simulé où il perd.
- **Suite possible** (non faite, à décider) : réapprendre sur des runs simulés plus longs pour tester la chaîne de bout en bout (en acceptant que le résultat ne prouve que la chaîne), ou chercher un jeu urbain de licence connue.

## 7. Reproduire

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Créer l'environnement (une fois) | `python3 scripts/dev/dev.py ml-env` | `py -3 scripts/dev/dev.py ml-env` |
| Télécharger METR-LA (57 Mo) et contrôler l'empreinte | `python3 scripts/dev/dev.py ml-prevision telecharger` | `py -3 scripts/dev/dev.py ml-prevision telecharger` |
| Campagne complète (environ 3 minutes), réécrit `prevision.json` et `prevision-resultats.md` | `python3 scripts/dev/dev.py ml-prevision evaluer` ou `make ml-prevision ETAPE=evaluer` | `py -3 scripts/dev/dev.py ml-prevision evaluer` |
| Tests | `ml/.venv/bin/python -m unittest discover -s ml/tests -t ml -p test_prevision.py` | `ml\.venv\Scripts\python.exe -m unittest discover -s ml\tests -t ml -p test_prevision.py` |

Deux exécutions donnent les mêmes chiffres (graines fixes, aucune date écrite). Les tests ne lisent ni METR-LA ni le réseau.
