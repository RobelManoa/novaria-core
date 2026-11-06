"""Règles d'alerte : lister, activer, désactiver, régler (contrat `alerte.openapi.yaml`).

Lire est permis au `viewer`, modifier réserve à l'`admin`. Un réglage inconnu ou hors des valeurs
permises est refusé (`422`) : une règle qui ne ferait rien en silence est pire qu'une erreur. Les
paramètres envoyés sont **fusionnés** avec ceux de la règle ; ceux qu'on ne cite pas restent.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_store, require_role
from app.api.mapping import rule_out
from app.core.auth import Claims, Role
from app.core.errors import NOT_FOUND, VALIDATION_ERROR, ProblemError
from app.domain.rules import invalid_params
from app.schemas.api import AlertRuleListOut, AlertRuleOut, AlertRuleUpdate, Problem
from app.services.ports import AlertStore, NotFound

router = APIRouter(tags=["Alertes"])

RULE_ID = re.compile(r"^[a-z0-9_.-]{3,60}$")


@router.get(
    "/alert-rules",
    response_model=AlertRuleListOut,
    operation_id="listAlertRules",
    summary="Lister les règles d'alerte",
    openapi_extra={"x-required-role": "viewer"},
    responses={
        401: {"model": Problem, "description": "Jeton absent, invalide ou expiré."},
        403: {"model": Problem, "description": "Rôle insuffisant."},
    },
)
def list_rules(
    _: Annotated[Claims, Depends(require_role(Role.VIEWER))],
    store: Annotated[AlertStore, Depends(get_store)],
) -> dict:
    return {"items": [rule_out(r) for r in store.rules()]}


@router.patch(
    "/alert-rules/{rule_id}",
    response_model=AlertRuleOut,
    operation_id="updateAlertRule",
    summary="Activer, désactiver ou régler une règle",
    openapi_extra={"x-required-role": "admin"},
    responses={
        401: {"model": Problem, "description": "Jeton absent, invalide ou expiré."},
        403: {"model": Problem, "description": "Rôle insuffisant."},
        404: {"model": Problem, "description": "Règle inconnue ; `NOT_FOUND`."},
        422: {"model": Problem, "description": "Entrée invalide ; `VALIDATION_ERROR`."},
    },
)
def update_rule(
    rule_id: str,
    changes: AlertRuleUpdate,
    _: Annotated[Claims, Depends(require_role(Role.ADMIN))],
    store: Annotated[AlertStore, Depends(get_store)],
) -> dict:
    if not RULE_ID.fullmatch(rule_id):
        raise ProblemError(NOT_FOUND, "Règle inconnue.")
    if not changes.model_fields_set:
        raise ProblemError(
            VALIDATION_ERROR,
            "1 champ invalide.",
            errors=[{"field": "body", "message": "Au moins un champ à modifier est attendu."}],
        )
    rule = next((r for r in store.rules() if r.rule_id == rule_id), None)
    if rule is None:
        raise ProblemError(NOT_FOUND, "Règle inconnue.")
    if changes.params is not None:
        problems = [
            {"field": f"body.params.{name}", "message": message}
            for name, message in invalid_params(rule.kind, changes.params)
        ]
        if problems:
            noun = "champ invalide" if len(problems) == 1 else "champs invalides"
            raise ProblemError(VALIDATION_ERROR, f"{len(problems)} {noun}.", errors=problems)
    try:
        updated = store.update_rule(
            rule_id, enabled=changes.enabled, params=changes.params, min_gap_s=changes.min_gap_s
        )
    except NotFound as error:
        raise ProblemError(NOT_FOUND, "Règle inconnue.") from error
    return rule_out(updated)
