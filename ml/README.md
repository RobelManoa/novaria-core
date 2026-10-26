# Machine Learning et MLOps

`src/` code d'entraînement · `evaluation/` comparaisons et métriques · `registry/` suivi des modèles
(table `model_runs` dans MongoDB, modèles versionnés dans le dossier local `var/models/` ; S3 (Simple Storage Service) documenté, non exécuté) · `notebooks/` exploration uniquement.

Ordre de travail : congestion d'abord, prévision ensuite ([ADR-015](../docs/01-architecture/adr/ADR-015-modeles-ia.md)). Les états et leurs seuils sont définis dans l'[ADR-028](../docs/01-architecture/adr/ADR-028-etats-de-congestion-et-alertes.md) et le [dictionnaire de données](../docs/03-donnees/dictionnaire-de-donnees.md) ; le découpage entraînement/test se fait par run et par scénario.
