#!/usr/bin/env python3
"""Tableau de bord de pilotage du projet (GES-11) : trois indicateurs recalculés à partir de GitHub.

Indicateurs :
  1. Exigences vérifiées : les états (Prouvé, Partiel, À faire) du tableau de docs/02-specifications/exigences.md.
  2. Risques traités : les statuts (Ouvert, Suspendu, Clos) de docs/07-gestion/registre-risques.md.
  3. Livrables par jalon : les issues de chaque jalon (milestone) et, pour les issues fermées, la preuve attendue
     citée dans l'issue : le fichier existe-t-il dans le dépôt ?

Sources : l'API REST de GitHub (issues, jalons, arbre des fichiers) et les deux fichiers du dépôt à une révision donnée
(`--ref`, `main` par défaut), lus sur raw.githubusercontent.com. `--local` lit les deux fichiers dans la copie de travail
(utile avant de pousser) ; les issues viennent toujours de GitHub. Aucun jeton n'est nécessaire (dépôt public : 60 appels par
heure, la commande en fait 5) ; `GITHUB_TOKEN`, s'il existe, relève la limite et n'est jamais affiché.

Absence de mesure et résultat nul ne se confondent jamais : un indicateur « 0 sur 12 » est une mesure (le zéro est le
résultat) ; un indicateur « non mesuré » dit pourquoi (aucune issue dans le jalon, état illisible, source injoignable).

Bibliothèque standard seulement. Usage :
  python3 scripts/github/tableau_de_bord.py                 # tableau en Markdown sur la sortie standard
  python3 scripts/github/tableau_de_bord.py --json          # les mêmes mesures en JSON
  python3 scripts/github/tableau_de_bord.py --ecrire        # met à jour le bloc mesuré de docs/07-gestion/tableau-de-bord.md
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
DEPOT = "RobelManoa/novaria-core"
EXIGENCES = "docs/02-specifications/exigences.md"
RISQUES = "docs/07-gestion/registre-risques.md"
DOCUMENT = RACINE / "docs" / "07-gestion" / "tableau-de-bord.md"
DEBUT, FIN = "<!-- debut:mesures -->", "<!-- fin:mesures -->"
ETATS_EXIGENCE = ("Prouvé", "Partiel", "À faire")
STATUTS_RISQUE = ("Ouvert", "Suspendu", "Clos")
PRIORITES = ("Doit", "Devrait", "Pourrait")
EXIGENCE = re.compile(r"^EXG-([A-Z]+)-\d{2}$")
RISQUE = re.compile(r"^R\d+$")
CHEMIN = re.compile(r"(?<![\w/.\-])((?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-*]*)")
PREUVE = re.compile(r"##\s*Preuve attendue\s*\n(.*?)(?:\n\s*\n|\Z)", re.S)


class ErreurSource(Exception):
    """Une source est injoignable ou illisible : l'indicateur concerné est « non mesuré », jamais zéro."""


