#!/usr/bin/env python3
"""Convertit les documents Markdown cités par le site de soutenance en pages lisibles hors ligne (site/docs.js).

    Linux   : python3 scripts/dev/site_docs.py [--depuis DOSSIER ...] [--mermaid CHEMIN --playwright DOSSIER] [--verifier]
    Windows : py -3 scripts/dev/site_docs.py [--depuis DOSSIER ...] [--mermaid CHEMIN --playwright DOSSIER] [--verifier]

Principe (issue SIT-02, lecteur de preuves) :

- La liste des documents vient de `site/contenu.js` : champs `docs` des scènes, des questions du jury et des lignes de la
  matrice BC05 (un chemin du dépôt, avec une ancre facultative : `docs/…/fichier.md#section`). Rien n'est listé deux fois.
- Chaque document est lu tel quel (jamais réécrit), converti en HTML par un convertisseur Markdown restreint (bibliothèque
  standard), puis écrit dans `site/docs.js` avec son commit d'origine et l'empreinte de son contenu.
- Un document existe parfois dans plusieurs dossiers de travail (branches différentes) : on prend la version dont le
  dernier commit est le plus récent ; le rapport dit laquelle.
- Les diagrammes Mermaid sont dessinés une fois (SVG) par un navigateur sans interface et gardés dans
  `scripts/dev/site_docs_cache/diagrammes.json` ; sans ce dessin, le site montre le texte du diagramme.
- Le site reste statique : `docs.js` est commité, le site ne lit aucun dossier au moment de l'ouverture.
- `--verifier` ne change rien : il échoue si `docs.js` ne correspond plus aux fichiers sources trouvés.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SITE = RACINE / "site"
SORTIE = SITE / "docs.js"
CACHE = Path(__file__).resolve().parent / "site_docs_cache" / "diagrammes.json"
SCRIPT_MERMAID = Path(__file__).resolve().parent / "site_mermaid.mjs"


class ErreurDocs(Exception):
    pass


# --- liste des documents ----------------------------------------------------------------------------------


def contenu_du_site() -> dict:
    node = shutil.which("node")
    if node is None:
        raise ErreurDocs("Node.js est nécessaire pour lire site/contenu.js.")
    script = "global.window={};eval(require('fs').readFileSync(process.argv[1],'utf8'));console.log(JSON.stringify(window.CONTENU))"
    sortie = subprocess.run([node, "-e", script, str(SITE / "contenu.js")], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(sortie.stdout)


def references(contenu: dict) -> list[str]:
    """Toutes les références `chemin#ancre` du contenu, dans l'ordre de première apparition."""
    brutes: list[str] = []
    for scene in contenu["scenes"]:
        brutes += scene.get("docs", [])
    for question in contenu["jury"]:
        brutes += question.get("docs", [])
    for ligne in contenu["matrice"]["lignes"]:
        if len(ligne) > 4:
            brutes += ligne[4]
    return brutes


def chemins(contenu: dict) -> list[str]:
    vus: list[str] = []
    for reference in references(contenu):
        chemin = reference.partition("#")[0]
        if chemin not in vus:
            vus.append(chemin)
    return vus


# --- sources ----------------------------------------------------------------------------------------------


def dossiers_de_travail(demandes: list[str]) -> list[Path]:
    """Le dépôt courant d'abord, puis les dossiers donnés, sinon les voisins `Novaria-Core*`."""
    if demandes:
        candidats = [RACINE] + [Path(d).resolve() for d in demandes]
    else:
        candidats = [RACINE] + sorted(p for p in RACINE.parent.glob("Novaria-Core*") if p.is_dir())
    vus: list[Path] = []
    for dossier in candidats:
        if dossier not in vus and dossier.is_dir():
            vus.append(dossier)
    return vus


def git(dossier: Path, *arguments: str) -> str:
    resultat = subprocess.run(["git", "-C", str(dossier), *arguments], capture_output=True, text=True, check=False)
    return resultat.stdout.strip() if resultat.returncode == 0 else ""


