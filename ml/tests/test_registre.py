"""Registre des modèles (IA-04) : magasin d'objets, document model_runs, format sans exécution de code, cycle de vie,
chargement côté service, lignée, import d'IA-03 et ligne de commande.

Presque tout tourne en bibliothèque standard (sans MongoDB, sans scikit-learn) : le magasin local est un dossier
temporaire et `model_runs` une collection en mémoire ou une fausse collection MongoDB. Les tests qui entraînent un modèle
ont besoin de scikit-learn ; ceux qui parlent à un vrai MongoDB sont ignorés sans la variable `REGISTRE_MONGO_URL`.
"""

import json
import logging
import os
import pickle
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401 : chemins d'import

from entrainement import tracabilite
from jeu_entrainement.simulation import RACINE
from preparation import variables
from registre import documents, format_lineaire, importer_ia03, lignee, service
from registre import __main__ as cli
from registre.registre import POINTEUR, Registre, RegistreErreur, cle_du_manifeste, cle_du_modele
from registre.runs import FichierRunStore, MemoireRunStore, MongoRunStore, RunDejaEnregistre
from stockage import ObjetAbsent, ObjetDejaEcrit, StockageErreur, StockageLocal, sha256

try:
    import sklearn  # noqa: F401

    SKLEARN = True
except ImportError:
    SKLEARN = False
try:
    import pymongo
    from pymongo.errors import DuplicateKeyError
except ImportError:
    pymongo = None

SHA_JEU = "5" * 64
GIT = "a" * 40
T0 = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


def document_de_modele(**changements) -> dict:
    """Un modèle linéaire valide, écrit à la main (aucune dépendance) : trois états, toutes les variables de la détection."""
    numeriques = [c for c in variables.DETECTION.numeriques]
    medianes = {c: 1.0 for c in numeriques}
    categories = {"road_type": ["ARTERIAL", "COLLECTOR", "LOCAL"]}
    noms = numeriques + [f"road_type={c}" for c in categories["road_type"]]
    n = len(noms)
    document = {
        "format": format_lineaire.NOM, "version": 1, "classes": ["CONGESTED", "FREE_FLOW", "SLOW"], "variables": noms,
        "centrage": {"moyenne": [0.0] * n, "echelle": [1.0] * n},
        "coefficients": [[0.0] * n, [0.0] * n, [0.0] * n], "intercepts": [0.0, 1.0, 0.0],
        "preparation": {"usage": "detection", "medianes": medianes, "categories": categories, "runs_d_ajustement": ["r1"]},
    }
    document.update(changements)
    return document


def octets_de_modele(**changements) -> bytes:
    return (json.dumps(document_de_modele(**changements), sort_keys=True) + "\n").encode("utf-8")


def ligne_de_mesure(**valeurs) -> dict:
    base = {nom: 1.0 for nom in variables.DETECTION.numeriques}
    base.update(road_type="LOCAL", window_start=T0)
    base.update(valeurs)
    return base


def run_pret(registre: Registre, run_id="essai-1", decision="accepté", **champs):
    return registre.enregistrer_entrainement(
        run_id, git_sha=champs.get("git_sha", GIT), git_dirty=champs.get("git_dirty", False), dataset_id="novaria-congestion-v1",
        dataset_sha256=champs.get("dataset_sha256", SHA_JEU), seed=42, params={"candidat": "logistique"}, metrics={"decision": decision},
        created_at=champs.get("created_at", T0),
    )


def nouveau_registre(racine: Path, horloge=None) -> Registre:
    return Registre(MemoireRunStore(), StockageLocal(racine), horloge or (lambda: T0 + timedelta(minutes=5)))


class TempTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dossier = Path(self._tmp.name)


class TestStockage(TempTestCase):
    def setUp(self):
        super().setUp()
        self.magasin = StockageLocal(self.dossier / "models")

    def test_aller_retour_et_empreinte(self):
        self.assertEqual(self.magasin.put("run-1/modele.json", b"abc"), sha256(b"abc"))
        self.assertEqual(self.magasin.get("run-1/modele.json"), b"abc")
        self.assertTrue(self.magasin.exists("run-1/modele.json"))
        self.assertFalse(self.magasin.exists("run-2/modele.json"))

    def test_un_objet_versionne_ne_se_reecrit_pas(self):
        self.magasin.put("run-1/modele.json", b"abc")
        with self.assertRaises(ObjetDejaEcrit):
            self.magasin.put("run-1/modele.json", b"autre")
        self.assertEqual(self.magasin.get("run-1/modele.json"), b"abc")

    def test_le_pointeur_se_remplace(self):
        self.magasin.put("en-service.json", b"1")
        self.magasin.put("en-service.json", b"2", remplacer=True)
        self.assertEqual(self.magasin.get("en-service.json"), b"2")

    @unittest.skipIf(os.name == "nt", "les droits POSIX n'existent pas sous Windows")
    def test_les_fichiers_sont_en_lecture_seule_sauf_le_pointeur(self):
        self.magasin.put("run-1/modele.json", b"abc")
        mode = stat.S_IMODE((self.dossier / "models" / "run-1" / "modele.json").stat().st_mode)
        self.assertEqual(mode & 0o222, 0)

    def test_les_cles_dangereuses_sont_refusees(self):
        for cle in ("../x", "/etc/passwd", "a/../b", "A/b", "a//b", ".cache", "a b", "", "a/b/c/d/e", "a" * 101, "run-1/../../x", "run\\x", "a/.", "%2e%2e/x"):
            with self.subTest(cle=cle), self.assertRaises(StockageErreur):
                self.magasin.put(cle, b"x")
            with self.subTest(lecture=cle), self.assertRaises(StockageErreur):
                self.magasin.get(cle)
        with self.assertRaises(StockageErreur):
            self.magasin.put(None, b"x")  # type: ignore[arg-type]

    @unittest.skipIf(os.name == "nt", "les liens symboliques demandent des droits sous Windows")
    def test_un_lien_symbolique_vers_l_exterieur_est_refuse(self):
        exterieur = self.dossier / "dehors"
        exterieur.mkdir()
        (exterieur / "secret.json").write_bytes(b"secret")
        racine = self.dossier / "models"
        racine.mkdir()
        try:
            (racine / "evade").symlink_to(exterieur, target_is_directory=True)
        except OSError:
            self.skipTest("liens symboliques indisponibles sur ce système de fichiers")
        with self.assertRaises(StockageErreur):
            StockageLocal(racine).get("evade/secret.json")
        with self.assertRaises(StockageErreur):
            StockageLocal(racine).put("evade/nouveau.json", b"x")
        self.assertFalse((exterieur / "nouveau.json").exists())

    def test_objet_absent_et_trop_gros(self):
        with self.assertRaises(ObjetAbsent):
            self.magasin.get("run-9/modele.json")
        petit = StockageLocal(self.dossier / "petit", taille_max=4)
        with self.assertRaises(StockageErreur):
            petit.put("run-1/gros.json", b"12345")
        petit.put("run-1/ok.json", b"1234")

    def test_aucun_fichier_temporaire_ne_reste(self):
        self.magasin.put("run-1/modele.json", b"abc")
        with self.assertRaises(ObjetDejaEcrit):
            self.magasin.put("run-1/modele.json", b"autre")
        noms = sorted(p.name for p in (self.dossier / "models" / "run-1").iterdir())
        self.assertEqual(noms, ["modele.json"])


