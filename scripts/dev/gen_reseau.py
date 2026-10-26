#!/usr/bin/env python3
"""Génère la migration SQL du réseau de démonstration (6 carrefours, 24 tronçons, 24 capteurs).

Le réseau est fictif et déterministe : mêmes identifiants dans l'entrepôt, le simulateur (MS-07)
et les événements. Pour le modifier, changer les paramètres ci-dessous, relancer le script, puis
AJOUTER une migration (une migration déjà appliquée ne se réécrit pas) :

    python scripts/dev/gen_reseau.py --out db/postgres/migrations/0005_reseau_demo.sql

(L'option --out évite la redirection « > » de PowerShell, qui réencode le fichier en UTF-16.)
"""
import argparse

# (identifiant, type de route, voies, longueur d'approche en m, vitesse limite km/h)
CARREFOURS = [
    ("INT_01", "ARTERIAL", 2, 300, 50),
    ("INT_02", "ARTERIAL", 2, 300, 50),
    ("INT_03", "COLLECTOR", 1, 250, 50),
    ("INT_04", "COLLECTOR", 1, 250, 50),
    ("INT_05", "LOCAL", 1, 150, 30),
    ("INT_06", "LOCAL", 1, 150, 30),
]
APPROCHES = [("N", "Nord"), ("E", "Est"), ("S", "Sud"), ("W", "Ouest")]


def lignes():
    """Rend les lignes (carrefour, tronçon, capteur) dans un ordre stable."""
    n = 0
    for idx, (int_id, rtype, lanes, length, limit) in enumerate(CARREFOURS, start=1):
        for code, nom in APPROCHES:
            n += 1
            yield {
                "int_id": int_id, "int_name": f"Carrefour {idx:02d}",
                "road_id": f"ROAD_{n:03d}", "road_name": f"Carrefour {idx:02d} · approche {nom}",
                "approach": code, "road_type": rtype, "lanes": lanes, "length": length, "limit": limit,
                "sensor_id": f"SENSOR_{n:03d}",
            }


def sql() -> str:
    rows = list(lignes())
    out = [
        "-- 0005 · Réseau de démonstration fictif : 6 carrefours, 24 tronçons d'approche, 24 capteurs simulés.",
        "-- Généré par scripts/dev/gen_reseau.py (ne pas modifier à la main).",
        "-- Vitesse en circulation fluide = vitesse limite (hypothèse de simulation).",
        "",
        "INSERT INTO dwh.dim_intersection (intersection_id, name) VALUES",
    ]
    ints = [(r["int_id"], r["int_name"]) for r in rows if r["approach"] == "N"]
    out.append(",\n".join(f"    ('{i}', '{n}')" for i, n in ints) + ";")
    out += ["", "INSERT INTO dwh.dim_road_segment",
            "    (road_segment_id, intersection_key, name, approach, road_type, lane_count, length_m, speed_limit_kmh, free_flow_speed_kmh)",
            "SELECT v.road_segment_id, i.intersection_key, v.name, v.approach, v.road_type, v.lane_count, v.length_m, v.limit_kmh, v.limit_kmh",
            "FROM (VALUES"]
    vals = [f"    ('{r['road_id']}', '{r['int_id']}', '{r['road_name']}', '{r['approach']}', '{r['road_type']}', "
            f"{r['lanes']}, {r['length']}, {r['limit']})" for r in rows]
    out.append(",\n".join(vals))
    out += [") AS v (road_segment_id, intersection_id, name, approach, road_type, lane_count, length_m, limit_kmh)",
            "JOIN dwh.dim_intersection i ON i.intersection_id = v.intersection_id;", "",
            "INSERT INTO dwh.dim_sensor (sensor_id, road_segment_key, sensor_type, reporting_interval_s)",
            "SELECT v.sensor_id, s.road_segment_key, 'SIMULATED', 10",
            "FROM (VALUES"]
    out.append(",\n".join(f"    ('{r['sensor_id']}', '{r['road_id']}')" for r in rows))
    out += [") AS v (sensor_id, road_segment_id)",
            "JOIN dwh.dim_road_segment s ON s.road_segment_id = v.road_segment_id;", ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="fichier SQL à écrire")
    args = parser.parse_args()
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(sql())
    print(f"{args.out} écrit.")


if __name__ == "__main__":
    main()
