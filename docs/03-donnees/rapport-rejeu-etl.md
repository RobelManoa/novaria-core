# Rapport de comparaison — rejeu du chargement (DAT-06)

- Date : 2026-10-30 08:25 UTC
- Fichier : `fenetres-demo.csv` (sha256 `6a751c3ce154…`), 868 lignes lues
- Run : `preuve-dat06`
- Clé d'idempotence : clé primaire de `dwh.fact_traffic_window` (tronçon, début, taille de fenêtre, run_id)
- État de départ : run supprimé avant la première passe (864 lignes)

| Passe | Lignes retirées avant | Chargées | Rejetées | Créées | Lignes en base | Véhicules | Débit | Empreinte |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Chargement initial | 0 | 864 | 4 | 864 | 864 | 58695 | 11739.00 | `1cdeb260f755744a65253102c6694241` |
| Rejeu à l'identique | 0 | 864 | 4 | 0 | 864 | 58695 | 11739.00 | `1cdeb260f755744a65253102c6694241` |
| Reprise après suppression | 86 | 864 | 4 | 86 | 864 | 58695 | 11739.00 | `1cdeb260f755744a65253102c6694241` |

## Verdict

**Totaux identiques** aux trois passes : le rejeu ne crée aucune ligne, ne change aucune valeur, et la reprise rétablit exactement les lignes supprimées.

## Comparaison avec AWS Glue

Le job Glue équivalent est documenté (`docs/03-donnees/etl-planifie-local.md`) et **non exécuté** : exécution locale d'abord (ADR-023, ADR-025). Colonne Glue : non exécuté ; aucun total Glue n'est annoncé ici.