class TestDocuments(unittest.TestCase):
    def base(self, **changements):
        d = {"run_id": "essai-1", "created_at": T0, "git_sha": GIT, "dataset_sha256": SHA_JEU, "seed": 42, "params": {}, "metrics": {}, "status": "trained"}
        d.update(changements)
        return d

    def test_un_document_conforme_passe(self):
        self.assertEqual(documents.valider(self.base())["run_id"], "essai-1")

    def test_chaque_champ_obligatoire_est_exige(self):
        for nom in documents.OBLIGATOIRES:
            d = self.base()
            del d[nom]
            with self.subTest(nom=nom), self.assertRaises(documents.DocumentInvalide):
                documents.valider(d)

    def test_les_valeurs_mal_formees_sont_refusees(self):
        for champ, valeur in (("run_id", "../x"), ("run_id", "Majuscule"), ("run_id", ""), ("git_sha", "abc"), ("git_sha", "A" * 40),
                              ("dataset_sha256", "z" * 64), ("seed", "42"), ("seed", True), ("params", []), ("metrics", "x"),
                              ("status", "inconnu"), ("created_at", datetime(2026, 1, 1)), ("created_at", "2026-01-01"),
                              ("model_sha256", "12"), ("git_dirty", "oui"), ("registered_at", datetime(2026, 1, 1))):
            with self.subTest(champ=champ, valeur=valeur), self.assertRaises(documents.DocumentInvalide):
                documents.valider(self.base(**{champ: valeur}))

    def test_un_champ_inconnu_est_refuse(self):
        with self.assertRaises(documents.DocumentInvalide):
            documents.valider(self.base(pickle_path="/tmp/x"))

    def test_un_modele_enregistre_a_ses_champs_et_les_autres_n_en_ont_pas(self):
        with self.assertRaises(documents.DocumentInvalide):
            documents.valider(self.base(status="registered"))
        complet = self.base(status="registered", model_sha256="1" * 64, model_uri="local:x/modele.json", model_format="f", registered_at=T0)
        documents.valider(complet)
        with self.assertRaises(documents.DocumentInvalide):
            documents.valider(self.base(status="rejected", model_sha256="1" * 64))

    def test_en_json_n_a_plus_de_date_python(self):
        sortie = documents.en_json({**self.base(), "_id": 1})
        self.assertEqual(sortie["created_at"], T0.isoformat())
        self.assertNotIn("_id", sortie)
        json.dumps(sortie)

    def test_valider_run_id(self):
        self.assertEqual(documents.valider_run_id("ia03-logistique-876c217f3f"), "ia03-logistique-876c217f3f")
        for faux in (None, 3, "a/b", "..", "a b", "x" * 101):
            with self.subTest(faux=faux), self.assertRaises(documents.DocumentInvalide):
                documents.valider_run_id(faux)


class CollectionFactice:
    """Le sous-ensemble de `pymongo.collection.Collection` que `MongoRunStore` utilise, avec l'unicité de `run_id`."""

    def __init__(self):
        self.documents = []

    def insert_one(self, document):
        if any(d["run_id"] == document["run_id"] for d in self.documents):
            raise DuplicateKeyError("run_id dupliqué")
        self.documents.append(dict(document))

    @staticmethod
    def _filtre(document, filtre):
        return all(document.get(cle) == valeur for cle, valeur in filtre.items())

    def find_one(self, filtre, projection=None):
        return next((dict(d) for d in self.documents if self._filtre(d, filtre)), None)

    def find(self, filtre, projection=None):
        return Curseur([dict(d) for d in self.documents if self._filtre(d, filtre)])

    def update_one(self, filtre, modification):
        for d in self.documents:
            if self._filtre(d, filtre):
                d.update(modification["$set"])
                return mock.Mock(matched_count=1, modified_count=1)
        return mock.Mock(matched_count=0, modified_count=0)


class Curseur:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, cle, sens=None):
        critere = [(cle, sens)] if isinstance(cle, str) else cle
        for nom, direction in reversed(critere):
            self.documents.sort(key=lambda d: d.get(nom, T0), reverse=direction < 0)
        return self

    def limit(self, n):
        self.documents = self.documents[:n]
        return self

    def __iter__(self):
        return iter(self.documents)


class ContratRunStore:
    """Ce que tout `RunStore` doit faire : le même contrat pour la mémoire et pour MongoDB."""

    def creer(self):
        raise NotImplementedError

    def doc(self, run_id="r1", status="trained", minutes=0, **plus):
        d = {"run_id": run_id, "created_at": T0 + timedelta(minutes=minutes), "git_sha": GIT, "dataset_sha256": SHA_JEU, "seed": 1,
             "params": {}, "metrics": {}, "status": status}
        d.update(plus)
        return d

    def enregistre(self, run_id, minutes, registered):
        return self.doc(run_id, "registered", minutes, model_sha256="1" * 64, model_uri=f"local:{run_id}/modele.json", model_format="f",
                        registered_at=T0 + timedelta(minutes=registered))

    def test_inserer_et_obtenir(self):
        s = self.creer()
        s.inserer(self.doc())
        self.assertEqual(s.obtenir("r1")["seed"], 1)
        self.assertIsNone(s.obtenir("absent"))

    def test_un_run_id_est_unique(self):
        s = self.creer()
        s.inserer(self.doc())
        with self.assertRaises(RunDejaEnregistre):
            s.inserer(self.doc())

    def test_un_document_invalide_n_est_pas_ecrit(self):
        s = self.creer()
        with self.assertRaises(documents.DocumentInvalide):
            s.inserer(self.doc(git_sha="x"))
        self.assertEqual(s.lister(), [])

    def test_mise_a_jour_conditionnelle(self):
        s = self.creer()
        s.inserer(self.doc())
        self.assertFalse(s.mettre_a_jour("r1", {"status": "rejected", "reason": "x"}, statut_attendu="registered"))
        self.assertFalse(s.mettre_a_jour("absent", {"status": "rejected", "reason": "x"}, statut_attendu="trained"))
        self.assertTrue(s.mettre_a_jour("r1", {"status": "rejected", "reason": "x"}, statut_attendu="trained"))
        self.assertFalse(s.mettre_a_jour("r1", {"status": "rejected", "reason": "y"}, statut_attendu="trained"))  # le second perd
        self.assertEqual(s.obtenir("r1")["reason"], "x")

    def test_une_mise_a_jour_invalide_est_refusee_sans_rien_changer(self):
        s = self.creer()
        s.inserer(self.doc())
        with self.assertRaises(documents.DocumentInvalide):
            s.mettre_a_jour("r1", {"status": "registered"}, statut_attendu="trained")  # sans champs de modèle
        self.assertEqual(s.obtenir("r1")["status"], "trained")

    def test_lister_dans_l_ordre_et_par_etat(self):
        s = self.creer()
        s.inserer(self.doc("r2", minutes=2))
        s.inserer(self.doc("r1", minutes=1))
        s.inserer(self.doc("r3", "rejected", 3, reason="x"))
        self.assertEqual([d["run_id"] for d in s.lister()], ["r1", "r2", "r3"])
        self.assertEqual([d["run_id"] for d in s.lister("rejected")], ["r3"])

    def test_le_dernier_en_service_est_le_plus_recemment_enregistre(self):
        s = self.creer()
        self.assertIsNone(s.dernier_en_service())
        s.inserer(self.doc("r0", minutes=0))  # pas enregistré : jamais en service
        s.inserer(self.enregistre("r1", 1, registered=10))
        s.inserer(self.enregistre("r2", 2, registered=5))
        self.assertEqual(s.dernier_en_service()["run_id"], "r1")
        self.assertTrue(s.mettre_a_jour("r2", {"registered_at": T0 + timedelta(minutes=20)}, statut_attendu="registered"))
        self.assertEqual(s.dernier_en_service()["run_id"], "r2")  # remise en service : le plus récent gagne


