"""Les modèles Pydantic des événements restent alignés sur contracts/events/ (MS-03).

Trois contrôles :
1. la forme : mêmes champs, champs obligatoires, énumérations et bornes, pour chaque sujet ;
2. l'acceptation : sur tous les exemples et cas invalides du dépôt, le modèle accepte
   exactement ce que le schéma accepte ;
3. l'aller-retour : un exemple lu par le modèle et réécrit redonne le même JSON.
Si un schéma ou un modèle change seul, l'un de ces tests échoue.
"""

import json

import pytest
import validate_events as ve
from cases import EXAMPLES, INVALID_CASES, load, mutate
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from app.schemas import events

CONTRACTS_EVENTS = ve.EVENTS_DIR
SCHEMA_OF = {event_type: ve.SCHEMA_BY_TYPE[event_type] for event_type in events.EVENT_MODELS}
EXAMPLE_FILES = sorted(p.name for p in EXAMPLES.glob("*.json"))
SEMANTIC_ONLY = {
    "subject différent du carrefour de data",
    "id de mesure qui ne suit pas la convention",
    "fenêtre non alignée",
    "time d'un indicateur différent de la fin de fenêtre",
    "alerte résolue avant d'être ouverte",
    "mesure PARTIAL sans drapeau de champ manquant",
    "mesure SUSPECT sans drapeau de valeur implausible",
    "id d'indicateur qui ne suit pas la convention",
    "alerte créée avec un état précédent",
    "alerte au-delà de la création sans état précédent",
    "alerte qui revient en arrière",
    "alerte qui reste dans le même état",
    "id différent de recommendation_id",
    "fin de validité antérieure à l'émission",
    "cycle différent de la somme des phases",
    "identifiant de phase en double",
    "phase courante absente du plan",
    "début de phase postérieur à l'événement",
    "durée inférieure à la durée minimale",
    "identifiant de phase d'état en double",
    "sujet UNKNOWN alors que le carrefour est connu",
    "sujet de carrefour alors que le carrefour est inconnu",
    "time différent de rejected_at",
}


# ------------------------------------------------------------------------------ forme des schémas
def normalise(noeud, resolveur):
    """Forme comparable d'un nœud de schéma : références résolues, `null` rendu par `nullable`."""
    if "$ref" in noeud:
        trouve = resolveur.lookup(noeud["$ref"])
        return normalise(trouve.contents, trouve.resolver)
    branches = noeud.get("oneOf") or noeud.get("anyOf")
    if branches:
        restantes = [b for b in branches if b != {"type": "null"}]
        resultat = (
            normalise(restantes[0], resolveur)
            if len(restantes) == 1
            else {"branches": [normalise(b, resolveur) for b in restantes]}
        )
        return {
            **resultat,
            "nullable": len(restantes) != len(branches) or resultat.get("nullable", False),
        }
    forme = {}
    types = noeud.get("type")
    types = set(types) if isinstance(types, list) else ({types} if types else set())
    valeurs = [noeud["const"]] if "const" in noeud else noeud.get("enum")
    nullable = "null" in types or (valeurs is not None and None in valeurs)
    if types - {"null"}:
        forme["type"] = sorted(types - {"null"})
    if valeurs is not None:
        forme.pop("type", None)  # le type se déduit des valeurs permises
        forme["valeurs"] = sorted((v for v in valeurs if v is not None), key=str)
    forme["nullable"] = nullable
    for cle in ("minimum", "maximum", "minLength", "maxLength", "pattern", "minItems", "maxItems"):
        if cle in noeud:
            forme[cle] = noeud[cle]
    if "properties" in noeud:
        forme["champs"] = {
            nom: normalise(sous, resolveur) for nom, sous in noeud["properties"].items()
        }
        forme["obligatoires"] = sorted(noeud.get("required", []))
        forme["ferme"] = noeud.get("additionalProperties") is False
    if "items" in noeud:
        forme["elements"] = normalise(noeud["items"], resolveur)
    return forme


def forme_du_contrat(type_evenement):
    nom = SCHEMA_OF[type_evenement]
    schema = ve._SCHEMAS[nom]
    resolveur = ve._REGISTRY.resolver(schema["$id"])
    donnees = normalise(schema["$defs"]["data"], resolveur)
    enveloppe = ve._SCHEMAS["envelope.schema.json"]
    specifique = schema["allOf"][1]["properties"]
    champs = {**enveloppe["properties"], **{k: v for k, v in specifique.items() if k != "data"}}
    constantes = {k: specifique[k]["const"] for k in ("type", "schema_version", "domain")}
    return donnees, set(enveloppe["required"]), set(champs) | {"data"}, constantes


