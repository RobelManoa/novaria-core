"""Retour de version en local (CLD-16) : images par SHA, révision précédente, vérification de /health, jamais de donnée touchée.

Git, Docker et le réseau sont remplacés : aucun conteneur, aucun service n'est lancé. La preuve sur la vraie pile est dans
docs/08-exploitation/rollback.md.
Lancement : python3 -m unittest discover -s scripts/dev -p "test_rollback.py"  (Windows : py -3 ...).
"""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

import rollback as r

SHA_A, SHA_B = "a" * 40, "b" * 40
RACINE = Path(__file__).resolve().parents[2]


def archive(service):
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        contenu = b"FROM scratch\n"
        info = tarfile.TarInfo(f"services/{service}/Dockerfile")
        info.size = len(contenu)
        tar.addfile(info, io.BytesIO(contenu))
    return tampon.getvalue()


class Faux:
    """Git, Docker et /health : les images existantes, les révisions annoncées et les commandes lancées sont ceux du test."""

    def __init__(self, images=(), refs=None):
        self.images, self.commandes = set(images), []
        self.refs = refs if refs is not None else {"ancienne": SHA_A, "nouvelle": SHA_B}
        self.sante_par_service, self.echec = {}, set()

    def executer(self, commande, **_):
        self.commandes.append(commande)
        if commande[:2] == ["git", "rev-parse"]:
            nom = commande[-1].removesuffix("^{commit}")
            return CompletedProcess(commande, 0 if nom in self.refs else 1, (self.refs.get(nom, "") + "\n"), "")
        if commande[:2] == ["git", "archive"]:
            return CompletedProcess(commande, 1 if "archive" in self.echec else 0, archive(commande[-1].split("/")[-1]), b"")
        if commande[:3] == ["docker", "image", "inspect"]:
            return CompletedProcess(commande, 0 if commande[3] in self.images else 1, "", "")
        if commande[:2] == ["docker", "build"]:
            if "build" in self.echec:
                return CompletedProcess(commande, 1, "", "erreur de build")
            self.images.add(commande[commande.index("-t") + 1])
            return CompletedProcess(commande, 0, "", "")
        if commande[:3] == ["docker", "compose", "exec"]:
            return CompletedProcess(commande, 1 if "reload" in self.echec else 0, "", "")
        if commande[:2] == ["docker", "compose"]:
            if "compose" in self.echec:
                return CompletedProcess(commande, 1, "", "compose a échoué")
            surcharge = Path(commande[commande.index("-f", 3) + 1]).read_text(encoding="utf-8")
            for service, sha in self.annonce(surcharge).items():
                self.sante_par_service[service] = sha
            if "traitement" in self.sante_par_service:
                self.sante_par_service["passerelle"] = self.sante_par_service["traitement"]
            return CompletedProcess(commande, 0, "", "")
        raise AssertionError(f"commande inattendue : {commande}")

    @staticmethod
    def annonce(surcharge):
        """Le comportement d'un vrai conteneur : /health annonce le GIT_SHA que la surcharge lui a donné."""
        sortie, courant = {}, None
        for ligne in surcharge.splitlines():
            ligne = ligne.strip()
            if ligne.endswith(":") and ligne[:-1] in {c for s in r.SERVICES.values() for c in s["conteneurs"]}:
                courant = next(nom for nom, s in r.SERVICES.items() if ligne[:-1] in s["conteneurs"])
            elif ligne.startswith("GIT_SHA:") and courant:
                sortie[courant] = ligne.split(": ")[1]
        return sortie


class Simule:
    """Un moteur sur un dossier temporaire, avec une horloge qui avance seule à chaque attente."""

    def __init__(self, images=(), refs=None):
        self.dossier = tempfile.TemporaryDirectory()
        self.faux = Faux(images, refs)
        self.t = 1_800_000_000.0
        self.moteur = r.Moteur(racine=RACINE, dossier=Path(self.dossier.name), env={"COLLECTE_PORT": "9001"}, executer=self.faux.executer,
                               lire_sante=lambda s: self.faux.sante_par_service.get(s), horloge=lambda: self.t, dormir=self._dormir)

    def _dormir(self, secondes):
        self.t += secondes

    def fermer(self):
        self.dossier.cleanup()


