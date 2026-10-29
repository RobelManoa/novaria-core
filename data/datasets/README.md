# Jeux de données

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsables : Daddy Luciano (données) et Manoa Robel (relecture croisée)
Dernière mise à jour : 26/10/2026
Issue de suivi : DAT-01
Statut : **choix proposé**, à valider par le professeur (point 2 de GES-06) et par relecture du binôme

Les fichiers de données ne sont pas versionnés (voir `.gitignore`, qui exclut tout `data/datasets/` sauf ce fichier) : un jeu simulé se régénère par sa graine, un jeu réel se télécharge par script avec contrôle de l'empreinte. Le dépôt est public : **aucun jeu réel n'est ajouté tant que sa licence n'autorise pas la redistribution**. La fiche de provenance de chaque jeu ([ADR-027](../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), section 4) figure dans ce fichier, aux sections 3 et 4.

Abréviations : API (Application Programming Interface, interface de programmation), CC BY 4.0 (Creative Commons Attribution 4.0 International), CSV (Comma-Separated Values, valeurs séparées par des virgules), DOI (Digital Object Identifier, identifiant numérique d'objet), ETL (Extract, Transform, Load, extraction, transformation, chargement), ODbL (Open Database License, licence ouverte de base de données), SHA-256 (Secure Hash Algorithm, algorithme de hachage sécurisé), UCI (University of California, Irvine).

Toutes les informations de ce document ont été relevées à la source le **26/10/2026** (liste en section 7). Un point non vérifié est signalé « non vérifié ».

## 1. Résultat

| Rôle | Jeu | Licence | Verdict |
|---|---|---|---|
| **Jeu urbain ouvert choisi** (ETL, indicateurs) | Comptage routier de la Ville de Paris, capteurs permanents | ODbL | **Retenu** |
| Tutoriel de prise en main (ETL, qualité) | Metro Interstate Traffic Volume (UCI) | CC BY 4.0 | Retenu comme prévu dans l'ADR-027 |
| Prévision (IA-10) | METR-LA | **Aucune licence de données trouvée** | **Non retenu pour l'instant** |

Le jeu simulé v1 (IA-08) reste la source des runs de congestion ([ADR-027](../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) : un jeu réel ne la remplace pas.

## 2. Comparaison des jeux

| Critère | Paris, comptage routier | UCI, Metro Interstate | METR-LA |
|---|---|---|---|
| **Licence** | **ODbL**, indiquée sur les 3 jeux du portail | **CC BY 4.0**, indiquée sur la page du jeu | **Non trouvée** : ni sur la page de téléchargement, ni dans les sources consultées. Le dépôt qui l'héberge est sous licence MIT, mais cela ne vaut que pour son code |
| Producteur | Ville de Paris, Direction de la Voirie et des Déplacements | John Hogue ; trafic de la station ATR (Automatic Traffic Recorder) 301 du ministère des transports du Minnesota | Boucles de comptage routier du comté de Los Angeles ; fichier diffusé par le dépôt DCRNN (producteur d'origine non vérifié) |
| Couverture | **3 036 tronçons** d'une ville | **Une seule station** d'autoroute (I-94 Ouest, Minnesota) | 207 capteurs d'autoroute |
| Mesures utiles | **Débit** (véhicules par heure), **taux d'occupation**, état du trafic | Volume horaire de trafic + météo | Vitesse moyenne (mph) toutes les 5 minutes |
| Période | 13 mois glissants (jeu courant) ; **2010 à A-1** (historique) | 2012 à 2018 | 1er mars au 30 juin 2012 |
| Mise à jour | **Quotidienne** (jusqu'à J-1) ; historique par année | Aucune (jeu figé, donné en 2019) | Aucune (jeu figé) |
| Volume | **29,1 millions de lignes** (jeu courant) ; 186 à 247 Mo compressés par année d'historique | **48 204 lignes**, 0,4 Mo | 207 capteurs × une mesure toutes les 5 minutes ; nombre exact de lignes non vérifié |
| Adéquation au contrat `iot-measurement` | **Directe** : `q` = `vehicle_count`, `k` = `occupancy_rate` | Partielle : un volume par heure, pas de taux d'occupation | Partielle : une vitesse, pas de comptage |
| Qualité mesurée | 43 % des lignes sans état du trafic ; 46 % sans débit (section 3.5) | 23 % des heures absentes, horodates en double, valeurs aberrantes (section 4.3) | Non mesurée |
| Redistribution | Permise sous conditions (attribution, partage à l'identique) | Permise avec attribution | **Impossible à affirmer** |

**Justification du choix.** Le jeu de Paris est le seul des trois qui réunit une licence ouverte explicite, un réseau urbain réel (3 036 tronçons), un volume qui justifie un pipeline ETL (29,1 millions de lignes), une mise à jour quotidienne et les deux grandeurs qui définissent la congestion en ingénierie du trafic : débit et taux d'occupation. Le jeu de l'UCI ne couvre qu'une station d'autoroute, mais il est petit et riche en défauts de qualité : il sert de tutoriel. METR-LA est écarté tant que sa licence n'est pas établie.

## 3. Jeu choisi : comptage routier de la Ville de Paris

### 3.1 Identité et source

| Rubrique | Contenu |
|---|---|
| Identifiant proposé | `paris-comptages-routiers`, version = date de téléchargement |
| Titre | Comptage routier - Données trafic issues des capteurs permanents |
| Producteur | Direction de la Voirie et des Déplacements, Service des Déplacements, Poste central d'exploitation Lutèce, Ville de Paris |
| Portail | Paris Data (opendata.paris.fr) |
| Origine | Réel, provenance `REAL_HISTORICAL` |
| Mesure | Boucles électromagnétiques dans la chaussée : stations de taux d'occupation seul, ou de taux d'occupation et de comptage |

| Jeu | Adresse |
|---|---|
| Données courantes (13 mois glissants) | https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents/ |
| Historique (2010 à A-1, un fichier ZIP par année) | https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents-historique/ |
| Référentiel géographique (géométrie des tronçons) | https://opendata.paris.fr/explore/dataset/referentiel-comptages-routiers/ |
| Notice du producteur (7 juin 2019) | pièce jointe du jeu courant : `NOTICE_donnes_trafic_capteurs_permanents_version_20190607.pdf` |

### 3.2 Licence et conditions

| Rubrique | Contenu |
|---|---|
| Licence | Open Database License (ODbL), indiquée dans les métadonnées des trois jeux : http://opendatacommons.org/licenses/odbl/ |
| Usage autorisé | Copier, distribuer, utiliser la base ; produire des œuvres à partir d'elle ; l'adapter |
| Attribution | Obligatoire : citer le producteur et la licence. Mention proposée : « Source : Ville de Paris, Direction de la Voirie et des Déplacements, Comptage routier (licence ODbL). » |
| Partage à l'identique | Une version adaptée **utilisée publiquement** doit aussi être proposée sous ODbL |
| Redistribution | Autorisée sous ces conditions. **Décision du projet : aucune donnée n'est versionnée** (règles 6 et 7 de l'ADR-027) ; un script de téléchargement contrôle l'empreinte |
| Conséquence pour Novaria Core | Les graphiques et rapports restent libres, avec attribution. Un export de l'entrepôt diffusé publiquement serait une base adaptée, donc sous ODbL |

Cette lecture est un résumé : le texte intégral de l'ODbL 1.0 fait foi. Elle n'a pas fait l'objet d'un avis juridique.

### 3.3 Schéma des données de trafic

Une ligne = un tronçon (`iu_ac`) pour une heure (`t_1h`).

| Champ | Type | Sens |
|---|---|---|
| `iu_ac` | entier | Identifiant du tronçon (clé étrangère vers le référentiel) |
| `libelle` | texte | Libellé de la voie ou de la section |
| `t_1h` | horodate | Fin de la période d'une heure. `2019-01-01 01:00:00` désigne le 1er janvier de 00 h à 01 h. Le portail indique l'heure de Paris (UTC+1) ; l'API renvoie l'horodate avec le décalage `+00:00` : **le fuseau est à vérifier avant tout calcul par heure** (non vérifié) |
| `q` | nombre | Débit : véhicules comptés pendant l'heure |
| `k` | nombre | Taux d'occupation, en pourcentage de l'heure |
| `etat_trafic` | texte (entier dans les fichiers historiques) | 0 Inconnu, 1 Fluide, 2 Pré-saturé, 3 Saturé, 4 Bloqué |
| `etat_barre` | texte (entier dans les fichiers historiques) | 0 Inconnu, 1 Ouvert, 2 Barré, 3 Invalide |
| `iu_nd_amont`, `libelle_nd_amont`, `iu_nd_aval`, `libelle_nd_aval` | entier, texte | Nœuds amont et aval du tronçon |
| `date_debut`, `date_fin` | date | Période de disponibilité des données du tronçon |
| `geo_point_2d`, `geo_shape` | géométrie | Point et tracé du tronçon (jeu courant). Fichiers historiques : champ `Dessin` (schéma de l'arc) ; géométrie exacte par jointure avec le référentiel sur `iu_ac` |

Seuils officiels du taux d'occupation (notice) : `k` < 15 % fluide ; 15 à 30 % pré-saturé ; 30 à 50 % saturé ; 50 % et plus bloqué.

### 3.4 Fréquence et volume

| Rubrique | Valeur relevée le 26/10/2026 |
|---|---|
| Mise à jour | Quotidienne : dernière mise à jour des données le 19/10/2026 ; les données vont jusqu'à J-1 |
| Période du jeu courant | 01/09/2025 au 18/10/2026 (13 mois glissants) |
| Pas de temps | 1 heure |
| Lignes (jeu courant) | 29 122 132 |
| Tronçons distincts | 3 036 |
| Historique | Un ZIP par année, de 2010 à 2025 (deux fichiers pour 2025) ; exemples : 2018 : 228 Mo, 2023 : 247 Mo, 2024 : 186 Mo, 2025 : 212 Mo (compressés). Les mois de septembre à décembre 2025 figurent dans l'historique **et** dans le jeu courant |

### 3.5 Qualité mesurée (jeu courant, 29 122 132 lignes)

| Mesure | Lignes | Part |
|---|---|---|
| Débit `q` absent | 13 364 572 | 45,9 % |
| Taux d'occupation `k` absent | 12 615 166 | 43,3 % |
| `q` et `k` tous deux absents | 9 704 558 | 33,3 % |
| État du trafic « Inconnu » | 12 615 155 | 43,3 % |

| État du trafic | Lignes | Part |
|---|---|---|
| Fluide | 14 341 918 | 49,2 % |
| Pré-saturé | 1 405 361 | 4,8 % |
| Saturé | 549 045 | 1,9 % |
| Bloqué | 210 642 | 0,7 % |
| Inconnu | 12 615 155 | 43,3 % |
| Vide | 11 | 0,0 % |

Les stations de taux d'occupation seul n'ont pas de débit (notice, section 1.2) : une partie des `q` absents est structurelle. Ces taux sont ceux du jeu courant ; l'historique n'a pas été mesuré (non vérifié).

### 3.6 Limites

| Limite | Conséquence |
|---|---|
| Pas de vitesse | L'état de congestion de l'[ADR-028](../../docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) repose sur un ratio de vitesse : il ne se calcule pas sur ce jeu. Seuls `k` et `q` sont disponibles |
| `etat_trafic` est une fonction de `k` | Les états viennent des seuils de la section 3.3 : ce n'est **pas** une vérité terrain indépendante. L'utiliser comme réponse d'un modèle apprenant à partir de `k` mesurerait la règle des seuils (ADR-027, section 3.3) |
| Une heure par ligne | Le simulateur produit une mesure toutes les 10 secondes : le jeu ne remplace pas les runs simulés |
| Réseau réel de Paris | Il ne se mélange pas au réseau fictif du simulateur (`INT_01`, `ROAD_001`) : chaque ligne porte sa provenance |
| Taux d'absence élevés | Le pipeline ETL doit les rejeter ou les marquer, avec un taux de rejet journalisé (DAT-04) : fait, [nettoyage du comptage de Paris](../../docs/03-donnees/nettoyage-paris.md) (`dev.py etl-nettoyer-paris`) ; 40,94 % de refus le 17/10/2026, presque tous par absence de débit |

### 3.7 Correspondance avec le contrat `iot-measurement`

| Champ du contrat | Champ de Paris | Règle |
|---|---|---|
| `vehicle_count` | `q` | Rejet si absent ; `interval_s` = 3600 |
| `occupancy_rate` | `k` | Divisé par 100 (le contrat attend 0 à 1) |
| `average_speed_kmh` | aucun | `null` |
| `road_segment_id`, `sensor_id` | `iu_ac` | À associer par le pipeline |
| `provenance` | | `REAL_HISTORICAL`, avec `dataset_id` |

La correspondance détaillée et l'effet sur l'entrepôt relèvent de DAT-02 et DAT-05.

### 3.8 Accès

| Linux (bash) | Windows (PowerShell) |
|---|---|
| `curl -s "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/comptages-routiers-permanents/records?limit=3"` | `curl.exe -s "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/comptages-routiers-permanents/records?limit=3"` |

Cette commande renvoie trois lignes du jeu courant au format JSON. Le script de téléchargement par fenêtre de temps, avec calcul de l'empreinte et journal dans MongoDB, est celui de DAT-03 : [ingestion du comptage routier de Paris](../../docs/03-donnees/ingestion-paris.md) (`dev.py etl-paris`).

| Rubrique | Contenu |
|---|---|
| Empreinte SHA-256 | À calculer au téléchargement, par fichier (le jeu courant change chaque jour) |

## 4. Jeu de tutoriel : Metro Interstate Traffic Volume (UCI)

### 4.1 Identité, source et licence

| Rubrique | Contenu |
|---|---|
| Identifiant proposé | `uci-metro-interstate`, version 1 |
| Origine | Réel (`REAL_HISTORICAL`) |
| Producteur | John Hogue (créateur) ; données de trafic de la station ATR 301 du ministère des transports du Minnesota, entre Minneapolis et Saint Paul |
| Adresse | https://archive.ics.uci.edu/dataset/492/metro+interstate+traffic+volume |
| DOI | 10.24432/C5X60B |
| Licence | CC BY 4.0 : https://creativecommons.org/licenses/by/4.0/legalcode |
| Attribution demandée | Hogue, J. (2019). Metro Interstate Traffic Volume [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5X60B |
| Redistribution | Permise avec attribution ; **non versionné** dans ce dépôt, par cohérence avec la règle de l'ADR-027 |

### 4.2 Schéma, fréquence, volume

| Variable | Type | Sens |
|---|---|---|
| `holiday` | catégorie | Jour férié américain ou fête régionale (« None » sinon) |
| `temp` | nombre | Température moyenne, en kelvin |
| `rain_1h` | nombre | Pluie de l'heure, en mm |
| `snow_1h` | nombre | Neige de l'heure, en mm |
| `clouds_all` | entier | Couverture nuageuse, en % |
| `weather_main`, `weather_description` | catégorie | Météo courte et détaillée |
| `date_time` | date | Heure de collecte, heure locale CST (Central Standard Time) |
| `traffic_volume` | entier | Volume horaire de trafic de l'I-94 Ouest, station 301 |

| Rubrique | Valeur |
|---|---|
| Mise à jour | Aucune : jeu donné le 5/6/2019 (lu au format américain : 6 mai 2019) |
| Pas de temps | 1 heure |
| Période mesurée | du 02/10/2012 09:00 au 30/09/2018 23:00 |
| Lignes, colonnes | 48 204 lignes, 9 colonnes |
| Fichier | `Metro_Interstate_Traffic_Volume.csv.gz`, 405 373 octets |
| Archive | https://archive.ics.uci.edu/static/public/492/metro+interstate+traffic+volume.zip |

### 4.3 Qualité mesurée (contrôle fait sur le fichier téléchargé le 26/10/2026)

La page du jeu annonce « aucune valeur manquante » : c'est exact pour les cellules vides, mais le jeu a d'autres défauts.

| Mesure | Résultat |
|---|---|
| Cellules vides | 0 |
| Horodates distinctes | 40 575 sur 52 551 heures de la période : **11 976 heures absentes (22,8 %)** |
| Lignes en double sur une même heure | **7 629** (jusqu'à 6 lignes pour une heure, avec des descriptions météo différentes) |
| Température égale à 0 K | 10 lignes (valeur impossible) |
| Pluie maximale `rain_1h` | 9 831,3 mm en une heure (valeur aberrante) |
| `traffic_volume` | de 0 à 7 280 |
| Jours fériés (`holiday` ≠ « None ») | 61 lignes |

Ces défauts en font un bon support de tutoriel pour les règles de nettoyage de l'ETL (doublons, trous, valeurs aberrantes).

### 4.4 Limites et empreinte

| Rubrique | Contenu |
|---|---|
| Limites | Une seule station d'autoroute américaine : aucune notion de réseau urbain, ni de taux d'occupation, ni de congestion étiquetée |
| Empreinte SHA-256 du fichier `.csv.gz` | `0b3679ac15173f79c6dc6c5ef8a0798d806fa5c5d7f05c84a5fa711bd1b05f07` |

| Contrôle de l'empreinte | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Extraire l'archive | `unzip metro+interstate+traffic+volume.zip` | `Expand-Archive metro+interstate+traffic+volume.zip .` |
| Calculer l'empreinte | `sha256sum Metro_Interstate_Traffic_Volume.csv.gz` | `Get-FileHash Metro_Interstate_Traffic_Volume.csv.gz -Algorithm SHA256` |

## 5. Jeu non retenu : METR-LA

| Rubrique | Contenu |
|---|---|
| Contenu | Vitesse moyenne (en miles par heure) de 207 capteurs d'autoroute du comté de Los Angeles, toutes les 5 minutes, du 1er mars au 30 juin 2012 (d'après les articles de recherche qui l'utilisent) |
| Diffusion | Fichier `metr-la.h5` sur Google Drive et Baidu Yun, via le dépôt https://github.com/liyaguang/DCRNN |
| Licence | **Aucune licence de données trouvée.** La page du dépôt ne mentionne que la licence MIT du code ; elle ne cite ni la source d'origine des données ni condition de redistribution |
| Décision | Non retenu pour l'instant, et jamais redistribué ici |
| Réexamen | Avant IA-10 : établir le producteur d'origine et ses conditions d'usage, ou remplacer par un jeu de vitesses de licence connue |

Cette décision touche l'[ADR-027](../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), qui prévoit METR-LA pour la prévision « sous réserve de licence » : la réserve n'est pas levée.

## 6. Décision et suite

| Point | État |
|---|---|
| Comparaison de 3 jeux ouverts | Faite (section 2) |
| Source, licence, schéma, fréquence, volume du jeu choisi | Documentés (section 3) |
| Licence du jeu choisi autorise l'usage | Oui : ODbL, avec attribution et partage à l'identique (section 3.2) |
| Validation par le professeur | [À COMPLÉTER : date et décision, à consigner dans `docs/07-gestion/decisions-professeur.md`] |
| Relecture croisée | [À COMPLÉTER : relecteur et date] |

**Écarts avec l'ADR-027 à traiter après la validation** (aucun n'est modifié par ce document) :

| Passage de l'ADR-027 | Constat |
|---|---|
| Section 3.2 : « Les jeux réels ne contiennent pas de comptages de véhicules par fenêtre ni d'état de congestion » | Faux pour le jeu de Paris : il contient un débit horaire et un état du trafic. L'état dépend toutefois de `k` (section 3.6) |
| Section 3.2 : « Jeu de l'UCI retenu dans DAT-01 » | Le jeu de l'UCI est retenu pour le tutoriel, le jeu urbain choisi est celui de Paris |
| Règle 7 | Compatible : aucune donnée n'est redistribuée |
| Questions pour le professeur (GES-06, point 2) | Simulateur seul, ou simulateur calé sur le jeu de Paris ? Le jeu de Paris peut-il servir à calibrer les profils horaires du générateur ? |

## 7. Sources consultées le 26/10/2026

| Information | Source |
|---|---|
| Jeu de l'UCI : licence, variables, DOI, citation | https://archive.ics.uci.edu/dataset/492/metro+interstate+traffic+volume |
| Jeu de l'UCI : contrôle des 48 204 lignes | Archive de l'UCI téléchargée et lue |
| Paris : licence ODbL, producteur, champs, dates de mise à jour | API de métadonnées de Paris Data (`/api/explore/v2.1/catalog/datasets/…`) pour les trois jeux |
| Paris : nombre de lignes, tronçons, périodes, absences | Requêtes d'agrégation sur la même API |
| Paris : taille des fichiers annuels | En-têtes HTTP des pièces jointes de l'historique |
| Paris : schéma des fichiers, seuils, types de stations | Notice du producteur du 7 juin 2019 |
| ODbL : droits et obligations | https://opendatacommons.org/licenses/odbl/summary/ (résumé non officiel) |
| METR-LA : téléchargement, licence du code | https://github.com/liyaguang/DCRNN |
| METR-LA : contenu | Articles de recherche citant le jeu (207 capteurs, 5 minutes, 1er mars au 30 juin 2012) |
