"""Dépôt de rapports de test : ce que fait le robot (PDF d'abord, métadonnées en dernier)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
BASE = datetime(2026, 10, 26, 6, 0, tzinfo=UTC)


def deposit(
    directory: Path,
    *,
    report_id: uuid.UUID | None = None,
    title: str = "Rapport hebdomadaire du 19 au 26 octobre 2026",
    generated_at: datetime = BASE,
    content: bytes = PDF,
    file_name: str | None = None,
    metadata: dict | None = None,
) -> uuid.UUID:
    report_id = report_id or uuid.uuid4()
    (directory / f"{report_id}.pdf").write_bytes(content)
    record = {
        "report_id": str(report_id),
        "title": title,
        "period_start": (generated_at - timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "period_end": generated_at.isoformat().replace("+00:00", "Z"),
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "file_name": file_name or f"rapport-{generated_at:%Y-%m-%d}.pdf",
        "size_bytes": len(content),
        "content_type": "application/pdf",
        "sha256": hashlib.sha256(content).hexdigest(),
    } | (metadata or {})
    (directory / f"{report_id}.json").write_text(json.dumps(record), encoding="utf-8")
    return report_id