def version_la_plus_recente(chemin: str, dossiers: list[Path]) -> tuple[Path, str, str, str]:
    """(dossier, texte, commit court, date) de la copie dont le dernier commit est le plus récent."""
    meilleure = None
    for dossier in dossiers:
        fichier = dossier / chemin
        if not fichier.is_file():
            continue
        entree = git(dossier, "log", "-1", "--format=%h|%cI", "--", chemin)
        commit, _, date = entree.partition("|")
        modifie = bool(git(dossier, "status", "--porcelain", "--", chemin))
        cle = date or "0"
        if meilleure is None or cle > meilleure[0]:
            meilleure = (cle, dossier, commit + (" (modifié)" if modifie else "") if commit else "non commité", date[:10])
    if meilleure is None:
        raise ErreurDocs(f"Document introuvable dans {', '.join(d.name for d in dossiers)} : {chemin}")
    _, dossier, commit, date = meilleure
    return dossier, (dossier / chemin).read_text(encoding="utf-8"), commit, date


# --- convertisseur Markdown restreint ---------------------------------------------------------------------


def echapper(texte: str) -> str:
    return html.escape(texte, quote=False)


def ancre(titre: str) -> str:
    """Identifiant d'un titre, à la manière de GitHub : minuscules, sans ponctuation, tirets."""
    sans_balises = re.sub(r"[`*_]", "", titre)
    return re.sub(r"[^\w\- ]", "", sans_balises.lower().strip()).replace(" ", "-")


class Contexte:
    def __init__(self, chemin: str, inclus: set[str], diagrammes: dict[str, str]):
        self.chemin = chemin
        self.inclus = inclus
        self.diagrammes = diagrammes
        self.liens_hors_liste: list[str] = []
        self.diagrammes_sans_dessin = 0
        self.diagrammes_total = 0
        self.constructions_non_gerees: list[str] = []


def lien(texte: str, url: str, ctx: Contexte) -> str:
    url = html.unescape(url)
    if re.match(r"https?://", url):
        return f'<span class="ext">{texte} <small>({echapper(url)})</small></span>'
    if url.startswith("mailto:"):
        return texte
    chemin, _, partie = url.partition("#")
    cible = ctx.chemin if not chemin else posixpath.normpath(posixpath.join(posixpath.dirname(ctx.chemin), chemin))
    if cible in ctx.inclus:
        return f'<a href="#" class="doc" data-doc="{echapper(cible)}" data-anc="{echapper(partie)}">{texte}</a>'
    ctx.liens_hors_liste.append(cible)
    return f'<span class="fichier" title="Fichier du dépôt, hors du lecteur : {echapper(cible)}">{texte}</span>'


def en_ligne(texte: str, ctx: Contexte) -> str:
    gardes: list[str] = []

    def garder(m: re.Match) -> str:
        gardes.append(f"<code>{echapper(m.group(2))}</code>")
        return f"\x00{len(gardes) - 1}\x00"

    t = re.sub(r"(`+)(.+?)\1", garder, texte)
    t = echapper(t)
    t = re.sub(r"&lt;(https?://[^&\s]+)&gt;", lambda m: f'<span class="ext"><small>{m.group(1)}</small></span>', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)", lambda m: lien(m.group(1), m.group(2), ctx), t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"(?<![\w])_(?![\s_])(.+?)(?<![\s_])_(?![\w])", r"<em>\1</em>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: gardes[int(m.group(1))], t)


