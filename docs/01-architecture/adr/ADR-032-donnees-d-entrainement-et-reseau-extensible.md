# ADR-032 — Données d'entraînement : campagnes du simulateur, METR-LA intégré en local, réseau extensible, modèles servis et expliqués

| Champ | Valeur |
|---|---|
| Date | 22/11/2026 |
| Statut | Proposée : à relire par Daddy Luciano (risque de licence de METR-LA, point 4) et à présenter au professeur |
| Décideurs | Manoa Robel (données et IA (intelligence artificielle)), Daddy Luciano (relecture) |
| Issues liées | IA-10, IA-12 à IA-17 (à créer), DAT-01, MS-07 |
| Compétences BC05 | Machine Learning et modélisation des données, ETL (Extract, Transform, Load), MLOps (Machine Learning Operations) |
| S'appuie sur | [ADR-015](ADR-015-modeles-ia.md), [ADR-027](ADR-027-jeux-de-donnees-et-provenance.md), [ADR-028](ADR-028-etats-de-congestion-et-alertes.md) |
| Modifie | [ADR-027](ADR-027-jeux-de-donnees-et-provenance.md), section 3.2 (METR-LA : de « évaluation hors ligne » à « intégré en local »), et sa [fiche de provenance](../../../data/datasets/metr-la/PROVENANCE.md), voir la section 4.3 |

Abréviations : MAE (*Mean Absolute Error*, erreur absolue moyenne), mph (miles par heure), ODbL (*Open Database License*), ETL (extraction, transformation, chargement).

## 1. Problème

Le projet doit être **un outil de prédiction**. Trois constats, vérifiés dans le dépôt le 22/11/2026, l'empêchent aujourd'hui :

| Constat | Preuve |
|---|---|
| **Aucun modèle appris n'est en service.** La règle de seuils classe la congestion, la persistance (dernière vitesse connue) sert la prévision | `ml/evaluation/comparaison.md` (régression logistique rejetée sur 2 conditions sur 5), `docs/03-donnees/api-previsions.md` (`model.kind = MODEL` n'est jamais rendu) |
| **Le jeu d'entraînement ne couvre que trois situations.** 12 runs, **un seul jour simulé** (20/10/2026), environ 55 h de réseau, et « la graine ne change que le bruit : deux runs du même scénario ont le même calendrier » | `ml/src/jeu_entrainement/catalogue.py`, `data/datasets/novaria-congestion-v1/PROVENANCE.md` |
| **Un modèle appris sur METR-LA ne se transfère pas au simulateur.** Il bat la persistance sur METR-LA (MAE 2,42 contre 2,78 mph à 5 min) mais **fait trois fois pire** sur un run simulé à 30 min (4,82 contre 1,57 mph) | `ml/evaluation/prevision-comparaison.md`, section 4 |

Deux exigences du binôme s'y ajoutent : (1) **les données et les modèles doivent être intégrés à l'application, expliqués, pas seulement cités** ; (2) **l'application doit accueillir de nouveaux capteurs sans modification du code** (par exemple 100 de plus que les 24 d'aujourd'hui).

## 2. Ce que le dépôt sait déjà faire (et ses limites)

