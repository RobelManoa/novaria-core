"""Chargement d'un réseau de vitesses (IA-16) : un manifeste et des mesures suffisent, rejouer ne change rien, un capteur ne change jamais de rang.

    python -m unittest discover -s data/etl/tests

Aucun accès à une base : un faux entrepôt garde ce qu'on lui donne, avec les mêmes règles de clé (réseau, instant, capteur) que la table.
"""

import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from pipelines import charger_vitesses as cv

MANIFESTE = {"network_id": "metr-la", "label": "METR-LA (essai)", "description": "fabriqué", "source_type": "REAL_HISTORICAL",
             "step_s": 300, "speed_unit": "mph", "sensors": ["A1", "B2", "C3"]}
ENTETE = "observed_at,sensor_id,speed\n"


class FauxEntrepot:
    def __init__(self) -> None:
        self.manifestes: dict[str, cv.Manifeste] = {}
        self.mesures: dict[tuple, float] = {}
        self.refuser_rang = False

    def enregistrer(self, manifeste: cv.Manifeste) -> None:
        ancien = self.manifestes.get(manifeste.network_id)
        if ancien and manifeste.sensors[: len(ancien.sensors)] != ancien.sensors:
            raise cv.ErreurChargement("le manifeste déplace un capteur déjà connu")
        self.manifestes[manifeste.network_id] = manifeste

    def charger(self, network_id: str, lot: list) -> int:
        for instant, rang, vitesse in lot:
            self.mesures[(network_id, instant, rang)] = vitesse
        return len(lot)


def dossier(tmp: Path, manifeste=MANIFESTE, lignes="") -> Path:
    (tmp / "manifeste.json").write_text(json.dumps(manifeste), encoding="utf-8")
    (tmp / "mesures.csv").write_text(ENTETE + lignes, encoding="utf-8")
    return tmp


BONNES = "2012-06-20T08:00:00Z,A1,60.5\n2012-06-20T08:00:00Z,B2,55\n2012-06-20T08:05:00Z,A1,58.25\n"


class Manifestes(unittest.TestCase):
    def test_un_manifeste_valide_se_lit(self):
        with tempfile.TemporaryDirectory() as t:
            m = cv.lire_manifeste(dossier(Path(t)) / "manifeste.json")
        self.assertEqual((m.network_id, m.step_s, m.sensors), ("metr-la", 300, ("A1", "B2", "C3")))

    def test_les_manifestes_faux_sont_refuses(self):
        cas = {
            "champ en trop": {**MANIFESTE, "x": 1},
            "champ manquant": {k: v for k, v in MANIFESTE.items() if k != "label"},
            "nom de réseau": {**MANIFESTE, "network_id": "Pas Valide"},
            "source inconnue": {**MANIFESTE, "source_type": "AUTRE"},
            "pas": {**MANIFESTE, "step_s": 7},
            "unité": {**MANIFESTE, "speed_unit": "furlong"},
            "aucun capteur": {**MANIFESTE, "sensors": []},
            "capteurs en double": {**MANIFESTE, "sensors": ["A1", "A1"]},
            "identifiant de capteur": {**MANIFESTE, "sensors": ["a b"]},
        }
        for nom, manifeste in cas.items():
            with self.subTest(nom), tempfile.TemporaryDirectory() as t, self.assertRaises(cv.ErreurChargement):
                cv.lire_manifeste(dossier(Path(t), manifeste) / "manifeste.json")

    def test_un_manifeste_illisible_est_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "manifeste.json").write_text("{pas du json", encoding="utf-8")
            with self.assertRaises(cv.ErreurChargement):
                cv.lire_manifeste(Path(t) / "manifeste.json")