MOTIF_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
MOTIF_SEPARATEUR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
MOTIF_TITRE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MOTIF_BARRE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def cellules(ligne: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", ligne.strip().strip("|"))]


def debut_de_bloc(ligne: str, suivante: str | None) -> bool:
    return bool(
        MOTIF_TITRE.match(ligne) or ligne.lstrip().startswith(("```", ">", "<!--")) or MOTIF_ITEM.match(ligne) or MOTIF_BARRE.match(ligne)
        or ("|" in ligne and suivante is not None and MOTIF_SEPARATEUR.match(suivante) and "|" in suivante)
    )


def rendre_liste(items: list[tuple[int, bool, str]], ctx: Contexte) -> str:
    sortie: list[str] = []
    pile: list[tuple[int, str]] = []  # (retrait, balise)
    for retrait, ordonnee, texte in items:
        balise = "ol" if ordonnee else "ul"
        while pile and retrait < pile[-1][0]:
            sortie.append("</li></%s>" % pile.pop()[1])
        if pile and retrait == pile[-1][0]:
            sortie.append("</li>")
        elif not pile or retrait > pile[-1][0]:
            sortie.append(f"<{balise}>")
            pile.append((retrait, balise))
        sortie.append("<li>" + en_ligne(texte, ctx))
    while pile:
        sortie.append("</li></%s>" % pile.pop()[1])
    return "".join(sortie)


def rendre(markdown: str, ctx: Contexte) -> tuple[str, list[list], str]:
    """(html, sommaire [[niveau, id, texte]], titre)."""
    lignes = markdown.replace("\r\n", "\n").split("\n")
    sortie: list[str] = []
    sommaire: list[list] = []
    identifiants: dict[str, int] = {}
    titre = ""
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        suivante = lignes[i + 1] if i + 1 < len(lignes) else None
        if not ligne.strip():
            i += 1
        elif ligne.lstrip().startswith("<!--"):
            while i < len(lignes) and "-->" not in lignes[i]:
                i += 1
            i += 1
        elif ligne.lstrip().startswith("```"):
            langue = ligne.strip()[3:].strip()
            i += 1
            bloc = []
            while i < len(lignes) and not lignes[i].lstrip().startswith("```"):
                bloc.append(lignes[i])
                i += 1
            i += 1
            code = "\n".join(bloc)
            if langue == "mermaid":
                ctx.diagrammes_total += 1
                empreinte = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
                svg = ctx.diagrammes.get(empreinte)
                if svg:
                    sortie.append(f'<figure class="schema" role="img" aria-label="Diagramme">{svg}</figure>')
                else:
                    ctx.diagrammes_sans_dessin += 1
                    sortie.append(f'<figure class="schema texte"><figcaption>Diagramme (texte Mermaid : le dessin n’est pas disponible)</figcaption><pre><code>{echapper(code)}</code></pre></figure>')
            else:
                classe = ' class="langue-' + echapper(langue) + '"' if langue else ""
                sortie.append(f"<pre><code{classe}>{echapper(code)}</code></pre>")
        elif (m := MOTIF_TITRE.match(ligne)):
            niveau, texte = len(m.group(1)), m.group(2)
            identifiant = ancre(texte)
            n = identifiants.get(identifiant, 0)
            identifiants[identifiant] = n + 1
            identifiant = identifiant if n == 0 else f"{identifiant}-{n}"
            if niveau == 1 and not titre:
                titre = re.sub(r"[`*]", "", texte)
            if 2 <= niveau <= 3:
                sommaire.append([niveau, identifiant, re.sub(r"[`*]", "", texte)])
            sortie.append(f'<h{niveau} id="{echapper(identifiant)}">{en_ligne(texte, ctx)}</h{niveau}>')
            i += 1
        elif MOTIF_BARRE.match(ligne):
            sortie.append("<hr>")
            i += 1
        elif "|" in ligne and suivante is not None and "|" in suivante and MOTIF_SEPARATEUR.match(suivante):
            entete = cellules(ligne)
            i += 2
            corps = []
            while i < len(lignes) and lignes[i].strip() and "|" in lignes[i]:
                corps.append(cellules(lignes[i]))
                i += 1
            html_table = "<div class=\"tableau\"><table><thead><tr>" + "".join(f"<th>{en_ligne(c, ctx)}</th>" for c in entete) + "</tr></thead><tbody>"
            for rang in corps:
                html_table += "<tr>" + "".join(f"<td>{en_ligne(c, ctx)}</td>" for c in rang) + "</tr>"
            sortie.append(html_table + "</tbody></table></div>")
        elif ligne.lstrip().startswith(">"):
            citation = []
            while i < len(lignes) and lignes[i].lstrip().startswith(">"):
                citation.append(re.sub(r"^\s*>\s?", "", lignes[i]))
                i += 1
            sortie.append("<blockquote>" + en_ligne(" ".join(citation), ctx) + "</blockquote>")
        elif MOTIF_ITEM.match(ligne):
            items: list[tuple[int, bool, str]] = []
            while i < len(lignes):
                courante = lignes[i]
                m = MOTIF_ITEM.match(courante)
                if m and items and len(m.group(1).expandtabs(4)) <= items[0][0] and m.group(2)[0].isdigit() != items[0][1]:
                    break  # une liste numérotée qui suit une liste à puces (ou l'inverse) est une autre liste
                if m:
                    items.append((len(m.group(1).expandtabs(4)), m.group(2)[0].isdigit(), m.group(3)))
                    i += 1
                elif courante.strip() and courante.startswith("  ") and items:  # suite d'un élément
                    retrait, ordonnee, texte = items[-1]
                    items[-1] = (retrait, ordonnee, texte + " " + courante.strip())
                    i += 1
                elif not courante.strip() and i + 1 < len(lignes) and (MOTIF_ITEM.match(lignes[i + 1]) or lignes[i + 1].startswith("  ")) and lignes[i + 1].strip():
                    i += 1
                else:
                    break
            sortie.append(rendre_liste(items, ctx))
        else:
            paragraphe = [ligne.strip()]
            i += 1
            while i < len(lignes) and lignes[i].strip() and not debut_de_bloc(lignes[i], lignes[i + 1] if i + 1 < len(lignes) else None):
                paragraphe.append(lignes[i].strip())
                i += 1
            texte = " ".join(paragraphe)
            if re.match(r"^<[a-zA-Z/]", texte):
                ctx.constructions_non_gerees.append(texte[:60])
            sortie.append("<p>" + en_ligne(texte, ctx) + "</p>")
    return "\n".join(sortie), sommaire, titre


# --- diagrammes -------------------------------------------------------------------------------------------


def blocs_mermaid(markdown: str) -> list[str]:
    return [m.group(1).strip("\n") for m in re.finditer(r"^\s*```mermaid\s*\n(.*?)^\s*```", markdown.replace("\r\n", "\n"), re.S | re.M)]


def dessiner(codes: dict[str, str], mermaid: str, playwright: str) -> dict[str, str]:
    """Dessine chaque diagramme (empreinte -> code) dans un navigateur sans interface ; renvoie empreinte -> SVG."""
    if not codes:
        return {}
    temporaire = CACHE.parent / "entree.json"
    temporaire.parent.mkdir(exist_ok=True)
    temporaire.write_text(json.dumps(codes), encoding="utf-8")
    sortie = CACHE.parent / "sortie.json"
    try:
        resultat = subprocess.run(["node", str(SCRIPT_MERMAID), str(temporaire), str(sortie), mermaid, playwright], capture_output=True, text=True, timeout=300, check=False)
        if resultat.returncode != 0:
            raise ErreurDocs(f"Le dessin des diagrammes a échoué :\n{resultat.stdout}\n{resultat.stderr}")
        rendus = json.loads(sortie.read_text(encoding="utf-8"))
    finally:
        temporaire.unlink(missing_ok=True)
        sortie.unlink(missing_ok=True)
    for empreinte, valeur in rendus.items():
        if not valeur.get("svg"):
            print(f"  diagramme {empreinte} : non dessiné ({valeur.get('erreur', 'erreur inconnue')[:120]})")
    return {e: v["svg"] for e, v in rendus.items() if v.get("svg")}


# --- programme --------------------------------------------------------------------------------------------


def construire(depuis: list[str], mermaid: str | None, playwright: str | None) -> tuple[dict, list[str]]:
    contenu = contenu_du_site()
    liste = chemins(contenu)
    dossiers = dossiers_de_travail(depuis)
    inclus = set(liste)
    rapport = [f"Dossiers lus : {', '.join(d.name for d in dossiers)}"]

    sources = {c: version_la_plus_recente(c, dossiers) for c in liste}
    cache: dict[str, str] = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}
    manquants = {}
    for chemin, (_, texte, _, _) in sources.items():
        for code in blocs_mermaid(texte):
            empreinte = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
            if empreinte not in cache:
                manquants[empreinte] = code
    if manquants and mermaid and playwright:
        rapport.append(f"Diagrammes à dessiner : {len(manquants)}")
        cache.update(dessiner(manquants, mermaid, playwright))
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

    documents: dict[str, dict] = {}
    for chemin in liste:
        dossier, texte, commit, date = sources[chemin]
        ctx = Contexte(chemin, inclus, cache)
        corps, sommaire, titre = rendre(texte, ctx)
        documents[chemin] = {
            "titre": titre or Path(chemin).stem,
            "commit": commit,
            "date": date,
            "sha256": hashlib.sha256(texte.encode("utf-8")).hexdigest(),
            "toc": sommaire,
            "html": corps,
        }
        cloud = len(re.findall(r"\b(aws|amazon|cloudwatch|terraform)\b", texte, re.I))
        rapport.append(
            f"  {chemin:<62} {len(texte) // 1024:>3} Ko  {dossier.name:<19} {commit:<14} diagrammes {ctx.diagrammes_total - ctx.diagrammes_sans_dessin}/{ctx.diagrammes_total}"
            f"  liens hors lecteur {len(set(ctx.liens_hors_liste))}  mentions cloud {cloud}"
            + (f"  HTML brut non géré {len(ctx.constructions_non_gerees)}" if ctx.constructions_non_gerees else "")
        )
    return documents, rapport


