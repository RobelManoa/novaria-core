"""Le service respecte son contrat OpenAPI de contracts/openapi/ (MS-03).

La sonde de santé répond selon le schéma `Health`, et aucune route n'existe sans être décrite dans
le contrat du service, `contracts/openapi/<nom du dossier du service>.openapi.yaml`. Un service qui
porte provisoirement le rôle d'un autre déclare les contrats en plus dans son `pyproject.toml`
(`[tool.novaria] contrats = ["<son nom>", "<autre contrat>"]`) : une route doit alors figurer dans
l'un d'eux. Le modèle de service (dossier dont le nom commence par `_`) n'a pas de contrat propre :
seule la sonde est testée.
"""

import tomllib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.main import app
from tests.contract.conftest import CONTRACTS

RACINE_SERVICE = Path(__file__).resolve().parents[2]
SERVICE = RACINE_SERVICE.name
client = TestClient(app)


def charger(chemin: Path) -> dict:
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


def noms_des_contrats() -> list[str]:
    pyproject = tomllib.loads((RACINE_SERVICE / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject.get("tool", {}).get("novaria", {}).get("contrats", [SERVICE])


def contrats_du_service() -> list[Path]:
    return [CONTRACTS / "openapi" / f"{nom}.openapi.yaml" for nom in noms_des_contrats()]


def test_la_sonde_repond_selon_le_schema_health():
    schema = charger(CONTRACTS / "openapi" / "common.yaml")["components"]["schemas"]["Health"]
    reponse = client.get("/api/v1/health")
    assert reponse.status_code == 200
    assert list(Draft202012Validator(schema).iter_errors(reponse.json())) == []


@pytest.mark.skipif(
    SERVICE.startswith("_"), reason="le modèle de service n'a pas de contrat propre"
)
def test_toute_route_du_service_est_decrite_dans_son_contrat():
    assert SERVICE in noms_des_contrats(), (
        "le contrat du service ne peut pas être retiré de la liste"
    )
    chemins: dict[str, dict] = {}
    for contrat in contrats_du_service():
        assert contrat.is_file(), f"contrat manquant : {contrat.relative_to(CONTRACTS.parent)}"
        for chemin, operations in charger(contrat)["paths"].items():
            chemins.setdefault(chemin, {}).update(operations)
    for chemin, operations in app.openapi()["paths"].items():
        assert chemin in chemins, f"route absente du contrat : {chemin}"
        for methode in operations:
            assert methode in chemins[chemin], f"{methode.upper()} {chemin} absent du contrat"