class Mesures(unittest.TestCase):
    def test_les_mesures_valides_sont_chargees_telles_quelles(self):
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            resultat = cv.charger_reseau(dossier(Path(t), lignes=BONNES), entrepot=entrepot)
        self.assertEqual((resultat.lues, resultat.chargees, resultat.rejetees, resultat.capteurs), (3, 3, 0, 3))
        self.assertEqual(sorted(entrepot.mesures.values()), [55.0, 58.25, 60.5])
        self.assertEqual({rang for (_, _, rang) in entrepot.mesures}, {0, 1})  # le capteur C3 n'a aucune ligne : rien n'est inventé

    def test_rejouer_ne_cree_aucune_ligne_et_ne_change_aucune_valeur(self):
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            d = dossier(Path(t), lignes=BONNES)
            cv.charger_reseau(d, entrepot=entrepot)
            avant = dict(entrepot.mesures)
            cv.charger_reseau(d, entrepot=entrepot)
        self.assertEqual(entrepot.mesures, avant)

    def test_une_valeur_corrigee_dans_le_fichier_remplace_l_ancienne(self):
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            cv.charger_reseau(dossier(Path(t), lignes="2012-06-20T08:00:00Z,A1,60\n"), entrepot=entrepot)
            cv.charger_reseau(dossier(Path(t), lignes="2012-06-20T08:00:00Z,A1,61\n"), entrepot=entrepot)
        self.assertEqual(list(entrepot.mesures.values()), [61.0])

    def test_les_lignes_refusees_sont_comptees_par_motif_et_le_reste_charge(self):
        lignes = (BONNES + "2012-06-20T08:00:00Z,ZZ,50\n" + "pas un instant,A1,50\n" + "2012-06-20T08:03:00Z,A1,50\n"
                  + "2012-06-20T08:10:00Z,A1,0\n" + "2012-06-20T08:10:00Z,A1,abc\n" + "2012-06-20T08:10:00Z,A1,400\n"
                  + "2012-06-20T08:10:00Z,A1\n" + "2012-13-45T08:10:00Z,A1,50\n")
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            resultat = cv.charger_reseau(dossier(Path(t), lignes=lignes), entrepot=entrepot)
        self.assertEqual(resultat.chargees, 3)
        self.assertEqual(resultat.par_motif, {"capteur inconnu": 1, "instant mal formé": 2, "instant non aligné sur le pas": 1,
                                              "vitesse hors bornes": 3, "colonnes": 1})
        self.assertEqual(resultat.lues, resultat.chargees + resultat.rejetees)

    def test_un_en_tete_faux_est_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            d = dossier(Path(t))
            (d / "mesures.csv").write_text("a,b,c\n", encoding="utf-8")
            with self.assertRaises(cv.ErreurChargement):
                cv.charger_reseau(d, entrepot=FauxEntrepot())

    def test_un_gros_fichier_est_charge_par_lots(self):
        lignes = "".join(f"2012-06-20T08:{5 * i // 60 % 60:02d}:00Z,A1,50\n" for i in range(3))
        with tempfile.TemporaryDirectory() as t:
            appels = []

            class Compte(FauxEntrepot):
                def charger(self, network_id, lot):
                    appels.append(len(lot))
                    return super().charger(network_id, lot)

            ancien = cv.LOT
            cv.LOT = 2
            try:
                cv.charger_reseau(dossier(Path(t), lignes=lignes), entrepot=Compte())
            finally:
                cv.LOT = ancien
        self.assertEqual(appels, [2, 1])


class Extensibilite(unittest.TestCase):
    def test_ajouter_des_capteurs_ne_demande_qu_un_fichier(self):
        """Cent capteurs de plus : on les ajoute en fin de liste, le même code charge tout, les anciens gardent leur rang."""
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            cv.charger_reseau(dossier(Path(t), lignes=BONNES), entrepot=entrepot)
            nouveaux = [f"N{i:03d}" for i in range(100)]
            manifeste = {**MANIFESTE, "sensors": [*MANIFESTE["sensors"], *nouveaux]}
            lignes = BONNES + "".join(f"2012-06-20T08:00:00Z,{c},50\n" for c in nouveaux)
            resultat = cv.charger_reseau(dossier(Path(t), manifeste, lignes), entrepot=entrepot)
        self.assertEqual(resultat.capteurs, 103)
        self.assertEqual(resultat.chargees, 103)
        self.assertEqual({rang for (_, _, rang) in entrepot.mesures}, {0, 1, *range(3, 103)})

    def test_un_manifeste_qui_deplace_un_capteur_connu_est_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            entrepot = FauxEntrepot()
            cv.charger_reseau(dossier(Path(t), lignes=BONNES), entrepot=entrepot)
            deplace = {**MANIFESTE, "sensors": ["B2", "A1", "C3"]}
            with self.assertRaises(cv.ErreurChargement):
                cv.charger_reseau(dossier(Path(t), deplace, BONNES), entrepot=entrepot)


