"""Le lecteur du service est la copie, octet pour octet, de celui de l'entraînement (IA-16)."""

from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[2]
SOURCE = SERVICE.parents[1] / "ml" / "src" / "registre" / "lecteur_reseau.py"
COPIE = SERVICE / "app" / "forecast" / "reseau.py"


@pytest.mark.skipif(not SOURCE.is_file(), reason="le dossier ml/ n'est pas dans cet environnement")
def test_the_service_reader_is_the_training_reader():
    assert COPIE.read_bytes() == SOURCE.read_bytes(), (
        "ml/src/registre/lecteur_reseau.py a changé : recopier le fichier dans "
        "services/traitement/app/forecast/reseau.py"
    )


def test_the_service_reader_needs_nothing_but_numpy():
    imports = {
        line.split()[1].split(".")[0]
        for line in COPIE.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imports <= {"json", "math", "dataclasses", "numpy"}
