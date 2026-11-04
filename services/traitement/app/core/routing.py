"""Modèles de route publiés (`/api/v1/users/{user_id}`) et méthodes permises par chemin.

Deux usages, une seule correspondance chemin → modèle :
- le journal d'audit nomme chaque appel par son modèle de route (BE-05) ;
- l'erreur 405 liste dans `Allow` toutes les méthodes du chemin (BE-06). Starlette n'y met que
  celles de la *première* route qui correspond : `DELETE /api/v1/users` annoncerait `GET` seul
  alors que `POST` existe aussi. Les méthodes sont donc relues dans les routes publiées
  (`/openapi.json`).
"""

import re
from collections.abc import Iterable

from starlette.types import Scope

Compiled = list[tuple[re.Pattern[str], str]]


def compile_templates(templates: Iterable[str]) -> Compiled:
    """Modèles de route prêts à comparer, les plus précis d'abord.

    `/indicators/latest` passe avant `/indicators/{indicator_id}` : il correspond aux deux.
    """
    ordered = sorted(templates, key=lambda template: template.count("{"))
    return [
        (re.compile(re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(template)) + "$"), template)
        for template in ordered
    ]


def match_template(path: str, compiled: Compiled) -> str | None:
    """Le modèle de route du chemin, ou `None` s'il n'en existe pas."""
    return next((template for pattern, template in compiled if pattern.match(path)), None)


def compiled_templates(application) -> Compiled:
    """Les modèles de route publiés par l'application, compilés une fois et gardés sur elle."""
    compiled = getattr(application.state, "route_templates", None)
    if compiled is None:
        compiled = application.state.route_templates = compile_templates(
            application.openapi()["paths"]
        )
    return compiled


def allowed_methods(scope: Scope) -> list[str]:
    """Méthodes permises sur le chemin de la requête, ou une liste vide si la route est inconnue."""
    application = scope.get("app")
    if application is None:
        return []
    template = match_template(scope.get("path", ""), compiled_templates(application))
    if template is None:
        return []
    return sorted(method.upper() for method in application.openapi()["paths"][template])