def ecrire(documents: dict) -> str:
    return "/* Généré par scripts/dev/site_docs.py à partir des documents du dépôt : ne pas modifier à la main. */\nwindow.DOCS = " + json.dumps(documents, ensure_ascii=False, separators=(",", ":")) + ";\n"


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Convertit les documents Markdown cités par le site en pages hors ligne.")
    parseur.add_argument("--depuis", action="append", default=[], help="dossier de travail supplémentaire où chercher les documents (répétable)")
    parseur.add_argument("--mermaid", help="chemin de mermaid.min.js (pour dessiner les diagrammes absents du cache)")
    parseur.add_argument("--playwright", help="dossier qui contient node_modules/playwright-core")
    parseur.add_argument("--verifier", action="store_true", help="ne rien écrire ; échouer si site/docs.js n'est plus celui des sources")
    arguments = parseur.parse_args(argv)
    try:
        documents, rapport = construire(arguments.depuis, arguments.mermaid, arguments.playwright)
    except ErreurDocs as erreur:
        print(erreur, file=sys.stderr)
        return 1
    texte = ecrire(documents)
    print("\n".join(rapport))
    if arguments.verifier:
        actuel = SORTIE.read_text(encoding="utf-8") if SORTIE.is_file() else ""
        if actuel != texte:
            print("site/docs.js n'est plus celui des sources : relancer scripts/dev/site_docs.py", file=sys.stderr)
            return 1
        print("site/docs.js correspond aux sources.")
        return 0
    SORTIE.write_text(texte, encoding="utf-8", newline="\n")
    print(f"\n{len(documents)} documents, {len(texte) // 1024} Ko écrits dans {SORTIE.relative_to(RACINE).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
