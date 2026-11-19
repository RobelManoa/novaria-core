# Fiche du modèle : détection de congestion, régression logistique (IA-05)

Dernière mise à jour : 12/11/2026 · Issue IA-05 (#81) · Cadre : [cadrage ML](cadrage-ml.md), condition S5 · Chiffres : [comparaison](../../ml/evaluation/comparaison.md), [résultats](../../ml/evaluation/resultats.md)

Abréviations : ML (Machine Learning, apprentissage automatique), F1 (moyenne harmonique de la précision et du rappel), SHA-256 (Secure Hash Algorithm, empreinte de 256 bits).

> **Données simulées.** Ce modèle apprend le simulateur du dépôt. Il ne décrit aucun trafic réel et ne doit jamais être présenté comme tel.

## 1. Usage prévu

| Rubrique | Contenu |
|---|---|
| Candidat | **logistique** : régression logistique multiclasse, variables centrées et réduites, confirmation sur 2 fenêtres, `C = 10`, classes pondérées |
| Question | dans quel état est un tronçon de route à cette minute : `FREE_FLOW`, `SLOW` ou `CONGESTED` ? |
| Entrée | une fenêtre d'une minute d'un tronçon : mesures, historique des 15 minutes précédentes, caractéristiques du tronçon (cadrage, section 3) |
| Sortie | un état par minute ; une alerte naît à l'entrée dans `CONGESTED` |
| Usage hors domaine | un autre réseau que les 24 tronçons du simulateur, des données réelles, une commande de feux : **non prévus**. Le modèle ne commande jamais un équipement (garde-fous du service de réponse) |

## 2. Données

| Rubrique | Contenu |
|---|---|
| Jeu | `novaria-congestion-v1`, empreinte `5fc6f1832bd9f02dcf86de0e56dfbafb0854b57041819e6452820325c195c19e`, [fiche de provenance](../../data/datasets/novaria-congestion-v1/PROVENANCE.md) |
| Origine | **simulé** (générateur Python v0), 12 runs, 3 scénarios, graines distinctes |
| Découpage | par run et par scénario : 6 runs d'entraînement, 3 de validation, 3 de test |
| Étiquette | l'état **voulu par le scénario** (vérité terrain), jamais la sortie de la règle de seuils |
| Variables interdites | calendrier, identifiants, réponses de prévision (cadrage, section 3) |

## 3. Métriques (test, lu une seule fois)

| Condition | Règle de seuils | Modèle | Exigé | Remplie |
|---|---|---|---|---|
| A1 F1 macro | 0,968 | 0,981 | ≥ 0,978 | oui |
| A2 rappel de `CONGESTED` | 0,979 | 0,980 | ≥ 0,9885 | **non** |
| A3 délai médian | 1 min | 1 min | ≤ 1 min | oui |
| A4 épisodes manqués | 0 sur 9 | 0 sur 9 | 0 | oui |
| A5 fausses alertes par tronçon et jour | 0,07 | 0,21 | ≤ 0,10 | **non** |

## 4. Limites

| Limite | Conséquence |
|---|---|
| Données simulées, états bien séparés par le ratio de vitesse | le résultat prouve la chaîne, pas la précision réelle |
| Minutes sans mesure (capteur muet, messages en retard) | le modèle annonce parfois `CONGESTED` sur une route sans mesure : cause établie des fausses alertes (le jeu n'a pas la complétude) |
| Même calendrier d'états pour les runs d'un même scénario | pas de test sur un scénario jamais vu |
| Un seul jour simulé | le calendrier ne porte aucune information |

## 5. Statut

| Rubrique | Valeur |
|---|---|
| Décision | **rejeté** : A2 et A5 manquées |
| Registre | **non enregistré** : un modèle sous le seuil n'entre pas au registre (IA-04, IA-05) |
| En service | **non** : la règle de seuils reste le classificateur en service (ADR-015, section 6) |
| Format de fichier | `novaria-modele-lineaire` (JSON, aucun `pickle`) : le seul qui se charge |
| Reproduction | `python3 scripts/dev/dev.py ml-pipeline` refait l'entraînement et l'évaluation depuis la configuration figée et compare les métriques à celles enregistrées |

## 6. Contrôles de sécurité du cycle (MLSecOps)

Jeu vérifié avant l'entraînement (S1), artefact relu et comparé au modèle évalué (S2), format sans exécution de code (S3), dépendances auditées (S4, rapporté), cette fiche (S5), code commité (T1), métriques reproduites (R1) : [pipeline MLSecOps](pipeline-mlsecops.md).

## 7. Relecture

**Relue par** : à faire (Daddy Luciano). La condition S5 n'est remplie que lorsque cette ligne porte le nom de l'autre membre et la date de sa relecture.