# --------------------------------------------------------------------------- lecture de GitHub
class GitHub:
    """API REST de GitHub (issues, jalons, arbre) et fichiers bruts du dépôt, en lecture seule."""

    def __init__(self, depot: str = DEPOT, ref: str = "main", jeton: str | None = None, ouvrir=urllib.request.urlopen) -> None:
        self.depot, self.ref, self.jeton, self.ouvrir = depot, ref, jeton, ouvrir

    def _requete(self, url: str, accepte: str) -> bytes:
        en_tetes = {"Accept": accepte, "User-Agent": "novaria-tableau-de-bord", "X-GitHub-Api-Version": "2022-11-28"}
        if self.jeton:
            en_tetes["Authorization"] = f"Bearer {self.jeton}"
        try:
            with self.ouvrir(urllib.request.Request(url, headers=en_tetes), timeout=30) as reponse:
                return reponse.read()
        except urllib.error.HTTPError as erreur:
            raison = "limite d'appels atteinte (définir GITHUB_TOKEN)" if erreur.code in (403, 429) else f"HTTP {erreur.code}"
            raise ErreurSource(f"{url.split('?')[0]} : {raison}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as erreur:
            raise ErreurSource(f"{url.split('?')[0]} : injoignable ({type(erreur).__name__})") from None

    def _json(self, chemin: str) -> object:
        try:
            return json.loads(self._requete(f"https://api.github.com/repos/{self.depot}/{chemin}", "application/vnd.github+json"))
        except ValueError:
            raise ErreurSource(f"{chemin} : réponse illisible") from None

    def _pages(self, chemin: str) -> list[dict]:
        resultat, page = [], 1
        while True:
            lot = self._json(f"{chemin}{'&' if '?' in chemin else '?'}per_page=100&page={page}")
            if not isinstance(lot, list):
                raise ErreurSource(f"{chemin} : réponse inattendue")
            resultat += lot
            if len(lot) < 100:
                return resultat
            page += 1

    def issues(self) -> list[dict]:
        """Toutes les issues (ouvertes et fermées), sans les pull requests."""
        return [i for i in self._pages("issues?state=all") if "pull_request" not in i]

    def jalons(self) -> list[dict]:
        return self._pages("milestones?state=all")

    def arbre(self) -> set[str]:
        """Tous les chemins de fichiers du dépôt à la révision `ref`."""
        arbre = self._json(f"git/trees/{urllib.parse.quote(self.ref, safe='')}?recursive=1")
        if not isinstance(arbre, dict) or arbre.get("truncated"):
            raise ErreurSource("arbre des fichiers incomplet : preuves non vérifiables")
        return {e["path"] for e in arbre.get("tree", []) if e.get("type") == "blob"}

    def fichier(self, chemin: str) -> str:
        url = f"https://raw.githubusercontent.com/{self.depot}/{urllib.parse.quote(self.ref, safe='')}/{chemin}"
        return self._requete(url, "text/plain").decode("utf-8")


# --------------------------------------------------------------------------- mesures
def mesure(valeur: int, sur: int, **detail) -> dict:
    """Une mesure : `valeur` sur `sur`. Un `sur` de 0 n'est pas un pourcentage de 0 : c'est « non mesuré »."""
    if sur <= 0:
        return non_mesure("aucun élément à compter", **detail)
    return {"mesure": True, "valeur": valeur, "sur": sur, "pourcentage": round(100 * valeur / sur, 1), "raison": None, **detail}


def non_mesure(raison: str, **detail) -> dict:
    return {"mesure": False, "valeur": None, "sur": None, "pourcentage": None, "raison": raison, **detail}


def cellules(ligne: str) -> list[str]:
    return [c.strip() for c in ligne.strip().strip("|").split("|")]


def premier_mot(texte: str, mots: tuple[str, ...]) -> str | None:
    """Le mot attendu par lequel commence la cellule (« Prouvé : détail » donne « Prouvé »), sinon `None`."""
    nettoye = texte.strip().strip("*").strip()
    return next((m for m in mots if re.match(rf"{re.escape(m)}(?!\w)", nettoye)), None)


def exigences(texte: str) -> dict:
    """Exigences vérifiées : lignes `| EXG-… |` du tableau ; l'état est le premier mot de l'avant-dernière cellule."""
    etats: Counter[str] = Counter()
    par_priorite: dict[str, Counter[str]] = {p: Counter() for p in PRIORITES}
    par_domaine: dict[str, Counter[str]] = {}
    illisibles: list[str] = []
    total = 0
    for ligne in texte.splitlines():
        cases = cellules(ligne) if ligne.startswith("| EXG-") else []
        if len(cases) < 7 or not EXIGENCE.match(cases[0]):
            continue
        total += 1
        etat = premier_mot(cases[-2], ETATS_EXIGENCE)
        priorite = premier_mot(cases[-4], PRIORITES)
        if etat is None:
            illisibles.append(cases[0])
            continue
        etats[etat] += 1
        if priorite:
            par_priorite[priorite][etat] += 1
        par_domaine.setdefault(EXIGENCE.match(cases[0]).group(1), Counter())[etat] += 1
    if total == 0:
        return {"verifiees": non_mesure("aucune exigence lue dans le tableau"), "par_etat": {}, "illisibles": []}
    lues = total - len(illisibles)
    return {
        "verifiees": mesure(etats["Prouvé"], lues, total_lignes=total) if lues else non_mesure("aucun état lisible"),
        "par_etat": {e: etats[e] for e in ETATS_EXIGENCE},
        "par_priorite": {p: {e: c[e] for e in ETATS_EXIGENCE} for p, c in par_priorite.items()},
        "par_domaine": {d: {e: c[e] for e in ETATS_EXIGENCE} for d, c in sorted(par_domaine.items())},
        "illisibles": illisibles,
    }


def risques(texte: str) -> dict:
    """Risques traités : lignes `| R<n> |` ; un risque est traité quand son statut est Clos (un risque suspendu n'est pas traité)."""
    statuts: Counter[str] = Counter()
    illisibles, incomplets, total = [], [], 0
    for ligne in texte.splitlines():
        cases = cellules(ligne) if ligne.startswith("| R") else []
        if len(cases) < 8 or not RISQUE.match(cases[0]):
            continue
        total += 1
        statut = premier_mot(cases[-1], STATUTS_RISQUE)
        if not cases[4] or not cases[5]:
            incomplets.append(cases[0])  # un risque sans responsable ni action n'est pas accepté (mode d'emploi du registre)
        if statut is None:
            illisibles.append(cases[0])
        else:
            statuts[statut] += 1
    if total == 0:
        return {"traites": non_mesure("aucun risque lu dans le registre"), "par_statut": {}, "illisibles": [], "incomplets": []}
    lus = total - len(illisibles)
    return {
        "traites": mesure(statuts["Clos"], lus, total_lignes=total) if lus else non_mesure("aucun statut lisible"),
        "par_statut": {s: statuts[s] for s in STATUTS_RISQUE},
        "illisibles": illisibles,
        "incomplets": incomplets,
    }


def preuves_citees(corps: str | None) -> list[str]:
    """Les chemins cités dans la section « Preuve attendue » d'une issue (vide : la preuve n'est pas un fichier)."""
    trouve = PREUVE.search(corps or "")
    if not trouve:
        return []
    chemins = [c.rstrip(".,;:)") for c in CHEMIN.findall(trouve.group(1).replace("`", " "))]
    return [c for c in dict.fromkeys(chemins) if c.rstrip("/")]


def preuve_existe(chemin: str, arbre: set[str]) -> bool:
    if "*" in chemin:
        return any(fnmatch.fnmatch(p, chemin) for p in arbre)
    return chemin in arbre or any(p.startswith(chemin.rstrip("/") + "/") for p in arbre)


def classer_preuve(corps: str | None, arbre: set[str] | None) -> str:
    """`versionnee` (tous les chemins cités existent), `partielle`, `absente`, `non_verifiable` (aucun chemin cité ou arbre inconnu)."""
    chemins = preuves_citees(corps)
    if not chemins or arbre is None:
        return "non_verifiable"
    presents = sum(preuve_existe(c, arbre) for c in chemins)
    return "versionnee" if presents == len(chemins) else "absente" if presents == 0 else "partielle"


def livrables(jalons: list[dict], issues: list[dict], arbre: set[str] | None, aujourdhui: date) -> dict:
    """Une ligne par jalon : issues fermées sur total, et la preuve attendue des issues fermées."""
    lignes, introuvables = [], []
    for jalon in sorted(jalons, key=lambda j: j.get("due_on") or "9999"):
        siennes = [i for i in issues if (i.get("milestone") or {}).get("number") == jalon["number"]]
        fermees = [i for i in siennes if i["state"] == "closed"]
        echeance = (jalon.get("due_on") or "")[:10] or None
        en_retard = bool(echeance and date.fromisoformat(echeance) < aujourdhui and len(fermees) < len(siennes))
        preuves = Counter(classer_preuve(i.get("body"), arbre) for i in fermees)
        if arbre is not None:
            for i in fermees:
                manquants = [c for c in preuves_citees(i.get("body")) if not preuve_existe(c, arbre)]
                if manquants:
                    introuvables.append({"issue": i["number"], "titre": i["title"], "jalon": jalon["title"], "chemins": manquants})
        lignes.append({
            "jalon": jalon["title"], "echeance": echeance, "en_retard": en_retard,
            "issues": len(siennes), "fermees": len(fermees), "ouvertes": len(siennes) - len(fermees),
            "avancement": mesure(len(fermees), len(siennes)) if siennes else non_mesure("aucune issue dans ce jalon"),
            "preuves": {k: preuves[k] for k in ("versionnee", "partielle", "absente", "non_verifiable")},
            "ouvertes_p0": sorted(i["number"] for i in siennes if i["state"] == "open" and any(l["name"] == "prio:P0" for l in i.get("labels", []))),
        })
    sans_jalon = [i for i in issues if not i.get("milestone")]
    total_issues = sum(l["issues"] for l in lignes)
    return {
        "global": mesure(sum(l["fermees"] for l in lignes), total_issues) if total_issues else non_mesure("aucune issue"),
        "jalons": lignes,
        "sans_jalon": len(sans_jalon),
        "preuves_verifiees": arbre is not None,
        "preuves_introuvables": sorted(introuvables, key=lambda x: x["issue"]),
    }


# --------------------------------------------------------------------------- calcul
def calculer(source, fichiers_locaux: bool = False, aujourdhui: date | None = None, racine: Path = RACINE) -> dict:
    """Les trois indicateurs. Une source injoignable donne un indicateur « non mesuré » avec sa raison, jamais un zéro."""
    aujourdhui = aujourdhui or datetime.now(UTC).date()
    erreurs: dict[str, str] = {}

    def lire(chemin: str) -> str | None:
        try:
            return (racine / chemin).read_text(encoding="utf-8") if fichiers_locaux else source.fichier(chemin)
        except (ErreurSource, OSError, UnicodeDecodeError) as erreur:
            erreurs[chemin] = str(erreur)
            return None

    texte_exigences, texte_risques = lire(EXIGENCES), lire(RISQUES)
    sortie: dict = {"depot": getattr(source, "depot", DEPOT), "ref": "copie de travail" if fichiers_locaux else getattr(source, "ref", "?"),
                    "calcule_le": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "erreurs": erreurs}
    sortie["exigences"] = exigences(texte_exigences) if texte_exigences is not None else {"verifiees": non_mesure(erreurs[EXIGENCES]), "par_etat": {}, "illisibles": []}
    sortie["risques"] = risques(texte_risques) if texte_risques is not None else {"traites": non_mesure(erreurs[RISQUES]), "par_statut": {}, "illisibles": [], "incomplets": []}
    try:
        jalons, issues = source.jalons(), source.issues()
        try:
            arbre: set[str] | None = source.arbre()
        except ErreurSource as erreur:
            erreurs["arbre"] = str(erreur)
            arbre = None
        sortie["livrables"] = livrables(jalons, issues, arbre, aujourdhui)
    except ErreurSource as erreur:
        erreurs["issues"] = str(erreur)
        sortie["livrables"] = {"global": non_mesure(str(erreur)), "jalons": [], "sans_jalon": 0, "preuves_verifiees": False, "preuves_introuvables": []}
    return sortie


# --------------------------------------------------------------------------- présentation
def texte_mesure(m: dict) -> str:
    if not m["mesure"]:
        return f"**non mesuré** ({m['raison']})"
    return f"{m['valeur']} sur {m['sur']} ({str(m['pourcentage']).replace('.', ',')} %)"


def markdown(r: dict) -> str:
    e, k, lv = r["exigences"], r["risques"], r["livrables"]
    sortie = [f"Mesures du **{r['calcule_le']}**, dépôt `{r['depot']}`, fichiers lus à : **{r['ref']}**.", ""]
    sortie += ["| Indicateur | Valeur | Ce que dit un zéro |", "|---|---|---|",
               f"| Exigences vérifiées (état « Prouvé ») | {texte_mesure(e['verifiees'])} | 0 prouvée : aucune exigence n'a sa preuve exécutée |",
               f"| Risques traités (statut « Clos ») | {texte_mesure(k['traites'])} | 0 clos : aucun risque n'a disparu ; ce n'est pas l'absence de risque |",
               f"| Livrables : issues fermées, tous jalons | {texte_mesure(lv['global'])} | 0 fermée : rien n'est livré |", ""]
    if e["par_etat"]:
        sortie += ["### Exigences par état", "", "| Priorité | Prouvé | Partiel | À faire |", "|---|---|---|---|"]
        sortie += [f"| {p} | {c['Prouvé']} | {c['Partiel']} | {c['À faire']} |" for p, c in e["par_priorite"].items()]
        sortie += [f"| **Toutes** | **{e['par_etat']['Prouvé']}** | **{e['par_etat']['Partiel']}** | **{e['par_etat']['À faire']}** |", ""]
        if e["illisibles"]:
            sortie += [f"État illisible (non compté) : {', '.join(e['illisibles'])}.", ""]
    if k["par_statut"]:
        sortie += ["### Risques par statut", "", "| Ouvert | Suspendu | Clos |", "|---|---|---|",
                   f"| {k['par_statut']['Ouvert']} | {k['par_statut']['Suspendu']} | {k['par_statut']['Clos']} |", ""]
        if k["illisibles"]:
            sortie += [f"Statut illisible (non compté) : {', '.join(k['illisibles'])}.", ""]
        if k["incomplets"]:
            sortie += [f"Sans responsable ou sans action : {', '.join(k['incomplets'])}.", ""]
    if lv["jalons"]:
        sortie += ["### Livrables par jalon", "", "| Jalon | Échéance | Fermées / total | Avancement | Preuves des issues fermées (versionnée / partielle / absente / non vérifiable) | P0 ouvertes |", "|---|---|---|---|---|---|"]
        for j in lv["jalons"]:
            p = j["preuves"]
            if not lv["preuves_verifiees"]:
                preuves = "non mesuré (arbre des fichiers illisible)"
            elif j["fermees"] == 0:
                preuves = "non mesuré (aucune issue fermée)"  # zéro issue fermée : il n'y a rien à compter, ce n'est pas « 0 preuve »
            else:
                preuves = f"{p['versionnee']} / {p['partielle']} / {p['absente']} / {p['non_verifiable']}"
            sortie.append(f"| {j['jalon']} | {j['echeance'] or '—'}{' **en retard**' if j['en_retard'] else ''} | {j['fermees']} / {j['issues']} | {texte_mesure(j['avancement'])} | {preuves} | {', '.join('#' + str(n) for n in j['ouvertes_p0']) or '0'} |")
        sortie += ["", f"Issues sans jalon : {lv['sans_jalon']}."]
        if lv["preuves_introuvables"]:
            sortie += ["", "### Preuves citées par une issue fermée et introuvables à cette révision", "", "| Issue | Jalon | Chemin cité |", "|---|---|---|"]
            sortie += [f"| #{x['issue']} {x['titre'][:60]} | {x['jalon'].split(' · ')[0]} | {', '.join('`' + c + '`' for c in x['chemins'])} |" for x in lv["preuves_introuvables"]]
    if r["erreurs"]:
        sortie += ["", "### Sources en défaut", ""] + [f"- `{cle}` : {message}" for cle, message in r["erreurs"].items()]
    return "\n".join(sortie).rstrip() + "\n"


def mettre_a_jour(document: Path, bloc: str) -> None:
    """Remplace ce qui est entre les deux repères du document ; le reste n'est pas touché. UTF-8, fins de ligne LF."""
    texte = document.read_text(encoding="utf-8")
    if DEBUT not in texte or FIN not in texte or texte.index(DEBUT) > texte.index(FIN):
        raise SystemExit(f"Repères {DEBUT} et {FIN} introuvables dans {document}")
    avant, reste = texte.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    with document.open("w", encoding="utf-8", newline="\n") as fichier:
        fichier.write(f"{avant}{DEBUT}\n{bloc}{FIN}{apres}")


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("--ref", default="main", help="branche, étiquette ou empreinte lue sur GitHub (défaut : main)")
    analyseur.add_argument("--local", action="store_true", help="lire exigences.md et registre-risques.md dans la copie de travail")
    analyseur.add_argument("--json", action="store_true", help="sortie JSON")
    analyseur.add_argument("--ecrire", action="store_true", help=f"met à jour le bloc mesuré de {DOCUMENT.relative_to(RACINE).as_posix()}")
    args = analyseur.parse_args(argv)
    source = GitHub(ref=args.ref, jeton=os.environ.get("GITHUB_TOKEN") or None)
    resultat = calculer(source, fichiers_locaux=args.local)
    bloc = json.dumps(resultat, ensure_ascii=False, indent=2) + "\n" if args.json else markdown(resultat)
    if args.ecrire:
        mettre_a_jour(DOCUMENT, markdown(resultat))
        print(f"{DOCUMENT.relative_to(RACINE).as_posix()} mis à jour.")
    else:
        sys.stdout.buffer.write(bloc.encode("utf-8"))
    return 1 if resultat["erreurs"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
