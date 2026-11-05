"""Intergiciel des erreurs imprévues (BE-06) : branchement ASGI, sans application ni base."""

import asyncio
import json

import pytest

from app.core.logs import correlation_id_var
from app.core.unhandled import DETAIL, UnhandledErrorMiddleware


async def run(inner, scope_type="http"):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await UnhandledErrorMiddleware(inner)({"type": scope_type, "method": "GET"}, receive, send)
    return sent


async def fine(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_a_request_that_succeeds_goes_through_untouched():
    sent = asyncio.run(run(fine))
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 204


def test_an_error_before_the_response_becomes_a_500_problem_with_the_correlation_id():
    async def crash(scope, receive, send):
        raise RuntimeError("ne doit pas sortir")

    token = correlation_id_var.set("abc-123")
    try:
        sent = asyncio.run(run(crash))
    finally:
        correlation_id_var.reset(token)
    start, body = sent
    assert start["status"] == 500
    headers = dict(start["headers"])
    assert headers[b"content-type"].startswith(b"application/problem+json")
    assert int(headers[b"content-length"]) == len(body["body"])
    content = json.loads(body["body"])
    assert content == {
        "type": "https://novaria.local/problems/internal-error",
        "title": "Erreur interne",
        "status": 500,
        "code": "INTERNAL_ERROR",
        "detail": DETAIL,
        "correlation_id": "abc-123",
    }
    assert b"ne doit pas sortir" not in body["body"]


def test_the_error_is_logged_with_its_type_and_stack_but_not_its_message(caplog):
    async def crash(scope, receive, send):
        raise ValueError("valeur-secrète-" + "1234")

    asyncio.run(run(crash))
    (record,) = [r for r in caplog.records if r.name == "app.errors"]
    assert record.levelname == "ERROR"
    assert record.fields["error"] == "ValueError"
    assert "crash" in record.fields["trace"]
    assert "valeur-secrète-1234" not in str(record.fields)


def test_after_the_response_started_the_error_propagates_and_no_second_response_is_sent():
    async def late(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("flux interrompu")

    sent: list[dict] = []

    async def go():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await UnhandledErrorMiddleware(late)({"type": "http"}, receive, send)

    with pytest.raises(RuntimeError, match="flux interrompu"):
        asyncio.run(go())
    assert [message["status"] for message in sent] == [200]


def test_a_cancellation_is_not_swallowed():
    async def cancelled(scope, receive, send):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run(cancelled))


def test_other_kinds_of_connection_pass_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])
        raise RuntimeError("laissé tel quel")

    with pytest.raises(RuntimeError):
        asyncio.run(run(inner, scope_type="websocket"))
    assert seen == ["websocket"]