class TestMemoireRunStore(ContratRunStore, unittest.TestCase):
    def creer(self):
        return MemoireRunStore()

    def test_fermer_est_sans_effet_sur_une_collection_sans_connexion(self):
        MongoRunStore(CollectionFactice()).fermer()

    def test_fermer_libere_la_connexion(self):
        client = mock.Mock()
        MongoRunStore(mock.Mock(database=mock.Mock(client=client))).fermer()
        client.close.assert_called_once_with()

    def test_le_document_rendu_est_une_copie(self):
        s = self.creer()
        s.inserer(self.doc())
        s.obtenir("r1")["seed"] = 999
        self.assertEqual(s.obtenir("r1")["seed"], 1)


class TestFichierRunStore(ContratRunStore, TempTestCase):
    def creer(self):
        return FichierRunStore(self.dossier / "runs")

    def test_les_dates_font_l_aller_retour_et_le_fichier_est_lisible(self):
        s = self.creer()
        s.inserer(self.doc())
        self.assertEqual(s.obtenir("r1")["created_at"], T0)
        contenu = json.loads((self.dossier / "runs" / "r1.json").read_text(encoding="utf-8"))
        self.assertEqual(contenu["created_at"], T0.isoformat())

    def test_un_run_id_dangereux_n_ecrit_rien_hors_du_dossier(self):
        s = self.creer()
        for faux in ("../x", "a/b", ".."):
            with self.subTest(faux=faux), self.assertRaises(documents.DocumentInvalide):
                s.obtenir(faux)
        self.assertEqual(list(self.dossier.glob("*.json")), [])

    def test_aucun_fichier_temporaire_ne_reste(self):
        s = self.creer()
        s.inserer(self.doc())
        with self.assertRaises(RunDejaEnregistre):
            s.inserer(self.doc())
        self.assertEqual(sorted(p.name for p in (self.dossier / "runs").iterdir()), ["r1.json"])

    def test_un_dossier_absent_donne_une_liste_vide(self):
        self.assertEqual(self.creer().lister(), [])


@unittest.skipIf(pymongo is None, "pymongo absent : python3 scripts/dev/dev.py ml-env")
class TestMongoRunStoreAvecUneFausseCollection(ContratRunStore, unittest.TestCase):
    def creer(self):
        return MongoRunStore(CollectionFactice())