| Sujet | État vérifié | Limite |
|---|---|---|
| Référentiel des capteurs | Lu dans `dwh.dim_*` (`services/traitement/app/flux/adapters/warehouse.py`) : le traitement n'a **aucun identifiant en dur** ; les motifs d'identifiants du contrat acceptent `ROAD_` et `SENSOR_` suivis de **3 chiffres ou plus** | Chargé **une seule fois au démarrage** du service de flux ; les capteurs naissent par une migration SQL générée (`scripts/dev/gen_reseau.py`) ; aucune voie d'enregistrement |
| Simulateur | Réseau en dur dans `simulator/novaria_sim/network.py` (6 carrefours × 4 tronçons), comparé à `gen_reseau.py` par un test | Un autre réseau demande de modifier le code |
| Application citoyenne | Noms de lieux (`citizen/src/lieux.json`) et 24 identifiants en dur | Hors périmètre de cette ADR (l'application citoyenne reste sur le réseau fictif) |
| METR-LA | 34 272 pas de 5 minutes × 207 capteurs, 1er mars au 27 juin 2012, vitesses seules ; lu par `ml/src/prevision/source.py` | Hors ligne : rien n'est servi ; licence des données **non établie** |
| Modèles de prévision | Ridge et HistGradientBoosting, 3 horizons ; HGB bat les trois références sur METR-LA de 8 à 13 % | Appris sur les vitesses d'autoroutes de Los Angeles, pas sur le réseau du projet |

## 3. Options

### 3.1 D'où viennent les données d'entraînement

| Option | Avantages | Inconvénients | Verdict |
|---|---|---|---|
| A. Seulement les 3 scénarios actuels | Rien à faire | Trois situations : un modèle n'apprend rien de plus que le calendrier | Écartée |
| B. **Campagnes du simulateur** : un calendrier différent par jour (semaine, week-end, pluie, pointes décalées, incidents tirés au sort) | Vérité terrain exacte, reproductible, même domaine que l'application ; quelques semaines en quelques minutes (3 h simulées en 2,5 s, mesuré) | Reste du simulateur : le modèle apprend le générateur | **Retenue** (point 4.1) |
| C. **METR-LA** comme second réseau réel historique, avec ses 207 capteurs | Données réelles, 4 mois, 207 capteurs : de quoi tester l'extensibilité (207 contre 24) et entraîner des modèles de prévision sur de vraies vitesses | Vitesses seules (pas de comptage ni d'occupation) ; Los Angeles 2012 ; **licence non établie** | **Retenue, en local** (points 4.2 et 4.3) |
| D. PEMS-BAY (même dépôt, 325 capteurs, 2017) | Autres capteurs et une autre année | Licence aussi non établie ; non téléchargé | **Réservée** : même traitement que METR-LA, seulement si la plage horaire de METR-LA ne suffit pas |
| E. Paris, comptage routier (ODbL) | Licence claire, débit et occupation | Pas horaire fin, J-1, 3 036 tronçons de ville réelle qui ne se plaquent pas sur le réseau fictif | Gardée pour l'ETL (ADR-027) ; ne sert pas à l'entraînement ici |

### 3.2 Quel modèle sert quelle donnée

| Règle | Raison |
|---|---|
| **Un modèle ne sert que le réseau sur lequel il a été appris** (ou un réseau de même nature, et seulement si un essai le montre) | Constat 3 de la section 1 : le transfert de METR-LA vers le simulateur échoue |
| Le réseau fictif est servi par un modèle appris sur les **campagnes du simulateur** | Même domaine |
| Le réseau METR-LA est servi par un modèle appris sur **METR-LA** | Même domaine |
| Tout modèle est comparé à la persistance et à la règle de seuils ; **il ne remplace une référence que s'il la bat** avec un intervalle de confiance qui exclut zéro | ADR-015 ; la porte du pipeline IA-05 |

## 4. Choix

### 4.1 Campagnes du simulateur

Un scénario `campagne` s'ajoute aux trois d'origine (fait le 22/11/2026, IA-12). Le calendrier d'un jour ne dépend **que de sa date** (graine fixe, BLAKE2b) ; la graine d'un run ne change toujours que le bruit :

