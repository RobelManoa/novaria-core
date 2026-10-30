"""Messages de validation en français, sans la valeur saisie (BE-04) : corps Problem."""

import pytest

from app.core.errors import french_message


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
        ({"type": "quelque_chose_d_inedit"}, "Valeur invalide."),
    ],
)
def test_a_validation_error_is_explained_in_french(erreur, message):
    assert french_message(erreur) == message


def test_the_value_that_was_typed_is_never_repeated_in_the_message():
    erreur = {"type": "string_too_short", "input": "mot-de-passe-secret", "ctx": {"min_length": 12}}
    assert "secret" not in french_message(erreur)