class TestFormatSansExecution(unittest.TestCase):
    def test_un_modele_valide_se_charge_et_predit_par_le_plus_grand_score(self):
        m = format_lineaire.ModeleLineaire.depuis_octets(octets_de_modele())
        self.assertEqual(m.classes, ("CONGESTED", "FREE_FLOW", "SLOW"))
        self.assertEqual(m.predire([ligne_de_mesure()]), ["FREE_FLOW"])  # l'ordonnée de FREE_FLOW est la plus grande

    def test_une_ligne_seule_ou_dans_un_lot_donne_la_meme_reponse(self):
        m = format_lineaire.ModeleLineaire.depuis_octets(octets_de_modele(intercepts=[0.0, 0.0, 0.5]))
        lot = [ligne_de_mesure(), ligne_de_mesure(speed_ratio=None)]
        self.assertEqual(m.predire(lot), [m.predire([x])[0] for x in lot])

    def test_une_valeur_absente_prend_la_mediane_enregistree(self):
        d = document_de_modele()
        n = len(d["variables"])
        d["coefficients"][0] = [0.0] * n
        d["coefficients"][0][d["variables"].index("speed_ratio")] = -10.0  # CONGESTED gagne quand le ratio est faible
        d["coefficients"][1][d["variables"].index("speed_ratio")] = 10.0
        d["intercepts"] = [0.0, 0.0, -5.0]
        m = format_lineaire.ModeleLineaire.depuis_octets((json.dumps(d)).encode())
        self.assertEqual(m.predire([ligne_de_mesure(speed_ratio=None)]), ["FREE_FLOW"])  # médiane 1,0 : fluide
        d["preparation"]["medianes"]["speed_ratio"] = -1.0
        m2 = format_lineaire.ModeleLineaire.depuis_octets((json.dumps(d)).encode())
        self.assertEqual(m2.predire([ligne_de_mesure(speed_ratio=None)]), ["CONGESTED"])

    def test_le_calcul_est_celui_de_la_formule(self):
        d = document_de_modele()
        noms = d["variables"]
        i = noms.index("flow_veh_per_min")
        d["centrage"]["moyenne"][i], d["centrage"]["echelle"][i] = 10.0, 2.0
        d["coefficients"][2][i] = 1.0  # SLOW : (flux − 10) ÷ 2
        d["intercepts"] = [-100.0, -100.0, 0.0]
        m = format_lineaire.ModeleLineaire.depuis_octets(json.dumps(d).encode())
        self.assertEqual(m.predire([ligne_de_mesure(flow_veh_per_min=14.0)]), ["SLOW"])

    def test_une_categorie_jamais_vue_est_refusee(self):
        m = format_lineaire.ModeleLineaire.depuis_octets(octets_de_modele())
        with self.assertRaises(ValueError):
            m.predire([ligne_de_mesure(road_type="MOTORWAY")])

    def test_ce_qui_n_est_pas_exactement_le_format_est_refuse(self):
        base = document_de_modele()
        n = len(base["variables"])
        cas = {
            "format inconnu": {"format": "autre"}, "version 2": {"version": 2}, "champ en trop": {"extra": 1},
            "classe inconnue": {"classes": ["CONGESTED", "FREE_FLOW", "EXPLOSE"]}, "une seule classe": {"classes": ["SLOW"]},
            "classe en double": {"classes": ["SLOW", "SLOW", "FREE_FLOW"]},
            "variables différentes": {"variables": base["variables"][:-1]},
            "échelle nulle": {"centrage": {"moyenne": [0.0] * n, "echelle": [0.0] * n}},
            "échelle négative": {"centrage": {"moyenne": [0.0] * n, "echelle": [-1.0] * n}},
            "mauvaise longueur de coefficients": {"coefficients": [[0.0] * n] * 2},
            "vecteur trop court": {"coefficients": [[0.0] * (n - 1)] * 3},
            "nombre en texte": {"intercepts": ["0", "1", "0"]},
            "booléen pris pour un nombre": {"intercepts": [True, 0.0, 0.0]},
            "centrage mal formé": {"centrage": {"moyenne": [0.0] * n}},
            "préparation d'un autre usage": {"preparation": {**base["preparation"], "usage": "prevision-h5"}},
            "médiane en trop": {"preparation": {**base["preparation"], "medianes": {**base["preparation"]["medianes"], "seed": 1.0}}},
            "catégories absentes": {"preparation": {**base["preparation"], "categories": {}}},
        }
        for nom, changement in cas.items():
            with self.subTest(nom), self.assertRaises(format_lineaire.FormatInvalide):
                format_lineaire.ModeleLineaire.depuis_octets(octets_de_modele(**changement))

    def test_un_champ_manquant_est_refuse(self):
        for champ in format_lineaire.CHAMPS:
            d = document_de_modele()
            del d[champ]
            with self.subTest(champ=champ), self.assertRaises(format_lineaire.FormatInvalide):
                format_lineaire.ModeleLineaire.depuis_octets(json.dumps(d).encode())

    def test_nan_infini_et_json_illisible_sont_refuses(self):
        for texte in ("NaN", "Infinity", "-Infinity", "{", "", "[]", "null", '"x"'):
            with self.subTest(texte=texte), self.assertRaises(format_lineaire.FormatInvalide):
                format_lineaire.ModeleLineaire.depuis_octets(texte.encode())
        brut = octets_de_modele().replace(b'"intercepts": [0.0, 1.0, 0.0]', b'"intercepts": [NaN, 1.0, 0.0]')
        with self.assertRaises(format_lineaire.FormatInvalide):
            format_lineaire.ModeleLineaire.depuis_octets(brut)
        with self.assertRaises(format_lineaire.FormatInvalide):
            format_lineaire.ModeleLineaire.depuis_octets(b"\xff\xfe")

    def test_un_fichier_trop_gros_est_refuse(self):
        with self.assertRaises(format_lineaire.FormatInvalide):
            format_lineaire.ModeleLineaire.depuis_octets(b" " * (format_lineaire.TAILLE_MAX + 1))

    def test_un_fichier_pickle_n_est_jamais_execute(self):
        """S3 : lire un fichier `pickle` exécuterait du code ; ce format le refuse sans y toucher."""
        appels = []

        class Piege:
            def __reduce__(self):
                return (appels.append, ("EXECUTE",))

        with self.assertRaises(format_lineaire.FormatInvalide):
            format_lineaire.ModeleLineaire.depuis_octets(pickle.dumps(Piege()))
        self.assertEqual(appels, [])

    @unittest.skipUnless(SKLEARN, "scikit-learn absent : python3 scripts/dev/dev.py ml-env")
    def test_l_export_de_scikit_learn_predit_comme_scikit_learn(self):
        from entrainement import candidats, evaluation

        lignes = [ligne_de_mesure(speed_ratio=0.2 + 0.07 * (i % 12), flow_veh_per_min=float(i % 9), run_id="r1", label_state=("CONGESTED", "SLOW", "FREE_FLOW")[min(2, (i % 12) // 4)])
                  for i in range(120)]
        preparation = evaluation.preparer(lignes, {"r1"})
        x, y = preparation.transformer(lignes, imputer=True)
        pipeline, _ = candidats.ajuster(candidats.LOGISTIQUE, {"C": 1.0, "class_weight": "balanced"}, x, y)
        octets = format_lineaire.exporter(pipeline, preparation)
        self.assertEqual(octets, format_lineaire.exporter(pipeline, preparation), "deux exports, mêmes octets")
        modele = format_lineaire.ModeleLineaire.depuis_octets(octets)
        attendu = [str(e) for e in pipeline.predict(x)]
        self.assertEqual(modele.predire(lignes), attendu)
        self.assertGreater(len(set(attendu)), 1)

    def test_seul_un_pipeline_lineaire_s_exporte(self):
        with self.assertRaises(format_lineaire.FormatInvalide):
            format_lineaire.exporter(object(), None)  # type: ignore[arg-type]


class TestRegistre(TempTestCase):
    def setUp(self):
        super().setUp()
        self.r = nouveau_registre(self.dossier / "models")

    def test_enregistrer_un_entrainement_ecrit_parametres_metriques_jeu_et_revision(self):
        d = run_pret(self.r)
        lu = self.r.runs.obtenir("essai-1")
        self.assertEqual((lu["status"], lu["git_sha"], lu["dataset_sha256"], lu["seed"], lu["dataset_id"]), ("trained", GIT, SHA_JEU, 42, "novaria-congestion-v1"))
        self.assertEqual((lu["params"], lu["metrics"]), ({"candidat": "logistique"}, {"decision": "accepté"}))
        self.assertEqual(d["created_at"], T0)

    def test_un_run_ne_s_enregistre_pas_deux_fois(self):
        run_pret(self.r)
        with self.assertRaises(RunDejaEnregistre):
            run_pret(self.r)

    def test_une_revision_git_mal_formee_est_refusee(self):
        with self.assertRaises(documents.DocumentInvalide):
            run_pret(self.r, git_sha="main")

    def test_rejeter_garde_la_trace_sans_fichier(self):
        run_pret(self.r, decision="rejeté")
        self.r.rejeter("essai-1", "A2 manquée")
        lu = self.r.runs.obtenir("essai-1")
        self.assertEqual((lu["status"], lu["reason"]), ("rejected", "A2 manquée"))
        self.assertNotIn("model_sha256", lu)
        self.assertFalse(self.r.objets.exists(cle_du_modele("essai-1")))
        self.assertIsNone(self.r.en_service())

    def test_un_rejet_exige_sa_raison_et_un_entrainement_en_attente(self):
        run_pret(self.r)
        with self.assertRaises(RegistreErreur):
            self.r.rejeter("essai-1", "  ")
        self.r.rejeter("essai-1", "x")
        with self.assertRaises(RegistreErreur):
            self.r.rejeter("essai-1", "x")
        with self.assertRaises(RegistreErreur):
            self.r.rejeter("inconnu", "x")

    def test_promouvoir_stocke_le_modele_son_manifeste_et_le_pointeur(self):
        run_pret(self.r)
        octets = octets_de_modele()
        run = self.r.promouvoir("essai-1", octets)
        self.assertEqual(run["status"], "registered")
        self.assertEqual(run["model_sha256"], sha256(octets))
        self.assertEqual(run["model_uri"], "local:essai-1/modele.json")
        self.assertEqual(run["model_format"], format_lineaire.NOM)
        self.assertEqual(run["registered_at"], T0 + timedelta(minutes=5))
        self.assertEqual(self.r.objets.get(cle_du_modele("essai-1")), octets)
        manifeste = json.loads(self.r.objets.get(cle_du_manifeste("essai-1")))
        self.assertEqual({k: manifeste[k] for k in ("run_id", "git_sha", "dataset_sha256", "seed", "model_sha256", "dataset_id")},
                         {"run_id": "essai-1", "git_sha": GIT, "dataset_sha256": SHA_JEU, "seed": 42, "model_sha256": sha256(octets), "dataset_id": "novaria-congestion-v1"})
        self.assertEqual(json.loads(self.r.objets.get(POINTEUR))["run_id"], "essai-1")
        self.assertEqual(self.r.en_service()["run_id"], "essai-1")

    def test_un_modele_sous_le_seuil_n_entre_pas_au_registre(self):
        for decision in ("rejeté", None, "peut-être"):
            with self.subTest(decision=decision):
                r = nouveau_registre(self.dossier / f"m-{decision}")
                run_pret(r, decision=decision)
                with self.assertRaises(RegistreErreur) as e:
                    r.promouvoir("essai-1", octets_de_modele())
                self.assertIn("accepté", str(e.exception))
                self.assertFalse(r.objets.exists(cle_du_modele("essai-1")))
                self.assertEqual(r.runs.obtenir("essai-1")["status"], "trained")

    def test_un_fichier_qui_n_est_pas_du_format_sur_n_entre_pas(self):
        run_pret(self.r)
        for octets in (pickle.dumps({"modele": 1}), b"{}", octets_de_modele(version=2)):
            with self.subTest(octets=octets[:12]), self.assertRaises(RegistreErreur):
                self.r.promouvoir("essai-1", octets)
        self.assertFalse(self.r.objets.exists(cle_du_modele("essai-1")))
        self.assertEqual(self.r.runs.obtenir("essai-1")["status"], "trained")

    def test_seul_un_entrainement_en_attente_se_promeut(self):
        run_pret(self.r)
        self.r.promouvoir("essai-1", octets_de_modele())
        with self.assertRaises(RegistreErreur):
            self.r.promouvoir("essai-1", octets_de_modele())
        with self.assertRaises(RegistreErreur):
            self.r.promouvoir("inconnu", octets_de_modele())
        run_pret(self.r, "essai-2")
        self.r.rejeter("essai-2", "x")
        with self.assertRaises(RegistreErreur):
            self.r.promouvoir("essai-2", octets_de_modele())

    def test_un_run_id_dangereux_n_atteint_jamais_le_magasin(self):
        for faux in ("../x", "a/b", "/abs", ".."):
            with self.subTest(faux=faux), self.assertRaises(documents.DocumentInvalide):
                self.r.promouvoir(faux, octets_de_modele())

    def test_une_reprise_apres_un_echec_passe_avec_les_memes_octets(self):
        run_pret(self.r)
        octets = octets_de_modele()
        self.r.objets.put(cle_du_modele("essai-1"), octets)  # reste d'une promotion interrompue après l'écriture du fichier
        run = self.r.promouvoir("essai-1", octets)
        self.assertEqual(run["status"], "registered")

    def test_un_fichier_deja_la_avec_un_autre_contenu_arrete_la_promotion(self):
        run_pret(self.r)
        self.r.objets.put(cle_du_modele("essai-1"), octets_de_modele(intercepts=[9.0, 0.0, 0.0]))
        with self.assertRaises(RegistreErreur) as e:
            self.r.promouvoir("essai-1", octets_de_modele())
        self.assertIn("autre contenu", str(e.exception))
        self.assertEqual(self.r.runs.obtenir("essai-1")["status"], "trained")

    def test_un_changement_d_etat_pendant_la_promotion_ne_met_rien_en_service(self):
        run_pret(self.r)
        reel = self.r.runs.mettre_a_jour
        self.r.runs.mettre_a_jour = lambda *a, **k: False  # un autre processus a gagné la course
        with self.assertRaises(RegistreErreur) as e:
            self.r.promouvoir("essai-1", octets_de_modele())
        self.r.runs.mettre_a_jour = reel
        self.assertIn("a changé d'état", str(e.exception))
        self.assertFalse(self.r.objets.exists(POINTEUR))
        self.assertIsNone(self.r.en_service())

    def test_le_dernier_enregistre_est_en_service_et_un_retour_en_arriere_est_possible(self):
        temps = iter(T0 + timedelta(minutes=m) for m in (1, 2, 3, 4, 5, 6))
        r = Registre(MemoireRunStore(), StockageLocal(self.dossier / "m2"), lambda: next(temps))
        run_pret(r, "essai-1")
        run_pret(r, "essai-2", created_at=T0 + timedelta(minutes=1))
        r.promouvoir("essai-1", octets_de_modele())
        r.promouvoir("essai-2", octets_de_modele(intercepts=[0.0, 0.0, 1.0]))
        self.assertEqual(r.en_service()["run_id"], "essai-2")
        self.assertEqual(json.loads(r.objets.get(POINTEUR))["run_id"], "essai-2")
        r.remettre_en_service("essai-1")  # ADR-017 : retour à la version précédente
        self.assertEqual(r.en_service()["run_id"], "essai-1")
        self.assertEqual(json.loads(r.objets.get(POINTEUR))["run_id"], "essai-1")

    def test_remettre_en_service_refuse_un_modele_altere_ou_non_enregistre(self):
        run_pret(self.r)
        with self.assertRaises(RegistreErreur):
            self.r.remettre_en_service("essai-1")  # pas enregistré
        self.r.promouvoir("essai-1", octets_de_modele())
        chemin = self.dossier / "models" / "essai-1" / "modele.json"
        chemin.chmod(0o644)
        chemin.write_bytes(octets_de_modele(intercepts=[5.0, 0.0, 0.0]))
        with self.assertLogs("registre", level="WARNING"), self.assertRaises(RegistreErreur):
            self.r.remettre_en_service("essai-1")

    def test_aucun_chemin_pour_modifier_un_modele_enregistre(self):
        run_pret(self.r)
        run = self.r.promouvoir("essai-1", octets_de_modele())
        self.assertFalse(self.r.runs.mettre_a_jour("essai-1", {"status": "rejected", "reason": "x"}, statut_attendu="trained"))
        with self.assertRaises(RegistreErreur):
            self.r.rejeter("essai-1", "x")
        self.assertEqual(self.r.runs.obtenir("essai-1")["model_sha256"], run["model_sha256"])


class TestServiceCoteInference(TempTestCase):
    def setUp(self):
        super().setUp()
        self.racine = self.dossier / "models"
        self.r = nouveau_registre(self.racine)
        run_pret(self.r)
        self.octets = octets_de_modele()
        self.r.promouvoir("essai-1", self.octets)
        self.magasin = StockageLocal(self.racine)

    def alterer(self, cle, octets):
        chemin = self.racine / cle
        chemin.chmod(0o644)
        chemin.write_bytes(octets)

    def test_le_modele_en_service_se_charge_avec_sa_lignee_sans_mongodb(self):
        modele = service.charger_le_modele_en_service(self.magasin)
        self.assertEqual(modele.run_id, "essai-1")
        self.assertEqual((modele.manifeste["git_sha"], modele.manifeste["dataset_sha256"], modele.manifeste["model_sha256"]), (GIT, SHA_JEU, sha256(self.octets)))
        self.assertEqual(modele.predire([ligne_de_mesure()]), ["FREE_FLOW"])

    def test_sans_pointeur_rien_n_est_charge(self):
        with self.assertLogs("registre", level="WARNING"), self.assertRaises(service.ModeleRefuse):
            service.charger_le_modele_en_service(StockageLocal(self.dossier / "vide"))

    def test_un_modele_altere_est_refuse_et_journalise(self):
        self.alterer("essai-1/modele.json", octets_de_modele(intercepts=[9.0, 0.0, 0.0]))
        with self.assertLogs("registre", level="WARNING") as journal, self.assertRaises(service.ModeleRefuse) as e:
            service.charger_le_modele_en_service(self.magasin)
        self.assertIn("altéré", str(e.exception))
        self.assertTrue(any("refusé" in ligne for ligne in journal.output))

    def test_un_manifeste_altere_est_refuse(self):
        manifeste = json.loads(self.magasin.get(cle_du_manifeste("essai-1")))
        manifeste["git_sha"] = "b" * 40
        self.alterer("essai-1/manifeste.json", json.dumps(manifeste).encode())
        with self.assertLogs("registre", level="WARNING"), self.assertRaises(service.ModeleRefuse) as e:
            service.charger_le_modele_en_service(self.magasin)
        self.assertIn("pointeur", str(e.exception))

    def test_un_pointeur_vers_un_run_inconnu_ou_dangereux_est_refuse(self):
        for contenu in ({"run_id": "autre", "manifeste_sha256": "0" * 64}, {"run_id": "../x", "manifeste_sha256": "0" * 64}, {"run_id": 3}, []):
            with self.subTest(contenu=contenu):
                self.alterer(POINTEUR, json.dumps(contenu).encode())
                with self.assertLogs("registre", level="WARNING"), self.assertRaises(service.ModeleRefuse):
                    service.charger_le_modele_en_service(self.magasin)

    def test_un_pointeur_ou_un_manifeste_illisible_est_refuse(self):
        self.alterer(POINTEUR, b"pas du json")
        with self.assertLogs("registre", level="WARNING"), self.assertRaises(service.ModeleRefuse):
            service.charger_le_modele_en_service(self.magasin)

    def test_un_attaquant_qui_refait_manifeste_et_pointeur_ne_fait_pas_executer_de_code(self):
        """Même avec des empreintes cohérentes (manifeste et pointeur réécrits), un fichier `pickle` n'est jamais exécuté."""
        appels = []

        class Piege:
            def __reduce__(self):
                return (appels.append, ("EXECUTE",))

        piege = pickle.dumps(Piege())
        manifeste = json.loads(self.magasin.get(cle_du_manifeste("essai-1")))
        manifeste["model_sha256"] = sha256(piege)
        octets_manifeste = json.dumps(manifeste).encode()
        self.alterer("essai-1/modele.json", piege)
        self.alterer("essai-1/manifeste.json", octets_manifeste)
        self.alterer(POINTEUR, json.dumps({"run_id": "essai-1", "manifeste_sha256": sha256(octets_manifeste)}).encode())
        with self.assertLogs("registre", level="WARNING"), self.assertRaises(service.ModeleRefuse):
            service.charger_le_modele_en_service(self.magasin)
        self.assertEqual(appels, [])


def sha_du_depot() -> str | None:
    try:
        sortie = subprocess.run(["git", "-C", str(RACINE), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return sortie.stdout.strip() if sortie.returncode == 0 and len(sortie.stdout.strip()) == 40 else None


class TestLignee(TempTestCase):
    def setUp(self):
        super().setUp()
        self.racine = self.dossier / "models"
        self.r = nouveau_registre(self.racine)

    def enregistre(self, run_id="essai-1", **champs):
        run_pret(self.r, run_id, **champs)
        self.r.promouvoir(run_id, octets_de_modele())
        return self.r.runs.obtenir(run_id)

    def jeu_fabrique(self) -> Path:
        from tests.test_integrite import fabriquer

        dossier = self.dossier / "jeu"
        dossier.mkdir()
        manifeste = fabriquer(dossier)
        self.sha_du_jeu = manifeste["empreinte_du_jeu"]
        return dossier

    def test_un_modele_en_service_est_relie_a_son_entrainement_et_a_son_jeu(self):
        """Le critère de l'issue : le modèle en service remonte au run, à la révision Git et à l'empreinte du jeu."""
        git = sha_du_depot()
        if git is None:
            self.skipTest("git indisponible")
        jeu = self.jeu_fabrique()
        run = self.enregistre(git_sha=git, dataset_sha256=self.sha_du_jeu)
        res = lignee.verifier_la_chaine(self.r.en_service(), self.r.objets, jeu=jeu)
        self.assertTrue(res.intacte, res.ecarts)
        self.assertEqual(res.ecarts, [])
        self.assertEqual(res.chaine["entrainement"]["run_id"], run["run_id"])
        self.assertEqual(res.chaine["code"]["git_sha"], git)
        self.assertEqual(res.chaine["jeu"]["dataset_sha256"], self.sha_du_jeu)
        self.assertEqual(res.chaine["modele"]["model_sha256"], run["model_sha256"])
        self.assertTrue(res.chaine["en_service"])
        self.assertEqual(len(res.verifie), 4)
        self.assertEqual(res.non_verifie, [])

    def test_ce_qui_n_a_pas_ete_controle_est_dit(self):
        run = self.enregistre()
        res = lignee.verifier_la_chaine(run, self.r.objets)
        self.assertTrue(any("jeu de données non fourni" in m for m in res.non_verifie))

    def test_un_modele_remplace_est_un_ecart(self):
        run = self.enregistre()
        chemin = self.racine / "essai-1" / "modele.json"
        chemin.chmod(0o644)
        chemin.write_bytes(octets_de_modele(intercepts=[3.0, 0.0, 0.0]))
        res = lignee.verifier_la_chaine(run, self.r.objets)
        self.assertFalse(res.intacte)
        self.assertTrue(any("empreinte" in e for e in res.ecarts))

    def test_un_manifeste_qui_diverge_de_model_runs_est_un_ecart(self):
        run = self.enregistre()
        manifeste = json.loads(self.r.objets.get(cle_du_manifeste("essai-1")))
        manifeste["dataset_sha256"] = "9" * 64
        chemin = self.racine / "essai-1" / "manifeste.json"
        chemin.chmod(0o644)
        chemin.write_bytes(json.dumps(manifeste).encode())
        res = lignee.verifier_la_chaine(run, self.r.objets)
        self.assertTrue(any("manifeste" in e and "dataset_sha256" in e for e in res.ecarts))

    def test_un_jeu_modifie_est_un_ecart(self):
        jeu = self.jeu_fabrique()
        run = self.enregistre(dataset_sha256=self.sha_du_jeu)
        (jeu / "train.parquet").write_bytes(b"PAR1 autre PAR1")
        res = lignee.verifier_la_chaine(run, self.r.objets, jeu=jeu)
        self.assertTrue(any(e.startswith("jeu :") for e in res.ecarts))

    def test_un_autre_jeu_que_celui_de_l_entrainement_est_un_ecart(self):
        jeu = self.jeu_fabrique()
        res = lignee.verifier_la_chaine(self.enregistre(), self.r.objets, jeu=jeu)  # run enregistré avec SHA_JEU, pas celui du dossier
        self.assertTrue(any("empreinte attendue" in e for e in res.ecarts))

    def test_un_run_non_enregistre_n_a_pas_de_modele_a_relier(self):
        run_pret(self.r, "essai-9", decision="rejeté")
        self.r.rejeter("essai-9", "A2")
        res = lignee.verifier_la_chaine(self.r.runs.obtenir("essai-9"), self.r.objets)
        self.assertFalse(res.intacte)
        self.assertIn("rejected", res.ecarts[0])

    def test_une_revision_inconnue_ou_un_code_non_commite_sont_signales(self):
        run = self.enregistre(git_sha="c" * 40, git_dirty=True)
        res = lignee.verifier_la_chaine(run, self.r.objets)
        self.assertTrue(res.intacte, "ce sont des avertissements, pas des écarts")
        self.assertTrue(any("introuvable" in a for a in res.avertissements))
        self.assertTrue(any("non commité" in a for a in res.avertissements))

    def test_git_indisponible_est_non_verifie(self):
        run = self.enregistre()
        with mock.patch("registre.lignee.subprocess.run", side_effect=OSError):
            res = lignee.verifier_la_chaine(run, self.r.objets)
        self.assertTrue(any("git est indisponible" in m for m in res.non_verifie))

    def test_un_modele_qui_n_est_pas_celui_du_pointeur_est_signale(self):
        self.enregistre("essai-1")
        self.r.horloge = lambda: T0 + timedelta(minutes=9)
        self.enregistre("essai-2")
        res = lignee.verifier_la_chaine(self.r.runs.obtenir("essai-1"), self.r.objets)
        self.assertFalse(res.chaine["en_service"])
        self.assertTrue(any("pointeur" in a for a in res.avertissements))

    def test_le_resultat_se_serialise(self):
        run = self.enregistre()
        json.dumps(lignee.verifier_la_chaine(run, self.r.objets).en_dict())


class TestImportDeLEvaluationIa03(unittest.TestCase):
    def setUp(self):
        if not tracabilite.RESULTAT_TEST.is_file():
            self.skipTest("ml/evaluation/resultat-test.json absent")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r = nouveau_registre(Path(self.tmp.name))
        self.resultat = json.loads(tracabilite.RESULTAT_TEST.read_text(encoding="utf-8"))

    def test_le_run_d_ia03_entre_dans_model_runs_rejete_et_sans_fichier(self):
        run_id, doc, cree = importer_ia03.importer(self.r)
        self.assertTrue(cree)
        self.assertEqual(run_id, f"ia03-logistique-{self.resultat['selection_sha256'][:10]}")
        self.assertEqual(doc["status"], "rejected")
        self.assertIn("A2", doc["reason"])
        self.assertIn("A5", doc["reason"])
        self.assertNotIn("model_sha256", doc)
        self.assertFalse(self.r.objets.exists(cle_du_modele(run_id)))
        self.assertIsNone(self.r.en_service())

    def test_les_champs_du_registre_sont_ceux_de_l_evaluation(self):
        _, doc, _ = importer_ia03.importer(self.r)
        t = self.resultat["tracabilite"]
        self.assertEqual((doc["git_sha"], doc["git_dirty"], doc["dataset_sha256"], doc["dataset_id"], doc["seed"]),
                         (t["git_sha"], t["code_modifie_non_commite"], t["dataset_sha256"], t["dataset_id"], t["seed"]))
        self.assertEqual(doc["params"]["hyperparametres"], self.resultat["params"])
        self.assertEqual(doc["params"]["versions"], t["versions"])
        self.assertEqual(doc["metrics"]["decision"], "rejeté")
        self.assertEqual(doc["metrics"]["modele"], self.resultat["modele"])
        self.assertEqual(len(doc["metrics"]["conditions"]), 5)
        self.assertEqual(doc["created_at"], datetime.fromisoformat(self.resultat["lu_le"]))

    def test_refaire_l_import_ne_cree_pas_de_doublon(self):
        importer_ia03.importer(self.r)
        run_id, doc, cree = importer_ia03.importer(self.r)
        self.assertFalse(cree)
        self.assertEqual(len(self.r.runs.lister()), 1)
        self.assertEqual(doc["status"], "rejected")

    def test_un_resultat_accepte_reste_en_attente_de_promotion(self):
        accepte = {**self.resultat, "decision": "accepté", "conditions": [{**c, "remplie": True} for c in self.resultat["conditions"]]}
        with mock.patch.object(tracabilite, "RESULTAT_TEST", Path(self.tmp.name) / "r.json"):
            tracabilite.RESULTAT_TEST.write_text(json.dumps(accepte), encoding="utf-8")
            run_id, doc, _ = importer_ia03.importer(self.r)
        self.assertEqual(doc["status"], "trained")
        self.assertEqual(doc["metrics"]["decision"], "accepté")
        self.r.promouvoir(run_id, octets_de_modele())  # c'est alors la seule garde qui reste : la décision
        self.assertEqual(self.r.en_service()["run_id"], run_id)


class TestLigneDeCommande(TempTestCase):
    def appeler(self, *argv, registre=None, magasin=None, environnement=None):
        sortie, erreur = StringIO(), StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur), \
                mock.patch.object(cli, "registre", return_value=registre), \
                mock.patch.object(cli, "RACINE_DU_MAGASIN", self.dossier / "models"), \
                mock.patch.dict(os.environ, environnement or {}, clear=False):
            code = cli.main(list(argv))
        return code, sortie.getvalue(), erreur.getvalue()

    def test_sans_adresse_mongodb_la_configuration_manque(self):
        sortie, erreur = StringIO(), StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur), mock.patch.dict(os.environ, {}, clear=True):
            code = cli.main(["lister"])
        self.assertEqual(code, 2)
        self.assertIn("MONGO_URL", erreur.getvalue())

    def test_seul_le_stockage_local_existe(self):
        code, _, erreur = self.appeler("charger", environnement={"STORAGE_BACKEND": "s3"})
        self.assertEqual(code, 2)
        self.assertIn("S3", erreur)

    def test_charger_sans_modele_en_service_refuse(self):
        with self.assertLogs("registre", level="WARNING"):
            code, _, erreur = self.appeler("charger")
        self.assertEqual(code, 1)
        self.assertIn("Refusé", erreur)

    def test_sans_modele_enregistre_la_regle_reste_en_service(self):
        r = nouveau_registre(self.dossier / "models")
        code, sortie, _ = self.appeler("en-service", registre=r)
        self.assertEqual(code, 0)
        self.assertIn("règle de seuils", sortie)

    def test_lister_lignee_en_service_et_charger_sur_un_modele_enregistre(self):
        r = nouveau_registre(self.dossier / "models")
        run_pret(r)
        r.promouvoir("essai-1", octets_de_modele())
        code, sortie, _ = self.appeler("lister", registre=r)
        self.assertEqual((code, json.loads(sortie)[0]["run_id"]), (0, "essai-1"))
        code, sortie, _ = self.appeler("en-service", registre=r)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(sortie)["chaine"]["en_service"])
        code, sortie, _ = self.appeler("lignee", "essai-1", registre=r)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(sortie)["chaine"]["jeu"]["dataset_sha256"], SHA_JEU)
        code, sortie, _ = self.appeler("charger")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(sortie)["lignee"]["git_sha"], GIT)

    def test_une_lignee_rompue_rend_le_code_1(self):
        r = nouveau_registre(self.dossier / "models")
        run_pret(r)
        r.promouvoir("essai-1", octets_de_modele())
        chemin = self.dossier / "models" / "essai-1" / "modele.json"
        chemin.chmod(0o644)
        chemin.write_bytes(b"{}")
        code, sortie, _ = self.appeler("lignee", "essai-1", registre=r)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(sortie)["intacte"])

    def test_un_run_inconnu_ou_dangereux(self):
        r = nouveau_registre(self.dossier / "models")
        code, _, erreur = self.appeler("lignee", "inconnu", registre=r)
        self.assertEqual((code, "aucun run" in erreur), (1, True))
        code, _, erreur = self.appeler("lignee", "../x", registre=r)
        self.assertEqual((code, "Refusé" in erreur), (1, True))

    @unittest.skipUnless(tracabilite.RESULTAT_TEST.is_file(), "résultat d'IA-03 absent")
    def test_importer_ia03_deux_fois(self):
        r = nouveau_registre(self.dossier / "models")
        code, sortie, _ = self.appeler("importer-ia03", registre=r)
        self.assertEqual((code, sortie.startswith("Écrit")), (0, True))
        code, sortie, _ = self.appeler("importer-ia03", registre=r)
        self.assertEqual((code, sortie.startswith("Déjà présent")), (0, True))

    def test_le_registre_se_construit_depuis_l_environnement(self):
        with mock.patch.dict(os.environ, {"MONGO_URL": "mongodb://x"}), \
                mock.patch.object(cli.MongoRunStore, "depuis_l_adresse", return_value=MemoireRunStore()) as fabrique:
            r = cli.registre()
        fabrique.assert_called_once_with("mongodb://x")
        self.assertIsInstance(r.objets, StockageLocal)