class Construction(unittest.TestCase):
    def setUp(self):
        self.s = Simule()
        self.addCleanup(self.s.fermer)

    def test_une_reference_devient_un_sha_complet(self):
        self.assertEqual(self.s.moteur.resoudre("ancienne"), SHA_A)

    def test_une_reference_inconnue_ou_une_option_est_refusee_sans_appeler_git(self):
        with self.assertRaises(r.ErreurRollback):
            self.s.moteur.resoudre("n-existe-pas")
        for mauvaise in ("--output=/tmp/x", "-h", ""):
            with self.assertRaises(r.ErreurRollback):
                self.s.moteur.resoudre(mauvaise)
        self.assertEqual(len(self.s.faux.commandes), 1, "seule la référence inconnue est allée jusqu'à git")

    def test_l_image_est_construite_depuis_les_sources_du_commit_et_etiquetee_par_son_sha(self):
        message = self.s.moteur.construire("collecte", SHA_A)
        build = next(c for c in self.s.faux.commandes if c[:2] == ["docker", "build"])
        self.assertIn(f"GIT_SHA={SHA_A}", build)
        self.assertIn(f"novaria-local/collecte:{SHA_A[:12]}", build)
        self.assertIn(f"sources/{SHA_A[:12]}/services/collecte", build[-1].replace("\\", "/"))
        self.assertTrue((Path(self.s.dossier.name) / "sources" / SHA_A[:12] / "services" / "collecte" / "Dockerfile").is_file())
        self.assertIn("construite", message)

    def test_une_image_deja_construite_n_est_pas_reconstruite(self):
        self.s.faux.images.add(r.image("collecte", SHA_A))
        self.assertIn("déjà construite", self.s.moteur.construire("collecte", SHA_A))
        self.assertFalse([c for c in self.s.faux.commandes if c[:2] in (["docker", "build"], ["git", "archive"])])

    def test_un_service_inconnu_est_refuse(self):
        with self.assertRaises(r.ErreurRollback):
            self.s.moteur.construire("postgres", SHA_A)

    def test_un_echec_de_git_archive_ou_de_build_est_dit(self):
        self.s.faux.echec = {"archive"}
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.s.moteur.construire("collecte", SHA_A)
        self.assertIn("git archive", str(ctx.exception))
        self.s.faux.echec = {"build"}
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.s.moteur.construire("collecte", SHA_B)
        self.assertIn("erreur de build", str(ctx.exception))


class Surcharge(unittest.TestCase):
    def test_chaque_conteneur_d_un_service_recoit_l_image_et_la_revision(self):
        texte = r.Moteur().surcharge({"traitement": SHA_A})
        for conteneur in ("traitement", "traitement-flux", "traitement-pipeline"):
            self.assertIn(f"  {conteneur}:\n    image: novaria-local/traitement:{SHA_A[:12]}\n    environment:\n      GIT_SHA: {SHA_A}", texte)
        self.assertNotIn("collecte", texte)

    def test_la_surcharge_ne_touche_ni_aux_volumes_ni_aux_ports_ni_aux_secrets(self):
        texte = r.Moteur().surcharge({s: SHA_A for s in r.SERVICES})
        for interdit in ("volumes", "ports", "secrets", "environment: {", "MONGO", "POSTGRES", "PASSWORD"):
            self.assertNotIn(interdit, texte)

    def test_les_conteneurs_listes_existent_dans_docker_compose_yml(self):
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        for service in r.SERVICES.values():
            for conteneur in service["conteneurs"]:
                self.assertRegex(compose, rf"(?m)^  {conteneur}:\n", conteneur)

    def test_les_ports_viennent_du_env_ou_de_la_valeur_par_defaut(self):
        m = r.Moteur(env={"COLLECTE_PORT": "9001"})
        self.assertEqual(m._port("collecte"), "9001")
        self.assertEqual(m._port("traitement"), "8002")


