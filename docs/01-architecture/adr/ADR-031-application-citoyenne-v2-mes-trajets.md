# ADR-031 — Application citoyenne v2 : « mes trajets », une décision de départ, la tendance et la cause confirmée

| Champ | Valeur |
|---|---|
| Date | 21/11/2026 |
| Statut | Proposée : à valider par les deux membres. **Phase 1 réalisée le 21/11/2026** (écran « Mes trajets », CIT-10) ; navigation, messages, réglages, carte et ajout par les croix ajoutés le 22/11/2026 (section 3.3) ; phases 2 et 3 non commencées |
| Décideurs | Daddy Luciano, Manoa Robel |
| Validation du professeur | Sans objet pour ce choix (changement d'interface) ; la demande C-08 reste à confirmer |
| Issues liées | CIT-04 à CIT-07 (v1, fermées) ; nouvelles issues CIT-09 à CIT-14 (section 7) |
| Compétences BC05 | Architecture, Sécurité applicative |
| S'appuie sur | [ADR-028](ADR-028-etats-de-congestion-et-alertes.md), [ADR-030](ADR-030-application-citoyenne-perimetre-et-acces.md) |
| Amende | ADR-030, section 4.3 (rien sur l'appareil, point 5), section 4.4 (liste blanche, **en phase 2 seulement**) et « Hors v1 » (historique) |

Abréviations : **UX** (User eXperience, expérience d'usage), **API** (Application Programming Interface, interface de programmation), **ADR** (Architecture Decision Record, fiche de décision d'architecture), **RGPD** (Règlement général sur la protection des données), **WCAG** (Web Content Accessibility Guidelines, règles d'accessibilité du web).

## 1. Problème

Au premier essai à la main de l'application citoyenne (21/11/2026), le retour est net : **elle est compliquée à utiliser, même pour son auteur.** Une application pour les citoyens doit se comprendre sans explication, pour des habitués ou non, des gens techniques ou non.

Le parcours attendu :

| Étape | Ce que fait le citoyen |
|---|---|
| 1 | Il ouvre l'application et voit **ses trajets habituels** |
| 2 | Il voit si la route qu'il compte prendre est **fluide, ralentie ou congestionnée** |
| 3 | Il **décide** : partir maintenant ou attendre |

Pour aller plus loin, il doit pouvoir : voir **quand** la circulation redevient fluide, **décider plus facilement**, savoir **pourquoi** une route est bloquée.

## 2. Constat sur la v1

La v1 a été construite autour de ce que le système sait, pas de ce que le citoyen cherche.

| Ce que montre la v1 | Pourquoi c'est difficile |
|---|---|
| « Tronçon ROAD_017 », « Carrefour INT_05 », « Arrivée par l'ouest » | Des codes du système : aucun citoyen ne sait où est `ROAD_017` |
| « Alertes en cours » en premier, 44 alertes anciennes repliées à 10 | Une liste du service d'alertes, pas une réponse à « ma route est-elle libre ? » |
| Un encadré de consentement de trois garanties et une case à cocher, **avant** tout suivi | Du vocabulaire juridique pour un geste simple |
| Quatre compteurs (« 1 tronçon ralenti »…) puis la liste de **tous** les carrefours | Le citoyen doit chercher sa route dans 24 tronçons |
| « Suivre ce tronçon », « Notification simulée » | Deux notions (suivre, notifier) que personne n'a demandées |
| Aucune phrase qui aide à décider | L'état est dit, jamais la conséquence (« partez » ou « attendez ») |

## 3. Décisions

| N° | Décision | Phase |
|---|---|---|
| D1 | **Un seul écran : « Mes trajets ».** Chaque trajet est une carte : un nom lisible, un mot et une forme (jamais la couleur seule), une phrase qui aide à décider, depuis quand. Rien d'autre au premier plan | 1 |
| D2 | **La phrase de décision est une règle, pas une estimation.** Elle découle du pire état des tronçons du trajet (tableau 4.1). Aucune durée de trajet n'est annoncée : aucune donnée ne le permet | 1 |
| D3 | **Les trajets habituels restent sur l'appareil** (stockage local du navigateur), jamais envoyés au serveur, effaçables en un clic. Cela amende l'ADR-030 (section 4.3, point 5) | 1 |
| D4 | **Des noms de lieux lisibles** pour le réseau fictif, marqués « simulé » comme tout le reste. En phase 1, ils vivent dans un fichier de l'application (`citizen/src/lieux.ts`), sans changer les contrats | 1 |
| D5 | **La tendance, sans prédiction** : « congestionné depuis 12 min, en train de s'améliorer », calculée côté serveur sur les dernières minutes mesurées. Aucune heure de retour à la normale n'est annoncée | 2 |
| D6 | **L'ampleur en mots** (« un peu plus lent », « beaucoup plus lent », « presque à l'arrêt »), dérivée de la vitesse. Aucune vitesse n'est exposée | 2 |
| D7 | **La cause confirmée par un opérateur.** L'équipe indique « accident », « travaux » ou « événement » sur une alerte ; le citoyen le voit. Sans confirmation : « cause non confirmée ». Jamais de cause déduite d'une vitesse (ADR-028, règle 6) | 3 |
| D8 | **Le suivi devient « Me prévenir »** : un interrupteur sur la carte d'un trajet, une phrase (« Un message s'affichera ici, rien n'est envoyé »), sans case de consentement. La notification reste simulée | 1 |

### 3.1 Ce qui disparaît de l'écran principal

La liste « Alertes en cours », le bloc de consentement, les compteurs par état, la liste par carrefour et tous les codes (`ROAD_…`, `INT_…`). L'état d'un tronçon qui n'est dans aucun trajet n'est visible que dans « Ajouter un trajet ».

### 3.2 Ce qui est gardé

Le bandeau « Données simulées » (ADR-027), la mise à jour automatique (5 s pour les alertes, 15 s pour la circulation), les messages clairs en cas de panne (CIT-07), l'accessibilité (WCAG 2.1 AA : un mot et une forme, contrastes calculés, lecteur d'écran), l'absence de compte et de cookie.

### 3.3 Navigation, carte, ajout, messages et réglages (amendement du 22/11/2026)

La maquette validée (design « Novaria Citoyen », 12 planches téléphone, 8 planches ordinateur) ajoute à l'écran principal une navigation du bas à trois onglets (Mes trajets, Carte, Messages), un écran de réglages, une carte du réseau et un ajout de trajet par les côtés des places. Cela précise la section 3.1 sans la contredire pour l'accueil :

| Écran | Décision | Écart avec la maquette |
|---|---|---|
| Navigation | Trois onglets ; la roue de l'accueil ouvre les réglages ; le détail, l'ajout et les réglages n'ont pas d'onglets, seulement « Mes trajets » ou « Annuler » en haut | Aucun |
| Messages | Les messages « Me prévenir » reçus **depuis l'ouverture de la page**, lus ou non (pastille sur l'onglet, bandeau en haut) ; réglage trajet par trajet | **Pas gardés sur l'appareil** : les garder étendrait la liste de la section 4.3 (D3). « De nouveau libre » n'est pas annoncé (seules les alertes qui s'ouvrent le sont) |
| Réglages | Ce que veut dire chaque mot, ce qui est gardé et où, « Effacer mes trajets », supprimer un trajet, confort de lecture | « Modifier un trajet » non fait |
| Carte | Résumé des 24 endroits par état, plan de six places (une croix de quatre côtés chacune), fiche de la place choisie avec ses faits fixes, alertes en cours, « Faire un trajet avec cette place » | **Réintroduit les compteurs par état** que la section 3.1 avait retirés de l'écran principal : ils ne sont plus sur l'accueil, seulement sur la carte |
| Ajouter | Écran à part (`#/ajouter`) : on touche les côtés des places (boutons « <endroit> : <état> »), le verdict du trajet se lit avant de le garder, nom facultatif, « Me prévenir » | Remplace la liste de cases à cocher de la section 4.2 |

**Mots de l'état d'un endroit.** Ceux de la maquette remplacent « Fluide » et « Congestionné » de l'ADR-030 (4.2), pour parler comme le verdict d'un trajet. Un endroit sans mesure est « Sans mesure » :

| Code du contrat | Mot à l'écran |
|---|---|
| `FREE_FLOW` → « Libre » | Libre |
| `SLOW` → « Ralenti » | Ralenti |
| `CONGESTED` → « Bloqué » | Bloqué |
| `UNKNOWN` → « Sans mesure » | Sans mesure |

## 4. Détail

### 4.1 La phrase de décision (D2)

| Pire état des tronçons du trajet | Titre de la carte | Phrase |
|---|---|---|
| `FREE_FLOW` | **Libre** | Vous pouvez partir. |
| `SLOW` | **Ralenti** | Partez si vous le pouvez : prévoyez un peu de retard. |
| `CONGESTED` | **Bloqué** | Prévoyez beaucoup de retard. Si vous pouvez, attendez ou choisissez un autre trajet. |
| Fluide là où l'on mesure, au moins un tronçon sans mesure | **Information incomplète** | Nous n'avons pas toutes les mesures de ce trajet : prenez cette information avec prudence. |
| `UNKNOWN` partout (aucune mesure récente) | **Information indisponible** | Nous n'avons pas assez de mesures : ne vous fiez pas à cette carte. |

Avec la tendance (phase 2) : « Bloqué, mais en train de s'améliorer : attendre un peu peut valoir la peine » ; « Ralenti, en train de se dégrader : mieux vaut partir maintenant ». Ces phrases décrivent une tendance mesurée, elles ne promettent rien.

### 4.2 Ajouter un trajet (D1, D4)

Le réseau de démonstration n'a ni carte ni rues connectées entre elles (6 carrefours, 24 tronçons). Un **trajet** est donc une liste de **1 à 4 tronçons** choisis par le citoyen dans une liste de lieux nommés, ou parmi trois **trajets proposés** à la première ouverture (pour qu'un écran vide n'arrête personne). L'état du trajet est le pire de ses tronçons. L'application ne calcule aucun itinéraire (hors v1, ADR-030).

Noms proposés (fictifs, à valider) :

| Carrefour | Nom | Tronçons |
|---|---|---|
| INT_01 | Place de la Gare | vers le nord, l'est, le sud, l'ouest |
| INT_02 | Avenue des Tilleuls | idem |
| INT_03 | Rue du Marché | idem |
| INT_04 | Boulevard de la Rivière | idem |
| INT_05 | Rue des Écoles | idem |
| INT_06 | Chemin des Vergers | idem |

Écriture d'un tronçon : « Place de la Gare, côté nord ». Un test vérifie que les 24 tronçons ont un nom, que deux tronçons n'ont pas le même, et qu'aucun nom ne contient `ROAD_` ni `INT_`.

### 4.3 Ce qui est gardé sur l'appareil (D3)

| Élément | Règle |
|---|---|
| Contenu | La liste des identifiants de tronçons de chaque trajet, le nom que le citoyen lui donne, l'état de l'interrupteur « Me prévenir ». **Rien d'autre** : ni date de visite, ni identifiant de visiteur, ni position |
| Où | Une seule clé du stockage local, lue et écrite par **un seul fichier** (`citizen/src/stockage.ts`) ; la règle de lint qui interdit le stockage a une exception pour ce fichier et pour lui seul |
| Jamais | Envoyé au serveur, mis dans un cookie, partagé entre appareils |
| Contrôle du citoyen | « Effacer mes trajets » (un clic, tout part) ; le texte dit en une phrase : « Vos trajets restent sur cet appareil. » |
| Données corrompues ou d'une autre version | Ignorées sans erreur : l'application repart des trajets proposés |
| Navigateur sans stockage (mode privé) | L'application marche, sans mémoire : un message le dit |

Ce n'est pas une donnée personnelle envoyée à quelqu'un, mais c'est une préférence gardée sur l'appareil : l'**analyse RGPD n'est pas faite** (comme pour la journalisation, ADR-030 point 5). À consigner dans le registre des risques.

### 4.4 Changements de contrat (phases 2 et 3)

| Phase | Route | Ajout | Garde-fou |
|---|---|---|---|
| 2 | `GET /api/v1/public/congestion` | `since` (début de l'état actuel, UTC), `trend` (`IMPROVING`, `STABLE`, `WORSENING`), `slowdown` (`NORMAL`, `A_BIT`, `MUCH`, `NEARLY_STOPPED`) | Trois champs de plus à la liste blanche, **aucun nombre** de vitesse, de comptage ou d'historique |
| 3 | `GET /api/v1/public/alerts` | `cause` : `UNKNOWN`, `CONFIRMED_INCIDENT`, `ROADWORKS`, `SPECIAL_EVENT` (jamais `SENSOR_FAULT`) | Le public ne voit jamais le nom de l'opérateur ni le commentaire |
| 3 | `POST /api/v1/alerts/{id}/cause` (équipe) | Nouvelle route, rôle `operator`, corps `{ "cause": … }`, trace d'audit | Matrice d'accès étendue : un `viewer` et un anonyme sont refusés |

Le test `test_contrat_public.py` lit la liste blanche dans l'ADR-030 : **l'ADR-030 sera amendée en même temps que le contrat**, en phase 2 ; ni avant, ni sans ce test.

## 5. Options écartées

| Option | Raison |
|---|---|
| Annoncer une **heure** de retour à la normale | Aucun modèle de prévision n'est branché ni validé sur ce réseau (le modèle étudié l'a été sur METR-LA, un autre réseau). Ce serait inventé |
| Dire **pourquoi** à partir de la vitesse | ADR-028, règle 6 : une baisse de vitesse ne prouve pas un accident |
| Calculer un **itinéraire** | Le réseau n'a pas de graphe ; hors v1 (ADR-030) |
| Géolocaliser le citoyen | Hors v1 ; donnée personnelle |
| Garder les trajets **sur le serveur** | Il faudrait un compte : écarté par l'ADR-030 (option B) |
| Garder les trajets dans l'**adresse de la page** (favori) | Respecte l'ADR-030 mais exige que le citoyen y pense : écarté pour la facilité d'usage |
| Un champ public `label` dans le contrat | Utile plus tard ; en phase 1 un fichier de l'application suffit et évite de toucher aux contrats |

## 6. Conséquences

| Domaine | Effet |
|---|---|
| Application citoyenne | **Fait en phase 1.** Refonte de l'écran principal ; nouveaux fichiers `lieux.ts`, `stockage.ts`, `trajets.ts`, `verdict.ts` ; les tests de composants, d'accessibilité et de parcours (164 tests) sont réécrits pour le nouvel écran, **sans en supprimer** sans les remplacer |
| Contrats, services, passerelle | Phase 2 (`traitement`) et phase 3 (`alerte`, passerelle, matrice d'accès) ; `gateway/citoyen.conf` inchangé |
| Tableau de bord de l'équipe | Phase 3 : un bouton « Indiquer la cause » sur une alerte |
| `dev.py parcours` | Les cas U1 à U5 sont adaptés au nouvel écran (U4 : « le trajet affiche Bloqué ») |
| Documentation | ADR-030 amendée, [application-citoyenne.md](../../08-exploitation/application-citoyenne.md), [api-citoyen.md](../../03-donnees/api-citoyen.md), registre des risques (R13, nouveau risque sur le stockage local) |
| Risque | Le jalon M6 se termine le 08/12/2026 (R14) : l'ordre de livraison de la section 7 permet de s'arrêter après la phase 1 avec une application utilisable |

## 7. Plan et issues proposées

| Issue | Contenu | Phase | Dépend de |
|---|---|---|---|
| CIT-09 | Cette décision validée, parcours et textes relus par une personne qui n'a pas écrit l'application | 1 | — |
| CIT-10 | **Écran « Mes trajets »** : noms, trajets proposés, stockage local, phrase de décision, « Me prévenir », bandeau et pannes conservés ; tests de composants, d'accessibilité et un parcours | 1 | CIT-09 |
| CIT-11 | Tendance et ampleur : `since`, `trend`, `slowdown` dans `traitement`, contrat, ADR-030 amendée, matrice d'accès | 2 | CIT-10 |
| CIT-12 | Cause confirmée : route d'équipe, bouton du tableau de bord, champ public, matrice d'accès | 3 | CIT-11 |
| CIT-13 | Parcours de bout en bout (cas U1 à U5) et essai d'usage avec des personnes extérieures au projet | 1 à 3 | CIT-10 à CIT-12 |
| CIT-14 | Documentation (ex-CIT-08) à jour | 3 | CIT-13 |

**Critère de réussite de la phase 1** (à mesurer, pas à supposer) : une personne qui n'a jamais vu l'application, sans explication, trouve en moins de 30 secondes si le trajet de son choix est libre, et dit ce qu'elle ferait. À essayer avec au moins trois personnes ; les résultats, y compris les échecs, sont consignés.

## 8. Limites et points ouverts

| N° | Point | État |
|---|---|---|
| 1 | Les noms de lieux sont fictifs : un citoyen réel ne retrouverait pas sa rue. C'est la limite d'un réseau de démonstration | Assumée, dite à l'écran (« simulé ») |
| 2 | La tendance se lit sur quelques minutes simulées : elle peut osciller ; un seuil de stabilité est à fixer en phase 2 | Ouvert |
| 3 | « Cause confirmée » suppose qu'un opérateur la saisit : dans la démonstration, c'est la personne qui présente | Ouvert |
| 4 | Pas d'essai avec un lecteur d'écran réel ni un vrai téléphone (la v1 non plus) | Non vérifié |
| 5 | Stockage local : analyse RGPD non faite | Ouvert |