def forme_du_modele(modele):
    schema = modele.model_json_schema(mode="validation")
    schema["$id"] = "urn:modele"
    registre = Registry().with_resource(
        "urn:modele", Resource.from_contents(schema, default_specification=DRAFT202012)
    )
    resolveur = registre.resolver("urn:modele")
    donnees = normalise(schema["properties"]["data"], resolveur)
    constantes = {k: schema["properties"][k]["const"] for k in ("type", "schema_version", "domain")}
    return donnees, set(schema["required"]), set(schema["properties"]), constantes


@pytest.mark.parametrize("type_evenement", sorted(events.EVENT_MODELS))
def test_le_modele_a_la_meme_forme_que_le_schema(type_evenement):
    attendu_data, attendu_obligatoires, attendu_champs, attendu_constantes = forme_du_contrat(
        type_evenement
    )
    data, obligatoires, champs, constantes = forme_du_modele(events.EVENT_MODELS[type_evenement])
    assert champs == attendu_champs
    assert obligatoires == attendu_obligatoires
    assert constantes == attendu_constantes
    assert data == attendu_data


def test_chaque_type_du_validateur_a_son_modele_et_inversement():
    assert set(events.EVENT_MODELS) == set(ve.SCHEMA_BY_TYPE)


def test_la_forme_detecte_un_ecart_de_borne():
    """Garde-fou du garde-fou : une borne modifiée ferait bien échouer la comparaison."""
    attendu, *_ = forme_du_contrat("novaria.iot.measurement.v1")
    copie = json.loads(json.dumps(attendu))
    copie["champs"]["interval_s"]["maximum"] = 7200
    assert copie != attendu


# --------------------------------------------------------------------------------- acceptation
def accepte_par_le_modele(evenement) -> bool:
    try:
        events.parse_event(evenement)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize("nom", EXAMPLE_FILES)
def test_chaque_exemple_est_accepte_et_se_reecrit_a_l_identique(nom):
    exemple = load(nom)
    modele = events.parse_event(exemple)
    assert type(modele) is events.EVENT_MODELS[exemple["type"]]
    assert modele.model_dump(mode="json", exclude_unset=True) == exemple
    assert ve.schema_errors(modele.model_dump(mode="json", exclude_unset=True)) == []


@pytest.mark.parametrize("cas", INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_le_modele_accepte_exactement_ce_que_le_schema_accepte(cas):
    description, exemple, changement, _ = cas
    evenement = mutate(exemple, changement)
    assert accepte_par_le_modele(evenement) == (ve.schema_errors(evenement) == [])
    if description in SEMANTIC_ONLY:
        # le schéma ne sait pas exprimer ces règles : le modèle les accepte, le validateur non
        assert accepte_par_le_modele(evenement)
        assert ve.validate_event(evenement) != []
    else:
        assert not accepte_par_le_modele(evenement)


def test_un_type_inconnu_est_refuse():
    evenement = load("mesure-valide.json")
    evenement["type"] = "novaria.autre.v1"
    assert not accepte_par_le_modele(evenement)


def test_les_types_sont_stricts_comme_le_schema():
    evenement = load("mesure-valide.json")
    evenement["data"]["vehicle_count"] = "4"  # un texte n'est pas converti en entier
    assert not accepte_par_le_modele(evenement)
    evenement = load("mesure-valide.json")
    evenement["data"]["vehicle_count"] = True  # un booléen n'est pas un entier
    assert not accepte_par_le_modele(evenement)


def test_une_date_impossible_est_refusee():
    evenement = load("mesure-valide.json")
    evenement["time"] = "2026-13-45T08:00:10Z"
    assert not accepte_par_le_modele(evenement)


def test_un_uuid_mal_forme_est_refuse():
    evenement = load("alerte-creee.json")
    evenement["data"]["alert_id"] = "6f1c2b9e4c7a4f0e9d531a2b3c4d5e6f"  # sans tirets
    assert not accepte_par_le_modele(evenement)


def test_le_message_illisible_garde_sa_charge_sous_forme_de_texte():
    illisible = events.parse_event(load("rejet-illisible.json"))
    assert isinstance(illisible.data.original_payload, str)
    assert illisible.subject == "UNKNOWN"
