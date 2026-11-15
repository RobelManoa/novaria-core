"""Préparation des variables et découpage (IA-02) : de `data/datasets/novaria-congestion-v1/` à des matrices prêtes à apprendre.

Règles (docs/06-ia-mlops/cadrage-ml.md, sections 3 et 7) : seules les variables permises entrent dans un modèle ; ce
qui est appris (médianes, catégories) l'est sur l'entraînement seul ; rien du futur n'alimente une variable ; le
découpage est par run et par scénario, et dans l'ordre du temps (avec un délai de garde) pour la prévision.
Bibliothèque standard seulement.
"""