class LigneDeCommande(unittest.TestCase):
    def lancer(self, base: Path, *arguments, entrepot=None):
        sortie, erreur = StringIO(), StringIO()
        with redirect_stdout(sortie), redirect_stderr(erreur):
            code = cv.principal(list(arguments), entrepot=entrepot or FauxEntrepot(), base=base)
        return code, sortie.getvalue(), erreur.getvalue()

    def test_un_chargement_reussi_dit_ce_qu_il_a_fait(self):
        with tempfile.TemporaryDirectory() as t:
            dossier(Path(t) / "metr-la" if (Path(t) / "metr-la").mkdir() is None else Path(t), lignes=BONNES)
            code, sortie, _ = self.lancer(Path(t), "--reseau", "metr-la")
        self.assertEqual(code, 0)
        self.assertIn("3 capteurs ; 3 lignes lues, 3 chargées, 0 refusées", sortie)

    def test_un_nom_de_reseau_qui_sort_du_dossier_est_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            for nom in ("../x", "/etc", "A B", "metr_la", ""):
                with self.subTest(nom):
                    code, _, erreur = self.lancer(Path(t), "--reseau", nom)
                    self.assertEqual(code, 1)
                    self.assertIn("ERREUR", erreur)

    def test_un_reseau_sans_fichiers_est_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "vide").mkdir()
            code, _, erreur = self.lancer(Path(t), "--reseau", "vide")
        self.assertEqual(code, 1)
        self.assertIn("manifeste.json", erreur)

    def test_sans_adresse_postgresql_le_message_est_clair(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "metr-la").mkdir()
            dossier(Path(t) / "metr-la", lignes=BONNES)
            sortie, erreur = StringIO(), StringIO()
            import os
            avant = os.environ.pop("POSTGRES_URL", None)
            try:
                with redirect_stdout(sortie), redirect_stderr(erreur):
                    code = cv.principal(["--reseau", "metr-la"], base=Path(t))
            finally:
                if avant is not None:
                    os.environ["POSTGRES_URL"] = avant
        self.assertEqual(code, 1)
        self.assertIn("POSTGRES_URL", erreur.getvalue())


class FausseConnexion:
    """Une connexion PostgreSQL de papier : garde les requêtes, rend des rangs connus, peut refuser une écriture."""

    def __init__(self, connus=(), erreur=None) -> None:
        self.requetes: list[tuple] = []
        self.connus = list(connus)
        self.erreur = erreur
        self.fermee = False

    def transaction(self):
        return nullcontext()

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, requete, parametres=()):
        if self.erreur and ("INSERT" in requete or "SELECT" in requete):
            raise self.erreur
        self.requetes.append((requete, parametres))

    def fetchall(self):
        return self.connus

    def close(self):
        self.fermee = True