class Deploiement(unittest.TestCase):
    def setUp(self):
        self.s = Simule(images=[r.image(sv, sha) for sv in r.SERVICES for sha in (SHA_A, SHA_B)])
        self.addCleanup(self.s.fermer)
        self.m, self.f = self.s.moteur, self.s.faux

    def compose(self):
        return [c for c in self.f.commandes if c[:3] == ["docker", "compose", "-f"]]  # les « up » ; le rechargement de la passerelle est un « exec »

    def test_deployer_puis_verifier_la_revision_annoncee(self):
        messages = self.m.deployer({"collecte": SHA_A})
        self.assertIn("collecte : " + SHA_A[:12] + " en service (précédente : aucune)", messages)
        self.assertEqual(self.m.etat()["collecte"], {"en_service": SHA_A, "precedente": None, "historique": [self.m.etat()["collecte"]["historique"][0]]})

    def test_la_commande_ne_supprime_rien_et_ne_touche_pas_aux_dependances(self):
        self.m.deployer({"traitement": SHA_A, "alerte": SHA_A})
        (commande,) = self.compose()
        for requis in ("--no-build", "--no-deps", "--force-recreate", "up", "-d"):
            self.assertIn(requis, commande)
        for interdit in ("down", "rm", "-v", "--volumes", "volume", "--remove-orphans", "prune", "restart"):
            self.assertNotIn(interdit, commande)
        self.assertEqual(commande[commande.index("--force-recreate") + 1:], ["traitement", "traitement-flux", "traitement-pipeline", "alerte", "alerte-worker"])
        self.assertNotIn("postgres", commande)
        self.assertNotIn("mongo", commande)
        self.assertNotIn("kafka", commande)

    def test_une_image_absente_est_refusee_avant_toute_commande_compose(self):
        self.f.images.discard(r.image("reponse", SHA_B))
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"collecte": SHA_B, "reponse": SHA_B})
        self.assertIn("n'existe pas", str(ctx.exception))
        self.assertEqual(self.compose(), [])
        self.assertEqual(self.m.etat(), {})

    def test_un_sha_invalide_est_refuse(self):
        for mauvais in ("HEAD", "abc", "g" * 40, SHA_A + "; rm -rf /"):
            with self.assertRaises(r.ErreurRollback):
                self.m.deployer({"collecte": mauvais})
        self.assertEqual(self.compose(), [])

    def test_une_revision_annoncee_differente_echoue_et_ne_change_pas_l_etat(self):
        self.m.deployer({"collecte": SHA_A})
        self.f.sante_par_service["collecte"] = "ancienne-revision-restee"

        def sourd(*_a, **_k):  # le conteneur ne prend pas la nouvelle révision
            self.f.sante_par_service["collecte"] = SHA_A

        original = self.f.executer

        def executer(commande, **options):
            sortie = original(commande, **options)
            if commande[:2] == ["docker", "compose"]:
                sourd()
            return sortie

        self.m.executer = executer
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"collecte": SHA_B})
        self.assertIn("au lieu de", str(ctx.exception))
        self.assertIn("Reprise automatique", str(ctx.exception))
        self.assertEqual(self.m.etat()["collecte"]["en_service"], SHA_A, "l'état enregistré reste celui qui tourne")

    def test_la_passerelle_relit_les_adresses_sans_etre_redemarree(self):
        self.m.deployer({"traitement": SHA_A})
        (rechargement,) = [c for c in self.f.commandes if c[:3] == ["docker", "compose", "exec"]]
        self.assertEqual(rechargement[3:], ["-T", "passerelle", "nginx", "-s", "reload"])
        self.assertFalse([c for c in self.f.commandes if "restart" in c])

    def test_la_passerelle_est_rechargee_apres_les_services_et_avant_l_enregistrement(self):
        self.m.deployer({"collecte": SHA_A})
        compose = [i for i, c in enumerate(self.f.commandes) if c[:3] == ["docker", "compose", "-f"]]
        recharge = [i for i, c in enumerate(self.f.commandes) if c[:3] == ["docker", "compose", "exec"]]
        self.assertLess(compose[0], recharge[0])

    def test_un_rechargement_refuse_est_dit_avec_la_commande_a_lancer_et_n_enregistre_rien(self):
        self.f.echec = {"reload"}
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"traitement": SHA_A})
        self.assertIn("nginx -s reload", str(ctx.exception))
        self.assertEqual(self.m.etat(), {})

    def test_la_passerelle_doit_annoncer_la_revision_du_traitement(self):
        self.m.deployer({"traitement": SHA_A})
        self.f.sante_par_service["passerelle"] = "revision-figee"
        original = self.f.executer

        def executer(commande, **options):
            sortie = original(commande, **options)
            if commande[:3] == ["docker", "compose", "-f"]:
                self.f.sante_par_service["passerelle"] = "revision-figee"  # la passerelle garde l'ancienne adresse
            return sortie

        self.m.executer = executer
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"traitement": SHA_B})
        self.assertIn("passerelle", str(ctx.exception))
        self.assertEqual(self.m.etat()["traitement"]["en_service"], SHA_A)

    def test_une_nouvelle_revision_qui_ne_repond_pas_est_remplacee_seule_par_la_precedente(self):
        self.m.deployer({"collecte": SHA_A})
        original = self.f.executer

        def executer(commande, **options):
            sortie = original(commande, **options)
            if commande[:3] == ["docker", "compose", "-f"] and f"novaria-local/collecte:{SHA_B[:12]}" in Path(commande[commande.index("-f", 3) + 1]).read_text(encoding="utf-8"):
                self.f.sante_par_service["collecte"] = None  # la nouvelle révision ne démarre pas
            return sortie

        self.m.executer = executer
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"collecte": SHA_B})
        self.assertIn(f"collecte {SHA_A[:12]} remis en service", str(ctx.exception))
        self.assertEqual(self.f.sante_par_service["collecte"], SHA_A, "l'ancienne révision tourne de nouveau")
        self.assertEqual(self.m.etat()["collecte"]["en_service"], SHA_A)

    def test_sans_revision_precedente_enregistree_il_n_y_a_pas_de_reprise(self):
        self.f.echec = set()
        original = self.f.executer

        def executer(commande, **options):
            sortie = original(commande, **options)
            if commande[:3] == ["docker", "compose", "-f"]:
                self.f.sante_par_service["collecte"] = None
            return sortie

        self.m.executer = executer
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"collecte": SHA_A})
        self.assertNotIn("Reprise automatique", str(ctx.exception))
        self.assertEqual(len([c for c in self.compose()]), 1)

    def test_un_echec_de_compose_est_dit_et_n_enregistre_rien(self):
        self.f.echec = {"compose"}
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.deployer({"collecte": SHA_A})
        self.assertIn("compose a échoué", str(ctx.exception))
        self.assertEqual(self.m.etat(), {})

    def test_le_retour_remet_la_revision_precedente_et_garde_la_suivante_pour_revenir_en_avant(self):
        self.m.deployer({"collecte": SHA_A})
        self.m.deployer({"collecte": SHA_B})
        self.assertEqual(self.m.etat()["collecte"]["precedente"], SHA_A)
        messages = self.m.retour(["collecte"])
        self.assertEqual(self.f.sante_par_service["collecte"], SHA_A)
        etat = self.m.etat()["collecte"]
        self.assertEqual((etat["en_service"], etat["precedente"]), (SHA_A, SHA_B))
        self.assertEqual([h["action"] for h in etat["historique"]], ["deploiement", "deploiement", "retour"])
        self.assertIn(SHA_A[:12], messages[0])

    def test_un_retour_sans_revision_precedente_est_refuse_sans_toucher_a_la_pile(self):
        self.m.deployer({"collecte": SHA_A})
        avant = len(self.compose())
        with self.assertRaises(r.ErreurRollback) as ctx:
            self.m.retour(["collecte"])
        self.assertIn("aucune révision précédente", str(ctx.exception))
        self.assertEqual(len(self.compose()), avant)

    def test_un_retour_ne_concerne_que_les_services_demandes(self):
        for sha in (SHA_A, SHA_B):
            self.m.deployer({"collecte": sha, "reponse": sha})
        self.m.retour(["collecte"])
        self.assertEqual(self.f.sante_par_service["collecte"], SHA_A)
        self.assertEqual(self.f.sante_par_service["reponse"], SHA_B)
        self.assertEqual(self.m.etat()["reponse"]["en_service"], SHA_B)

    def test_redeployer_la_meme_revision_ne_decale_pas_la_precedente(self):
        self.m.deployer({"collecte": SHA_A})
        self.m.deployer({"collecte": SHA_B})
        messages = self.m.deployer({"collecte": SHA_B})
        self.assertIn("déjà en service", messages[0])
        self.assertEqual(self.m.etat()["collecte"]["precedente"], SHA_A)

    def test_l_etat_est_ecrit_en_utf8_avec_des_fins_de_ligne_lf(self):
        self.m.deployer({"collecte": SHA_A})
        octets = (Path(self.s.dossier.name) / "etat.json").read_bytes()
        self.assertNotIn(b"\r", octets)
        json.loads(octets.decode("utf-8"))

    def test_l_historique_est_borne(self):
        for i in range(30):
            self.m.deployer({"collecte": SHA_A if i % 2 else SHA_B})
        self.assertLessEqual(len(self.m.etat()["collecte"]["historique"]), 20)


