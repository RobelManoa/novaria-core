# Prototype SUMO : résultats du rejeu et de la comparaison (IA-11)

Fichier **généré** par `python3 scripts/dev/dev.py ml-sumo comparer` (Linux) ou `py -3 scripts/dev/dev.py ml-sumo comparer` (Windows) (ne pas modifier à la main) ; l'analyse est dans [`prototype-sumo.md`](../../docs/06-ia-mlops/prototype-sumo.md).

## Le run

- Run `sumo-int01-pointe-s42` : carrefour INT_01, 5 h simulées à partir de 06:00, graine 42, 7200 événements, empreintes SHA-256 dans le manifeste.
- Capacité mesurée d'une approche : 855 véhicules/h (le v0 suppose 1 400).

## Rejeu dans le moteur de fenêtres du traitement

| Contrôle | Résultat |
|---|---|
| Messages acceptés | 7200 sur 7200 |
| Fenêtres d'une minute | 1200 (4 approches × 300 minutes) |
| Véhicules conservés | 13070 dans les fenêtres |
| Écarts | aucun |

## SUMO contre le générateur v0 (mêmes minutes, mêmes quatre approches)

| Mesure | SUMO | v0 |
|---|---|---|
| Véhicules par minute et approche (moyenne ; écart type) | 10,9 ; 3,9 | 15,8 ; 4,8 |
| Ratio de vitesse (moyenne ; écart type ; minimum) | 0,80 ; 0,15 ; 0,31 | 0,69 ; 0,27 ; 0,11 |
| File moyenne ; maximale (m) | 114 ; 280 | 53 ; 217 |
| Minutes annoncées FREE_FLOW / SLOW / CONGESTED par la règle de seuils | 76 % / 24 % / 0 % | 60 % / 25 % / 16 % |

Corrélation des profils de demande par tranche de 30 minutes : 0,58.

### Par tranche de 30 minutes (moyenne des quatre approches)

| Début | Véhicules/min SUMO | v0 | Ratio SUMO | v0 | File SUMO (m) | v0 (m) |
|---|---|---|---|---|---|---|
| 06:00 | 8,5 | 14,4 | 0,91 | 0,90 | 24 | 0 |
| 06:30 | 11,9 | 18,9 | 0,86 | 0,85 | 54 | 14 |
| 07:00 | 13,2 | 19,4 | 0,66 | 0,59 | 144 | 80 |
| 07:30 | 13,3 | 16,4 | 0,66 | 0,35 | 240 | 144 |
| 08:00 | 13,2 | 14,8 | 0,67 | 0,35 | 257 | 140 |
| 08:30 | 11,8 | 14,2 | 0,72 | 0,46 | 219 | 115 |
| 09:00 | 10,8 | 16,0 | 0,81 | 0,75 | 122 | 40 |
| 09:30 | 9,0 | 15,0 | 0,90 | 0,90 | 31 | 0 |
| 10:00 | 8,4 | 14,4 | 0,91 | 0,90 | 23 | 0 |
| 10:30 | 8,8 | 14,3 | 0,91 | 0,90 | 25 | 0 |

## Sensibilité

| Variante | Ratio moyen | Ratio minimal | FREE_FLOW / SLOW / CONGESTED | File max (m) | Écarts au rejeu |
|---|---|---|---|---|---|
| graine 42, boucle à 10 m | 0,53 | 0,01 | 1 % / 98 % / 1 % | 280 | aucun |
| graine 43, boucle à 100 m | 0,79 | 0,01 | 68 % / 29 % / 2 % | 280 | aucun |
| graine 44, boucle à 100 m | 0,79 | 0,01 | 73 % / 25 % / 2 % | 280 | aucun |
