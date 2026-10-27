# Passerelle d'API

**État : routage seulement (MS-06).** Un nginx (`nginxinc/nginx-unprivileged`, même base que le front-end) qui reçoit tous les appels de l'API sur `127.0.0.1:${GATEWAY_PORT:-8000}` et les envoie au service propriétaire. L'authentification, la limitation de débit et CORS sont l'issue **MS-13**.

| Préfixe | Destination |
|---|---|
| `/health` | la passerelle elle-même |
| `/api/v1/health` | `traitement` (provisoire, jusqu'au service API métier) |
| `/api/v1/intersections`, `/road-segments`, `/indicators`, `/forecasts` | `traitement` |
| `/api/v1/alerts`, `/alert-rules`, `/events/stream` (SSE) | `alerte` |
| `/api/v1/signals` | `reponse` |
| `/api/v1/auth`, `/users` | 503 `UPSTREAM_UNAVAILABLE` : pas encore de service API métier |
| `/api/v1/measurements` | 404 : dépôt des mesures interne (simulateur vers collecte) |
| le reste | 404 au format `application/problem+json` |

Chaque réponse porte `X-Correlation-ID` (repris de la requête, ou généré) ; les erreurs de la passerelle suivent le format `Problem` des contrats. Contrôle de la syntaxe : `docker run --rm --add-host traitement:127.0.0.1 --add-host alerte:127.0.0.1 --add-host reponse:127.0.0.1 -v "$PWD/gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginxinc/nginx-unprivileged:1.30-alpine-slim nginx -t`.