class Pile:
    """La pile pour l'essai : une collecte qui écrit dans un faux raw_events que le retour ne vide pas."""

    collecte = "http://127.0.0.1:8001"

    def __init__(self, ecrit=True, perd_au_retour=False):
        self.copies, self.ecrit, self.perd_au_retour = {}, ecrit, perd_au_retour

    def appel(self, methode, url, corps=None, **_):
        if not self.ecrit:
            return 503, None
        self.copies[corps["id"]] = 1
        return 202, {"status": "ACCEPTED"}

    def mongo(self, expression):
        identifiant = expression.split('"id": "')[1].split('"')[0]
        return f"{0 if self.perd_au_retour and identifiant not in self.copies else self.copies.get(identifiant, 0)}"


class Essai(unittest.TestCase):
    def setUp(self):
        self.s = Simule(images=[r.image(sv, sha) for sv in r.SERVICES for sha in (SHA_A, SHA_B)])
        self.addCleanup(self.s.fermer)

    def jouer(self, pile=None, **options):
        sortie = []
        etapes = r.essai(self.s.moteur, pile or Pile(), "ancienne", "nouvelle", options.pop("services", ["collecte", "reponse"]), afficher=sortie.append)
        return etapes, sortie

    def test_un_essai_reussi_prouve_le_retour_et_la_conservation_des_donnees(self):
        etapes, sortie = self.jouer()
        self.assertTrue(all(ok for _, ok, _ in etapes), etapes)
        self.assertEqual([nom for nom, *_ in etapes], [
            "révisions construites", "ancienne révision en service", "nouvelle révision en service", "écriture pendant la nouvelle révision",
            "retour : l'ancienne révision est de nouveau en service", "les données ne sont pas revenues en arrière"])
        self.assertEqual(self.s.faux.sante_par_service["collecte"], SHA_A)
        self.assertEqual(self.s.faux.sante_par_service["reponse"], SHA_A)

    def test_la_meme_revision_deux_fois_est_refusee(self):
        with self.assertRaises(r.ErreurRollback):
            r.essai(self.s.moteur, Pile(), "ancienne", "ancienne", ["collecte"], afficher=lambda _: None)

    def test_une_ecriture_refusee_est_un_echec_et_pas_un_succes_silencieux(self):
        etapes, _ = self.jouer(Pile(ecrit=False))
        ecriture = next(e for e in etapes if e[0].startswith("écriture"))
        self.assertFalse(ecriture[1])

    def test_une_donnee_perdue_au_retour_est_un_echec(self):
        pile = Pile(perd_au_retour=True)
        original = self.s.moteur.retour

        def retour(services):
            pile.copies.clear()
            return original(services)

        self.s.moteur.retour = retour
        etapes, _ = self.jouer(pile)
        self.assertFalse(etapes[-1][1])


class Documents(unittest.TestCase):
    def test_le_document_de_preuve_existe_et_cite_les_limites(self):
        texte = (RACINE / "docs" / "08-exploitation" / "rollback.md").read_text(encoding="utf-8")
        for attendu in ("dev.py rollback", "ne restaure pas", "restauration", "migration", "non vérifié", "ECS"):
            self.assertIn(attendu, texte)

    def test_la_surcharge_generee_est_ignoree_par_git(self):
        self.assertIn("var/", (RACINE / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