@unittest.skipUnless(os.environ.get("REGISTRE_MONGO_URL") and pymongo, "MongoDB d'essai absent : python3 scripts/dev/dev.py ml-registre-essai")
class TestAvecUnVraiMongoDB(TempTestCase):
    """Le même cycle sur le vrai `model_runs` (index unique, validateur, dates BSON), avec le compte `svc_ml`."""

    @classmethod
    def setUpClass(cls):
        cls.prefixe = f"essai-{os.getpid()}-{int(datetime.now(UTC).timestamp())}"

    def registre(self) -> Registre:
        runs = MongoRunStore.depuis_l_adresse(os.environ["REGISTRE_MONGO_URL"])
        self.addCleanup(runs.fermer)
        return Registre(runs, StockageLocal(self.dossier / "models"))

    def test_cycle_complet_et_lignee_sur_mongodb(self):
        r = self.registre()
        gagnant, perdant = f"{self.prefixe}-a", f"{self.prefixe}-b"
        run_pret(r, gagnant, created_at=T0)
        run_pret(r, perdant, decision="rejeté", created_at=T0)
        with self.assertRaises(RunDejaEnregistre):
            run_pret(r, gagnant)
        r.rejeter(perdant, "sous le seuil")
        run = r.promouvoir(gagnant, octets_de_modele())
        self.assertEqual(r.runs.obtenir(perdant)["status"], "rejected")
        self.assertEqual(r.en_service()["run_id"], gagnant)
        res = lignee.verifier_la_chaine(r.en_service(), r.objets)
        self.assertTrue(res.intacte, res.ecarts)
        self.assertEqual(res.chaine["jeu"]["dataset_sha256"], SHA_JEU)
        self.assertEqual(res.chaine["modele"]["model_sha256"], run["model_sha256"])
        self.assertEqual(service.charger_le_modele_en_service(r.objets).manifeste["run_id"], gagnant)

    def test_une_mise_a_jour_perdante_ne_change_rien_et_le_validateur_de_la_base_refuse_un_document_mal_forme(self):
        r = self.registre()
        run_id = f"{self.prefixe}-c"
        run_pret(r, run_id)
        self.assertTrue(r.runs.mettre_a_jour(run_id, {"status": "rejected", "reason": "x"}, statut_attendu="trained"))
        self.assertFalse(r.runs.mettre_a_jour(run_id, {"status": "rejected", "reason": "y"}, statut_attendu="trained"))
        mauvais = {"run_id": f"{self.prefixe}-d", "created_at": T0, "git_sha": GIT, "dataset_sha256": SHA_JEU, "seed": 1, "params": {}, "metrics": {}, "status": "trained"}
        with self.assertRaises(pymongo.errors.WriteError):  # on contourne valider() : c'est le validateur de la base qui juge
            r.runs.collection.insert_one({**mauvais, "dataset_sha256": "pas-un-sha"})


if __name__ == "__main__":
    unittest.main()