| Ce qui varie d'un jour à l'autre | Règle |
|---|---|
| Jour | Semaine (profil à deux pointes) ou week-end (plateau de fin de matinée, demande plus faible) |
| Météo | Pluie dans 25 % des jours : demande × 1,10 |
| Pointes | Échelle de demande 0,85 à 1,15, décalage de ±20 minutes (semaine) |
| Sens des flux | Le matin Nord et Ouest, le soir Est et Sud |
| Incidents | Semaine : 0 (40 %), 1 (45 %) ou 2 (15 %) ; week-end : 0 (70 %) ou 1 ; tronçon, heure (06:00 à 20:00) et durée (15 à 60 min) tirés au sort ; le tronçon sature, les voisins du carrefour ralentissent, puis il se résorbe en 15 minutes |
| Vérité terrain | La **charge** du tronçon (part de la capacité d'une artère à sa pointe) : saturé à partir de 0,90, ralenti à partir de 0,60, **indépendante de la règle de seuils** (ADR-027, 3.3) |

Mesuré sur 28 jours (24 tronçons, pas de 10 min) : 84,1 % fluide, 12,0 % ralenti, 3,9 % saturé, avec, pour les jours de semaine, de 58 à 360 tronçon-pas saturés par jour (week-end : de 0 à 5). Le jeu `novaria-congestion-v2` (plusieurs semaines, découpage **par jour**, jours de semaine et de week-end dans chaque ensemble) est la tâche suivante (IA-13).

### 4.2 METR-LA devient un réseau de l'application, pas seulement un fichier d'évaluation

| Élément | Décision |
|---|---|
| Entrée dans la plateforme | Un **rejeu** (même rôle que le simulateur) lit le fichier local et émet des mesures au contrat, `source_type = REAL_HISTORICAL`, vers la collecte. Aucun contournement du pipeline |
| Contrat | Une mesure METR-LA n'a **qu'une vitesse** : le contrat des mesures devra accepter l'absence de comptage et d'occupation (à vérifier et à tester avant de coder, IA-14) |
| Identifiants | Les 207 capteurs reçoivent des identifiants du motif existant (`SENSOR_…`, `ROAD_…`) ; la table de correspondance avec les identifiants d'origine est gardée et documentée |
| Affichage | Toujours « donnée réelle historique, Los Angeles, 2012 » : jamais présentée comme actuelle ni comme notre ville, et jamais mélangée à la donnée simulée |

### 4.3 Licence : ce qui change dans l'ADR-027

La fiche de METR-LA établit que le fichier ne sera ni commité, ni publié, ni copié dans une image Docker, ni utilisé dans la CI. Choix du binôme du 22/11/2026 : **intégrer le pipeline et les modèles, garder les données en local.**

| Règle | Contenu |
|---|---|
| Le dépôt contient | Le **code** (rejeu, entraînement, service, explications) et les fiches. **Jamais** le fichier ni un extrait |
| Obtention | Téléchargement par script, taille et SHA-256 contrôlés (déjà en place) |
| Docker | Le fichier est **monté au lancement** depuis `data/datasets/`, pas copié dans une image ni un volume nommé partagé |
| CI | Aucun test de la CI ne lit METR-LA : les tests utilisent un **échantillon fabriqué** de même forme, dit « fabriqué » |
| Modèles appris | Écrits dans `var/models/` (ignoré par Git). Un modèle appris sur METR-LA n'est pas redistribué tant que la licence n'est pas établie |
| Risque | Assumé (fiche de provenance, section 3). **Relecture de Daddy : à faire.** Plan de sortie : retirer le fichier, garder la fiche, rejouer sur un jeu de licence connue |

### 4.4 Réseau extensible (sans modifier le code)

| Besoin | Décision |
|---|---|
| Ajouter des capteurs | Un **fichier de description du réseau** (carrefours, tronçons, capteurs) et une commande idempotente qui met à jour `dwh.dim_*` ; plus de migration SQL par réseau |
| Les prendre en compte sans redémarrer | Le référentiel du flux se **recharge** périodiquement et quand un capteur inconnu arrive plusieurs fois (aujourd'hui il est chargé une fois) |
| Un capteur inconnu | Reste rejeté (`UNKNOWN_SENSOR`) et tracé, jamais perdu ni inventé |
| Le simulateur | Lit le même fichier de description au lieu de son réseau en dur ; un test compare toujours simulateur et base |
| **Preuve exigée (IA-15)** | Décrire 100 capteurs de plus dans un fichier, lancer la commande, rejouer des mesures : elles traversent collecte, traitement, entrepôt, API et tableau de bord, **sans aucune modification du code** (la différence Git ne contient que le fichier de description) |

### 4.5 Modèles servis et expliqués

| Élément | Décision |
|---|---|
| Service | `GET /api/v1/forecasts` rend `model.kind = MODEL` quand un modèle battant la persistance existe pour le réseau demandé ; sinon la référence, comme aujourd'hui |
| Contrat | Ajouter au modèle sa date d'entraînement, sa métrique (MAE contre la persistance) et le jeu d'origine : déjà prévu comme manque dans `api-previsions.md`, section 3 |
| Expliquer | Une page de l'administration par modèle : jeu et plage couverte, variables, importance des variables, erreur par horizon, **où il se trompe**, comparaison aux références. Texte en français simple, chiffres lus dans le registre `model_runs` |
| Détection d'anomalies | Les règles restent en service (elles battent Isolation Forest, `ml/evaluation/anomalies-comparaison.md`) ; l'écran admin montre pourquoi |
| Surveillance | La dérive (déjà faite) alerte quand un modèle servi s'écarte de sa période d'apprentissage |

## 5. Plan et issues proposées

| Id proposé | Tâche | Dépend de | Preuve |
|---|---|---|---|
| **IA-12** | Scénario `campagne` du simulateur (**fait le 22/11/2026**) | | 156 tests du simulateur, dont 12 nouveaux ; 3 h simulées en 2,5 s |
| IA-13 | Jeu `novaria-congestion-v2` : plusieurs semaines, découpage par jour, fiche de provenance, relance de la comparaison règle / modèles | IA-12 | MAE et F1 mesurés sur des jours jamais vus |
| IA-14 | METR-LA comme réseau de l'application : **fait le 22/11/2026 par chargement de fichier** (pas par rejeu temps réel) : manifeste et mesures, 207 capteurs, 1 924 971 mesures dans `dwh.speed_*` ; contrat sans comptage résolu par des tables à part | IA-15 | 207 capteurs de bout en bout, mesurés à travers l'API |
| IA-15 | Réseau extensible : **fait pour les réseaux de vitesse** (fichier de description, commande idempotente `etl-vitesses`, ordre des capteurs verrouillé, test +100 capteurs sans changer le code). **Reste** : le référentiel du traitement en flux (rechargement sans redémarrage) et le simulateur qui lit le même fichier | | +100 capteurs sans modifier le code (fait pour les vitesses) |
| IA-16 | Modèles de prévision réappris par réseau, enregistrés, servis par l'API. **Fait le 22/11/2026 pour METR-LA** : réseau spatio-temporel (PyTorch), gain de 19,9 / 21,8 / 25,2 % sur la persistance, à 0,6 à 2,3 % du réseau à graphe publié, **servi** par `/api/v1/speed-networks` ([résultats](../../../ml/evaluation/prevision-reseau.md)). **Reste** : l'enregistrer dans `model_runs`, un modèle pour le réseau fictif | IA-13, IA-14 | Un modèle sert, sinon 503 |
| IA-17 | Pages d'administration : modèles, données couvertes, explications. **Première partie faite** : section « Modèle entraîné » de la page Prévisions (fiche, erreur de test, comparaison en direct prévu / observé) ; **reste** une page des données couvertes | IA-16 | Tests ; rendu non vu dans un navigateur |

## 6. Conséquences

| Positives | Négatives ou à surveiller |
|---|---|
| Plusieurs semaines de situations différentes au lieu de trois | Un modèle appris sur le simulateur apprend le simulateur : à dire à chaque fois |
| Un vrai réseau de 207 capteurs pour prouver l'extensibilité et la prévision | Risque de licence sur METR-LA, relu par un seul membre à ce jour |
| Les modèles sont servis, expliqués et comparables | Les gains d'IA-10 étaient **modestes** (8 à 13 %) ; ceux d'IA-16 sont de 17 à 20 % sur METR-LA, encore 6 à 8 % au-dessus du réseau de neurones à graphe publié : ne pas les présenter comme une rupture |

## 7. Plan de repli, vérification, réexamen

| Rubrique | Contenu |
|---|---|
| Repli | Si METR-LA est refusé (licence, professeur) : IA-14 est retirée, le réseau reste simulé, les campagnes (IA-12, IA-13) et l'extensibilité (IA-15) restent valables |
| Vérification | Tests du simulateur (Linux : `python3 -m unittest discover -s simulator/tests` ; Windows : `py -3 -m unittest discover -s simulator/tests`) ; pour chaque tâche, la preuve de la colonne « Preuve » |
| Réexamen | Licence de METR-LA établie ou refusée ; un modèle appris bat la règle de seuils sur des jours jamais vus ; le professeur demande un autre jeu |

## 8. Limites et points ouverts

| N° | Point | État |
|---|---|---|
| 1 | Le calendrier de la campagne est inventé par l'auteur (seuils 0,60 et 0,90, probabilités d'incident, pluie) : à valider | À valider |
| 2 | Le simulateur reste hors des vraies dynamiques de trafic (pas de feux, pas de propagation de file entre carrefours) | Limite connue |
| 3 | Les modèles de prévision de METR-LA ne voient aucun capteur voisin : 11 à 24 % moins bons que le réseau de neurones à graphe publié (DCRNN). Un modèle à graphe n'est pas prévu | Non fait |
| 4 | Licence de METR-LA : non établie ; relecture de Daddy et avis du professeur | **À faire** |
| 5 | Le contrat des mesures accepte-t-il l'absence de comptage ? | **Non vérifié** |
