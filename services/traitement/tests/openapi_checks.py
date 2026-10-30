"""Validation de corps de réponse contre les schémas des contrats OpenAPI (BE-03, BE-04)."""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.contract.conftest import CONTRACTS

OPENAPI = CONTRACTS / "openapi"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


API = load(OPENAPI / "api-metier.openapi.yaml")
TRAITEMENT = load(OPENAPI / "traitement.openapi.yaml")
REGISTRY = Registry().with_resources(
    [
        ("common.yaml", Resource.from_contents(load(OPENAPI / "common.yaml"), DRAFT202012)),
        ("api-metier.openapi.yaml", Resource.from_contents(API, DRAFT202012)),
        ("traitement.openapi.yaml", Resource.from_contents(TRAITEMENT, DRAFT202012)),
    ]
)


def check(body, reference: str) -> None:
    """Valide `body` contre un schéma du contrat, par exemple `api-metier.openapi.yaml#/...`."""
    validator = Draft202012Validator(
        {"$ref": reference}, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    erreurs = [f"{'/'.join(map(str, e.path))} : {e.message}" for e in validator.iter_errors(body)]
    assert erreurs == [], erreurs


def schema(name: str, contract: str = "api-metier") -> str:
    return f"{contract}.openapi.yaml#/components/schemas/{name}"


PROBLEM = "common.yaml#/components/schemas/Problem"
