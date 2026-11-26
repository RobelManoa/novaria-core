# Site de soutenance : Behind the Intelligence

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Issue : SIT-02 (plan : [site-plan.md](../docs/09-soutenance/site-plan.md), SIT-01)
Dernière mise à jour : 26/11/2026

Une page unique, statique (HTML, CSS, JavaScript), qui raconte Novaria Core en sept parties et 20 minutes. Elle s'ouvre **hors ligne** : aucune ressource externe n'est chargée, aucun service tiers n'est appelé, aucune construction n'est nécessaire.

Abréviations : BC05 (bloc de compétences 5 : données décisionnelles et intelligence artificielle), ADR (Architecture Decision Record, fiche de décision d'architecture), PDF (Portable Document Format).

## 1. Ouvrir le site

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Ouvrir la page | `xdg-open site/index.html` | `Start-Process site/index.html` |
| Ou la servir en local (port 8095) | `python3 -m http.server 8095 --directory site` | `py -3 -m http.server 8095 --directory site` |
| Adresse du serveur local | `http://127.0.0.1:8095/` | `http://127.0.0.1:8095/` |
| Tester le site (sans navigateur) | `python3 -m unittest scripts/dev/test_site.py` | `py -3 -m unittest scripts/dev/test_site.py` |

Le double-clic sur `index.html` suffit : le contenu est du JavaScript (`contenu.js`), pas du JSON chargé par le réseau, pour que `file://` fonctionne.

## 2. Se servir du site

| Touche | Effet |
|---|---|
| Défilement ou flèches gauche et droite | Avancer ou reculer d'une scène |
| `J` | Menu « Questions du jury » : chaque question mène à la scène et ouvre ses documents |
| `L` | Lexique : sigles, mots techniques et vocabulaire du projet |
| `P` | Mode orateur : notes de la scène en cours et chronomètre (20:00) |
| `T` | Thème : système, sombre, clair |
| `Échap` | Fermer le menu ou le mode orateur |

Sous chaque scène, le tiroir « Preuves et limites » donne les fichiers du dépôt qui prouvent ce qui est dit, et ce qu'il faut reconnaître ; les documents s'y lisent dans le site (section 3). Les sections « Démonstration » (captures de secours, commandes de la pile locale) et « BC05 » (neuf compétences, niveau, preuve) suivent le film.

## 3. Lire les documents dans le site

Une question du jury, un tiroir de scène ou une ligne de la matrice BC05 ouvre **une page de lecture** qui réunit tous les documents concernés : liste à gauche (avec le sommaire du document ouvert), texte à droite. Une question qui a plusieurs documents les montre tous sur la même page.

| Geste | Effet |
|---|---|
| Question du jury (menu `J`) | Va à la scène, ouvre la page des documents de la question, à la bonne section |
| Bouton « Tout lire » ou une puce, dans le tiroir de la scène | Même page, pour les documents de la scène |
| Bouton « Lire » d'une ligne BC05 | Même page, pour cette compétence |
| Lien d'un document vers un autre document du lecteur | Ouvre ce document dans la même page ; « ← Retour » revient |
| `Échap` | Ferme la page |

Les documents sont les fichiers du dépôt, **sans réécriture** : chaque page affiche le chemin du fichier et le commit dont elle est la copie. Les liens vers un fichier absent du lecteur (code, autre document) restent du texte pointillé. Les diagrammes Mermaid sont dessinés une fois (SVG).

| Action | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Régénérer `site/docs.js` après un changement de `docs` dans `contenu.js` ou d'un document | `python3 scripts/dev/site_docs.py` | `py -3 scripts/dev/site_docs.py` |
| Chercher aussi dans d'autres dossiers de travail | `python3 scripts/dev/site_docs.py --depuis ../Novaria-Core` | `py -3 scripts/dev/site_docs.py --depuis ..\Novaria-Core` |
| Dessiner de nouveaux diagrammes (Node.js, Playwright, mermaid.min.js) | `python3 scripts/dev/site_docs.py --mermaid CHEMIN/mermaid.min.js --playwright citizen` | `py -3 scripts/dev/site_docs.py --mermaid CHEMIN\mermaid.min.js --playwright citizen` |
| Vérifier que `docs.js` est à jour (ne change rien) | `python3 scripts/dev/site_docs.py --verifier` | `py -3 scripts/dev/site_docs.py --verifier` |
| Tester | `python3 -m unittest scripts/dev/test_site_docs.py scripts/dev/test_site.py` | `py -3 -m unittest scripts/dev/test_site_docs.py scripts/dev/test_site.py` |

Pour ajouter un document : le citer dans le champ `docs` (chemin du dépôt, ancre facultative `#section`) d'une scène, d'une question ou d'une ligne BC05 de `contenu.js`, puis régénérer. Un document qui parle du cloud doit être inscrit dans `DOCUMENTS_AVEC_MENTION_CLOUD` de `test_site.py` : c'est une décision du binôme.

Le dessin des diagrammes est gardé dans `scripts/dev/site_docs_cache/diagrammes.json` : régénérer sans Node.js reprend ce cache. La bibliothèque Mermaid n'est pas dans le dépôt.

## 4. Lexique

Le bouton « Lexique » (ou la touche `L`) ouvre une page de **256 termes** : les sigles employés dans le projet avec leur forme développée, les mots techniques et le vocabulaire propre à Novaria (carrefour, tronçon, hystérésis, épisode…). Il ne remplace pas le dictionnaire de données du dépôt, qui décrit les tables et les colonnes (il s'ouvre depuis les termes « Carrefour », « Tronçon » et « Capteur »).

| Fonction | Détail |
|---|---|
| Recherche | Par terme, forme développée, définition ; sans tenir compte des accents ni des majuscules ; le terme cherché passe en premier |
| Thèmes | Projet et gestion · Architecture et exploitation · Données · Intelligence artificielle · Sécurité et qualité · Application citoyenne · Tests et preuves |
| Index | Une lettre mène au début de sa section |
| « Dans Novaria » | Ce que le terme est dans le projet : port, valeur, seuil, résultat |
| « Lire · … » | Ouvre le document du projet qui le définit, dans le lecteur de documents (section 3) |
| « Voir aussi » | Saute à un terme voisin |

Pour ajouter un terme : une entrée dans `lexique.js` (`t` le terme, `l` la forme développée, `c` le thème, `d` la définition, `p` ce que c'est dans Novaria, `docs` les documents, `v` les termes voisins, `a` d'autres écritures). `scripts/dev/test_site.py` vérifie : aucun doublon, aucun renvoi mort, chaque document présent dans le lecteur, **chaque sigle employé dans le site défini**, et aucun terme du cloud (choix du binôme, comme pour le film).

Les définitions du projet (états, seuils, règles de qualité, conditions A1 à A5, chiffres) reprennent les documents du dépôt ; les définitions générales (HTTP, SQL, Docker…) sont courantes. Ce lexique ne couvre pas les sigles propres au cloud : leur définition est dans les documents du dossier `docs/05-cloud-aws/`.

## 5. Organisation

| Fichier | Rôle |
|---|---|
| `index.html` | Squelette : en-tête, emplacements des scènes, menus |
| `contenu.js` | **Tout le contenu** : textes, chiffres, preuves, questions du jury, temps de chaque scène |
| `lexique.js` | Le lexique : sigles, mots techniques, vocabulaire (entrées éditables à la main) |
| `docs.js` | **Généré** (`scripts/dev/site_docs.py`) : les documents du dépôt lisibles dans le site ; ne pas modifier à la main |
| `app.js` | Comportement : défilement, scènes, menus, chronomètre, page de lecture des documents |
| `style.css` | Mise en page, thèmes clair et sombre, impression |
| `assets/` | Captures de l'application et photo du capteur |

Pour changer un texte ou un chiffre : modifier `contenu.js` seulement. Chaque chiffre de la scène « L'intelligence » vient de `ml/evaluation/` ; `scripts/dev/test_site.py` vérifie qu'il y est encore.

## 6. Honnêteté sur les données

- Un bandeau « Données simulées ou historiques » reste visible en bas de l'écran.
- La ville de l'application est fictive (simulateur). La mesure de la scène 2 est un vrai capteur de METR-LA (Los Angeles, 2012), dont la licence n'est pas établie : le site ne contient **aucune donnée** de ce jeu, seulement une valeur citée.
- La photo de la scène 2 est un exemple du principe d'un capteur à boucle inductive, pas le capteur de METR-LA.

## 7. Crédits

| Élément | Source | Licence |
|---|---|---|
| `assets/capteur-boucle.jpg` | Louis van Senden, [Inductive_Loop_Traffic_Counter.jpg](https://commons.wikimedia.org/wiki/File:Inductive_Loop_Traffic_Counter.jpg), Wikimedia Commons | CC BY-SA 4.0 : mention de l'auteur obligatoire, image **non modifiée** (le test compare son empreinte) |
| Captures de l'application et du tableau de bord | Ce dépôt (`docs/Capture d'ecran/`) | Celle du dépôt (non fixée) |

La licence CC BY-SA 4.0 s'applique à la photo seule. Si elle est un jour recadrée ou retouchée, l'image modifiée doit rester sous CC BY-SA 4.0.

## 8. Produire un PDF

La feuille de style d'impression met tout à plat, en clair, avec les tiroirs ouverts. Ouvrir la page dans un navigateur, puis Imprimer, destination « Enregistrer au format PDF ».

## 9. Non vérifié

| Sujet | État |
|---|---|
| Windows | Non essayé : les commandes ci-dessus sont celles de PowerShell, sans essai |
| Navigateurs | Essayé dans le navigateur de l'application seulement (Chromium) |
| Vidéoprojecteur et poste de soutenance | Non essayés (SIT-03) |
| Lecteur d'écran | Non essayé |
| Impression en PDF | Non essayée (la page de lecture est masquée à l'impression) |
| Documents du lecteur | Copies de plusieurs branches : plusieurs documents (partie citoyenne) ne sont pas encore dans `main` ; leur commit est affiché dans la page |
| Liens entre documents | Les liens vers un fichier hors lecteur sont du texte ; aucun lien mort n'est cliquable |
| Diagrammes | Dessinés par Mermaid 11.17.2 dans Chromium ; non relus un à un |
| Lexique | Définitions relues contre les documents pour les termes du projet ; les définitions générales sont de mémoire ; une trentaine de codes rares (secrets S1 à S7, numéros de jalons ou de risques au-delà de ceux cités) ne sont pas définis ; page non relue par Daddy Luciano |
