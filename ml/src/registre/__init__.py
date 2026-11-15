"""Suivi des expériences et registre des modèles (IA-04) : model_runs (MongoDB), modèles dans un magasin d'objets local.

Un modèle **en service** se relie, sans trou, à son entraînement (le document `model_runs`), à la révision Git du code et à
l'empreinte du jeu de données. Rien n'est chargé qui n'ait son SHA-256 vérifié, et aucun format ne peut exécuter du code à
la lecture (cadrage ML, section 9, M3 et M4). Le magasin est un port (`ObjectStore`, ADR-025) : un dossier local
(`var/models/`), S3 documenté et non exécuté.
"""
