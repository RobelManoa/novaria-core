"""Échantillon commun aux tests de data/etl : lignes fabriquées dans la forme exacte de l'export du portail.

Mêmes colonnes, BOM, fins de ligne CRLF, séparateur « ; », q et k vides, forme géographique entre guillemets doublés ;
valeurs inventées. Aucune donnée réelle n'est versionnée (licence ODbL, ADR-027 règle 7).
"""

import csv
import io
import re
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from pipelines import paris_comptages as paris  # noqa: E402

FORME = '{"coordinates": [[2.3103, 48.8625], [2.3111, 48.8627]], "type": "LineString"}'
LIGNES = [
    ("4392", "Quai_d'Orsay", "2026-10-18T10:00:00+00:00", "199.0", "2.03556", "Fluide", "2349", "Pl_de_Finlande", "189",
     "Pt_Alexandre_III_Gauche", "Ouvert", "1996-10-14", "2023-01-01", "48.8627, 2.3118", FORME),
    ("324", "Pt_Alexandre_III", "2026-10-18T10:00:00+00:00", "", "", "Inconnu", "165", "Pt_Alexandre_III_Droite", "189",
     "Pt_Alexandre_III_Gauche", "Invalide", "1996-10-03", "2023-01-01", "48.8637, 2.3134", FORME),
    ("327", "Bd_St_Germain", "2026-10-18T10:00:00+00:00", "1314.0", "10.36056", "Fluide", "186", "Pt_Concorde_Gauche", "190",
     "Bd_St_Germain-A.Briand", "Ouvert", "1996-10-03", "2023-01-01", "48.8623, 2.3193", FORME),
    ("193", "Sts_Peres", "2026-10-18T10:00:00+00:00", "167.0", "", "Inconnu", "120", "Bd_St_Germain-Sts_Peres", "117",
     "Sts_Peres-Grenelle", "Ouvert", "1996-10-03", "2023-01-01", "48.8535, 2.3298", FORME),
    ("501", "Bd_Peripherique", "2026-10-18T10:00:00+00:00", "2400.0", "31.5", "Saturé", "7", "Porte_A", "8", "Porte_B",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8000, 2.3000", FORME),
    ("502", "Bd_Peripherique", "2026-10-18T10:00:00+00:00", "100.0", "55.1", "Bloqué", "8", "Porte_B", "9", "Porte_C",
     "Barré", "1996-10-03", "2023-01-01", "48.8100, 2.3100", FORME),
    ("503", "Av_de_la_Republique", "2026-10-18T10:00:00+00:00", "800.0", "22.0", "Pré-saturé", "10", "Pl_A", "11", "Pl_B",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8200, 2.3200", FORME),
    ("504", "Rue_Sans_Etat", "2026-10-18T10:00:00+00:00", "50.0", "1.2", "", "12", "Pl_C", "13", "Pl_D",
     "Ouvert", "1996-10-03", "2023-01-01", "48.8300, 2.3300", FORME),
]


def fabriquer_csv(lignes=LIGNES, entete=paris.COLONNES, bom=True) -> bytes:
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(entete)
    ecrivain.writerows(lignes)
    return (b"\xef\xbb\xbf" if bom else b"") + sortie.getvalue().encode("utf-8")


def verifier_contre_le_validateur(document: dict, schema: dict):
    """Contrôle minimal d'un document contre un $jsonSchema : champs obligatoires, types, motifs, bornes, énumérations."""

    manquants = [champ for champ in schema["required"] if champ not in document]
    if manquants:
        raise AssertionError(f"champs obligatoires absents : {manquants}")
    for champ, regle in schema["properties"].items():
        if champ not in document:
            continue
        valeur = document[champ]
        type_attendu = regle.get("bsonType")
        types = {"string": str, "date": datetime, "number": (int, float), "object": dict}
        if type_attendu and not isinstance(valeur, types[type_attendu]):
            raise AssertionError(f"{champ} : type {type(valeur).__name__} au lieu de {type_attendu}")
        if "enum" in regle and valeur not in regle["enum"]:
            raise AssertionError(f"{champ} : {valeur!r} hors énumération")
        if "pattern" in regle and not re.search(regle["pattern"], valeur):
            raise AssertionError(f"{champ} : {valeur!r} ne respecte pas {regle['pattern']}")
        if "minimum" in regle and valeur < regle["minimum"]:
            raise AssertionError(f"{champ} : {valeur} sous le minimum")
        if "minLength" in regle and len(valeur) < regle["minLength"]:
            raise AssertionError(f"{champ} : trop court")
