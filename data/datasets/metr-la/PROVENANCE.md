# Fiche de provenance du jeu METR-LA

Issue : IA-10 (#154) · Décisions : [ADR-015](../../../docs/01-architecture/adr/ADR-015-modeles-ia.md), cas d'usage 3, et [ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md) · Dernière mise à jour : 18/11/2026

Abréviations : SHA-256 (Secure Hash Algorithm, empreinte de 256 bits), HDF5 (Hierarchical Data Format, format de fichier scientifique), mph (*miles per hour*, miles par heure), DCRNN (*Diffusion Convolutional Recurrent Neural Network*, nom de l'article et du dépôt qui diffusent le fichier).

> **Donnée réelle, licence non établie.** Le fichier n'est **pas dans le dépôt** et ne sera jamais redistribué ici. Il sert uniquement à évaluer la prévision de vitesse (IA-10), en local, à titre de recherche. Ce choix est un **risque assumé**, décrit en section 3.

## 1. Identifiant

| Rubrique | Valeur |
|---|---|
| `dataset_id` | `metr-la` |
| Type de source (`source_type`) | `REAL_HISTORICAL` (donnée réelle historique, jamais présentée comme simulée) |
| Rôle dans le projet | **prévision de vitesse uniquement** (IA-10). Aucune détection de congestion : le jeu ne contient que des vitesses ([ADR-027](../../../docs/01-architecture/adr/ADR-027-jeux-de-donnees-et-provenance.md)) |
| Fichier | `metr-la.h5` |
| Taille | 57 038 056 octets (vérifiée) |
| SHA-256 | `64784b76d6fb8ec9bff4b6decafb354da2bb37840468fdccee5044e511277c05` (calculée sur le fichier téléchargé le 18/11/2026) |
| Emplacement local | `data/datasets/metr-la/metr-la.h5` (ignoré par Git) |

## 2. Origine

| Rubrique | Valeur | Vérifié ? |
|---|---|---|
| Contenu décrit par la littérature | vitesses moyennes de 207 capteurs à boucles sur les autoroutes du comté de Los Angeles, toutes les 5 minutes | repris des articles, **non confirmé par un producteur** |
| Diffusion | dépôt https://github.com/liyaguang/DCRNN (Li, Yu, Shahabi, Liu, ICLR 2018), dossier Google Drive d'identifiant `10FOTa6HXPqX8Pf5WRoRwcFnW9BrNZEIX` qui contient `metr-la.h5` et `pems-bay.h5` | oui, le dossier a été listé le 18/11/2026 |
| Fichier utilisé | identifiant Drive `1pAGRfzMx6K9WWsfDcD1NMbIif0T0saFC` | oui |
| **Producteur d'origine** | **non établi.** Ni le dépôt, ni la page de téléchargement, ni les sources consultées ne le nomment de façon vérifiable | non |
| Version | une seule : le fichier est figé, sans numéro de version ni date de publication dans le fichier | |

## 3. Licence et décision

| Rubrique | Contenu |
|---|---|
| Licence du code du dépôt DCRNN | MIT (fichier `LICENSE` du dépôt, lu le 18/11/2026). **Elle ne couvre pas les données** |
| Licence des données | **aucune trouvée** : ni sur la page de téléchargement, ni dans le dépôt, ni dans les recherches faites le 18/11/2026 (pages d'archives de données de recherche, articles, documentation de bibliothèques qui rediffusent le fichier) |
| Conséquence | on ne peut **pas** affirmer que la redistribution est permise : le fichier n'est ni commité, ni publié, ni copié dans une image Docker, ni utilisé dans la CI |
| Décision | **utiliser METR-LA à titre de recherche et d'évaluation, en local, sans le redistribuer**, plutôt que de renoncer à un jeu réel de vitesses. Décidée par Manoa Robel le 18/11/2026 ; **relecture par Daddy Luciano : à faire** |
| Risque assumé | si le producteur d'origine impose des conditions d'usage plus strictes, elles s'appliqueraient. Le projet est un travail universitaire, le dépôt ne publie aucune donnée du jeu, mais **le droit d'usage n'est pas démontré** |
| Plan de sortie | retirer le fichier local, garder la fiche, et rejouer l'évaluation sur un jeu de licence connue (piste notée : vitesses de WebTRIS, National Highways, Royaume-Uni, pas de 15 minutes, licence à confirmer) |

## 4. Contenu vérifié le 18/11/2026

| Rubrique | Valeur |
|---|---|
| Format | table pandas « fixed » dans un fichier HDF5 (`pandas_version` 0.15.2) ; lue avec `h5py`, sans pandas |
| Dimensions | **34 272 instants × 207 capteurs** |
| Instants | du 2012-03-01 00:00 au **2012-06-27 23:55**, pas régulier de 5 minutes (vérifié : un seul écart, 300 s). Les articles écrivent « jusqu'au 30 juin » : **le fichier s'arrête au 27 juin** |
| Fuseau | non indiqué (heure murale « naïve ») ; Los Angeles est à l'heure du Pacifique, **non vérifié** |
| Capteurs | 207 identifiants numériques (par exemple `773869`, `767541`) |
| Vitesses | maximum 70 ; moyenne des valeurs non nulles 58,5. L'unité est le **mph** d'après les articles, **non vérifiable dans le fichier** |
| Valeurs manquantes | **8,1 %** des cellules valent 0. Le code du dépôt DCRNN traite 0 comme « manquant » (convention d'usage, non documentée dans le fichier) : la lecture le fait de même (`NaN`) |
| Autres colonnes | aucune : ni comptage, ni occupation, ni position (les positions des capteurs sont dans un autre fichier du dépôt DCRNN, non utilisé) |

## 5. Obtenir et contrôler le fichier

Le script contrôle la taille et le SHA-256 ; un fichier différent est refusé et n'est jamais lu. Le téléchargement passe par `drive.usercontent.google.com` (bibliothèque standard, environ 20 s).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Télécharger et contrôler | `python3 scripts/dev/dev.py ml-prevision telecharger` ou `make ml-prevision ETAPE=telecharger` | `py -3 scripts/dev/dev.py ml-prevision telecharger` |
| Contrôler seulement (sans réseau) | `python3 scripts/dev/dev.py ml-prevision verifier` | `py -3 scripts/dev/dev.py ml-prevision verifier` |
| Calculer l'empreinte à la main | `sha256sum data/datasets/metr-la/metr-la.h5` | `Get-FileHash data\datasets\metr-la\metr-la.h5 -Algorithm SHA256` |

Si le lien Google Drive disparaît, il n'y a pas de copie dans le dépôt : l'évaluation d'IA-10 ne peut plus être rejouée tant qu'un fichier d'empreinte identique n'est pas fourni.

## 6. Limites de ce jeu

- **Autoroutes, 2012, quatre mois** : ni du réseau urbain à feux, ni du trafic récent, ni plusieurs années de saisons.
- **Une grandeur** : la vitesse. Pas de comptage ni d'occupation : on ne peut pas y reconnaître la congestion au sens de l'[ADR-028](../../../docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md).
- **Producteur et unité non confirmés** ; fuseau inconnu ; la convention « 0 = manquant » vient du code qui diffuse le fichier.
- Une évaluation sur ce jeu dit comment les méthodes se comportent sur ces 207 capteurs, **pas** sur les rues d'une ville : voir la limite de validité dans [`ml/evaluation/prevision-comparaison.md`](../../../ml/evaluation/prevision-comparaison.md).
