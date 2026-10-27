"""Contrôle de compatibilité ascendante (contracts/check_compat.py). Lancer :
    python3 -m unittest discover -s contracts/tests -v        (Windows : py -3 -m unittest ...)
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import check_compat as cc  # noqa: E402

ANCIEN = {
    "type": "object", "additionalProperties": False, "required": ["a"],
    "properties": {
        "a": {"type": "integer", "minimum": 0, "maximum": 10},
        "b": {"enum": ["X", "Y"]},
        "c": {"type": ["string", "null"], "maxLength": 20},
        "d": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}


def modifie(change):
    nouveau = copy.deepcopy(ANCIEN)
    change(nouveau)
    return nouveau


# (description, modification, fragment attendu)
RUPTURES = [
    ("champ devenu obligatoire", lambda s: s["required"].append("b"), "obligatoire : b"),
    ("champ retiré d'un schéma fermé", lambda s: s["properties"].pop("c"), "champ retiré"),
    ("valeur d'énumération retirée", lambda s: s["properties"]["b"].update(enum=["X"]), "valeurs retirées"),
    ("énumération remplaçant un champ libre", lambda s: s["properties"]["c"].update(enum=["Z"]), "valeurs désormais limitées"),
    ("type restreint", lambda s: s["properties"]["c"].update(type="string"), "type restreint"),
    ("minimum relevé", lambda s: s["properties"]["a"].update(minimum=1), "minimum relevé"),
    ("maximum abaissé", lambda s: s["properties"]["a"].update(maximum=5), "maximum abaissé"),
    ("longueur maximale abaissée", lambda s: s["properties"]["c"].update(maxLength=10), "maxLength abaissé"),
    ("borne ajoutée", lambda s: s["properties"]["d"].update(minItems=1), "minItems ajouté"),
    ("unicité ajoutée", lambda s: s["properties"]["d"].update(uniqueItems=True), "uniqueItems"),
    ("règle conditionnelle ajoutée", lambda s: s.update(allOf=[{"if": {}, "then": {}}]), "allOf ajoutée"),
    ("contrainte de l'élément d'une liste durcie", lambda s: s["properties"]["d"]["items"].update(maxLength=3), "maxLength ajouté"),
    ("énumération remplacée par une constante", lambda s: s["properties"]["b"].update(const="Z") or s["properties"]["b"].pop("enum"),
     "valeurs retirées"),
]
COMPATIBLES = [
    ("champ facultatif ajouté", lambda s: s["properties"].update(e={"type": "string"})),
    ("valeur d'énumération ajoutée", lambda s: s["properties"]["b"].update(enum=["X", "Y", "Z"])),
    ("type élargi", lambda s: s["properties"]["c"].update(type=["string", "null", "integer"])),
    ("minimum abaissé", lambda s: s["properties"]["a"].update(minimum=-5)),
    ("maximum relevé", lambda s: s["properties"]["a"].update(maximum=100)),
    ("longueur maximale relevée", lambda s: s["properties"]["c"].update(maxLength=40)),
    ("champ devenu facultatif", lambda s: s.update(required=[])),
    ("contrainte supprimée", lambda s: s["properties"]["a"].pop("maximum")),
    ("constante élargie en énumération", lambda s: s["properties"]["b"].update(enum=["X", "Y", "Z"])),
    ("description modifiée", lambda s: s["properties"]["a"].update(description="nouveau texte")),
    ("schéma ouvert aux champs inconnus", lambda s: s.update(additionalProperties=True)),
]


class CompatibiliteAscendante(unittest.TestCase):
    def test_un_schema_identique_est_compatible(self):
        self.assertEqual(cc.breaking_changes(ANCIEN, copy.deepcopy(ANCIEN)), [])

    def test_chaque_rupture_est_detectee_pour_la_bonne_raison(self):
        for description, change, fragment in RUPTURES:
            nouveau = modifie(change)
            with self.subTest(cas=description):
                changes = cc.breaking_changes(ANCIEN, nouveau)
                self.assertTrue(changes, "la rupture aurait dû être détectée")
                if fragment:
                    self.assertTrue(any(fragment in c for c in changes), f"{fragment!r} absent de {changes}")

    def test_chaque_evolution_compatible_est_acceptee(self):
        for description, change in COMPATIBLES:
            with self.subTest(cas=description):
                self.assertEqual(cc.breaking_changes(ANCIEN, modifie(change)), [])

    def test_un_schema_ouvert_qui_se_ferme_est_une_rupture(self):
        ouvert = {"type": "object", "properties": {"a": {"type": "integer"}}}
        ferme = {**ouvert, "additionalProperties": False}
        changes = cc.breaking_changes(ouvert, ferme)
        self.assertTrue(any("champs inconnus désormais refusés" in c for c in changes), changes)
        self.assertEqual(cc.breaking_changes(ferme, ouvert), [])

    def test_un_pattern_ou_une_reference_modifies_sont_a_verifier_pas_des_ruptures(self):
        ancien = {"properties": {"x": {"$ref": "a.json#/x"}, "y": {"pattern": "^a$"}}}
        nouveau = {"properties": {"x": {"$ref": "a.json#/z"}, "y": {"pattern": "^(a|b)$"}}}
        changes = cc.breaking_changes(ancien, nouveau)
        self.assertEqual(len(changes), 2)
        self.assertTrue(all(c.startswith("? ") for c in changes), changes)

    def test_une_version_majeure_n_est_pas_comparee(self):
        def schema(type_, obligatoire):
            return {"allOf": [{}, {"properties": {"type": {"const": type_}}}], "required": obligatoire}
        ancien = {"e.schema.json": schema("novaria.x.v1", [])}
        self.assertEqual(cc.compare(ancien, {"e.schema.json": schema("novaria.x.v2", ["nouveau"])}), [])
        self.assertTrue(cc.compare(ancien, {"e.schema.json": schema("novaria.x.v1", ["nouveau"])}))

    def test_un_schema_supprime_est_une_rupture_et_un_schema_ajoute_non(self):
        self.assertEqual(cc.compare({}, {"nouveau.schema.json": {}}), [])
        self.assertEqual(cc.compare({"ancien.schema.json": {}}, {}), ["ancien.schema.json : schéma supprimé"])

    def test_les_schemas_actuels_sont_compatibles_avec_eux_memes(self):
        actuels = cc.load_directory(cc.EVENTS)
        self.assertEqual(len(actuels), 8)  # enveloppe, définitions communes et six sujets
        self.assertEqual(cc.compare(actuels, actuels), [])


if __name__ == "__main__":
    unittest.main()
