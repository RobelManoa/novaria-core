"""Enregistre des réponses réelles de l'API des indicateurs et calcule les valeurs que le tableau de bord doit afficher (FE-04).

Le front-end est testé sur ces réponses (frontend/tests/fixtures/dashboard-api.json) : chaque valeur affichée doit
être celle que ce script calcule, ici en Python et sans rien reprendre du code TypeScript. Bibliothèque standard seule.

    python3 scripts/dev/dashboard_fixture.py --api http://127.0.0.1:8000 --user fe04 --out frontend/tests/fixtures/dashboard-api.json

Le mot de passe est lu dans la variable d'environnement NOVARIA_PASSWORD, sinon saisi sans écho : il ne passe jamais par
la ligne de commande. Aucun jeton ni mot de passe n'est écrit dans le fichier produit. Sans `--out`, le calcul est
affiché sur la sortie standard.
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PAGE_SIZE = 500
MAX_PAGES = 10
STATES = ("CONGESTED", "SLOW", "FREE_FLOW", "UNKNOWN")
STATE_LABELS = {"CONGESTED": "Congestionné", "SLOW": "Ralenti", "FREE_FLOW": "Fluide", "UNKNOWN": "Inconnu"}

# Un scénario = un état des filtres du tableau de bord. Les zones et tailles de fenêtre sont celles du jeu de démonstration.
SCENARIOS = (
    {"name": "defaut-vide", "period_hours": 1, "window_size_s": 60, "intersection_id": None},
    {"name": "reseau-1h-5min", "period_hours": 1, "window_size_s": 300, "intersection_id": None},
    {"name": "zone-INT_02-6h-5min", "period_hours": 6, "window_size_s": 300, "intersection_id": "INT_02"},
)


def api_get(api: str, path: str, query: dict[str, str], token: str | None) -> dict:
    url = f"{api}{path}?{urllib.parse.urlencode(query)}" if query else f"{api}{path}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 : adresse donnée par l'utilisateur, http(s) seulement
        return json.loads(response.read())


def login(api: str, user: str, password: str) -> str:
    body = json.dumps({"username": user, "password": password}).encode()
    request = urllib.request.Request(f"{api}/api/v1/auth/login", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())["access_token"]


def api_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def collect(api: str, token: str, scenario: dict) -> tuple[list[dict], list[dict]]:
    """Fait les appels que le tableau de bord doit faire, dans le même ordre ; rend (appels enregistrés, indicateurs lus)."""
    zone = {"intersection_id": scenario["intersection_id"]} if scenario["intersection_id"] else {}
    calls = []

    def record(query: dict[str, str]) -> dict:
        response = api_get(api, "/api/v1/indicators", query, token)
        calls.append({"query": query, "response": response})
        return response

    newest = record({**zone, "window_size_s": str(scenario["window_size_s"]), "limit": "1"})
    if not newest["items"]:
        return calls, []
    last = newest["items"][0]
    end = parse_datetime(last["window_start"]) + timedelta(seconds=last["window_size_s"])
    query = {
        **zone,
        "window_size_s": str(scenario["window_size_s"]),
        "run_id": last["provenance"]["run_id"],
        "from": api_datetime(end - timedelta(hours=scenario["period_hours"])),
        "to": api_datetime(end),
        "limit": str(PAGE_SIZE),
    }
    indicators: list[dict] = []
    for _ in range(MAX_PAGES):
        page = record(query)
        indicators += page["items"]
        if page["next_cursor"] is None:
            break
        query = {**query, "cursor": page["next_cursor"]}
    return calls, indicators


def fixed(value: float | int | None, digits: int) -> str | None:
    """Arrondi à `digits` décimales de la valeur binaire exacte, moitié vers le haut : comme Intl.NumberFormat."""
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def weighted_speed(rows: list[dict]) -> float | None:
    with_speed = [row for row in rows if row["average_speed_kmh"] is not None]
    weight = sum(row["vehicle_count"] for row in with_speed)
    if weight == 0:
        return None
    return sum(row["average_speed_kmh"] * row["vehicle_count"] for row in with_speed) / weight


def expected_values(indicators: list[dict]) -> dict | None:
    """Ce que l'écran doit montrer pour ces indicateurs, calculé sans le code du front-end."""
    if not indicators:
        return None
    by_window: dict[str, list[dict]] = {}
    for row in indicators:
        by_window.setdefault(row["window_start"], []).append(row)
    windows = sorted(by_window)
    flows = [sum(row["flow_veh_per_min"] for row in by_window[window]) for window in windows]
    latest: dict[str, dict] = {}
    for row in indicators:
        known = latest.get(row["road_segment_id"])
        if known is None or row["window_start"] > known["window_start"]:
            latest[row["road_segment_id"]] = row
    states = {state: sum(1 for row in latest.values() if row["congestion_state"] == state) for state in STATES}
    provenance = indicators[0]["provenance"]
    return {
        "meta": {
            "source_type": provenance["source_type"],
            "run_id": provenance["run_id"],
            "indicator_count": len(indicators),
            "segment_count": len(latest),
            "first_window": windows[0],
            "last_window": windows[-1],
        },
        "cards": {
            "speed": fixed(weighted_speed(indicators), 1),
            "vehicles": str(sum(row["vehicle_count"] for row in indicators)),
            "flow": fixed(sum(flows) / len(flows), 1),
            "congested": f"{states['CONGESTED']} sur {len(latest)}",
        },
        "speed_series": [[window, fixed(weighted_speed(by_window[window]), 1)] for window in windows],
        "flow_series": [[window, fixed(flow, 1)] for window, flow in zip(windows, flows, strict=True)],
        "states": states,
        "segments": [
            {
                "road_segment_id": row["road_segment_id"],
                "intersection_id": row["intersection_id"],
                "state": STATE_LABELS[row["congestion_state"]],
                "speed": fixed(row["average_speed_kmh"], 1),
                "flow": fixed(row["flow_veh_per_min"], 1),
                "vehicles": str(row["vehicle_count"]),
                "window_start": row["window_start"],
            }
            for _, row in sorted(latest.items())
        ],
    }


