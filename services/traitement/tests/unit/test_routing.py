"""Modèles de route et méthodes permises (BE-05, BE-06), sans application réelle."""

from types import SimpleNamespace

from app.core.routing import allowed_methods, compile_templates, compiled_templates, match_template

PATHS = {
    "/api/v1/users": {"get": {}, "post": {}},
    "/api/v1/users/{user_id}": {"get": {}},
    "/api/v1/indicators/{indicator_id}": {"get": {}, "delete": {}},
    "/api/v1/indicators/latest": {"get": {}},
}


def application(paths=None):
    return SimpleNamespace(
        state=SimpleNamespace(), openapi=lambda: {"paths": PATHS if paths is None else paths}
    )


def scope(path: str, app=None) -> dict:
    return {"path": path, "app": app or application()}


# --- Correspondance chemin → modèle -----------------------------------------------------------


def test_a_path_is_matched_to_its_template():
    compiled = compile_templates(PATHS)
    assert match_template("/api/v1/users", compiled) == "/api/v1/users"
    assert match_template("/api/v1/users/abc", compiled) == "/api/v1/users/{user_id}"


def test_a_path_parameter_matches_one_segment_only():
    compiled = compile_templates(PATHS)
    assert match_template("/api/v1/users/abc/def", compiled) is None
    assert match_template("/api/v1/users/", compiled) is None


def test_the_most_precise_template_wins_whatever_the_declaration_order():
    for order in (list(PATHS), list(reversed(PATHS))):
        compiled = compile_templates(order)
        assert match_template("/api/v1/indicators/latest", compiled) == "/api/v1/indicators/latest"
        assert (
            match_template("/api/v1/indicators/x", compiled) == "/api/v1/indicators/{indicator_id}"
        )


def test_an_unknown_path_has_no_template():
    assert match_template("/api/v1/nope", compile_templates(PATHS)) is None


def test_a_dot_in_a_template_is_not_a_wildcard():
    compiled = compile_templates(["/v1.0/items"])
    assert match_template("/v1.0/items", compiled) == "/v1.0/items"
    assert match_template("/v1x0/items", compiled) is None


def test_the_templates_are_compiled_once_and_kept_on_the_application():
    app = application()
    first = compiled_templates(app)
    assert compiled_templates(app) is first
    assert app.state.route_templates is first


# --- Méthodes permises --------------------------------------------------------------------------


def test_all_the_methods_of_a_path_are_listed_in_order():
    assert allowed_methods(scope("/api/v1/users")) == ["GET", "POST"]


def test_the_methods_follow_the_most_precise_route():
    assert allowed_methods(scope("/api/v1/indicators/latest")) == ["GET"]
    assert allowed_methods(scope("/api/v1/indicators/autre")) == ["DELETE", "GET"]


def test_an_unknown_path_has_no_method():
    assert allowed_methods(scope("/api/v1/nope")) == []
    assert allowed_methods(scope("/api/v1/users/")) == []


def test_without_an_application_there_is_nothing_to_say():
    assert allowed_methods({"path": "/api/v1/users"}) == []
