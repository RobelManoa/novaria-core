# Relecture croisée du dictionnaire de données et des contrats d'événements v0 (DAT-10)

Issue DAT-10 (#146). Porte sur [le dictionnaire de données](dictionnaire-de-donnees.md) et sur `contracts/events/` : enveloppe, mesure, indicateur, alerte (les contrats « v0 »). Les trois sujets ajoutés ensuite par MS-03 (recommandation, état des feux, rejet) ne sont pas couverts par l'approbation demandée ici : leur section 13 du dictionnaire a été lue, pas leurs schémas.

**Statut : relecture faite par Daddy Luciano le 27/10/2026. Approbation de Manoa Robel en attente. Le contrat n'est PAS encore marqué v0** (voir la section 6).

## 1. Méthode

1. Lecture du dictionnaire (sections 1 à 8, 10, 12 et 13) en face de chaque schéma de `contracts/events/` : champs, types, bornes, énumérations, règles entre champs.
2. Comparaison automatique : chaque champ et chaque valeur d'énumération des huit schémas a été cherché dans le dictionnaire (un champ cité nulle part est un oubli).
3. Essais d'attaque : 16 variantes invalides de nos propres exemples soumises à `validate_events.py`, pour voir si le contrat refuse ce que le dictionnaire interdit. 15 ont été acceptées. Sept cas sont désormais refusés (section 3) ; les autres relèvent de choix à trancher (section 4).
4. Lecture de [ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) pour les seuils et le cycle de vie.

## 2. Tests des contrats

| Poste | Commande | Résultat |
|---|---|---|
| Windows 11, Python 3.14.3, jsonschema 4.26.0, referencing 0.37.0 | `py -3 -m unittest discover -s contracts/tests` | **36 tests OK** (19 exemples valides, 92 cas invalides refusés pour la bonne raison, matrice par service, compatibilité) |
| Windows 11, Python 3.14.3 | `pytest` dans `services/_gabarit` puis `services/traitement` (parité des modèles Pydantic avec les contrats) | 138 tests OK (1 ignoré), puis 139 OK ; ruff et ruff format sans remarque |
| Linux | `make test-contracts` | **À faire par Manoa Robel**, à inscrire ici (critère de l'issue : « sur les deux postes ») |

Cinq défauts introduits volontairement dans les nouvelles règles du validateur (règle retirée ou affaiblie) ont tous fait échouer les tests.

## 3. Constats corrigés dans cette pull request

| N° | Où | Constat | Correction |
|---|---|---|---|
| C1 | Contrat de mesure | Une mesure `PARTIAL` sans aucun drapeau était acceptée, alors que DQ-06 dit « qualité PARTIAL + drapeau » | `validate_events.py` : `PARTIAL` exige `MISSING_SPEED` ou `MISSING_OCCUPANCY` ; cas de test ajouté |
| C2 | Contrat de mesure | Une mesure `SUSPECT` sans `IMPLAUSIBLE_VALUE` était acceptée (DQ-05) | Règle ajoutée ; cas de test ajouté |
| C3 | Contrat d'indicateur | L'`id` d'un indicateur, qui sert d'idempotence, n'était défini ni dans le dictionnaire ni contrôlé ; les exemples suivent `<run_id>:<road_segment_id>:<window_size_s>:<début en ms>` | Convention écrite au dictionnaire (section 5) et contrôlée ; cas de test ajouté |
| C4 | Dictionnaire | L'événement d'alerte n'avait aucune section : `previous_state` et l'absence volontaire de `acknowledged_by` n'étaient décrits nulle part | Section 7.3.1 : champ par champ, avec la colonne d'origine |
| C5 | Contrat d'alerte | Étaient acceptés : `CREATED` avec un état précédent, un état avancé sans état précédent, un retour en arrière (`ACKNOWLEDGED` vers `NOTIFIED`), un état qui ne change pas | Règle : `previous_state` est `null` si et seulement si l'état est `CREATED`, sinon strictement antérieur ; 4 cas de test ajoutés |
| C6 | Schéma d'indicateur | `sample_count` décrit comme « mesures reçues », le dictionnaire dit « retenues » (VALID ou PARTIAL, doublons exclus) | Description du schéma alignée sur le dictionnaire (aucun effet sur la validation) |
| C7 | Dictionnaire, section 10.1 | La liste des valeurs de `domain` oubliait `error` | Corrigé, avec la précision que `raw_events` ne reçoit que `iot` |
| C8 | ADR-012 | Annonçait « 35 cas invalides » | 92 au 27/10/2026 |

Les règles C1, C2, C3 et C5 resserrent le contrat : tout producteur qui les violerait verrait ses messages refusés. Aucun producteur n'existe encore (le simulateur, MS-07, et les services n'écrivent pas ces événements), donc aucun code existant n'est cassé. C'est un choix à confirmer par l'approbation de l'autre membre : si une règle paraît trop stricte, la retirer avec son cas de test et la ligne du dictionnaire.

## 4. Constats non corrigés (à trancher)

Chacun est inscrit dans la section 12 du dictionnaire, avec une proposition.

| N° | Sujet | Pourquoi ce n'est pas tranché ici |
|---|---|---|
| T1 | Drapeau `LATE` d'une mesure et rejet `LATE` (DQ-04) | Un message trop tardif est rejeté, mais le drapeau existe sur les mesures acceptées. Dépend du retard autorisé (question Q2) |
| T2 | État d'une fenêtre de 5 minutes | Le schéma impose `congestion_state` pour 300 s alors que l'état se calcule sur 1 minute |
| T3 | `UNKNOWN` puis `FREE_FLOW` clôt un épisode | Une panne de capteur au milieu d'un bouchon résoudrait l'alerte, puis en créerait une autre (au `min_gap_s` près) |
| T4 | Identifiant d'un événement d'alerte | L'exemple utilise 8 caractères de l'UUID : risque de collision ; proposition `<alert_id>:<state>` |
| T5 | Validateur MongoDB de `raw_events` | Il n'exige pas `run_id`, `scenario_id`, `seed`, que le contrat exige |
| T6 | Non contrôlés par le contrat, volontairement | Complétude < 0,5 ⇒ `UNKNOWN` (le seuil 0,5 est une valeur de départ) ; `flow_veh_per_min` = `vehicle_count` ÷ minutes ; `time` d'une alerte égal à `opened_at` ou `resolved_at` |

## 5. Questions à poser au professeur

À soumettre à la prochaine réunion ; la réponse (écrite, ou orale puis confirmée) se consigne dans [decisions-professeur.md](../07-gestion/decisions-professeur.md).

| N° | Question | Hypothèse actuelle | Ce qui change selon la réponse |
|---|---|---|---|
| Q1 | **Seuils d'hystérésis** : quels ratios de vitesse et quel nombre de fenêtres consécutives pour passer fluide, ralenti, congestionné ? Une valeur de la littérature ou de la ville est-elle attendue ? | 0,60 et 0,35 à la descente, 0,45 et 0,70 à la remontée ; 2 fenêtres à la descente, 3 à la remontée ; fenêtres de 1 minute ([ADR-028](../01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md)) | Dictionnaire 7.1, `cadrage-ml.md` (IA-01), règle de seuils servant de référence au modèle |
| Q2 | **Retard autorisé** : quel retard maximal accepter pour une mesure (au-delà, rejet) ? | 30 s de retard autorisé, 10 s de désordre ([ADR-011](../01-architecture/adr/ADR-011-temps-reel-et-batch.md)) ; futur toléré : 5 s | DQ-04 et DQ-10, constat T1, mesures de MS-15 |
| Q3 | **Jours fériés** : faut-il en tenir compte pour la prévision, et quel calendrier (pays, région) ? | Non chargés, `is_holiday` toujours faux | Dimension `dim_date`, colonne `is_holiday` du jeu d'entraînement, DAT-01 |
| Q4 | **Jeu réel avec comptages** : exige-t-il un jeu réel avec comptages de véhicules et états de congestion, ou accepte-t-il le simulateur plus des jeux réels sans comptages pour la prévision ? | Simulateur d'abord, jeux réels pour la prévision seulement ([ADR-027](../01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) ; condition de réexamen de l'ADR-027 | Source des données de l'entrepôt, fiche de provenance, plan de charge (IA-08 à IA-11) |

## 6. Approbations et marquage v0

Le critère de l'issue : « les deux membres ont relu et approuvé ; les tests des contrats passent sur les deux postes ».

| Membre | Relecture | Approbation | Tests des contrats |
|---|---|---|---|
| Daddy Luciano | Faite le 27/10/2026 (ce document) | Auteur de la pull request : donne son accord en la publiant | Windows : OK (section 2) |
| Manoa Robel | **À faire** : relire le dictionnaire et les contrats, pas seulement ce compte rendu | **À donner** par l'approbation de la pull request GitHub | Linux : **à lancer** |

Une fois l'approbation donnée et le test Linux inscrit en section 2 :

1. Passer le statut en tête de ce document à « approuvé par les deux membres le JJ/MM/AAAA ».
2. Ajouter la même mention dans l'en-tête de `contracts/README.md`.
3. Poser l'étiquette sur le commit de fusion :

```bash
git tag -a contrats-v0 -m "Contrats d'événements v0 (enveloppe, mesure, indicateur, alerte) approuvés par les deux membres (DAT-10)"
git push origin contrats-v0
```

Toute modification ultérieure d'un schéma suit [la compatibilité ascendante](../../contracts/check_compat.py) et une nouvelle pull request relue par les deux membres.
