"""La boucle du service : lecture, traitement, validation des offsets, arrêt, panne."""

import threading

import pytest

from app.flux.ports import PublishFailed, Record
from app.flux.runner import run

from .support import minute_of, slot
from .test_processor import Rig


class ScriptedSource:
    """Rend des lots prévus à l'avance, puis lève `stop` quand ils sont épuisés."""

    def __init__(self, batches: list[list[Record]], stop: threading.Event) -> None:
        self._batches = list(batches)
        self._stop = stop
        self.commits: list[dict[int, int]] = []

    def poll(self, timeout_ms: int = 0) -> list[Record]:
        if not self._batches:
            self._stop.set()
            return []
        return self._batches.pop(0)

    def commit(self, offsets: dict[int, int]) -> None:
        self.commits.append(dict(offsets))


def records(payloads: list[bytes], first_offset: int = 0) -> list[Record]:
    return [Record(b"INT_01", p, 0, first_offset + i) for i, p in enumerate(payloads)]


def test_traite_les_lots_publie_et_valide_les_offsets(tmp_path):
    rig, stop = Rig(), threading.Event()
    beat = tmp_path / "alive"
    source = ScriptedSource([records(minute_of(0)), records([slot(80)], 6)], stop)

    handled = run(rig.processor, source, stop, heartbeat_file=str(beat))

    assert handled == 7
    assert [d["sample_count"] for d in rig.indicators()] == [6]
    assert rig.publisher.flushes >= 2  # accusés attendus avant chaque validation
    assert source.commits and source.commits[-1] == {0: 0}  # la fenêtre ouverte retient l'offset 0
    assert beat.exists()


def test_ne_valide_pas_deux_fois_les_memes_offsets():
    rig, stop = Rig(), threading.Event()
    source = ScriptedSource([records([b"x"]), [], []], stop)

    run(rig.processor, source, stop)

    assert source.commits == [{0: 1}]


def test_une_panne_du_broker_arrete_la_boucle_sans_valider():
    rig, stop = Rig(), threading.Event()
    rig.publisher.fail = True
    source = ScriptedSource([records([b"pas du json"])], stop)

    with pytest.raises(PublishFailed):
        run(rig.processor, source, stop)

    assert source.commits == []


def test_s_arrete_des_que_l_arret_est_demande():
    rig, stop = Rig(), threading.Event()
    stop.set()
    source = ScriptedSource([records([b"x"])], stop)

    assert run(rig.processor, source, stop) == 0
    assert source.commits == []


def test_le_fichier_de_vie_non_ecrit_n_arrete_rien(tmp_path):
    rig, stop = Rig(), threading.Event()
    source = ScriptedSource([records([b"x"])], stop)

    handled = run(rig.processor, source, stop, heartbeat_file=str(tmp_path / "absent" / "alive"))

    assert handled == 1  # la boucle est allée au bout malgré le fichier de vie
