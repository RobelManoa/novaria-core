"""Journaux JSON et identifiant de corrélation : même code dans tous les services (collecte).

Chaque ligne écrite sur la sortie standard est un objet JSON qui porte l'identifiant de corrélation
de la requête en cours. Il relie les journaux de plusieurs services (EXG-NFR-06) : il est lu dans
l'en-tête `X-Correlation-ID`, généré s'il manque, puis renvoyé dans la réponse.
"""

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "X-Correlation-ID"
# Une valeur reçue n'est reprise que si elle est sobre : sinon un client écrirait n'importe quoi
# dans les journaux.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_RESERVED = {"ts", "level", "service", "logger", "message", "correlation_id", "exception"}

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par enregistrement. Champs ajoutés par `extra={"fields": {...}}`."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        moment = datetime.fromtimestamp(record.created, UTC)
        entry: dict[str, object] = {
            "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update({key: value for key, value in fields.items() if key not in _RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class _StdoutHandler(logging.StreamHandler):
    """Écrit sur la sortie standard *courante* (comme le gestionnaire d'erreurs standard)."""

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout


def configure_logging(service: str, level: str = "INFO") -> None:
    """Remplace les gestionnaires par un seul, au format JSON ; uvicorn passe par lui."""
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        journal = logging.getLogger(name)
        journal.handlers = []
        journal.propagate = True
    # Les requêtes sont journalisées une seule fois, par CorrelationMiddleware (avec l'identifiant).
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False


class CorrelationMiddleware:
    """Pose l'identifiant de corrélation, l'ajoute à la réponse et journalise chaque requête.

    La query string n'est jamais journalisée : elle peut porter un jeton.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = Headers(scope=scope).get(CORRELATION_HEADER, "")
        correlation_id = received if _VALID_ID.fullmatch(received) else str(uuid.uuid4())
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        status = 500

        async def send_with_header(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            logging.getLogger("app.access").info(
                "requête traitée",
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            correlation_id_var.reset(token)
