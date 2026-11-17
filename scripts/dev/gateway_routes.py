#!/usr/bin/env python3
"""Génère les routes de la passerelle (gateway/routes.conf et gateway/routes.json) depuis les contrats OpenAPI.

Pourquoi générer : la passerelle doit connaître, pour chaque route, son service, ses méthodes et le rôle exigé.
Ces trois informations sont déjà écrites dans `contracts/openapi/*.openapi.yaml` (chemins, méthodes, `x-required-role`,
`security: []` pour une route publique). Les recopier à la main, c'est préparer le jour où un contrat change et où la
passerelle laisse passer une route sans le rôle voulu. Un test (`test_gateway_routes.py`) échoue si les fichiers
générés ne sont pas ceux que ce script produirait.

Une route absente des contrats n'existe pas à la passerelle : 404. Une route présente a un `location` à elle :
- le chemin exact (les paramètres `{id}` deviennent `[^/]+`) ; un autre chemin est un 404 ;
- les méthodes du contrat (plus OPTIONS, la pré-vérification CORS) ; une autre méthode est un 405 ;
- `routes.json` dit le rôle ; `auth.js` le vérifie avant que la requête n'atteigne le service.

Usage :  python scripts/dev/gateway_routes.py          écrit les deux fichiers
         python scripts/dev/gateway_routes.py --check  échoue si les fichiers ne sont pas à jour (code 1)
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRATS = ROOT / "contracts" / "openapi"
GATEWAY = ROOT / "gateway"

# Contrat -> service qui sert ses routes. `api-metier` est porté par `traitement` tant que le point ouvert n° 1 des
# diagrammes C4 n'est pas tranché ; `collecte` (dépôt des mesures) est interne : le simulateur parle à la collecte,
# pas à la passerelle.
SERVICES = {"alerte": "alerte", "traitement": "traitement", "reponse": "reponse", "api-metier": "traitement"}
INTERNES = {"collecte"}
VERBES = ("get", "post", "patch", "put", "delete")
# Réglages particuliers de certaines routes (flux SSE : pas de tampon, connexion longue, nombre de flux limité).
PARTICULARITES = {
    "/api/v1/events/stream": [
        "proxy_buffering off;",
        "proxy_read_timeout 1h;",
        "limit_conn streams 10;",
    ],
    "/api/v1/auth/login": ["limit_req zone=login burst=5 nodelay;"],
}
PROBLEME_405 = (
    '{"type":"https://novaria.local/problems/method-not-allowed","title":"Méthode non permise","status":405,'
    '"code":"METHOD_NOT_ALLOWED","detail":"Cette méthode n est pas permise sur cette route.",'
    '"correlation_id":"$correlation_id"}'
)


def lire_routes() -> list[dict]:
    """Une entrée par (chemin, méthode) : service, rôle (None si publique) et contrat d'origine."""
    routes: dict[tuple[str, str], dict] = {}
    # `traitement` d'abord : la sonde /api/v1/health, présente dans chaque contrat, est servie par lui.
    contrats = sorted(CONTRATS.glob("*.openapi.yaml"), key=lambda f: (f.name != "traitement.openapi.yaml", f.name))
    for fichier in contrats:
        nom = fichier.name.removesuffix(".openapi.yaml")
        if nom in INTERNES:
            continue
        service = SERVICES[nom]
        doc = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        for chemin, item in doc["paths"].items():
            for verbe in VERBES:
                operation = item.get(verbe)
                if operation is None:
                    continue
                publique = operation.get("security") == []
                role = None if publique else operation.get("x-required-role")
                if not publique and role is None:
                    raise SystemExit(f"{fichier.name} : {verbe.upper()} {chemin} est protégée mais sans x-required-role")
                cle = (chemin, verbe.upper())
                if cle in routes:  # la sonde /api/v1/health est dans chaque contrat : une seule route
                    continue
                routes[cle] = {"path": chemin, "method": verbe.upper(), "role": role, "service": service,
                               "contract": fichier.name, "operation": operation["operationId"]}
    return sorted(routes.values(), key=lambda r: (r["path"], r["method"]))


def motif(chemin: str) -> str:
    """Expression régulière ancrée du chemin : `{id}` devient un segment sans barre oblique."""
    morceaux = re.split(r"(\{[A-Za-z_]+\})", chemin)
    return "^" + "".join("[^/]+" if m.startswith("{") else re.escape(m) for m in morceaux) + "$"


def routes_json(routes: list[dict]) -> str:
    table = [{"method": r["method"], "pattern": motif(r["path"]), "role": r["role"]} for r in routes]
    return json.dumps(table, ensure_ascii=False, indent=1) + "\n"


def routes_conf(routes: list[dict]) -> str:
    par_chemin: dict[str, list[dict]] = {}
    for route in routes:
        par_chemin.setdefault(route["path"], []).append(route)
    exacts = [c for c in par_chemin if "{" not in c]
    avec_parametres = [c for c in par_chemin if "{" in c]
    lignes = [
        "# GÉNÉRÉ par scripts/dev/gateway_routes.py depuis contracts/openapi/ : ne pas modifier à la main",
        "# (python scripts/dev/gateway_routes.py). Un `location` par chemin des contrats : le service, les méthodes et",
        "# le rôle exigé (routes.json, vérifié par auth.js) en viennent. Rien d'autre n'est routé.",
        "",
    ]
    for chemin in exacts + avec_parametres:
        operations = par_chemin[chemin]
        service = operations[0]["service"]
        methodes = sorted({o["method"] for o in operations} | {"OPTIONS"})
        publique = all(o["role"] is None for o in operations)
        roles = ", ".join(f"{o['method']} {o['role'] or 'publique'}" for o in operations)
        autorisees = "|".join(methodes)
        lignes += [
            f"  # {operations[0]['contract']} : {roles}",
            f"  location {'=' if '{' not in chemin else '~'} {chemin if '{' not in chemin else motif(chemin)} {{",
            f"    if ($request_method !~ ^({autorisees})$) {{",
            f'      add_header Allow "{", ".join(methodes)}" always;',
            f"      return 405 '{PROBLEME_405}';",
            "    }",
            f"    include /etc/nginx/gateway/{'public' if publique else 'protected'}.conf;",
            *[f"    {ligne}" for ligne in PARTICULARITES.get(chemin, [])],
            f"    proxy_pass http://{service}:8000;",
            "  }",
            "",
        ]
    return "\n".join(lignes)


def produire() -> dict[Path, str]:
    routes = lire_routes()
    return {GATEWAY / "routes.json": routes_json(routes), GATEWAY / "routes.conf": routes_conf(routes)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="échoue si les fichiers générés ne sont pas à jour")
    args = parser.parse_args(argv)
    perimes = []
    for chemin, contenu in produire().items():
        actuel = chemin.read_bytes().decode("utf-8") if chemin.exists() else None
        if args.check:
            if actuel != contenu:
                perimes.append(chemin.relative_to(ROOT).as_posix())
        else:
            chemin.write_bytes(contenu.encode("utf-8"))  # fins de ligne Unix : le fichier est monté dans un conteneur Linux
            print(f"écrit {chemin.relative_to(ROOT).as_posix()}")
    if perimes:
        print("Fichiers périmés (relancer : python scripts/dev/gateway_routes.py) : " + ", ".join(perimes), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
