"""Validation de corps de réponse contre les schémas du contrat OpenAPI de la réponse (MS-12)."""

from functools import cache

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.contract.conftest import CONTRACTS

PROBLEM = "common.yaml#/components/schemas/Problem"


@cache
def document(name: str) -> dict:
    return yaml.safe_load((CONTRACTS / "openapi" / name).read_text(encoding="utf-8"))


def _retrieve(uri: str) -> Resource:
    """Les références du contrat (`common.yaml#/…`) se résolvent dans le dossier des contrats."""
    return Resource.from_contents(document(uri), DRAFT202012)


def schema(name: str) -> str:
    return f"reponse.openapi.yaml#/components/schemas/{name}"


def check(body: object, reference: str) -> None:
    """Valide `body` contre un schéma du contrat : `schema("SignalState")`, `PROBLEM`…"""
    validator = Draft202012Validator(
        {"$ref": reference},
        registry=Registry(retrieve=_retrieve),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    problems = [f"{list(e.path)} : {e.message}" for e in validator.iter_errors(body)]
    assert problems == []


def operations() -> dict[tuple[str, str], dict]:
    """{(méthode, chemin): opération} du contrat."""
    verbs = {"get", "post", "patch", "put", "delete"}
    paths = document("reponse.openapi.yaml")["paths"]
    return {
        (verb.upper(), path): operation
        for path, item in paths.items()
        for verb, operation in item.items()
        if verb in verbs
    }
