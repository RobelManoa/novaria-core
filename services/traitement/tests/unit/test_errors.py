"""Messages de validation en français, sans la valeur saisie (BE-04, BE-06) : corps Problem."""

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from app.core.errors import field_path, french_message, http_problem


@pytest.mark.parametrize(
    ("erreur", "message"),
    [
        ({"type": "missing"}, "Champ obligatoire."),
        ({"type": "string_too_short", "ctx": {"min_length": 3}}, "Au moins 3 caractères."),
        ({"type": "string_too_long", "ctx": {"max_length": 64}}, "Au plus 64 caractères."),
        ({"type": "string_pattern_mismatch"}, "Format invalide."),
        ({"type": "greater_than_equal", "ctx": {"ge": 1}}, "Doit être supérieur ou égal à 1."),
        ({"type": "less_than_equal", "ctx": {"le": 500}}, "Doit être inférieur ou égal à 500."),
        ({"type": "enum", "ctx": {"expected": "60, 300"}}, "Valeur non admise : 60, 300."),
        ({"type": "literal_error", "ctx": {"expected": "'a'"}}, "Valeur non admise : 'a'."),
        ({"type": "int_parsing"}, "Entier attendu."),
        ({"type": "int_from_float"}, "Entier attendu."),
        ({"type": "extra_forbidden"}, "Champ non prévu."),
        ({"type": "uuid_parsing"}, "Identifiant UUID attendu."),
        ({"type": "json_invalid"}, "JSON invalide."),
        ({"type": "too_short", "ctx": {"min_length": 1}}, "Au moins 1 éléments."),
        ({"type": "too_long", "ctx": {"max_length": 9}}, "Au plus 9 éléments."),
        ({"type": "greater_than", "ctx": {"gt": 0}}, "Doit être strictement supérieur à 0."),
        ({"type": "less_than", "ctx": {"lt": 5}}, "Doit être strictement inférieur à 5."),
        ({"type": "float_parsing"}, "Nombre attendu."),
        ({"type": "bool_parsing"}, "Booléen attendu (true ou false)."),
        ({"type": "string_type"}, "Texte attendu."),
        ({"type": "datetime_parsing"}, "Date et heure ISO 8601 attendues."),
        ({"type": "datetime_from_date_parsing"}, "Date et heure ISO 8601 attendues."),
        ({"type": "model_attributes_type"}, "Objet JSON attendu."),
        ({"type": "dict_type"}, "Objet JSON attendu."),
        ({"type": "list_type"}, "Liste attendue."),
        ({"type": "uuid_type"}, "Identifiant UUID attendu."),
        ({"type": "value_error", "ctx": {"error": "valeur-secrète"}}, "Valeur invalide."),
        ({"type": "quelque_chose_d_inedit"}, "Valeur invalide."),
    ],
)
def test_a_validation_error_is_explained_in_french(erreur, message):
    assert french_message(erreur) == message


def test_the_value_that_was_typed_is_never_repeated_in_the_message():
    erreur = {"type": "string_too_short", "input": "mot-de-passe-secret", "ctx": {"min_length": 12}}
    assert "secret" not in french_message(erreur)


def test_the_field_path_names_the_part_of_the_request():
    assert field_path({"type": "missing", "loc": ("body", "password")}) == "body.password"
    assert field_path({"type": "int_parsing", "loc": ("query", "limit")}) == "query.limit"
    assert field_path({"type": "uuid_parsing", "loc": ("path", "user_id")}) == "path.user_id"
    assert field_path({"type": "missing", "loc": ("body", "items", 2, "id")}) == "body.items.2.id"


def test_an_unreadable_json_designates_the_body_not_a_character_position():
    assert field_path({"type": "json_invalid", "loc": ("body", 17)}) == "body"


def request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "UNAUTHENTICATED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (405, "METHOD_NOT_ALLOWED"),
        (409, "CONFLICT"),
        (429, "RATE_LIMITED"),
        (400, "VALIDATION_ERROR"),
        (413, "VALIDATION_ERROR"),
        (418, "VALIDATION_ERROR"),
        (500, "INTERNAL_ERROR"),
        (502, "INTERNAL_ERROR"),
        (503, "INTERNAL_ERROR"),
    ],
)
def test_a_framework_http_error_is_translated_and_keeps_its_status(status, code):
    problem = http_problem(request("/api/v1/x"), HTTPException(status, detail="Texte anglais"))
    assert (problem.kind.status, problem.kind.code) == (status, code)
    assert "anglais" not in problem.detail
    assert problem.body()["status"] == status


def test_the_headers_of_the_framework_error_are_kept():
    error = HTTPException(405, detail="Method Not Allowed", headers={"Allow": "GET, POST"})
    assert http_problem(request("/api/v1/users"), error).headers == {"Allow": "GET, POST"}


def test_only_a_404_on_an_unpublished_version_gets_the_version_message():
    version = http_problem(request("/api/v2/users"), HTTPException(404)).detail
    assert version == "Version d'API non prise en charge : v2. Versions disponibles : v1."
    assert http_problem(request("/api/v2/users"), HTTPException(405)).detail.startswith("Méthode")
    assert http_problem(request("/api/v1/users"), HTTPException(404)).detail == (
        "Cette route n'existe pas."
    )
