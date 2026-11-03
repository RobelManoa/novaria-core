"""Middleware d'audit : qui, quoi, quand, pour chaque appel de l'API (BE-05).

Pur ASGI, comme `CorrelationMiddleware`, et placé **à l'intérieur** de lui pour retrouver
l'identifiant de corrélation. Il ne lit ni le corps, ni les en-têtes, ni la chaîne de requête : il
ne peut donc pas écrire un secret qu'il n'a pas vu. L'appelant est identifié par la dépendance
d'authentification (`request.state.actor`). L'écriture se fait après l'envoi de la réponse, dans un
fil séparé : MongoDB lent ou éteint ne ralentit pas le client. Règles : `app/services/audit.py`.
"""

import re
import time
from datetime import UTC, datetime

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logs import correlation_id_var
from app.db.observer import get_observer
from app.services.audit import HEALTH_PATH, UNMATCHED, Observer, RequestEvent


def compile_templates(templates: list[str]) -> list[tuple[re.Pattern, str]]:
    """Modèles de route, les plus précis d'abord (`/indicators/latest` avant `/indicators/{id}`)."""
    ordered = sorted(templates, key=lambda template: template.count("{"))
    return [(re.compile(re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(t)) + "$"), t) for t in ordered]


def match_template(path: str, compiled: list[tuple[re.Pattern, str]]) -> str:
    return next((template for pattern, template in compiled if pattern.match(path)), UNMATCHED)


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        status = 500

        async def send_and_keep_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_keep_status)
        finally:
            observer = self.observer_for(scope)
            if observer is not None:
                event = self.event_from(
                    scope, status, started_at, (time.perf_counter() - started) * 1000
                )
                if event is not None:
                    await anyio.to_thread.run_sync(observer.observe, event)

    @staticmethod
    def observer_for(scope: Scope) -> Observer | None:
        """L'observateur posé sur l'application (tests), sinon celui de la configuration."""
        application = scope.get("app")
        return getattr(getattr(application, "state", None), "observer", None) or get_observer()

    @staticmethod
    def event_from(
        scope: Scope, status: int, started_at: datetime, duration_ms: float
    ) -> RequestEvent | None:
        application = scope["app"]
        compiled = getattr(application.state, "audit_templates", None)
        if compiled is None:
            compiled = application.state.audit_templates = compile_templates(
                list(application.openapi()["paths"])
            )
        path = scope["path"]
        if path == HEALTH_PATH:
            return None  # la sonde de Docker n'est ni auditée ni comptée
        state = scope.get("state") or {}
        return RequestEvent(
            method=scope["method"],
            template=match_template(path, compiled),
            status=status,
            started_at=started_at,
            duration_ms=duration_ms,
            correlation_id=correlation_id_var.get(),
            actor=state.get("actor"),
            role=state.get("role"),
            path_params=dict(scope.get("path_params") or {}),
        )
