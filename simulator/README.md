# Simulateur de capteurs IoT

**État : squelette (MS-06).** Le conteneur démarre et répond à `GET /api/v1/health`. Il ne produit encore aucune mesure : la génération (réseau de la migration 0005, profils horaires, graine fixe, anomalies injectables) est l'issue **MS-07**, qui remplacera ce fichier par la documentation du format émis (`contracts/events/iot-measurement.schema.json`).

| Élément | Valeur |
|---|---|
| Image | `simulator/Dockerfile` (Python, bibliothèque standard, utilisateur non-root) |
| Port interne | 8000 ; publié sur `127.0.0.1:${SIMULATOR_PORT:-8005}` par `docker-compose.yml` |
| Dépend de | `collecte` (démarre quand la collecte est saine) |
| Test | `python3 -m unittest discover -s scripts/dev -p "test_compose.py"` |
