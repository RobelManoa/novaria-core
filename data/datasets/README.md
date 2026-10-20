# Jeux de données

Les fichiers de données ne sont pas versionnés (voir `.gitignore`) : un jeu simulé se régénère par sa graine, un jeu réel se télécharge par script avec contrôle de l'empreinte. Le dépôt est public : **aucun jeu réel n'est ajouté tant que sa licence n'autorise pas la redistribution**.

Chaque jeu a son dossier `data/datasets/<jeu>/` avec un fichier `PROVENANCE.md` (modèle dans l'[ADR-027](../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md), section 4) :

| Rubrique | Contenu |
|---|---|
| Identifiant et version | `dataset_id`, numéro de version |
| Origine | Simulé (générateur, version du code, graine, scénarios) ou réel (producteur, adresse, date de téléchargement) |
| Licence et conditions | Texte exact et lien ; redistribution oui ou non |
| Période et couverture | Dates, capteurs, pas de temps |
| Variables et unités | Renvoi au [dictionnaire de données](../../docs/03-donnees/dictionnaire-de-donnees.md) |
| Qualité mesurée | Valeurs manquantes, rejets, mesures suspectes |
| Limites | Ce que le jeu ne permet pas de conclure |
| Empreinte | SHA-256 (*Secure Hash Algorithm*) du fichier |

Jeux prévus : jeu simulé v1 (IA-08), METR-LA pour la prévision (IA-10), jeu de l'UCI (University of California, Irvine) pour le tutoriel (DAT-01).
