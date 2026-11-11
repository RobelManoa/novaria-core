"""Les routes de rapports respectent le contrat OpenAPI du traitement (FE-06).

`GET /api/v1/reports` liste les rapports que le robot a déposés ; `GET /api/v1/reports/{id}/content`
rend le PDF. Les réponses sont validées contre `Report` et `ReportPage` du contrat.
"""

import hashlib
import uuid
from datetime import timedelta

import pytest

from app.api.v1.reports import get_report_service
from app.core.config import get_settings
from app.main import app
from app.models import Role
from tests.fakes import bearer
from tests.openapi_checks import PROBLEM, TRAITEMENT, check, schema
from tests.reports_data import BASE, PDF, deposit

LIST = "/api/v1/reports"
REPORT = schema("Report", "traitement")
PAGE = schema("ReportPage", "traitement")


def content(report_id) -> str:
    return f"{LIST}/{report_id}/content"


@pytest.fixture
def viewer(repo):
    return bearer(repo.make("lecteur", Role.VIEWER))


def test_the_service_declares_the_two_operations_of_the_contract():
    paths = app.openapi()["paths"]
    for path, operation_id in (
        (LIST, "listReports"),
        (f"{LIST}/{{report_id}}/content", "downloadReport"),
    ):
        contract = TRAITEMENT["paths"][path]["get"]
        assert contract["operationId"] == operation_id
        assert paths[path]["get"]["x-required-role"] == contract["x-required-role"] == "viewer"
        assert set(paths[path]["get"]["responses"]) == set(contract["responses"])


def test_the_list_parameters_have_the_bounds_of_the_contract():
    declared = {p["name"]: p["schema"] for p in app.openapi()["paths"][LIST]["get"]["parameters"]}
    assert (declared["limit"]["minimum"], declared["limit"]["maximum"]) == (1, 500)
    assert declared["limit"]["default"] == 100


def test_an_empty_folder_gives_an_empty_page(client, viewer):
    response = client.get(LIST, headers=viewer)
    assert (response.status_code, response.json()) == (200, {"items": [], "next_cursor": None})
    check(response.json(), PAGE)


