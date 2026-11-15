"""Indicateurs de dérive au format texte de Prometheus, pour `GET /metrics` (ADR-025, IA-06).

Équivalent local d'une métrique CloudWatch. `novaria_input_drift_alert` vaut 1 tant qu'une
variable dépasse le seuil d'alerte : c'est l'indicateur que l'alerte locale expose.
"""

from app.drift.monitor import DriftReport, Status

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
VERDICTS = (Status.OK, Status.WARN, Status.ALERT)


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render(report: DriftReport) -> str:
    lines = [
        "# HELP novaria_input_drift_psi Indice de stabilité de population par variable d'entrée.",
        "# TYPE novaria_input_drift_psi gauge",
    ]
    lines += [
        f'novaria_input_drift_psi{{feature="{feature.feature}"}} {feature.psi:.6f}'
        for feature in report.features
    ]
    lines += [
        "# HELP novaria_input_drift_alert 1 si une variable dépasse le seuil d'alerte, sinon 0.",
        "# TYPE novaria_input_drift_alert gauge",
        f"novaria_input_drift_alert {1 if report.is_alert else 0}",
        "# HELP novaria_input_drift_check_ok 1 si la comparaison a pu être faite, sinon 0.",
        "# TYPE novaria_input_drift_check_ok gauge",
        f"novaria_input_drift_check_ok {1 if report.status in VERDICTS else 0}",
        "# HELP novaria_input_drift_status État de la surveillance (une seule valeur à 1).",
        "# TYPE novaria_input_drift_status gauge",
    ]
    lines += [
        f'novaria_input_drift_status{{status="{status.value}"}} {int(report.status is status)}'
        for status in Status
    ]
    lines += [
        "# HELP novaria_input_drift_threshold Seuils de PSI en vigueur.",
        "# TYPE novaria_input_drift_threshold gauge",
        f'novaria_input_drift_threshold{{level="warn"}} {report.thresholds.warn}',
        f'novaria_input_drift_threshold{{level="alert"}} {report.thresholds.alert}',
        "# HELP novaria_input_drift_runs_info Exécutions comparées (valeur toujours 1).",
        "# TYPE novaria_input_drift_runs_info gauge",
        "novaria_input_drift_runs_info{"
        f'reference_run_id="{escape(report.reference_run_id or "")}",'
        f'current_run_id="{escape(report.current_run_id or "")}"}} 1',
        "# HELP novaria_input_drift_checked_timestamp_seconds Dernière comparaison (UTC).",
        "# TYPE novaria_input_drift_checked_timestamp_seconds gauge",
        f"novaria_input_drift_checked_timestamp_seconds {report.checked_at.timestamp():.0f}",
    ]
    return "\n".join(lines) + "\n"
