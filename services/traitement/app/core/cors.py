"""CORS restreint (BE-08) : seules les origines listées lisent les réponses, avec les seules
méthodes et en-têtes que l'API utilise.

- Origines : celles de `CORS_ALLOWED_ORIGINS`, une par une, jamais `*` (refusé à la lecture de la
  configuration). Vide : le middleware n'est pas monté et le navigateur n'autorise que la
  même origine.
- Méthodes : `GET` et `POST`, les seules des routes publiées. Un test échoue si une route utilise
  une méthode absente de cette liste : il faut alors la décider ici, pas par accident.
- En-têtes de requête : `Authorization`, `Content-Type`, `X-Correlation-ID`.
- En-têtes de réponse lisibles par le script de la page : l'identifiant de corrélation,
  `Retry-After` (429), `Allow` (405), `Deprecation` et `Sunset` (versions).
- Pas de cookies ni d'identifiants du navigateur (`allow_credentials=False`) : l'authentification
  est un jeton porté par `Authorization`, que le script ajoute lui-même.
- Réponse de pré-vérification (`OPTIONS`) mise en cache 10 minutes.

Une origine non listée reçoit la réponse **sans** `Access-Control-Allow-Origin` : le navigateur en
interdit la lecture au script de la page (CORS est appliqué par le navigateur : le serveur ne
peut pas l'empêcher). Sa pré-vérification est refusée par `400 Disallowed CORS origin`, en texte
brut : c'est la réponse de Starlette, que seul un navigateur lit, et la seule de l'API qui n'est
pas un `Problem`.
"""

ALLOWED_METHODS = ["GET", "POST"]
ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Correlation-ID"]
EXPOSED_HEADERS = ["X-Correlation-ID", "Retry-After", "Allow", "Deprecation", "Sunset"]
PREFLIGHT_MAX_AGE_S = 600


def cors_options(origins: list[str]) -> dict:
    return {
        "allow_origins": origins,
        "allow_methods": ALLOWED_METHODS,
        "allow_headers": ALLOWED_HEADERS,
        "expose_headers": EXPOSED_HEADERS,
        "allow_credentials": False,
        "max_age": PREFLIGHT_MAX_AGE_S,
    }