def test_a_deposited_report_appears_in_the_list_with_its_metadata(client, viewer, reports_dir):
    report_id = deposit(
        reports_dir, title="Rapport hebdomadaire", file_name="rapport-2026-10-26.pdf"
    )
    body = client.get(LIST, headers=viewer).json()
    check(body, PAGE)
    (item,) = body["items"]
    assert item["report_id"] == str(report_id)
    assert item["title"] == "Rapport hebdomadaire"
    assert item["file_name"] == "rapport-2026-10-26.pdf"
    assert item["size_bytes"] == len(PDF)
    assert item["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert item["generated_at"] == "2026-10-26T06:00:00Z"


def test_dates_are_utc_with_a_z_whatever_the_offset_of_the_file(client, viewer, reports_dir):
    deposit(reports_dir, metadata={"generated_at": "2026-10-26T08:00:00+02:00"})
    item = client.get(LIST, headers=viewer).json()["items"][0]
    assert item["generated_at"] == "2026-10-26T06:00:00Z"
    check(item, REPORT)


def test_the_most_recent_report_comes_first(client, viewer, reports_dir):
    old = deposit(reports_dir, generated_at=BASE)
    new = deposit(reports_dir, generated_at=BASE + timedelta(days=7))
    assert [i["report_id"] for i in client.get(LIST, headers=viewer).json()["items"]] == [
        str(new),
        str(old),
    ]


def test_pages_are_read_with_the_cursor_until_the_last(client, viewer, reports_dir):
    ids = [deposit(reports_dir, generated_at=BASE + timedelta(days=d)) for d in range(5)]
    seen, cursor = [], None
    for _ in range(5):
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = client.get(LIST, headers=viewer, params=params).json()
        check(body, PAGE)
        seen += [i["report_id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [str(i) for i in reversed(ids)]


def test_an_unknown_cursor_is_a_422_that_names_the_field(client, viewer):
    response = client.get(LIST, headers=viewer, params={"cursor": "inconnu"})
    assert response.status_code == 422
    check(response.json(), PROBLEM)
    assert response.json()["errors"][0]["field"] == "query.cursor"


def test_the_pdf_is_downloaded_byte_for_byte_with_its_file_name(client, viewer, reports_dir):
    report_id = deposit(reports_dir, file_name="rapport-2026-10-26.pdf")
    response = client.get(content(report_id), headers=viewer)
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"] == 'attachment; filename="rapport-2026-10-26.pdf"'
    )
    assert int(response.headers["content-length"]) == len(PDF)


def test_an_unknown_report_is_a_404_problem(client, viewer):
    response = client.get(content(uuid.uuid4()), headers=viewer)
    assert response.status_code == 404
    check(response.json(), PROBLEM)
    assert response.json()["code"] == "NOT_FOUND"


def test_a_report_without_metadata_cannot_be_downloaded(client, viewer, reports_dir):
    stray = uuid.uuid4()
    (reports_dir / f"{stray}.pdf").write_bytes(PDF)
    assert client.get(content(stray), headers=viewer).status_code == 404


def test_an_identifier_that_is_not_a_uuid_is_a_422_not_a_file_lookup(client, viewer):
    for bad in ("pas-un-uuid", "12345", "00000000-0000-0000-0000-00000000000g"):
        response = client.get(f"{LIST}/{bad}/content", headers=viewer)
        assert response.status_code == 422, bad
        check(response.json(), PROBLEM)


def test_a_path_that_climbs_out_of_the_folder_is_never_served(client, viewer, reports_dir):
    deposit(reports_dir)
    for bad in ("..%2F..%2Fetc%2Fpasswd", "../../etc/passwd", "%2e%2e%2fsecret"):
        response = client.get(f"{LIST}/{bad}/content", headers=viewer)
        assert response.status_code in (404, 422), bad
        assert b"root:" not in response.content


def test_a_corrupted_pdf_is_a_500_that_does_not_leak_the_path(client, viewer, reports_dir):
    report_id = deposit(reports_dir)
    (reports_dir / f"{report_id}.pdf").write_bytes(b"autre chose")
    response = client.get(content(report_id), headers=viewer)
    assert response.status_code == 500
    assert "empreinte" in response.json()["detail"]
    assert str(reports_dir) not in response.text
    check(response.json(), PROBLEM)


def test_both_routes_need_a_token(client, reports_dir):
    report_id = deposit(reports_dir)
    for url in (LIST, content(report_id)):
        response = client.get(url)
        assert (response.status_code, response.json()["code"]) == (401, "UNAUTHENTICATED")


def test_the_routes_only_read(client, viewer, reports_dir):
    report_id = deposit(reports_dir)
    for url in (LIST, content(report_id)):
        for method in ("post", "put", "delete", "patch"):
            assert getattr(client, method)(url, headers=viewer).status_code == 405
    assert len(list(reports_dir.iterdir())) == 2


def test_without_a_configured_folder_the_answer_is_a_503_after_validation(
    client, viewer, monkeypatch
):
    app.dependency_overrides.pop(get_report_service)
    monkeypatch.delenv("REPORTS_DIR", raising=False)
    get_settings.cache_clear()
    response = client.get(LIST, headers=viewer)
    assert response.status_code == 503
    assert response.json()["code"] == "UPSTREAM_UNAVAILABLE"
    assert client.get(LIST, headers=viewer, params={"limit": 0}).status_code == 422


def test_the_folder_comes_from_the_environment(client, viewer, reports_dir, monkeypatch):
    app.dependency_overrides.pop(get_report_service)
    report_id = deposit(reports_dir)
    monkeypatch.setenv("REPORTS_DIR", str(reports_dir))
    get_settings.cache_clear()
    try:
        items = client.get(LIST, headers=viewer).json()["items"]
    finally:
        get_settings.cache_clear()
    assert [i["report_id"] for i in items] == [str(report_id)]


def test_a_download_is_audited_like_the_other_reads(client, viewer, reports_dir, journal):
    report_id = deposit(reports_dir)
    assert client.get(content(report_id), headers=viewer).status_code == 200
    (entry,) = journal.entries
    assert entry["action"] == f"GET {LIST}/{{report_id}}/content"
    assert (entry["outcome"], entry["details"]["status"]) == ("ok", 200)
