"""Chaque document technique donne les commandes Linux ET Windows (ADR-026, règle 3 ; CLAUDE.md, section 1 ; DOC-11).

Le test lit tous les fichiers Markdown suivis par Git et cherche, passage par passage (une ligne de tableau, un paragraphe, un
bloc de code), une commande écrite pour un seul système :

- une commande lancée par `python3 …` sans sa variante Windows (`py -3 …`) dans le même passage ;
- une commande lancée par `py -3 …` sans sa variante Linux (`python3 …`, `make …`) dans le même passage ;
- une habitude propre à bash (`source …/bin/activate`, `export X=…`, `sudo`, `sha256sum`, `grep`, `cat`, `curl -H …`) sans sa
  variante PowerShell dans le même passage.

Un tableau à colonnes Linux et Windows est jugé ligne par ligne : une ligne qui ne remplit qu'une colonne est refusée.

Ce test est une heuristique, pas une preuve : il ne sait pas si la commande de la colonne Windows marche (voir « non vérifié » dans
les documents). Les fichiers qui **rapportent** une exécution passée sous un seul système (journaux d'essai, tableaux de relecture)
sont listés dans EXEMPTES, avec la raison.
"""

import re
import subprocess
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

# Documents qui citent un relevé d'exécution sous un système précis (preuve datée, pas une procédure) ou qui présentent l'identité
# d'un membre du binôme.
EXEMPTES = {
    "CLAUDE.md": "tableau d'identité des deux membres (une ligne par système)",
    "docs/03-donnees/preuve-loc-02-mongodb.md": "journal d'une exécution réelle sous Windows",
    "docs/03-donnees/revue-croisee-dat-10.md": "relevé daté des essais de la relecture, un système par ligne",
    "docs/ia/journal-usage-ia.md": "journal d'usage de l'IA : prose et compte rendu, pas une procédure",
    "docs/ia/prompt-modele-issue.md": "gabarit de prompt",
}

LINUX = re.compile(r"(?<![\w./-])python3 (?:-m |scripts/|ml/|data/|contracts/|simulator/|services/|gateway/|automation/|infra/)")
WINDOWS = re.compile(r"(?<![\w./-])py -3 (?:-m |[\w.-]+[/\\])")
BASH_ISME = re.compile(
    r"source [\w./-]*activate|(?<![\w$])export [A-Z_]+=|\bsudo \w+|\bsha256sum\b|(?:^|[|`]\s*)grep [-\"']|\bcat [\w./-]+\b|\bcurl (?!\.exe)[^`\n|]*(?:-H|-d|--data)"
)
# Un passage qui contient l'un de ces mots a une variante pour l'autre système (ou dit que la commande est la même).
MARQUES_WINDOWS = re.compile(r"py -3\b|PowerShell|Windows|\$env:|Get-[A-Z]|Invoke-[A-Z]|Select-String|Out-File|\.ps1|curl\.exe|idem|identique|même commande")
MARQUES_LINUX = re.compile(r"python3\b|Linux|bash|`make |\bmake [a-z]|\bsudo\b|\./[\w./-]+\.sh|\bpip3? install")
# Blocs de code jugés : ceux qu'une personne tape dans un terminal. Un bloc yaml, json, text, mermaid ou sql montre un fichier ou une sortie.
LANGAGES_DE_TERMINAL = {"", "bash", "sh", "shell", "console", "powershell", "pwsh", "ps1"}


