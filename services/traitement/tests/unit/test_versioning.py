"""Règles de version et en-têtes de dépréciation (BE-06), sans application."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import Response

from app.core.versioning import deprecated, unsupported_version

SINCE = datetime(2027, 1, 15, 8, 0, tzinfo=UTC)
SUNSET = datetime(2027, 7, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("path", "version"),
    [
        ("/api/v2/users", "v2"),
        ("/api/v2", "v2"),
        ("/api/v0/", "v0"),
        ("/api/v10/health", "v10"),
        ("/api/v01/users", "v01"),
        ("/api/v999999/x", "v999999"),
    ],
)
def test_an_unpublished_version_is_recognised(path, version):
    assert unsupported_version(path) == version


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users",
        "/api/v1",
        "/api/v1/",
        "/api/V2/users",
        "/api/v2x/users",
        "/api/users",
        "/api",
        "/x/api/v2/users",
        "/api/v1234567/users",
        "",
    ],
)
def test_a_published_version_or_a_path_without_version_is_not_flagged(path):
    assert unsupported_version(path) is None


def headers_of(**kwargs) -> dict[str, str]:
    response = Response()
    deprecated(**kwargs)(response)
    return dict(response.headers)


def test_the_deprecation_header_is_the_announcement_date_in_seconds():
    assert headers_of(since=SINCE)["deprecation"] == f"@{int(SINCE.timestamp())}"


def test_without_a_sunset_date_only_the_deprecation_header_is_set():
    assert "sunset" not in headers_of(since=SINCE)


def test_the_sunset_header_is_an_http_date_in_gmt():
    assert headers_of(since=SINCE, sunset=SUNSET)["sunset"] == "Thu, 01 Jul 2027 00:00:00 GMT"


def test_dates_given_in_another_zone_are_converted_to_utc():
    paris = timezone(timedelta(hours=2))
    local = SUNSET.astimezone(paris)
    assert headers_of(since=SINCE, sunset=local)["sunset"] == "Thu, 01 Jul 2027 00:00:00 GMT"


def test_a_date_without_a_zone_is_refused():
    with pytest.raises(ValueError, match="fuseau"):
        deprecated(since=datetime(2027, 1, 15))
    with pytest.raises(ValueError, match="fuseau"):
        deprecated(since=SINCE, sunset=datetime(2027, 7, 1))


def test_a_removal_before_the_announcement_is_refused():
    with pytest.raises(ValueError, match="précéder"):
        deprecated(since=SUNSET, sunset=SINCE)
