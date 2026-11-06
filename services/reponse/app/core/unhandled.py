"""Erreurs imprévues : un 500 au format `Problem`, sans trace ni détail pour le client (MS-08).

Même mécanisme que le service de traitement (BE-06). Pourquoi un intergiciel et pas
`add_exception_handler(Exception, ...)` : Starlette envoie ce gestionnaire à
`ServerErrorMiddleware`, qui est **à l'extérieur** de `CorrelationMiddleware` ; la réponse partirait
sans `X-Correlation-ID`. Placé juste à l'intérieur de `CorrelationMiddleware`, celui-ci retrouve
l'identifiant.

Le client reçoit seulement `INTERNAL_ERROR` et l'identifiant de corrélation. Le journal reçoit le
type de l'erreur et les **lignes** de la pile, pas le message de l'exception (il pourrait reprendre
une adresse de connexion).
"""

import logging
import traceback

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import INTERNAL_ERROR, PROBLEM_MEDIA_TYPE, ProblemError

DETAIL = "Une erreur interne est survenue. Citez l'identifiant de corrélation pour la signaler."


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_and_remember(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_and_remember)
        except Exception as error:
            logging.getLogger("app.errors").error(
                "erreur interne non gérée",
                extra={
                    "fields": {
                        "error": type(error).__name__,
                        "trace": "".join(traceback.format_tb(error.__traceback__)),
                    }
                },
            )
            if started:
                raise  # l'en-tête est parti : on ne peut plus changer la réponse
            problem = ProblemError(INTERNAL_ERROR, DETAIL)
            response = JSONResponse(
                problem.body(), status_code=problem.kind.status, media_type=PROBLEM_MEDIA_TYPE
            )
            await response(scope, receive, send)
