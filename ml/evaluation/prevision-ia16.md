# Prévision de vitesse sur METR-LA : un modèle qui voit ses voisins (IA-16)

Dernière mise à jour : 22/11/2026 · Chiffres : [prevision-ia16.json](prevision-ia16.json) (écrit par `entrainer_ia16.py`, ne pas modifier à la main) · Décision : [ADR-032](../../docs/01-architecture/adr/ADR-032-donnees-d-entrainement-et-reseau-extensible.md) · Point de départ : [prevision-comparaison.md](prevision-comparaison.md) (IA-10)

Abréviations : MAE (*Mean Absolute Error*, erreur absolue moyenne), RMSE (*Root Mean Square Error*), mph (miles par heure), HGB (HistGradientBoosting).

> **Donnée réelle historique, Los Angeles, 2012.** Licence non établie : le fichier reste local, jamais redistribué (ADR-032, 4.3). Un modèle appris ici ne sert que ce réseau.

## 1. Résultat en une page

| Question | Réponse |
|---|---|
| Que change IA-16 ? | Le modèle d'IA-10 ne voyait que le passé du capteur. IA-16 lui ajoute **l'habituel du créneau de la semaine** et **les 10 capteurs voisins** (dont l'écart à l'habituel varie comme le sien), plus l'état du réseau |
| De combien le modèle bat-il la persistance ? | **17,1 % à 5 min, 16,8 % à 15 min, 19,5 % à 30 min** (IA-10 : 13,1 %, 9,6 %, 8,0 %) |
| Est-ce sûr ? | Oui pour le hasard des journées : les intervalles à 95 % de l'écart de MAE sont entièrement sous zéro, contre la persistance **et** contre le modèle d'IA-10 |
| Est-ce un test vierge ? | **Non.** La période de test (10 au 27 juin 2012) avait déjà été lue par IA-10 pour d'autres modèles. Variables, voisins et réglage ont été choisis sur la **validation** seulement ; le script refuse une seconde lecture |
| Le modèle est-il écrit sans `pickle` ? | Oui : format `novaria-modele-arbres` (JSON), 4,2 Mo par horizon, 400 arbres ; relu en bibliothèque standard, **écart maximal avec scikit-learn : 0** sur 2 000 lignes du test |

## 2. Test sur METR-LA (MAE / RMSE en mph)

| Méthode | 5 min | 15 min | 30 min |
|---|---|---|---|
| Persistance | 2,784 / 4,59 | 3,456 / 6,37 | 4,145 / 7,97 |
| HGB d'IA-10 (variables propres au capteur) | 2,418 / 4,11 | 3,123 / 5,70 | 3,811 / 6,94 |
| **HGB d'IA-16 (habituel, voisins, réseau)** | **2,307 / 3,84** | **2,876 / 5,15** | **3,337 / 6,10** |
| Gain d'IA-16 sur la persistance | 17,1 % | 16,8 % | 19,5 % |

Écart de MAE d'IA-16 (intervalle à 95 %, journées rééchantillonnées) : contre la persistance −0,477 [−0,501 ; −0,450], −0,580 [−0,626 ; −0,529], −0,807 [−0,901 ; −0,705] ; contre IA-10 −0,111 [−0,127 ; −0,096], −0,247 [−0,289 ; −0,205], −0,474 [−0,549 ; −0,391].

Pour l'orientation seulement (protocole différent, réseau de neurones à graphe) : le dépôt DCRNN publie 2,18 / 2,67 / 3,08 mph ; IA-16 est **5,8 %, 7,7 % et 8,4 % au-dessus**, contre 11 à 24 % pour IA-10.

## 3. Ce qui a apporté le gain (validation, 30 min, même réglage, HGB 200 arbres)

| Variables | MAE validation | Gain sur la persistance (4,007) |
|---|---|---|
| IA-10 (capteur seul) | 3,670 | 8,4 % |
| + habituel (version qui se fuit à elle-même) | 3,448 | 14,0 % |
| + habituel (hors semaine de la ligne) | 3,372 | 15,8 % |
| + voisins | 3,505 | 12,5 % |
| **tout (habituel hors semaine, voisins, réseau)** | **3,255** | **18,8 %** |

Le réglage fin (10 voisins, 127 feuilles, 400 arbres, taux 0,05) n'ajoute que 0,5 à 0,8 point : le gain vient des **variables**, pas de la taille du modèle.

**Un piège évité.** Calculer l'habituel sur toute la période d'apprentissage met chaque ligne dans sa propre moyenne : le modèle apprend une variable plus informative qu'elle ne le sera sur des données jamais vues, et se dégrade à 5 minutes (9,7 % au lieu de 13,3 %). Pour les lignes d'apprentissage, l'habituel est donc calculé **sans la semaine de la ligne** (`habituel_hors_semaine`) ; un test le vérifie.

## 4. Protocole

- **Données** : les mêmes qu'IA-10 : 34 272 pas de 5 minutes, 207 capteurs, 1er mars au 27 juin 2012, découpage dans l'ordre du temps 70 / 15 / 15 avec délai de garde de 30 minutes. L'apprentissage couvre **83 jours** (un pas sur trois : 1 654 137 exemples), pas une journée.
- **Voisins et habituel** : appris sur l'apprentissage seulement ; jamais sur la validation ni le test (un test le vérifie).
- **Aucune fuite du futur** : les variables ne regardent que `t` et le passé (un test change tout ce qui suit `t` sans changer les variables).
- **Cible** : écart à la persistance (`vitesse(t+h) − vitesse(t)`).
- **Réglage** : cinq réglages comparés sur la validation seulement (`experience_reglages.py`).

## 5. Limites

| N° | Limite | État |
|---|---|---|
| 1 | Les variables dépendent d'**un réseau** (habituel et voisins) : le modèle ne sert que METR-LA, pas un capteur jamais vu. Un capteur sans historique garde le modèle d'IA-10 | Assumé (ADR-032, 3.2) |
| 2 | Test déjà lu une fois par IA-10 | Dit plus haut |
| 3 | Pas de réseau de neurones à graphe (pas de PyTorch dans le dépôt) : 6 à 8 % au-dessus de DCRNN | Piste : GRU ou MLP, à essayer sur la validation |
| 4 | Vitesses seules, pas d'incident ni de météo connus | Limite du jeu |
| 5 | **Le modèle n'est pas encore servi par l'API** : il est entraîné, écrit et relu ; le service doit encore lire le fichier, construire les variables depuis l'entrepôt et rendre `model.kind = MODEL` | À faire (IA-16, suite) |

## 6. Rejouer

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Expérience sur la validation (aucune lecture du test) | `cd ml/src && ../.venv/bin/python -m prevision.experience_voisins` | `cd ml\src; ..\.venv\Scripts\python.exe -m prevision.experience_voisins` |
| Entraîner, lire le test, écrire les modèles dans `var/models/` (refusé si `prevision-ia16.json` existe) | `cd ml/src && ../.venv/bin/python -m prevision.entrainer_ia16` | `cd ml\src; ..\.venv\Scripts\python.exe -m prevision.entrainer_ia16` |
| Tests | `ml/.venv/bin/python -m unittest discover -s ml/tests -t ml` | `ml\.venv\Scripts\python.exe -m unittest discover -s ml\tests -t ml` |
