"""En-têtes de sécurité de toutes les réponses de l'API (BE-08), erreurs comprises.

| En-tête | Effet |
|---|---|
| `X-Content-Type-Options: nosniff` | le navigateur n'interprète pas un JSON comme un script |
| `X-Frame-Options: DENY` | la réponse ne s'affiche dans aucun cadre (clic détourné) |
| `Referrer-Policy: no-referrer` | l'adresse de la page appelante n'est pas transmise |
| `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` | rien n'est chargé |
| `Cache-Control: no-store` sur `/api/v1/auth/` | ni jeton ni identité dans un cache |

La politique de contenu n'est pas posée sur les pages de documentation de FastAPI (`/docs`,
`/redoc`) : elles chargent leurs scripts depuis un CDN et cesseraient de fonctionner. Une valeur
déjà posée par la route n'est jamais remplacée. `Strict-Transport-Security` n'est pas posé ici : le
service parle HTTP à son relais ; l'en-tête appartient au point qui termine TLS (voir le document).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.versioning import API_PREFIX

DOCUMENTATION_PREFIXES = ("/docs", "/redoc")
NO_STORE_PREFIX = f"{API_PREFIX}/auth/"
CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def headers_for(path: str) -> dict[str, str]:
    headers = dict(BASE_HEADERS)
    if not path.startswith(DOCUMENTATION_PREFIXES):
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    if path.startswith(NO_STORE_PREFIX):
        headers["Cache-Control"] = "no-store"
    return headers


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        wanted = headers_for(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in wanted.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