def fichiers_markdown() -> list[str]:
    sortie = subprocess.run(["git", "ls-files", "*.md"], cwd=RACINE, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return sorted(f for f in sortie.splitlines() if "node_modules" not in f and f not in EXEMPTES)


def passages(texte: str) -> list[tuple[int, str, bool]]:
    """(numéro de ligne, texte, est_une_ligne_de_tableau). Un tableau donne une entrée par ligne ; le reste, une par paragraphe ou bloc."""
    lignes = texte.split("\n")
    sortie: list[tuple[int, str, bool]] = []
    i = 0
    while i < len(lignes):
        if lignes[i].strip().startswith("```"):
            langage = lignes[i].strip().removeprefix("```").strip().lower()
            j = i + 1
            while j < len(lignes) and not lignes[j].strip().startswith("```"):
                j += 1
            if langage not in LANGAGES_DE_TERMINAL:
                i = j + 1
                continue
            # Un bloc de code est jugé avec les deux lignes qui le précèdent et la suivante (la phrase qui l'annonce ou le commente).
            contexte = lignes[max(0, i - 2) : i] + lignes[i : j + 2]
            sortie.append((i + 1, "\n".join(contexte), False))
            i = j + 1
            continue
        if not lignes[i].strip():
            i += 1
            continue
        if lignes[i].lstrip().startswith("|"):
            while i < len(lignes) and lignes[i].lstrip().startswith("|"):
                sortie.append((i + 1, lignes[i], True))
                i += 1
            continue
        j = i
        while j < len(lignes) and lignes[j].strip() and not lignes[j].strip().startswith("```") and not lignes[j].lstrip().startswith("|"):
            j += 1
        sortie.append((i + 1, "\n".join(lignes[i:j]), False))
        i = j
    return sortie


def anomalies(texte: str) -> list[str]:
    trouvees = []
    for numero, passage, _ in passages(texte):
        if LINUX.search(passage) and not MARQUES_WINDOWS.search(passage):
            trouvees.append(f"ligne {numero} : commande `python3` sans variante Windows : {passage.strip().splitlines()[0][:110]}")
        elif WINDOWS.search(passage) and not MARQUES_LINUX.search(passage):
            trouvees.append(f"ligne {numero} : commande `py -3` sans variante Linux : {passage.strip().splitlines()[0][:110]}")
        elif BASH_ISME.search(passage) and not MARQUES_WINDOWS.search(passage):
            trouvees.append(f"ligne {numero} : habitude bash sans variante PowerShell : {passage.strip().splitlines()[0][:110]}")
    return trouvees


class DeuxVariantes(unittest.TestCase):
    def test_chaque_document_technique_donne_les_deux_variantes(self):
        problemes = []
        for fichier in fichiers_markdown():
            texte = (RACINE / fichier).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            problemes += [f"{fichier}: {p}" for p in anomalies(texte)]
        self.assertEqual(problemes, [], "\n" + "\n".join(problemes))

    def test_les_exemptions_existent_et_ont_une_raison(self):
        for fichier, raison in EXEMPTES.items():
            self.assertTrue((RACINE / fichier).exists(), f"{fichier} n'existe plus : retirer l'exemption")
            self.assertGreater(len(raison), 15, f"raison trop courte pour {fichier}")

    # --- le détecteur lui-même : sans ces essais, un détecteur qui ne trouve jamais rien passerait pour correct -------------------
    def test_il_voit_une_commande_linux_seule(self):
        self.assertTrue(anomalies("Lancer `python3 scripts/dev/dev.py up`."))

    def test_il_voit_une_commande_windows_seule(self):
        self.assertTrue(anomalies("| Tout démarrer | `py -3 scripts/dev/dev.py up` |"))

    def test_il_voit_une_habitude_bash_seule(self):
        self.assertTrue(anomalies("| Activer | `source .venv/bin/activate` |"))
        self.assertTrue(anomalies("```bash\nexport JWT_SECRET=x\n```"))

    def test_il_accepte_les_deux_variantes_dans_la_meme_ligne(self):
        self.assertEqual(anomalies("| Démarrer | `python3 scripts/dev/dev.py up` | `py -3 scripts/dev/dev.py up` |"), [])
        self.assertEqual(anomalies("`python3 scripts/dev/dev.py up` (Linux) ou `py -3 scripts/dev/dev.py up` (Windows)"), [])

    def test_un_tableau_est_juge_ligne_par_ligne(self):
        tableau = "| Action | Linux (bash) | Windows (PowerShell) |\n|---|---|---|\n| A | `python3 scripts/dev/dev.py a` | `py -3 scripts/dev/dev.py a` |\n| B | `python3 scripts/dev/dev.py b` | |"
        trouvees = anomalies(tableau)
        self.assertEqual(len(trouvees), 1, trouvees)
        self.assertIn("ligne 4", trouvees[0])

    def test_un_bloc_de_code_est_juge_avec_la_phrase_qui_l_annonce(self):
        self.assertEqual(anomalies("Sous Linux comme sous Windows (`py -3`) :\n\n```bash\npython3 scripts/dev/dev.py up\n```"), [])
        self.assertTrue(anomalies("Lancer :\n\n```bash\npython3 scripts/dev/dev.py up\n```"))


if __name__ == "__main__":
    unittest.main()
