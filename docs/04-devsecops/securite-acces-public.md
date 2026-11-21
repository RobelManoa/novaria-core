# Sécurité de l'accès public (application citoyenne)

Projet : Novaria Core, socle d'UrbanHub (bloc de compétences BC05)
Responsable : Daddy Luciano (issue CIT-06), préparé par Manoa Robel, relecture croisée à faire
Dernière mise à jour : 21/11/2026
Issue de suivi : CIT-06 (#274), dépend de CIT-03 (#271) · Décision : [ADR-030](../01-architecture/adr/ADR-030-application-citoyenne-perimetre-et-acces.md) · Passerelle : [gateway/README.md](../../gateway/README.md)
Statut : à valider par les deux membres (relecture de la pull request)

Critère d'acceptation : **la matrice d'accès passe avec les routes citoyen ; aucun abus testé n'aboutit.** Preuve : la sortie de `dev.py acces` et de la CI (section 5).

> **Données simulées.** Tout ce que l'espace public renvoie vient du simulateur du dépôt (ADR-027).

Abréviations : **CORS** (Cross-Origin Resource Sharing, partage de ressources entre origines), **CI** (Continuous Integration, intégration continue), **API** (Application Programming Interface, interface de programmation), **IP** (Internet Protocol, ici l'adresse du client), **XFF** (en-tête `X-Forwarded-For`, adresse d'origine transmise par un relais), **njs** (JavaScript de nginx), **SSE** (Server-Sent Events, flux du serveur vers le navigateur), **RGPD** (Règlement général sur la protection des données).

## 1. En bref

| Tâche de l'issue | Réalisé | Où |
|---|---|---|
| Essais de refus : écriture, route interne, jeton d'équipe sur route publique, dépassement de débit | Déjà prouvés pour l'écriture, la route interne et le jeton d'équipe (CIT-02, famille « api public », 60 essais). **Ajout** : le dépassement de débit, joué sur la pile réelle (60 lectures d'affilée : 49 refusées en 429), et 19 autres abus | Sections 3 et 5 |
| En-têtes : CORS limité, pas de fuite d'erreur détaillée ; absence de secret dans le front | **CORS à part** pour l'espace public (liste dédiée, lecture seule, jamais le jeton d'équipe), prouvé dans un vrai navigateur ; erreurs au format commun sans détail interne (un défaut trouvé et corrigé : les réponses 400) ; aucune valeur secrète de `.env` dans le code livré | Sections 2, 3 et 4 |
| Étendre la matrice d'accès aux routes citoyen et la rejouer | Nouvelle famille **« api public (abus) »** de `dev.py acces` : 22 essais (3 témoins, 19 abus) | Section 5 |
| Scan Snyk et gitleaks verts sur le nouveau code | gitleaks : voir section 6 ; Snyk : **non exécutable en local** (jeton de compte), résultat de la CI à joindre | Section 6 |

## 2. Ce qui a changé dans la passerelle

| Sujet | Avant | Après (CIT-06) | Fichier |
|---|---|---|---|
| Origines CORS de l'espace public | Celles de l'équipe (`CORS_ALLOWED_ORIGINS`) : le tableau de bord pouvait lire l'espace public, l'application citoyenne n'avait aucune origine propre | **`CORS_PUBLIC_ORIGINS`** : seule liste qui vaut pour `/api/v1/public/`. L'origine de l'équipe n'y lit rien, l'origine citoyenne ne lit rien de l'API d'équipe | `gateway/auth.js`, `docker-compose.yml`, `.env.example` |
| Méthodes et en-têtes annoncés à la pré-vérification | `GET, POST, PATCH, OPTIONS` ; `Authorization, Content-Type, X-Correlation-ID` | Espace public : **`GET, OPTIONS`** et **aucun en-tête de requête** (donc pas `Authorization`) ; une pré-vérification qui demande une écriture ou un en-tête est refusée (403) | `gateway/auth.js` |
| Adresse du client dans le journal d'accès | Écrite pour toutes les routes | **Remplacée par `-`** pour l'espace public ; gardée pour l'API d'équipe | `gateway/nginx.conf` (`log_format passerelle_publique`) |
| Adresse du client transmise aux services (`X-Forwarded-For`) | Transmise pour toutes les routes | **Vide** pour l'espace public | `gateway/nginx.conf`, `gateway/upstream.conf` |
| Journal d'erreurs, refus de débit | Nommait l'adresse du client | Niveau `info` pour la zone citoyenne : **non écrit** | `gateway/citoyen.conf` |
| Réponse 400 (chemin non permis) | Sans `Cache-Control`, sans `nosniff` ni les autres en-têtes de sécurité (l'`if` du serveur ne peut pas poser d'en-têtes njs) | Passe par `@bad_request` : **mêmes en-têtes que toutes les erreurs** | `gateway/nginx.conf` |

Valeur par défaut de `CORS_PUBLIC_ORIGINS` (dans `docker-compose.yml`, sans rien changer à `.env`) : `http://127.0.0.1:5174,http://localhost:5174`, les deux adresses de l'application citoyenne du dépôt. Même règle que l'autre liste : origine exacte, jamais `*`, jamais de chemin.

## 3. Menaces et essais

| Abus tenté | Ce qui l'arrête | Essai (famille « api public (abus) » sauf mention) |
|---|---|---|
| Une page d'un site tiers lit l'espace public | Origine absente de `CORS_PUBLIC_ORIGINS` : aucun `Access-Control-Allow-Origin`, le navigateur bloque la lecture | `origine inconnue lit …` ; vrai navigateur : `dev.py citoyen cors` |
| Le tableau de bord de l'équipe lit l'espace public | Liste à part | `origine du tableau de bord lit …` |
| La page citoyenne lit l'API d'équipe | Son origine n'est pas dans la liste de l'équipe | `origine citoyenne lit l'API d'équipe` |
| Cookies entre origines | `Access-Control-Allow-Credentials` n'est jamais envoyé | `cookies autorisés entre origines` |
| Une page envoie le jeton d'équipe ou écrit | La pré-vérification est refusée (403) : le navigateur n'envoie pas la requête | `pré-vérification qui demande …` (2 essais) ; vrai navigateur (2 essais) |
| Inondation de lectures | Zone `citoyen` : 2 par seconde, rafale de 10, par adresse | `60 lectures publiques d'affilée sans être limité` ; le refus est au format commun, avec `Retry-After`, jamais mis en cache |
| La limite publique gêne un autre citoyen ou l'API d'équipe | Zones séparées, une par adresse | `une autre adresse n'est pas limitée (témoin)` ; `la limite publique ouvre l'API d'équipe` |
| Lire des détails internes dans une erreur | Format commun à six champs, `Server: nginx` sans version, aucun nom de service ni de chemin | 8 essais (4 erreurs : 404, 405, 400, 400 encodé), à chaque fois fuite et format |
| Réponse d'erreur gardée par un cache | `Cache-Control: no-store` sur toute erreur de l'espace public | idem |
| Retrouver un citoyen par le journal | Adresse remplacée par `-` ; XFF vide vers les services | `adresse d'un citoyen dans le journal de la passerelle` (+ un témoin : l'adresse de l'équipe y reste) ; tests de la passerelle réelle |
| Un secret dans le code livré au navigateur | Aucune variable secrète lue ; aucune valeur de `.env` dans `citizen/src`, `citizen/dist` | `valeur d'un secret de .env dans le code livré` ; `test_application_citoyenne.py` (6 tests) |
| Écriture, route interne, jeton d'équipe | 405, 404, jeton ignoré et non transmis | Famille « api public » (CIT-02) : 60 essais, 0 accordé |

**Sens des essais.** Pour la famille « api public (abus) », un essai « refusé » est un abus : « obtenu vrai » veut dire que l'abus a **abouti** et compte comme un accès interdit accordé. Trois essais témoins (« attendu » vrai) prouvent que la protection ne ferme pas ce qui doit rester ouvert : l'origine citoyenne lit, l'adresse de l'équipe reste journalisée, une autre adresse n'est pas limitée. Un essai qui ne peut pas être joué (réseau muet, journal illisible) n'est jamais un succès.

## 4. Défauts trouvés en chemin

| Défaut | Comment trouvé | Correction |
|---|---|---|
| Les réponses **400** de l'espace public n'avaient ni `Cache-Control`, ni `nosniff`, ni les autres en-têtes de sécurité | Test de la passerelle réelle (`test_aucune_erreur_de_l_espace_public_ne_laisse_voir_l_interieur`) | `@bad_request` (section 2) |
| Un premier essai de CORS dans un vrai navigateur échouait pour une **mauvaise raison** : une page fabriquée par Playwright est tenue pour « publique » et son appel vers une adresse locale est refusé | Lecture légitime refusée alors que `curl` montrait le bon en-tête | Chaque origine est servie par un vrai petit serveur local (`citizen/scripts/cors-navigateur.mjs`) |
| Le journal d'erreurs de nginx n'est pas un fichier lisible dans l'image : il passe par `docker logs` | Erreur du test de refus de débit | Le test lit `docker logs` |
| Les conteneurs `collecte`, `frontend`, `simulateur`, `traitement-flux` et `traitement-pipeline` étaient arrêtés pendant la session (cause non établie) : `dev.py acces` indiquait « HTTP 0 » pour le dépôt des mesures | Écart inattendu de la matrice | `docker compose up -d` (sans reconstruction) : « HTTP 422 » comme au 20/11/2026 |

## 5. Preuves

| Preuve | Commande | Résultat du 21/11/2026 |
|---|---|---|
| Matrice d'accès, famille « api public (abus) » | `python3 scripts/dev/dev.py acces` (Windows : `py -3 scripts/dev/dev.py acces`) | **témoins 3/3, abus refusés 19/19** ; famille « api public » inchangée : 8/8 et 52/52 ; **accès interdits accordés : 0** ; 442 essais conformes sur 445 (les 3 non conformes sont les droits MongoDB de `svc_traitement` sur `ingestion_runs`, déjà documentés le 17/11/2026 ; code de sortie 1) |
| Détail des 22 essais, CORS dans Chromium | voir le fichier | [sortie complète](../05-cloud-aws/sorties-acces/acces-citoyen-securite-2026-11-21.txt) : 22/22 conformes, CORS 7/7 |
| CORS vu par un vrai navigateur | `python3 scripts/dev/dev.py citoyen cors` (Windows : `py -3 scripts/dev/dev.py citoyen cors`) | **7/7** : lecture depuis l'origine citoyenne (2 routes, HTTP 200) ; bloqués : jeton d'équipe, écriture, API d'équipe, origine inconnue, origine du tableau de bord |
| Le banc sait voir un abus qui aboutit | `python3 -m unittest discover -s scripts/dev -p "test_acces_abus_public.py"` (Windows : `py -3 -m unittest discover -s scripts/dev -p "test_acces_abus_public.py"`) | **21 tests** : une passerelle conforme (0 abus), puis 11 passerelles défectueuses, une par défaut (origine inconnue, origine d'équipe, origine citoyenne sur l'équipe, cookies, pré-vérification ouverte, fuite d'erreur, en-têtes manquants, adresse dans le journal, aucune limite, refus de débit mal formé, journal illisible) ; 5 tests du contrôle des secrets du front |
| Passerelle réelle (nginx, njs, Docker) | `python3 -m unittest discover -s gateway/tests -p "test_gateway.py"` (Windows : `py -3 -m unittest discover -s gateway/tests -p "test_gateway.py"`) | **43 tests** (36 avant CIT-06, 7 ajoutés, 1 adapté) |
| `auth.js` sous Node | `node --test gateway/tests/auth.test.mjs` | **41 tests** (34 avant, 7 ajoutés) |
| Front : secrets et en-têtes | `python3 -m unittest discover -s scripts/dev -p "test_application_citoyenne.py"` (Windows : `py -3 -m unittest discover -s scripts/dev -p "test_application_citoyenne.py"`) | **28 tests** (22 avant, 6 ajoutés) |
| Tous les tests de `scripts/dev` | `python3 -m unittest discover -s scripts/dev` (Windows : `py -3 -m unittest discover -s scripts/dev`) | **1008 tests**, tous réussis |

Test existant adapté (jamais supprimé, règle de CLAUDE.md, section 11) : `test_cors_d_une_route_citoyenne_n_autorise_que_l_origine_configuree…` et un test de `auth.test.mjs` supposaient que l'espace public suivait la liste de l'équipe ; ils suivent désormais la liste citoyenne et vérifient aussi que l'origine de l'équipe est refusée.

## 6. Scans

| Contrôle | Résultat | État |
|---|---|---|
| gitleaks sur l'arbre de travail (hors `.env` et `var/`, ignorés par Git) | Aucune détection dans les fichiers de CIT-06 | Vérifié le 21/11/2026 |
| gitleaks dans la CI (historique complet) | À lire sur la pull request | Non vérifié ici |
| Snyk (job `snyk` de la CI) | À lire sur la pull request ; `security/snyk` (contrôle externe) échoue toujours, limite du compte (CLAUDE.md, section 10) | Non vérifié ici |
| SonarQube | Non exigé pour le code citoyen pendant son développement sur `dev-citoyen` (ADR-030, 4.6) ; doit passer ou être excepté par écrit avant la fusion dans `main` | Inchangé |

## 7. Limites et points ouverts pour la relecture croisée

| N° | Point | État |
|---|---|---|
| 1 | **Le journal d'erreurs de nginx** nomme l'adresse du client quand le service derrière la passerelle est injoignable (`connect() failed … client: …`). Seuls les refus de débit sont sortis de ce journal. Les journaux de la passerelle sont locaux au poste | Limite assumée |
| 2 | **`X-Forwarded-For` est cru d'un relais du réseau privé**, donc d'un appel venu de l'hôte. Les essais de débit et de journal s'en servent pour utiliser une adresse inventée sans bloquer la vraie. En déploiement, seule la passerelle doit être publiée, derrière un relais de confiance | Limite déjà dans `gateway/README.md` (section 8) |
| 3 | La limite de débit est **par adresse** : plusieurs citoyens derrière une même adresse la partagent | Choix de la v1 |
| 4 | **Les réponses 405 sont en `application/octet-stream`** (le corps est bien le format commun) : limite connue de la passerelle, pas corrigée ici | Ouvert |
| 5 | L'analyse juridique (RGPD) de la journalisation n'est pas faite (ADR-030, 4.3) : le journal ne garde plus l'adresse pour l'espace public, ce qui réduit le sujet sans le clore | Ouvert |
| 6 | Pas de TLS en local : HSTS n'est posé que derrière un point qui le termine | Inchangé |
| 7 | La mesure du dépassement de débit et du CORS est faite sur **un poste Linux** ; non vérifié sous Windows, ni avec plusieurs visiteurs en même temps, ni avec Firefox ou Safari (seul Chromium est essayé) | À rejouer par le binôme |
| 8 | Pas de test de charge : le banc prouve que la limite mord, pas qu'elle tient sous une vraie attaque distribuée | Hors périmètre d'un PoC |

## 8. Rejouer

| Besoin | Linux (bash) | Windows (PowerShell) |
|---|---|---|
| Appliquer la configuration (passerelle recréée) | `docker compose up -d passerelle` puis `docker compose exec -T passerelle nginx -s reload` | idem |
| Matrice d'accès complète | `python3 scripts/dev/dev.py acces` | `py -3 scripts/dev/dev.py acces` |
| CORS dans un vrai navigateur | `python3 scripts/dev/dev.py citoyen cors` | `py -3 scripts/dev/dev.py citoyen cors` |
| Passerelle réelle (Docker) | `python3 -m unittest discover -s gateway/tests -p "test_gateway.py"` | `py -3 -m unittest discover -s gateway/tests -p "test_gateway.py"` |
| `auth.js` sous Node | `node --test gateway/tests/auth.test.mjs` | idem |
| Essais du banc et contrôle du front | `python3 -m unittest discover -s scripts/dev -p "test_acces_abus_public.py"` | `py -3 -m unittest discover -s scripts/dev -p "test_acces_abus_public.py"` |
