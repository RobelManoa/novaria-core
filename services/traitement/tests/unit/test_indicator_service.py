"""Identifiants d'indicateur, curseur et pagination du service de lecture (BE-04)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.repositories.indicators import IndicatorFilters
from app.services.indicators import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    IndicatorService,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
    make_indicator_id,
    parse_indicator_id,
)
from tests.fakes import START, FakeIndicatorRepository, make_row

EXEMPLE = "run-demo-0001:ROAD_001:60:1792484400000"  # identifiant d'exemple du contrat


def test_the_identifier_of_the_contract_example_is_built_from_its_parts():
    assert make_indicator_id("run-demo-0001", "ROAD_001", 60, START) == EXEMPLE


def test_the_identifier_in_milliseconds_ignores_the_time_zone_of_the_date():
    tokyo = START.astimezone(timezone(timedelta(hours=9)))
    assert make_indicator_id("r", "ROAD_001", 60, tokyo) == make_indicator_id(
        "r", "ROAD_001", 60, START
    )


def test_the_identifier_is_read_back_into_its_parts():
    assert parse_indicator_id(EXEMPLE) == ("run-demo-0001", "ROAD_001", 60, START)


def test_a_run_identifier_with_colons_is_read_from_the_right():
    identifiant = make_indicator_id("a:b:c", "ROAD_012", 300, START)
    assert parse_indicator_id(identifiant) == ("a:b:c", "ROAD_012", 300, START)


@pytest.mark.parametrize(
    "texte",
    [
        "",
        "n-importe-quoi",
        "run:ROAD_001:60",
        ":ROAD_001:60:1792484400000",
        "r:ROAD_1:60:1792484400000",
        "r:road_001:60:1792484400000",
        "r:ROAD_001:61:1792484400000",
        "r:ROAD_001:60:",
        "r:ROAD_001:60:-1",
        "r:ROAD_001:60:1.5",
        "r:ROAD_001:60:1e9",
        "r:ROAD_001:60:١٢٣",
        "r:ROAD_001:60:99999999999999999999999999",
        f"{'r' * 81}:ROAD_001:60:1792484400000",
    ],
)
def test_a_text_that_is_not_an_identifier_is_not_read(texte):
    assert parse_indicator_id(texte) is None


def test_the_longest_run_identifier_is_still_read():
    assert parse_indicator_id(f"{'r' * 80}:ROAD_001:60:0")[0] == "r" * 80


def test_a_cursor_round_trips_the_position_of_the_last_row():
    ligne = make_row(run_id="run:x", road_segment_id="ROAD_007")
    curseur = encode_cursor(ligne)
    assert "=" not in curseur and "+" not in curseur and "/" not in curseur
    assert decode_cursor(curseur) == (START, "ROAD_007", "run:x")


@pytest.mark.parametrize(
    "curseur",
    [
        "",
        "!!!",
        "abc",
        "e30",
        "W10",
        "WyJhIl0",
        "W1sxXSwgMiwgM10",
        "WyIyMDI2LTEwLTIwVDA4OjIwOjAwIiwgIlIiLCAxXQ",
    ],
)
def test_a_cursor_that_was_not_made_by_the_service_is_refused(curseur):
    with pytest.raises(InvalidCursor):
        decode_cursor(curseur)


def test_a_cursor_whose_segment_or_run_is_not_text_is_refused():
    import base64
    import json

    for contenu in (
        ["2026-10-20T08:20:00+00:00", "ROAD_001", 1],
        ["2026-10-20T08:20:00+00:00", 7, "run"],
        ["2026-10-20T08:20:00+00:00", None, None],
    ):
        brut = base64.urlsafe_b64encode(json.dumps(contenu).encode()).decode().rstrip("=")
        with pytest.raises(InvalidCursor):
            decode_cursor(brut)


def test_a_cursor_without_a_time_zone_is_refused():
    import base64
    import json

    brut = json.dumps(["2026-10-20T08:20:00", "ROAD_001", "r"]).encode()
    with pytest.raises(InvalidCursor):
        decode_cursor(base64.urlsafe_b64encode(brut).decode().rstrip("="))


def test_the_limits_are_those_of_the_contract():
    assert (DEFAULT_LIMIT, MAX_LIMIT) == (100, 500)


def service(rows):
    return IndicatorService(FakeIndicatorRepository(rows))


def test_the_service_asks_for_one_more_row_to_know_whether_a_page_follows():
    demandes = []

    class Espion(FakeIndicatorRepository):
        def list_page(self, filters, *, limit, after):
            demandes.append(limit)
            return super().list_page(filters, limit=limit, after=after)

    IndicatorService(Espion([make_row()])).list_page(IndicatorFilters(), limit=7)
    assert demandes == [8]


def test_pages_cover_every_row_once_in_order():
    lignes = [make_row(window_start=START + timedelta(minutes=n)) for n in range(7)]
    vus, curseur = [], None
    while True:
        page = service(lignes).list_page(IndicatorFilters(), limit=3, cursor=curseur)
        vus += [r.window_start for r in page.items]
        curseur = page.next_cursor
        if curseur is None:
            break
    assert vus == sorted((r.window_start for r in lignes), reverse=True)


def test_an_exactly_full_last_page_has_no_cursor():
    lignes = [make_row(window_start=START + timedelta(minutes=n)) for n in range(4)]
    premiere = service(lignes).list_page(IndicatorFilters(), limit=2)
    derniere = service(lignes).list_page(IndicatorFilters(), limit=2, cursor=premiere.next_cursor)
    assert (len(derniere.items), derniere.next_cursor) == (2, None)


def test_an_empty_result_is_one_empty_page():
    page = service([]).list_page(IndicatorFilters())
    assert (page.items, page.next_cursor) == ([], None)


def test_an_unknown_cursor_is_refused_before_reading_anything():
    class Interdit(FakeIndicatorRepository):
        def list_page(self, *_, **__):
            raise AssertionError("aucune lecture avant d'avoir validé le curseur")

    with pytest.raises(InvalidCursor):
        IndicatorService(Interdit()).list_page(IndicatorFilters(), cursor="n-importe-quoi")


def test_get_finds_a_row_by_its_identifier_and_none_otherwise():
    ligne = make_row()
    assert service([ligne]).get(ligne.indicator_id) is ligne
    assert service([ligne]).get("r:ROAD_001:60:1") is None
    assert service([ligne]).get("n-importe-quoi") is None


def test_the_window_start_of_an_identifier_is_in_utc():
    assert parse_indicator_id(EXEMPLE)[3].tzinfo == UTC
    assert parse_indicator_id(EXEMPLE)[3] == datetime(2026, 10, 20, 8, 20, tzinfo=UTC)
