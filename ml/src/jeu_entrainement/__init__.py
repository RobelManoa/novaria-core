"""Jeu d'entraînement v1 (IA-08) : runs du simulateur, vérité terrain, export Parquet et fiche de provenance.

Chaîne : catalogue de runs -> simulateur -> fenêtres d'une minute (le moteur du traitement en flux) -> variables
et réponses du dictionnaire de données (section 9) -> fichiers Parquet par découpage -> PROVENANCE.md et empreintes.
Bibliothèque standard seulement (le simulateur et le moteur de fenêtres du dépôt sont importés tels quels).
"""

VERSION_DU_CODE = "1.0.0"  # version du constructeur de jeu ; entre dans la fiche de provenance
