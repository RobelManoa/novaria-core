"""Le convertisseur Markdown du site (scripts/dev/site_docs.py) : ce qu'il sait faire, sans navigateur ni réseau.

    Linux : python3 -m unittest scripts/dev/test_site_docs.py      Windows : py -3 -m unittest scripts/dev/test_site_docs.py
"""

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_docs  # noqa: E402


def rendre(markdown: str, chemin: str = "docs/a/un.md", inclus=("docs/a/un.md", "docs/b/autre.md"), diagrammes=None):
    ctx = site_docs.Contexte(chemin, set(inclus), diagrammes or {})
    html, sommaire, titre = site_docs.rendre(markdown, ctx)
    return html, sommaire, titre, ctx


class Blocs(unittest.TestCase):
    def test_titres_identifiants_et_sommaire(self):
        html, sommaire, titre, _ = rendre("# Mon titre `x`\n\n## 4. Référentiel du réseau (`dwh.dim_*`)\n\n### 4.1 Clés\n\n## Répété\n\n## Répété\n")
        self.assertEqual(titre, "Mon titre x")
        self.assertIn('id="4-référentiel-du-réseau-dwhdim"', html)
        self.assertIn('id="répété-1"', html)
        self.assertEqual([s[0] for s in sommaire], [2, 3, 2, 2])

    def test_tableau_avec_barre_echappee_et_code(self):
        html, *_ = rendre("| A | B |\n|---|---|\n| `x\\|y` | **gras** |\n")
        self.assertIn("<th>A</th>", html)
        self.assertIn("<td><code>x|y</code></td>", html)
        self.assertIn("<strong>gras</strong>", html)

    def test_listes_imbriquees(self):
        html, *_ = rendre("- un\n  - sous un\n  - sous deux\n- deux\n\n1. premier\n2. second\n")
        self.assertIn("<ul><li>un<ul><li>sous un</li><li>sous deux</li></ul></li><li>deux</li></ul>", html)
        self.assertIn("<ol><li>premier</li><li>second</li></ol>", html)

    def test_code_et_citation_et_ligne(self):
        html, *_ = rendre("```bash\necho '<b>'\n```\n\n> une remarque\n\n---\n")
        self.assertIn("<code class=\"langue-bash\">echo '&lt;b&gt;'</code>", html)
        self.assertIn("<blockquote>une remarque</blockquote>", html)
        self.assertIn("<hr>", html)

    def test_le_texte_est_echappe(self):
        html, *_ = rendre("Du <script>alert(1)</script> et a < b & c\n")
        self.assertNotIn("<script", html)
        self.assertIn("&lt;script&gt;", html)

    def test_un_identifiant_avec_tiret_bas_n_est_pas_mis_en_italique(self):
        html, *_ = rendre("la table fact_traffic_window et _vraiment_ utile\n")
        self.assertIn("fact_traffic_window", html)
        self.assertIn("<em>vraiment</em>", html)


class Liens(unittest.TestCase):
    def test_lien_vers_un_document_du_lecteur(self):
        html, _, _, ctx = rendre("Voir [l'autre](../b/autre.md#section).")
        self.assertIn('data-doc="docs/b/autre.md" data-anc="section"', html)
        self.assertEqual(ctx.liens_hors_liste, [])

    def test_lien_dans_le_meme_document(self):
        html, *_ = rendre("[haut](#intro)")
        self.assertIn('data-doc="docs/a/un.md" data-anc="intro"', html)

    def test_lien_hors_lecteur_n_est_pas_cliquable(self):
        html, _, _, ctx = rendre("[code](../../services/x.py) et [guide](../c/inconnu.md)")
        self.assertNotIn("<a ", html)
        self.assertEqual(sorted(ctx.liens_hors_liste), ["docs/c/inconnu.md", "services/x.py"])

    def test_lien_externe_montre_son_adresse_sans_etre_un_lien(self):
        html, *_ = rendre("[Commons](https://commons.wikimedia.org/x)")
        self.assertNotIn("<a ", html)
        self.assertIn("(https://commons.wikimedia.org/x)", html)


class Diagrammes(unittest.TestCase):
    CODE = "flowchart LR\n  A --> B"

    def test_diagramme_dessine(self):
        empreinte = hashlib.sha256(self.CODE.encode("utf-8")).hexdigest()[:16]
        html, _, _, ctx = rendre(f"```mermaid\n{self.CODE}\n```\n", diagrammes={empreinte: "<svg></svg>"})
        self.assertIn('<figure class="schema" role="img" aria-label="Diagramme"><svg></svg></figure>', html)
        self.assertEqual(ctx.diagrammes_sans_dessin, 0)

    def test_diagramme_sans_dessin_montre_son_texte(self):
        html, _, _, ctx = rendre(f"```mermaid\n{self.CODE}\n```\n")
        self.assertIn("schema texte", html)
        self.assertIn("A --&gt; B", html)
        self.assertEqual((ctx.diagrammes_total, ctx.diagrammes_sans_dessin), (1, 1))


class Contenu(unittest.TestCase):
    def test_les_references_sont_des_chemins_avec_ancre_facultative(self):
        contenu = {"scenes": [{"docs": ["a.md#x", "b.md"]}, {}], "jury": [{"docs": ["a.md"]}], "matrice": {"lignes": [["c", "d", "e", "f", ["b.md", "g.md"]], ["c", "d", "e", "f"]]}}
        self.assertEqual(site_docs.chemins(contenu), ["a.md", "b.md", "g.md"])


if __name__ == "__main__":
    unittest.main()
