"""Validation de corps de réponse contre les schémas du contrat OpenAPI de la collecte (MS-08)."""

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tests.contract.conftest import CONTRACTS

OPENAPI = CONTRACTS / "openapi"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


COLLECTE = load(OPENAPI / "collecte.openapi.yaml")
REGISTRY = Registry().with_resources(
    [
        ("common.yaml", Resource.from_contents(load(OPENAPI / "common.yaml"), DRAFT202012)),
        ("collecte.openapi.yaml", Resource.from_contents(COLLECTE, DRAFT202012)),
    ]
)
PROBLEM = "common.yaml#/components/schemas/Problem"
RECEIPT = "collecte.openapi.yaml#/components/schemas/MeasurementReceipt"


def errors_of(body: object, reference: str) -> list[str]:
    validator = Draft202012Validator(
        {"$ref": reference}, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [f"{'/'.join(map(str, e.path))} : {e.message}" for e in validator.iter_errors(body)]


def check(body: object, reference: str) -> None:
    """Valide `body` contre un schéma du contrat, par exemple `RECEIPT` ou `PROBLEM`."""
    assert errors_of(body, reference) == []
