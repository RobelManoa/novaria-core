"""Les contrôles de sécurité du pipeline (cadrage ML, section 9.2) : chacun rend un `Controle`, jamais une exception.

`ok` vaut vrai (vérifié), faux (échec) ou `None` (**non vérifié** : un contrôle bloquant non vérifié bloque, un contrôle
non bloquant est rapporté tel quel). Un contrôle qui n'a pas pu tourner n'est jamais déclaré réussi.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pipeline
from jeu_entrainement import integrite
from registre import format_lineaire


@dataclass(frozen=True)
class Controle:
    code: str
    libelle: str
    ok: bool | None
    detail: str
    bloquant: bool

    def en_dict(self) -> dict:
        return {"code": self.code, "libelle": self.libelle, "ok": self.ok, "detail": self.detail, "bloquant": self.bloquant}

    @property
    def etat(self) -> str:
        return "non vérifié" if self.ok is None else ("réussi" if self.ok else "ÉCHEC")


def s1_jeu_intact(dossier: Path, empreinte_attendue: str) -> Controle:
    ecarts = integrite.verifier(dossier, empreinte_attendue)
    return Controle("S1", "jeu de données intact et identique à celui de la sélection", not ecarts,
                    "SHA-256 recalculés, conformes au manifeste et à l'empreinte attendue" if not ecarts else " ; ".join(ecarts), True)


def s2_artefact_trace(octets: bytes | None, predits_du_modele: list[str], predire_depuis_l_artefact) -> Controle:
    """Le fichier exporté, relu, prédit exactement comme le modèle entraîné : ce qu'on enregistre est ce qu'on a évalué."""
    libelle = "l'artefact exporté prédit comme le modèle évalué"
    if octets is None:
        return Controle("S2", libelle, False, "aucun artefact exporté", True)
    try:
        relues = predire_depuis_l_artefact(octets)
    except (format_lineaire.FormatInvalide, ValueError) as erreur:
        return Controle("S2", libelle, False, f"l'artefact ne se relit pas ({erreur})", True)
    ecarts = sum(1 for a, b in zip(relues, predits_du_modele, strict=True) if a != b) if len(relues) == len(predits_du_modele) else len(predits_du_modele)
    return Controle("S2", libelle, ecarts == 0, f"{len(predits_du_modele)} prédictions comparées, {ecarts} écart(s)", True)


def s3_format_sur(candidat: str, octets: bytes | None, erreur_d_export: str | None) -> Controle:
    libelle = "format de modèle sans exécution de code"
    if erreur_d_export:
        return Controle("S3", libelle, False, f"le candidat « {candidat} » n'a pas de format sûr ({erreur_d_export})", True)
    try:
        format_lineaire.ModeleLineaire.depuis_octets(octets or b"")
    except format_lineaire.FormatInvalide as erreur:
        return Controle("S3", libelle, False, str(erreur), True)
    return Controle("S3", libelle, True, f"{format_lineaire.NOM}, relu sans exécuter de code", True)


def s4_dependances(exigences: Path | None = None, executable: str | None = None, delai_s: int = 180) -> Controle:
    """Audit des dépendances ML contre les avis de vulnérabilité publics (pip-audit) ; écrit aussi la nomenclature (SBOM).

    Non bloquant (cadrage S4) : le résultat est rapporté. Outil absent, réseau coupé ou réponse illisible : **non vérifié**.
    """
    libelle = "dépendances ML sans vulnérabilité connue (pip-audit)"
    exigences = exigences or pipeline.EXIGENCES
    exe = executable or os.environ.get("PIP_AUDIT") or shutil.which("pip-audit")
    if not exe:
        return Controle("S4", libelle, None, "pip-audit absent (ml/requirements-mlsecops.txt) : non vérifié", False)
    pipeline.DOSSIER.mkdir(parents=True, exist_ok=True)
    base = [exe, "-r", str(exigences), "--require-hashes", "--disable-pip"]
    try:
        resultat = subprocess.run([*base, "-f", "json", "-o", str(pipeline.AUDIT_JSON)], capture_output=True, text=True, timeout=delai_s, check=False)
        subprocess.run([*base, "-f", "cyclonedx-json", "-o", str(pipeline.SBOM)], capture_output=True, text=True, timeout=delai_s, check=False)
        rapport = json.loads(pipeline.AUDIT_JSON.read_text(encoding="utf-8"))
    except (OSError, subprocess.TimeoutExpired, ValueError) as erreur:
        return Controle("S4", libelle, None, f"audit impossible ({type(erreur).__name__}) : non vérifié", False)
    dependances = rapport.get("dependencies", [])
    vulnerables = [f"{d['name']} {d['version']} : {', '.join(v['id'] for v in d['vulns'])}" for d in dependances if d.get("vulns")]
    if resultat.returncode not in (0, 1) or not dependances:
        return Controle("S4", libelle, None, f"pip-audit a rendu le code {resultat.returncode} : non vérifié", False)
    if vulnerables:
        return Controle("S4", libelle, False, f"{len(dependances)} dépendances auditées ; vulnérables : " + " ; ".join(vulnerables), False)
    return Controle("S4", libelle, True, f"{len(dependances)} dépendances auditées, aucune vulnérabilité connue ; nomenclature (SBOM) écrite", False)


SECTIONS_DE_LA_FICHE = ("Usage prévu", "Données", "Métriques", "Limites", "Statut")


def s5_fiche_du_modele(candidat: str, fiche: Path | None = None) -> Controle:
    """La fiche du modèle existe, a ses sections, nomme le candidat et a été **relue par l'autre membre**."""
    libelle = "fiche du modèle écrite et relue par l'autre membre"
    fiche = fiche or pipeline.FICHE
    if not fiche.is_file():
        return Controle("S5", libelle, False, f"{fiche.name} absente", True)
    texte = fiche.read_text(encoding="utf-8")
    manquantes = [s for s in SECTIONS_DE_LA_FICHE if not re.search(rf"(?m)^#+ .*{re.escape(s)}", texte)]
    if manquantes:
        return Controle("S5", libelle, False, f"sections manquantes : {manquantes}", True)
    if candidat not in texte:
        return Controle("S5", libelle, False, f"la fiche ne nomme pas le candidat « {candidat} »", True)
    relue = re.search(r"(?mi)^\**Relue par\**\s*:\s*(.+)$", texte)
    if not relue or re.search(r"(?i)à faire|non relue|^\s*$", relue.group(1)):
        return Controle("S5", libelle, False, "relecture par l'autre membre absente (ligne « Relue par : nom, date »)", True)
    return Controle("S5", libelle, True, f"fiche complète, relue : {relue.group(1).strip()}", True)


def t1_code_commite(git_dirty: bool | None, git_sha: str | None) -> Controle:
    libelle = "code commité : le modèle se refait depuis sa révision Git"
    if git_sha is None or git_dirty is None:
        return Controle("T1", libelle, None, "état de Git inconnu : non vérifié", True)
    return Controle("T1", libelle, not git_dirty, f"révision {git_sha[:10]}" + (" avec du code non commité" if git_dirty else ", arbre propre"), True)


def r1_reproduction(recalcule: dict, enregistre: dict | None) -> Controle:
    """Les métriques recalculées sont celles du résultat enregistré : même graine, mêmes données, mêmes dépendances."""
    libelle = "métriques reproduites à l'identique"
    if enregistre is None:
        return Controle("R1", libelle, None, "aucun résultat enregistré à reproduire : non vérifié", True)
    differences = [f"{nom} : {recalcule.get(nom)} au lieu de {enregistre.get(nom)}" for nom in sorted(set(enregistre) | set(recalcule)) if recalcule.get(nom) != enregistre.get(nom)]
    return Controle("R1", libelle, not differences, "toutes les métriques du test recalculées sont identiques" if not differences else " ; ".join(differences[:6]), True)