class EntrepotPostgresDePapier(unittest.TestCase):
    def manifeste(self):
        with tempfile.TemporaryDirectory() as t:
            return cv.lire_manifeste(dossier(Path(t)) / "manifeste.json")

    def test_un_nouveau_reseau_est_inscrit_avec_ses_capteurs_dans_l_ordre(self):
        connexion = FausseConnexion()
        cv.EntrepotPostgres(connexion).enregistrer(self.manifeste())
        inserts = [p for r, p in connexion.requetes if "INSERT INTO dwh.speed_sensor" in r]
        self.assertEqual(inserts, [("metr-la", 0, "A1"), ("metr-la", 1, "B2"), ("metr-la", 2, "C3")])

    def test_seuls_les_capteurs_nouveaux_sont_ajoutes_en_fin_de_liste(self):
        connexion = FausseConnexion(connus=[(0, "A1"), (1, "B2")])
        cv.EntrepotPostgres(connexion).enregistrer(self.manifeste())
        inserts = [p for r, p in connexion.requetes if "INSERT INTO dwh.speed_sensor" in r]
        self.assertEqual(inserts, [("metr-la", 2, "C3")])

    def test_un_capteur_deplace_ou_retire_est_refuse(self):
        for nom, connus in {"déplacé": [(0, "B2")], "retiré": [(0, "A1"), (1, "B2"), (2, "C3"), (3, "D4")]}.items():
            with self.subTest(nom), self.assertRaisesRegex(cv.ErreurChargement, "rang"):
                cv.EntrepotPostgres(FausseConnexion(connus=connus)).enregistrer(self.manifeste())

    def test_un_lot_s_ecrit_en_une_requete_par_colonnes(self):
        connexion = FausseConnexion()
        ecrites = cv.EntrepotPostgres(connexion).charger("metr-la", [("2012-06-20T08:00:00Z", 0, 60.5), ("2012-06-20T08:05:00Z", 1, 55.0)])
        self.assertEqual(ecrites, 2)
        requete, parametres = connexion.requetes[0]
        self.assertIn("ON CONFLICT (network_id, observed_at, sensor_key) DO UPDATE", requete)
        self.assertNotIn("TEMP", requete.upper())  # le compte du traitement n'a pas le droit de créer une table temporaire
        self.assertEqual(parametres, ("metr-la", ["2012-06-20T08:00:00Z", "2012-06-20T08:05:00Z"], [0, 1], [60.5, 55.0]))

    def test_un_refus_de_postgresql_devient_une_erreur_de_chargement_sans_detail(self):
        import psycopg

        entrepot = cv.EntrepotPostgres(FausseConnexion(erreur=psycopg.errors.InsufficientPrivilege("secret interne")))
        with self.assertRaises(cv.ErreurChargement) as ctx:
            entrepot.charger("metr-la", [("2012-06-20T08:00:00Z", 0, 60.5)])
        self.assertIn("InsufficientPrivilege", str(ctx.exception))
        self.assertNotIn("secret interne", str(ctx.exception))
        with self.assertRaises(cv.ErreurChargement):
            entrepot.enregistrer(self.manifeste())

    def test_une_base_injoignable_donne_un_message_clair_sans_l_adresse(self):
        import psycopg

        with mock.patch.object(psycopg, "connect", side_effect=psycopg.OperationalError("hôte mot-de-passe-x")):
            with self.assertRaises(cv.ErreurChargement) as ctx:
                cv.EntrepotPostgres.depuis_url("postgresql://u:p@h/db")
        self.assertIn("db-up", str(ctx.exception))
        self.assertNotIn("mot-de-passe-x", str(ctx.exception))

    def test_une_connexion_reussie_est_gardee_puis_fermee_par_la_ligne_de_commande(self):
        import psycopg

        connexion = FausseConnexion()
        with tempfile.TemporaryDirectory() as t, mock.patch.object(psycopg, "connect", return_value=connexion):
            (Path(t) / "metr-la").mkdir()
            dossier(Path(t) / "metr-la", lignes=BONNES)
            sortie = StringIO()
            with redirect_stdout(sortie):
                code = cv.principal(["--reseau", "metr-la", "--postgres-url", "postgresql://u:p@h/db"], base=Path(t))
        self.assertEqual(code, 0)
        self.assertTrue(connexion.fermee)
        self.assertIn("3 chargées", sortie.getvalue())


class FichiersIllisibles(unittest.TestCase):
    def test_un_label_qui_n_est_pas_du_texte_est_refuse(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaisesRegex(cv.ErreurChargement, "label"):
            cv.lire_manifeste(dossier(Path(t), {**MANIFESTE, "label": 12}) / "manifeste.json")

    def test_des_mesures_absentes_ou_pas_en_utf8_sont_refusees(self):
        with tempfile.TemporaryDirectory() as t:
            manifeste = cv.lire_manifeste(dossier(Path(t)) / "manifeste.json")
            with self.assertRaisesRegex(cv.ErreurChargement, "illisible"):
                list(cv.lire_mesures(Path(t) / "absent.csv", manifeste, cv.Resultat("metr-la")))
            (Path(t) / "mesures.csv").write_bytes(b"\xff\xfe\x00")
            with self.assertRaisesRegex(cv.ErreurChargement, "UTF-8"):
                list(cv.lire_mesures(Path(t) / "mesures.csv", manifeste, cv.Resultat("metr-la")))


if __name__ == "__main__":
    unittest.main()
