"""Script de dérive : compare les entrées d'une exécution à celles d'une référence (IA-06).

    python -m app.drift check --reference-run <run_id> [--current-run <run_id>] [--json]

Lit l'entrepôt avec le compte en lecture seule du service (`POSTGRES_URL`). L'exécution courante
est la plus récente par défaut. Une dérive écrit la ligne d'alerte dans le journal JSON (sortie
standard), comme le fait `/metrics` pour l'API.

Code de sortie : 0 stable (ou décalage modéré), 1 dérive (seuil d'alerte dépassé), 2 comparaison
impossible (pas de référence, entrepôt vide, trop peu de valeurs, entrepôt injoignable).
"""

import argparse
import json
import sys
from collections.abc import Sequence

from app.core.config import get_settings
from app.core.logs import configure_logging
from app.db.session import DatabaseNotConfigured, get_warehouse_session_factory
from app.drift import alert
from app.drift.monitor import DriftReport, Status, Thresholds
from app.drift.service import compare
from app.repositories.indicators import SqlIndicatorRepository

EXIT_OK, EXIT_DRIFT, EXIT_UNAVAILABLE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.drift", description=__doc__.splitlines()[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="compare deux exécutions de l'entrepôt")
    check.add_argument(
        "--reference-run", help="exécution de référence (DRIFT_REFERENCE_RUN_ID par défaut)"
    )
    check.add_argument("--current-run", help="exécution courante (la plus récente par défaut)")
    check.add_argument("--json", action="store_true", help="écrit le rapport en JSON")
    return parser


def summary(report: DriftReport) -> str:
    lines = [
        f"Dérive des entrées : {report.status.value}",
        f"  référence : {report.reference_run_id or '-'}",
        f"  courante  : {report.current_run_id or '-'}",
        f"  seuils PSI : avertissement {report.thresholds.warn}, alerte {report.thresholds.alert}",
    ]
    lines += [
        f"  {f.feature:<18} PSI {f.psi:7.4f}  {f.status.value:<5}  "
        f"moyenne {f.reference_mean:.3f} -> {f.current_mean:.3f}  "
        f"({f.reference_count} et {f.current_count} valeurs)"
        for f in report.features
    ]
    if report.reason:
        lines.append(f"  {report.reason}")
    return "\n".join(lines)


def as_json(report: DriftReport) -> str:
    return json.dumps(
        {
            "status": report.status.value,
            "checked_at": report.checked_at.isoformat(),
            "reference_run_id": report.reference_run_id,
            "current_run_id": report.current_run_id,
            "thresholds": {
                "warn": report.thresholds.warn,
                "alert": report.thresholds.alert,
                "min_samples": report.thresholds.min_samples,
            },
            "features": [
                {
                    "feature": f.feature,
                    "psi": round(f.psi, 6),
                    "status": f.status.value,
                    "reference_mean": round(f.reference_mean, 6),
                    "current_mean": round(f.current_mean, 6),
                    "reference_count": f.reference_count,
                    "current_count": f.current_count,
                }
                for f in report.features
            ],
            "reason": report.reason,
        },
        ensure_ascii=False,
        indent=2,
    )


def exit_code(report: DriftReport) -> int:
    if report.is_alert:
        return EXIT_DRIFT
    return EXIT_OK if report.status in (Status.OK, Status.WARN) else EXIT_UNAVAILABLE


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    try:
        factory = get_warehouse_session_factory()
    except DatabaseNotConfigured:
        print("POSTGRES_URL absente : l'entrepôt n'est pas configuré.", file=sys.stderr)
        return EXIT_UNAVAILABLE
    with factory() as session:
        report = compare(
            SqlIndicatorRepository(session),
            reference_run_id=arguments.reference_run or settings.drift_reference_run_id,
            current_run_id=arguments.current_run,
            thresholds=Thresholds(
                warn=settings.drift_warn_psi,
                alert=settings.drift_alert_psi,
                min_samples=settings.drift_min_samples,
            ),
            max_rows=settings.drift_max_rows,
        )
    print(as_json(report) if arguments.json else summary(report))
    if report.is_alert:
        alert.emit_alert(report)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
