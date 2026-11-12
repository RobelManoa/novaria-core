"""Pipeline MLOps et MLSecOps (IA-05) : entraîner, évaluer, appliquer le seuil, enregistrer, avec ses contrôles de sécurité.

Étapes (`python -m pipeline evaluer|porte|enregistrer|tout`) :

1. `evaluer` : jeu intact (S1), entraînement de la configuration **figée** par IA-03, évaluation sur le test, conditions A1 à A5,
   contrôles de sécurité (S2 à S5, T1, R1), décision ; rien n'est enregistré comme modèle ;
2. `porte` : **bloque** (code de sortie 1) si la décision n'est pas « accepté » ; le run est alors écrit `rejected`, sans fichier ;
3. `enregistrer` : seulement après la porte, promeut le modèle dans le registre (IA-04).

Aucune valeur de seuil ne se règle ici : elles viennent de `entrainement.acceptation` (cadrage ML, section 6), et le
déclencheur du flux de travail n'a aucun paramètre. Tout ce que le pipeline écrit vit sous `var/` (jamais versionné).
"""

from jeu_entrainement.simulation import RACINE

VERSION = "1"
DOSSIER = RACINE / "var" / "pipeline"
RUNS = DOSSIER / "model_runs"
DECISION = DOSSIER / "decision.json"
MODELE_PREPARE = DOSSIER / "modele.json"
RAPPORT_MD = DOSSIER / "rapport.md"
AUDIT_JSON = DOSSIER / "audit-dependances.json"
SBOM = DOSSIER / "sbom.cdx.json"
MAGASIN = RACINE / "var" / "models"
EXIGENCES = RACINE / "ml" / "requirements.txt"
FICHE = RACINE / "docs" / "06-ia-mlops" / "fiche-modele.md"
