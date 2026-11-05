"""Validation des entrées contre les bornes du contrat (BE-06).

Le contrat dit, pour chaque paramètre de requête et chaque champ de corps, le type et les bornes
(`minimum`, `maximum`, `minLength`, `maxLength`, `pattern`, `enum`, `additionalProperties`).
Ces tests en tirent des valeurs invalides et vérifient que le service les refuse, avec `422`
`VALIDATION_ERROR` et le champ fautif désigné (`query.<nom>` ou `body.<nom>`), et qu'il accepte
les valeurs limites.

Quelques propriétés d'ensemble : toutes les erreurs d'une requête sont listées ensemble ; un message
ne reprend jamais la valeur saisie ; l'authentification passe avant la validation (un appelant sans
droit ne découvre pas les règles de saisie).
"""

import re

import pytest

from app.models import Role
from tests.contract.test_errors_contract import IMPLEMENTED, LOGIN, USERS, assert_problem
from tests.fakes import PASSWORD
from tests.openapi_checks import API, OPENAPI, TRAITEMENT, load
from tests.scene import UNKNOWN_ID

COMMON = load(OPENAPI / "common.yaml")
DOCUMENTS = {"common.yaml": COMMON, "api-metier": API, "traitement": TRAITEMENT}


def operation_document(method: str, path: str) -> dict:
    """Le contrat dont vient l'opération (pour résoudre ses `$ref` locaux)."""
    for document in (API, TRAITEMENT):
        if method in document["paths"].get(path, {}):
            return document
    raise KeyError((method, path))


def deref(node, document: dict):
    """Suit les `$ref` (locaux ou vers common.yaml) jusqu'à un objet qui n'en est plus un."""
    while isinstance(node, dict) and "$ref" in node:
        file, _, pointer = node["$ref"].partition("#")
        target = COMMON if file == "common.yaml" else document
        node = target
        for part in pointer.strip("/").split("/"):
            node = node[part]
        document = target
    return node


# --- Paramètres de requête ---------------------------------------------------------------------


def invalid_values(schema: dict) -> list[object]:
    """Des valeurs que le schéma refuse, une par contrainte déclarée."""
    values: list[object] = []
    kind = schema.get("type")
    if "enum" in schema:
        values.append("zz-hors-enumeration" if kind == "string" else 7919)
    if "minimum" in schema:
        values.append(schema["minimum"] - 1)
    if "maximum" in schema:
        values.append(schema["maximum"] + 1)
    if "minLength" in schema and schema["minLength"] > 0:
        values.append("a" * (schema["minLength"] - 1))
    if "maxLength" in schema:
        values.append("a" * (schema["maxLength"] + 1))
    if "pattern" in schema:
        candidate = "!! pas conforme !!"
        assert not re.search(schema["pattern"], candidate)
        values.append(candidate)
    if kind == "integer":
        values.append("abc")
    if kind == "boolean":
        values.append("peut-etre")
    return values


def query_parameters() -> list[tuple[str, str, str, dict]]:
    found = []
    for method, path in IMPLEMENTED:
        document = operation_document(method, path)
        item = document["paths"][path]
        raw = [*item.get("parameters", []), *item[method].get("parameters", [])]
        for parameter in raw:
            parameter = deref(parameter, document)
            if parameter["in"] == "query":
                found.append(
                    (method, path, parameter["name"], deref(parameter["schema"], document))
                )
    return found


QUERY = query_parameters()
INVALID_QUERY = [
    (method, path, name, value)
    for method, path, name, schema in QUERY
    for value in invalid_values(schema)
]
INVALID_QUERY_IDS = [f"{m.upper()} {p} {n}={str(v)[:12]!r}" for m, p, n, v in INVALID_QUERY]


def test_the_contract_declares_query_parameters_with_bounds_to_test():
    names = {name for _, _, name, _ in QUERY}
    assert {"limit", "cursor", "window_size_s", "intersection_id"} <= names
    assert len(INVALID_QUERY) >= 10


@pytest.mark.parametrize(("method", "path", "name", "value"), INVALID_QUERY, ids=INVALID_QUERY_IDS)
def test_a_query_parameter_outside_the_contract_bounds_is_refused_with_422(
    scene, method, path, name, value
):
    response = scene.request(method, path, role=Role.ADMIN, params={name: value})
    body = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert f"query.{name}" in [item["field"] for item in body["errors"]]