def build(api: str, token: str) -> dict:
    scenarios = []
    for scenario in SCENARIOS:
        calls, indicators = collect(api, token, scenario)
        scenarios.append({**scenario, "requests": calls, "expected": expected_values(indicators)})
    return {
        "note": "Réponses réelles de GET /api/v1/indicators (données simulées du dépôt) et valeurs attendues calculées par scripts/dev/dashboard_fixture.py.",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="adresse de l'API de traitement")
    parser.add_argument("--user", required=True, help="compte de lecture (rôle viewer au moins)")
    parser.add_argument("--out", type=Path, help="fichier JSON à écrire (UTF-8, fins de ligne LF)")
    options = parser.parse_args(argv)
    if not options.api.startswith(("http://", "https://")):
        print("ERREUR : --api doit commencer par http:// ou https://", file=sys.stderr)
        return 1
    password = os.environ.get("NOVARIA_PASSWORD") or getpass.getpass("Mot de passe : ")
    try:
        result = build(options.api.rstrip("/"), login(options.api.rstrip("/"), options.user, password))
    except (urllib.error.URLError, KeyError) as error:
        print(f"ERREUR : lecture de l'API impossible ({type(error).__name__}).", file=sys.stderr)
        return 1
    # Une seule ligne : fichier généré, pas relu à la main ; des centaines de blocs identiques fausseraient la détection de duplication.
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    if options.out:
        options.out.parent.mkdir(parents=True, exist_ok=True)
        options.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{options.out} : {len(text.encode('utf-8')) // 1024} Ko, {len(result['scenarios'])} scénarios")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
