"""Métriques au format Prometheus : même code dans tous les services (MS-16).

Un registre en mémoire (compteurs, jauges, histogrammes), un intergiciel qui compte chaque
requête HTTP (nombre par classe de statut, durée, requêtes en cours : les trois signaux « RED »,
Rate, Errors, Duration) et `GET /metrics` qui les rend en texte. Rien n'est écrit sur le disque et
aucun paquet n'est ajouté.

Le point d'exploitation reste hors du contrat OpenAPI et hors de la passerelle (qui ne le route
pas) : il ne sort que des nombres et des noms de routes, jamais une valeur de requête ni un
identifiant. L'étiquette `route` est le modèle de chemin (`/api/v1/alerts/{alert_id}`), pas le
chemin reçu.
"""

import threading
import time

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
Labels = tuple[tuple[str, str], ...]


def _labels(labels: dict[str, str] | None) -> Labels:
    return tuple(sorted((labels or {}).items()))


def _text(labels: Labels, extra: tuple[str, str] | None = None) -> str:
    pairs = [*labels, *([extra] if extra else [])]
    if not pairs:
        return ""
    escaped = (
        (k, v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")) for k, v in pairs
    )
    return "{" + ",".join(f'{k}="{v}"' for k, v in escaped) + "}"


class Registry:
    """Compteurs, jauges et histogrammes ; sûr entre fils (fils et tâches asynchrones se mêlent)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._help: dict[str, tuple[str, str]] = {}
        self._values: dict[str, dict[Labels, float]] = {}
        self._histograms: dict[str, dict[Labels, tuple[list[float], float, int]]] = {}

    def describe(self, name: str, kind: str, help_text: str) -> None:
        with self._lock:
            self._help.setdefault(name, (kind, help_text))

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            series = self._values.setdefault(name, {})
            key = _labels(labels)
            series[key] = series.get(key, 0.0) + value

    def set(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._values.setdefault(name, {})[_labels(labels)] = value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            series = self._histograms.setdefault(name, {})
            key = _labels(labels)
            counts, total, number = series.get(key, ([0.0] * len(BUCKETS), 0.0, 0))
            counts = [
                count + (1.0 if value <= bound else 0.0)
                for count, bound in zip(counts, BUCKETS, strict=True)
            ]
            series[key] = (counts, total + value, number + 1)

    def value(self, name: str, labels: dict[str, str] | None = None) -> float:
        with self._lock:
            return self._values.get(name, {}).get(_labels(labels), 0.0)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name in sorted({*self._values, *self._histograms}):
                kind, help_text = self._help.get(
                    name, ("histogram" if name in self._histograms else "gauge", name)
                )
                lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
                for labels, value in sorted(self._values.get(name, {}).items()):
                    lines.append(f"{name}{_text(labels)} {value:g}")
                for labels, (counts, total, number) in sorted(
                    self._histograms.get(name, {}).items()
                ):
                    lines += [
                        f"{name}_bucket{_text(labels, ('le', f'{bound:g}'))} {count:g}"
                        for bound, count in zip(BUCKETS, counts, strict=True)
                    ]
                    lines += [
                        f"{name}_bucket{_text(labels, ('le', '+Inf'))} {number}",
                        f"{name}_sum{_text(labels)} {total:g}",
                        f"{name}_count{_text(labels)} {number}",
                    ]
        return "\n".join(lines) + "\n"


REGISTRY = Registry()
REGISTRY.describe(
    "novaria_http_requests_total",
    "counter",
    "Requêtes HTTP traitées, par méthode, route et classe de statut",
)
REGISTRY.describe(
    "novaria_http_request_duration_seconds", "histogram", "Durée des requêtes HTTP, en secondes"
)
REGISTRY.describe("novaria_http_requests_in_flight", "gauge", "Requêtes HTTP en cours")
REGISTRY.describe(
    "novaria_process_start_time_seconds",
    "gauge",
    "Instant de démarrage du processus (secondes Unix)",
)
REGISTRY.set("novaria_process_start_time_seconds", time.time())


def status_class(status: int) -> str:
    return f"{status // 100}xx"


class MetricsMiddleware:
    """Compte chaque requête HTTP. Les routes inconnues (404) partagent l'étiquette `inconnue`."""

    def __init__(self, app: ASGIApp, service: str, registry: Registry = REGISTRY) -> None:
        self.app, self.service, self.registry = app, service, registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500
        base = {"service": self.service}
        self.registry.inc("novaria_http_requests_in_flight", base, 1.0)

        async def send_counting(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_counting)
        finally:
            route = getattr(scope.get("route"), "path", None) or "inconnue"
            labels = {**base, "method": scope["method"], "route": route}
            self.registry.inc("novaria_http_requests_in_flight", base, -1.0)
            self.registry.inc(
                "novaria_http_requests_total", {**labels, "status": status_class(status)}
            )
            self.registry.observe(
                "novaria_http_request_duration_seconds", time.perf_counter() - started, labels
            )


def metrics_response(extra: str = "", registry: Registry = REGISTRY) -> Response:
    """`GET /metrics` : le registre, suivi de `extra` (les métriques propres à un service)."""
    return Response(registry.render() + extra, media_type=CONTENT_TYPE)