def boundary_values(schema: dict) -> list[object]:
    values: list[object] = []
    if "minimum" in schema:
        values.append(schema["minimum"])
    if "maximum" in schema:
        values.append(schema["maximum"])
    if "maxLength" in schema and "pattern" not in schema:
        values.append("a" * schema["maxLength"])
    values.extend(schema.get("enum", []))
    return values


# Un curseur est opaque : sa longueur maximale est valide, un contenu inventé ne l'est pas.
VALID_QUERY = [
    (method, path, name, value)
    for method, path, name, schema in QUERY
    if name != "cursor"
    for value in boundary_values(schema)
]
VALID_QUERY_IDS = [f"{m.upper()} {p} {n}={str(v)[:12]!r}" for m, p, n, v in VALID_QUERY]


@pytest.mark.parametrize(("method", "path", "name", "value"), VALID_QUERY, ids=VALID_QUERY_IDS)
def test_a_query_parameter_on_a_contract_bound_is_not_refused(scene, method, path, name, value):
    response = scene.request(method, path, role=Role.ADMIN, params={name: value})
    fields = [item["field"] for item in response.json().get("errors", [])]
    assert f"query.{name}" not in fields, response.text


# --- Corps de requête ---------------------------------------------------------------------------

BODIES = {
    ("post", LOGIN): {"username": "operateur1", "password": PASSWORD},
    ("post", USERS): {
        "username": "nouveau",
        "password": "un-mot-de-passe-long",
        "role": "viewer",
    },
}


def request_schema(method: str, path: str) -> dict:
    document = operation_document(method, path)
    body = document["paths"][path][method]["requestBody"]["content"]["application/json"]
    return deref(body["schema"], document)


def invalid_bodies() -> list[tuple[str, str, str, dict]]:
    cases = []
    for (method, path), valid in BODIES.items():
        schema = request_schema(method, path)
        document = operation_document(method, path)
        for name, spec in schema["properties"].items():
            spec = deref(spec, document)
            for value in [*invalid_values(spec), 12345, ["liste"], {"objet": 1}, None]:
                cases.append((method, path, name, valid | {name: value}))
        for name in schema["required"]:
            cases.append((method, path, name, {k: v for k, v in valid.items() if k != name}))
    return cases


INVALID_BODIES = invalid_bodies()
BODY_IDS = [f"{m.upper()} {p} {n} #{i}" for i, (m, p, n, _) in enumerate(INVALID_BODIES)]


@pytest.mark.parametrize(("method", "path", "name", "body"), INVALID_BODIES, ids=BODY_IDS)
def test_a_body_field_outside_the_contract_is_refused_with_422(scene, method, path, name, body):
    response = scene.request(method, path, role=Role.ADMIN, json=body)
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert f"body.{name}" in [item["field"] for item in problem["errors"]]


@pytest.mark.parametrize(("method", "path"), sorted(BODIES), ids=lambda value: str(value))
def test_a_body_with_a_field_the_contract_does_not_declare_is_refused(scene, method, path):
    assert request_schema(method, path)["additionalProperties"] is False
    body = BODIES[(method, path)] | {"champ_inconnu": 1}
    response = scene.request(method, path, role=Role.ADMIN, json=body)
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["errors"] == [{"field": "body.champ_inconnu", "message": "Champ non prévu."}]


@pytest.mark.parametrize(("method", "path"), sorted(BODIES), ids=lambda value: str(value))
def test_a_body_on_the_contract_bounds_is_not_refused_for_validation(scene, method, path):
    schema = request_schema(method, path)
    document = operation_document(method, path)
    for name, spec in schema["properties"].items():
        spec = deref(spec, document)
        for value in boundary_values(spec):
            body = BODIES[(method, path)] | {name: value}
            if name == "username" and method == "post" and path == USERS:
                body[name] = str(value)  # le motif n'admet que des minuscules
            response = scene.request(method, path, role=Role.ADMIN, json=body)
            fields = [item["field"] for item in response.json().get("errors", [])]
            assert f"body.{name}" not in fields, (name, value, response.text)


# --- Propriétés d'ensemble ----------------------------------------------------------------------


