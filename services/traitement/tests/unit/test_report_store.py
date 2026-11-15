"""Lecture des rapports déposés par le robot (FE-06) : tri, validité, pagination, intégrité."""

import json
import uuid
from datetime import timedelta

import pytest

from app.services.reports import (
    FileReportStore,
    InvalidCursor,
    ReportCorrupted,
    ReportService,
    decode_cursor,
    encode_cursor,
)
from tests.reports_data import BASE, PDF, deposit


@pytest.fixture
def store(tmp_path):
    return FileReportStore(tmp_path)


def test_a_missing_or_empty_directory_has_no_report(tmp_path):
    assert FileReportStore(tmp_path / "absent").list_all() == []
    assert FileReportStore(tmp_path).list_all() == []


def test_reports_come_out_most_recent_first_then_by_identifier(tmp_path, store):
    older = deposit(tmp_path, generated_at=BASE)
    newer = deposit(tmp_path, generated_at=BASE + timedelta(days=7))
    low, high = sorted([uuid.uuid4(), uuid.uuid4()], key=str)
    deposit(tmp_path, report_id=high, generated_at=BASE + timedelta(days=3))
    deposit(tmp_path, report_id=low, generated_at=BASE + timedelta(days=3))
    ids = [item.report_id for item in store.list_all()]
    assert ids == [newer, low, high, older]


def test_a_report_without_its_pdf_or_without_its_metadata_is_not_listed(tmp_path, store):
    complete = deposit(tmp_path)
    no_pdf = deposit(tmp_path)
    (tmp_path / f"{no_pdf}.pdf").unlink()
    (tmp_path / f"{uuid.uuid4()}.pdf").write_bytes(PDF)  # PDF sans métadonnées
    assert [item.report_id for item in store.list_all()] == [complete]
    assert store.open(no_pdf) is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"file_name": "../secret.pdf"},
        {"file_name": 'a"b.pdf'},
        {"file_name": "a/b.pdf"},
        {"sha256": "ABC"},
        {"sha256": "0" * 63},
        {"title": ""},
        {"content_type": "text/html"},
        {"size_bytes": -1},
        {"period_start": "2026-10-19T00:00:00"},
        {"unknown_field": 1},
    ],
    ids=lambda m: next(iter(m)) + "=" + str(next(iter(m.values())))[:12],
)
def test_invalid_metadata_is_ignored_and_never_listed(tmp_path, store, metadata):
    valid = deposit(tmp_path)
    deposit(tmp_path, metadata=metadata)
    assert [item.report_id for item in store.list_all()] == [valid]


def test_unreadable_metadata_and_a_file_named_after_another_report_are_ignored(tmp_path, store):
    valid = deposit(tmp_path)
    (tmp_path / f"{uuid.uuid4()}.json").write_text("{pas du json", encoding="utf-8")
    other = deposit(tmp_path)
    (tmp_path / f"{other}.json").rename(tmp_path / f"{uuid.uuid4()}.json")  # nom ≠ report_id
    assert [item.report_id for item in store.list_all()] == [valid]


def test_a_stray_file_without_a_json_name_is_ignored(tmp_path, store):
    valid = deposit(tmp_path)
    (tmp_path / "notes.txt").write_text("rien", encoding="utf-8")
    assert [item.report_id for item in store.list_all()] == [valid]


# --- Ouverture et intégrité -------------------------------------------------------------------


def test_opening_a_report_gives_its_metadata_and_the_path_of_its_pdf(tmp_path, store):
    report_id = deposit(tmp_path, file_name="rapport.pdf")
    report = store.open(report_id)
    assert report is not None
    assert report.path == tmp_path / f"{report_id}.pdf"
    assert report.metadata.file_name == "rapport.pdf"
    assert report.path.read_bytes() == PDF


def test_an_unknown_report_is_none(store):
    assert store.open(uuid.uuid4()) is None


def test_a_pdf_that_changed_after_the_deposit_is_refused(tmp_path, store):
    report_id = deposit(tmp_path)
    (tmp_path / f"{report_id}.pdf").write_bytes(PDF.replace(b"1.4", b"1.5"))  # même taille
    with pytest.raises(ReportCorrupted):
        store.open(report_id)


def test_a_truncated_pdf_is_refused(tmp_path, store):
    report_id = deposit(tmp_path)
    (tmp_path / f"{report_id}.pdf").write_bytes(PDF[:10])
    with pytest.raises(ReportCorrupted):
        store.open(report_id)


def test_the_path_of_a_pdf_never_leaves_the_directory(tmp_path, store):
    outside = tmp_path.parent / "dehors.pdf"
    outside.write_bytes(PDF)
    report_id = deposit(tmp_path, metadata={"file_name": "../dehors.pdf"})  # refusé à la lecture
    assert store.open(report_id) is None


# --- Pagination --------------------------------------------------------------------------------


@pytest.fixture
def five(tmp_path):
    for day in range(5):
        deposit(tmp_path, generated_at=BASE + timedelta(days=day))
    return ReportService(FileReportStore(tmp_path))


def test_pages_follow_each_other_without_gap_or_duplicate(five):
    seen, cursor = [], None
    while True:
        page = five.list_page(limit=2, cursor=cursor)
        seen += [item.report_id for item in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 5
    assert seen == [item.report_id for item in five.list_page(limit=100).items]


def test_the_last_page_has_no_cursor_and_a_full_last_page_does_not_invent_one(five):
    assert five.list_page(limit=5).next_cursor is None
    assert five.list_page(limit=4).next_cursor is not None


def test_a_cursor_round_trips_and_garbage_is_refused(five):
    first = five.list_page(limit=1).items[0]
    assert decode_cursor(encode_cursor(first))[1] == str(first.report_id)
    for garbage in ("pas-un-curseur", "e30", "WzEsMl0", encode_cursor(first)[:-3]):
        with pytest.raises(InvalidCursor):
            five.list_page(cursor=garbage)


def test_a_cursor_with_a_naive_date_is_refused(five):
    from base64 import urlsafe_b64encode

    raw = json.dumps(["2026-10-20T00:00:00", str(uuid.uuid4())]).encode()
    with pytest.raises(InvalidCursor):
        five.list_page(cursor=urlsafe_b64encode(raw).decode().rstrip("="))
