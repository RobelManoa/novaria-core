"""Le lecteur du réseau est un seul fichier : celui du service, que l'entraînement charge."""

from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[2]
COPIE = SERVICE / "app" / "forecast" / "reseau.py"
CHARGEUR = SERVICE.parents[1] / "ml" / "src" / "registre" / "lecteur_reseau.py"


def test_the_reader_needs_nothing_but_numpy():
    imports = {
        line.split()[1].split(".")[0]
        for line in COPIE.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imports <= {"json", "math", "dataclasses", "numpy"}


@pytest.mark.skipif(not CHARGEUR.is_file(), reason="le dossier ml/ est absent ici")
def test_the_training_side_loads_this_file_and_does_not_hold_a_second_copy():
    code = CHARGEUR.read_text(encoding="utf-8")
    assert "app" in code and "forecast" in code and "reseau.py" in code
    assert "class ModeleReseau" not in code and "def creneau" not in code
