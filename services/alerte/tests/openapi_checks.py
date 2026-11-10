"""Validation de corps de réponse contre les schémas du contrat OpenAPI de l'alerte (MS-11)."""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.contract.conftest import CONTRACTS

OPENAPI = CONTRACTS / "openapi"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


ALERTE = load(OPENAPI / "alerte.openapi.yaml")
REGISTRY = Registry().with_resources(
    [
        ("common.yaml", Resource.from_contents(load(OPENAPI / "common.yaml"), DRAFT202012)),
        ("alerte.openapi.yaml", Resource.from_contents(ALERTE, DRAFT202012)),
    ]
)
PROBLEM = "common.yaml#/components/schemas/Problem"


def schema(name: str) -> str:
    return f"alerte.openapi.yaml#/components/schemas/{name}"


def errors_of(body: object, reference: str) -> list[str]:
    validator = Draft202012Validator(
        {"$ref": reference}, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [f"{'/'.join(map(str, e.path))} : {e.message}" for e in validator.iter_errors(body)]


def check(body: object, reference: str) -> None:
    """Valide `body` contre un schéma du contrat, par exemple `schema("Alert")` ou `PROBLEM`."""
    assert errors_of(body, reference) == []


def operations() -> dict[tuple[str, str], dict]:
    """{(méthode, chemin): opération} du contrat, chemins préfixés comme dans l'application."""
    return {
        (method.upper(), path): operation
        for path, item in ALERTE["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post", "patch", "put", "delete"}
    }