def test_every_invalid_field_of_a_request_is_listed_together(scene):
    response = scene.request(
        "post", USERS, role=Role.ADMIN, json={"username": "A", "password": "court", "role": "root"}
    )
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["detail"] == "3 champs invalides."
    assert [item["field"] for item in problem["errors"]] == [
        "body.username",
        "body.password",
        "body.role",
    ]


def test_one_invalid_field_is_announced_in_the_singular(scene):
    response = scene.request("get", USERS, role=Role.ADMIN, params={"limit": 0})
    assert assert_problem(response, 422, {"VALIDATION_ERROR"})["detail"] == "1 champ invalide."


def test_the_value_typed_by_the_caller_is_never_in_the_response(scene):
    secret = "-".join(
        ["saisie", "par", "l", "appelant", "9f3a"]
    )  # assemblée : ce n'est pas une clé
    for body in (  # chacune est invalide pour la connexion comme pour la création de compte
        {"username": "ab", "password": secret},
        {"username": secret, "password": "x", "inconnu": secret},
        {"username": "alice", "password": secret, "role": secret},
        {"username": secret * 20, "password": secret},
    ):
        for route in (LOGIN, USERS):
            response = scene.request("post", route, role=Role.ADMIN, json=body)
            assert response.status_code == 422
            assert secret not in response.text


def test_the_query_string_value_is_not_repeated_either(scene):
    response = scene.request("get", USERS, role=Role.ADMIN, params={"limit": "valeur-saisie-7c1"})
    assert response.status_code == 422
    assert "valeur-saisie-7c1" not in response.text


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"{oups", "application/json"),
        (b"", "application/json"),
        (b"[]", "application/json"),
        (b"null", "application/json"),
        (b'"texte"', "application/json"),
        (b"\xff\xfe", "application/json"),
        (b'{"username": "alice"', "application/json"),
        (b"username=alice", "application/x-www-form-urlencoded"),
        (b"{}", "text/plain"),
    ],
    ids=[
        "JSON cassé",
        "vide",
        "liste",
        "null",
        "texte",
        "octets",
        "tronqué",
        "formulaire",
        "texte brut",
    ],
)
def test_a_body_that_cannot_be_read_is_a_422_not_a_crash(scene, content, content_type):
    admin = scene.token(Role.ADMIN) | {"Content-Type": content_type}
    response = scene.client.post(USERS, headers=admin, content=content)
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["errors"], "au moins un champ est désigné"
    assert not any("input" in str(item) for item in problem["errors"])


def test_an_unreadable_json_designates_the_body_not_a_character_position(scene):
    admin = scene.token(Role.ADMIN) | {"Content-Type": "application/json"}
    response = scene.client.post(USERS, headers=admin, content=b"{oups")
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["errors"] == [{"field": "body", "message": "JSON invalide."}]


def test_without_a_token_the_caller_does_not_learn_the_input_rules(scene):
    response = scene.client.post(USERS, json={"username": "x"})
    assert_problem(response, 401, {"UNAUTHENTICATED"})
    assert "errors" not in response.json()
    response = scene.client.get(USERS, params={"limit": 0})
    assert_problem(response, 401, {"UNAUTHENTICATED"})


def test_with_an_insufficient_role_the_caller_does_not_learn_the_input_rules(scene):
    viewer = scene.token(Role.VIEWER)
    response = scene.client.post(USERS, headers=viewer, json={"username": "x"})
    assert_problem(response, 403, {"FORBIDDEN"})
    assert "errors" not in response.json()
    response = scene.client.get(USERS, headers=viewer, params={"limit": 0})
    assert_problem(response, 403, {"FORBIDDEN"})


def test_the_login_validates_before_it_looks_for_the_account(scene):
    response = scene.client.post(LOGIN, json={"username": "inconnu"})
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["errors"] == [{"field": "body.password", "message": "Champ obligatoire."}]


def test_a_path_identifier_that_is_not_a_uuid_is_a_422_naming_the_path(scene):
    admin = scene.token(Role.ADMIN)
    response = scene.client.get(f"{USERS}/{UNKNOWN_ID[:-1]}", headers=admin)
    problem = assert_problem(response, 422, {"VALIDATION_ERROR"})
    assert problem["errors"] == [{"field": "path.user_id", "message": "Identifiant UUID attendu."}]
