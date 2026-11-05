"""Pipeline d'écriture (MS-10) : `traffic.indicators` vers l'entrepôt, et recommandations de feux.

Le service de flux (`app/flux`) calcule et publie les indicateurs ; ce pipeline les **écrit** dans
`dwh.fact_traffic_window` (avec l'exécution dans `dwh.dim_run`) et publie
`traffic.recommendations`. L'API de consultation (`app/api`) ne fait que **lire** la vue
`dwh.v_indicator`, avec un compte qui ne peut pas écrire. Voir docs/03-donnees/entrepot.md.
"""
