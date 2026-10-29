"""Tests des règles de qualité du comptage routier de Paris (DAT-04). Fonctions pures : aucun accès au réseau ni à une base.

    python -m unittest discover -s data/etl/tests

Chaque règle de `REGLES` a son tableau de cas dans `CAS` : des lignes qu'elle doit refuser (avec un extrait du motif) et
des lignes qu'elle doit laisser passer, bornes comprises. Un test échoue si une règle est ajoutée sans cas.
"""

import sys
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "data" / "etl"))

from echantillon import LIGNES  # noqa: E402
from pipelines import paris_comptages as paris  # noqa: E402
from transforms import paris_qualite as q  # noqa: E402

MAINTENANT = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
BASE = dict(zip(paris.COLONNES, LIGNES[0], strict=True))  # une ligne valide : 199 véhicules, k = 2,03556, Fluide


def avec(**champs):
    return {**BASE, **champs}


def rejet(*lignes, motif, maintenant=MAINTENANT):
    """Cas refusé : la dernière ligne de la séquence est rejetée par la règle testée, les précédentes sont retenues."""
    return lignes, motif, maintenant


def accepte(*lignes, maintenant=MAINTENANT):
    return lignes, None, maintenant


CAS = {
    q.MISSING_REQUIRED: [
        rejet(avec(iu_ac=""), motif="iu_ac"),
        rejet(avec(t_1h=""), motif="t_1h"),
        rejet(avec(q=""), motif="q"),
        rejet(avec(q="   "), motif="q"),
        rejet(avec(iu_ac="", q=""), motif="iu_ac, q"),
        rejet(avec(q="", k="12.5", etat_trafic="Fluide"), motif="station de taux d'occupation seul"),
        accepte(avec()),
        accepte(avec(q="0")),
        accepte(avec(k="", etat_trafic="Inconnu")),
        accepte(avec(date_debut="", date_fin="")),
        accepte(avec(etat_trafic="", etat_barre="")),
    ],
    q.TYPE_INVALID: [
        rejet(avec(iu_ac="12a"), motif="iu_ac n'est pas un entier"),
        rejet(avec(iu_ac="-5"), motif="iu_ac"),
        rejet(avec(iu_ac="1.5"), motif="iu_ac"),
        rejet(avec(iu_ac="１２"), motif="iu_ac"),  # chiffres pleine chasse : ni ASCII ni accepté
        rejet(avec(iu_ac="1234567890"), motif="iu_ac"),
        rejet(avec(t_1h="2026-10-18"), motif="t_1h"),
        rejet(avec(t_1h="2026-10-18T10:00:00"), motif="avec fuseau"),
        rejet(avec(t_1h="hier"), motif="t_1h"),
        rejet(avec(q="abc"), motif="q n'est pas un nombre fini"),
        rejet(avec(q="1,5"), motif="q"),
        rejet(avec(q="nan"), motif="q"),
        rejet(avec(q="inf"), motif="q"),
        rejet(avec(q="1e999"), motif="q"),
        rejet(avec(q="١٢"), motif="q"),  # chiffres arabo-indiens : float() les accepterait, pas la règle
        rejet(avec(k="x"), motif="k n'est pas un nombre fini"),
        rejet(avec(date_debut="03/10/1996"), motif="date_debut"),
        rejet(avec(date_fin="2023-13-01"), motif="date_fin"),
        rejet(avec(etat_trafic="Libre"), motif="etat_trafic hors de la liste"),
        rejet(avec(etat_trafic="7"), motif="etat_trafic"),
        rejet(avec(etat_barre="Fermé"), motif="etat_barre hors de la liste"),
        rejet(avec(iu_ac="x", q="y"), motif="iu_ac n'est pas un entier; q n'est pas un nombre fini"),  # tous les défauts
        accepte(avec(iu_ac="0012")),
        accepte(avec(q="199"), avec(iu_ac="2", q="199.5")),
        accepte(avec(q="1e2")),
        accepte(avec(t_1h="2026-10-18T10:00:00Z")),
        accepte(avec(t_1h="2026-10-18T12:00:00+02:00")),
        accepte(avec(etat_trafic="1", etat_barre="1")),  # fichiers historiques : états en entiers
        accepte(avec(etat_trafic="Pré-saturé", k="20")),
    ],
    q.OUT_OF_RANGE: [
        rejet(avec(q="-1"), motif="q = -1 hors de 0 à 15000"),
        rejet(avec(q="15000.01"), motif="q = 15000.01"),
        rejet(avec(k="-0.1"), motif="k = -0.1 hors de 0 à 100"),
        rejet(avec(k="100.01"), motif="k = 100.01"),
        rejet(avec(t_1h="2011-12-31T23:00:00+00:00"), motif="hors du calendrier de l'entrepôt"),
        rejet(avec(t_1h="2031-01-01T00:00:00+00:00"), motif="hors du calendrier", maintenant=datetime(2032, 1, 1, tzinfo=UTC)),
        rejet(avec(q="-1", k="101"), motif="q = -1 hors de 0 à 15000 véhicules par heure; k = 101"),
        accepte(avec(q="0")),
        accepte(avec(q="15000")),
        accepte(avec(k="0", etat_trafic="Fluide")),
        accepte(avec(k="100", etat_trafic="Bloqué")),
        accepte(avec(t_1h="2012-01-01T00:00:00+00:00")),
        accepte(avec(t_1h="2030-12-31T23:00:00+00:00"), maintenant=datetime(2031, 1, 1, tzinfo=UTC)),
    ],
    q.NOT_ON_THE_HOUR: [
        rejet(avec(t_1h="2026-10-18T10:30:00+00:00"), motif="n'est pas une heure pleine"),
        rejet(avec(t_1h="2026-10-18T10:00:01+00:00"), motif="10:00:01Z"),
        rejet(avec(t_1h="2026-10-18T10:00:00.5+00:00"), motif="heure pleine"),
        accepte(avec(t_1h="2026-10-18T10:00:00+00:00")),
        accepte(avec(t_1h="2026-10-18T12:00:00+02:00")),
        accepte(avec(t_1h="2026-10-18T15:30:00+05:30")),  # 10:00 UTC : l'heure pleine se juge en UTC
    ],
    q.FUTURE_TIMESTAMP: [
        rejet(avec(t_1h="2026-10-29T13:00:00+00:00"), motif="après l'horloge"),
        rejet(avec(t_1h="2026-10-29T12:00:00+00:00"), motif="2026-10-29T12:00:00Z", maintenant=datetime(2026, 10, 29, 11, 59, 54, tzinfo=UTC)),
        accepte(avec(t_1h="2026-10-29T12:00:00+00:00")),
        accepte(avec(t_1h="2026-10-29T12:00:00+00:00"), maintenant=datetime(2026, 10, 29, 11, 59, 55, tzinfo=UTC)),  # 5 s d'avance : toléré
        accepte(avec(t_1h="2026-10-18T10:00:00+00:00")),
    ],
    q.STATE_MISMATCH: [
        rejet(avec(k="2.0", etat_trafic="Bloqué"), motif="etat_trafic = Bloqué alors que k = 2.0 donne Fluide"),
        rejet(avec(k="60", etat_trafic="Fluide"), motif="k = 60 donne Bloqué"),
        rejet(avec(k="20", etat_trafic="Saturé"), motif="Pré-saturé"),
        rejet(avec(k="2.0", etat_trafic="Inconnu"), motif="Inconnu alors que k = 2.0"),
        rejet(avec(k="", etat_trafic="Fluide"), motif="alors que k est vide"),
        rejet(avec(k="14.99", etat_trafic="Pré-saturé"), motif="k = 14.99 donne Fluide"),
        rejet(avec(k="50.01", etat_trafic="Saturé"), motif="k = 50.01 donne Bloqué"),
        accepte(avec(k="", etat_trafic="Inconnu")),
        accepte(avec(k="", etat_trafic="")),
        accepte(avec(k="2.0", etat_trafic="")),  # état vide : rien à comparer
        accepte(avec(k="14.99", etat_trafic="Fluide"), avec(iu_ac="2", k="15.01", etat_trafic="Pré-saturé")),
        accepte(avec(k="15", etat_trafic="Fluide"), avec(iu_ac="2", k="15", etat_trafic="Pré-saturé")),  # seuil exact : les deux passent
        accepte(avec(k="30", etat_trafic="Pré-saturé"), avec(iu_ac="2", k="30", etat_trafic="Saturé")),
        accepte(avec(k="50", etat_trafic="Saturé"), avec(iu_ac="2", k="50", etat_trafic="Bloqué")),
        accepte(avec(k="2.0", etat_trafic="1")),  # état en entier
    ],
    q.DUPLICATE_KEY: [
        rejet(avec(), avec(), motif="même (iu_ac, t_1h) que la ligne 1, valeurs identiques"),
        rejet(avec(), avec(q="200"), motif="valeurs différentes (vehicle_count 199.0 ≠ 200.0)"),
        rejet(avec(), avec(iu_ac="04392"), motif="ligne 1"),  # zéros de tête : même tronçon
        rejet(avec(), avec(t_1h="2026-10-18T12:00:00+02:00"), motif="ligne 1"),  # même instant, autre écriture
        rejet(avec(), avec(iu_ac="2"), avec(), motif="ligne 1"),
        accepte(avec(), avec(iu_ac="2")),
        accepte(avec(), avec(t_1h="2026-10-18T11:00:00+00:00")),
    ],
}


def traiter(lignes, maintenant=MAINTENANT):
    nettoyeur = q.Nettoyeur(maintenant)
    return [nettoyeur.traiter(rang, ligne) for rang, ligne in enumerate(lignes, start=1)], nettoyeur


class ChaqueRegleATonTest(unittest.TestCase):
    def test_toutes_les_regles_ont_un_tableau_de_cas(self):
        self.assertEqual(sorted(CAS), sorted(regle.code for regle in q.REGLES), "règle sans cas de test, ou cas sans règle")

    def test_chaque_regle_a_un_cas_refuse_et_un_cas_accepte(self):
        for code, cas in CAS.items():
            with self.subTest(regle=code):
                self.assertGreaterEqual(sum(motif is not None for _, motif, _ in cas), 2, "au moins deux cas refusés")
                self.assertGreaterEqual(sum(motif is None for _, motif, _ in cas), 2, "au moins deux cas acceptés")

    def test_les_codes_sont_uniques_et_les_familles_connues(self):
        codes = [regle.code for regle in q.REGLES]
        self.assertEqual(len(codes), len(set(codes)))
        familles = {"valeur manquante", "type", "borne", "cohérence", "doublon"}
        self.assertEqual({regle.famille for regle in q.REGLES}, familles, "les cinq familles de l'ADR-013 (section 4.3) sont couvertes")

    def test_seule_la_regle_de_doublon_se_juge_sur_le_lot(self):
        self.assertEqual([r.code for r in q.REGLES if r.verifier is None], [q.DUPLICATE_KEY])
        self.assertEqual(len(q.REGLES_DE_LIGNE), len(q.REGLES) - 1)

    def test_le_motif_d_un_etat_inconnu_avec_une_occupation_est_explicite(self):
        (resultat,), _ = traiter([avec(k="2.0", etat_trafic="Inconnu")])
        self.assertEqual(resultat.motif, "etat_trafic = Inconnu alors que k = 2.0")

    def test_les_cas_refuses(self):
        for code, cas in CAS.items():
            for lignes, motif, maintenant in (c for c in cas if c[1] is not None):
                with self.subTest(regle=code, derniere=dict(list(lignes[-1].items())[:5]), motif=motif):
                    resultats, _ = traiter(lignes, maintenant)
                    *avant, dernier = resultats
                    self.assertTrue(all(isinstance(r, q.LignePropre) for r in avant), "les lignes précédentes devaient être retenues")
                    self.assertIsInstance(dernier, q.Rejet)
                    self.assertEqual(dernier.regle, code)
                    self.assertIn(motif, dernier.motif)
                    self.assertEqual(dernier.ligne, len(lignes))
                    self.assertEqual(dernier.brut, lignes[-1], "la ligne d'origine est gardée telle quelle")

    def test_les_cas_acceptes(self):
        for code, cas in CAS.items():
            for lignes, _motif, maintenant in (c for c in cas if c[1] is None):
                with self.subTest(regle=code, lignes=[dict(list(ligne.items())[:5]) for ligne in lignes]):
                    resultats, _ = traiter(lignes, maintenant)
                    self.assertTrue(all(isinstance(r, q.LignePropre) for r in resultats), [getattr(r, "motif", None) for r in resultats])

    def test_chaque_regle_de_ligne_se_declenche_seule_sur_ses_cas_refuses(self):
        # La règle refuse bien par elle-même (pas seulement parce qu'une autre est passée avant elle).
        for regle in q.REGLES_DE_LIGNE:
            for lignes, motif, maintenant in (c for c in CAS[regle.code] if c[1] is not None):
                with self.subTest(regle=regle.code, motif=motif):
                    violation = regle.verifier(lignes[-1], maintenant)
                    self.assertIsNotNone(violation)
                    self.assertEqual(violation.regle, regle.code)
                    self.assertIn(motif, violation.motif)


class DoublonEtLignesRefusees(unittest.TestCase):
    def test_une_ligne_refusee_ne_masque_pas_la_suivante_de_meme_cle(self):
        for premiere in (avec(q=""), avec(q="x"), avec(q="-1")):
            with self.subTest(premiere=premiere["q"]):
                (rejetee, retenue), _ = traiter([premiere, avec()])
                self.assertIsInstance(rejetee, q.Rejet)
                self.assertNotEqual(rejetee.regle, q.DUPLICATE_KEY)
                self.assertIsInstance(retenue, q.LignePropre)

    def test_le_premier_exemplaire_est_celui_qui_est_garde(self):
        (premier, second), _ = traiter([avec(q="100"), avec(q="900")])
        self.assertEqual(premier.vehicle_count, 100.0)
        self.assertEqual(second.regle, q.DUPLICATE_KEY)


class LigneRetenue(unittest.TestCase):
    def test_une_ligne_valide_est_typee(self):
        (ligne,), _ = traiter([BASE])
        self.assertEqual(ligne, q.LignePropre(
            ligne=1, road_segment_id="4392", libelle="Quai_d'Orsay", heure=datetime(2026, 10, 18, 10, tzinfo=UTC), vehicle_count=199.0,
            occupancy_pct=2.03556, traffic_state="Fluide", barrier_state="Ouvert", upstream_node_id="2349", downstream_node_id="189", flags=()))

    def test_les_valeurs_sont_normalisees_sans_rien_inventer(self):
        (ligne,), _ = traiter([avec(iu_ac="0012", t_1h="2026-10-18T12:00:00+02:00", etat_trafic="1", etat_barre="3", libelle=" Rue ")])
        self.assertEqual((ligne.road_segment_id, ligne.heure, ligne.traffic_state, ligne.barrier_state, ligne.libelle),
                         ("12", datetime(2026, 10, 18, 10, tzinfo=UTC), "Fluide", "Invalide", "Rue"))

    def test_un_etat_ecrit_avec_des_accents_decomposes_est_reconnu(self):
        (ligne,), _ = traiter([avec(k="20", etat_trafic="Pré-saturé")])
        self.assertEqual(ligne.traffic_state, "Pré-saturé")

    def test_une_occupation_absente_n_est_pas_un_rejet_elle_porte_un_drapeau(self):
        (ligne,), nettoyeur = traiter([avec(k="", etat_trafic="Inconnu")])
        self.assertIsNone(ligne.occupancy_pct)
        self.assertEqual(ligne.flags, (q.MISSING_OCCUPANCY,))
        self.assertEqual(nettoyeur.bilan.drapeaux, {q.MISSING_OCCUPANCY: 1})

    def test_les_dates_de_validite_et_l_etat_vides_ne_font_pas_rejeter_la_ligne(self):
        (ligne,), _ = traiter([avec(date_debut="", date_fin="", etat_trafic="", etat_barre="")])
        self.assertEqual((ligne.traffic_state, ligne.barrier_state), (None, None))

    def test_la_ligne_brute_n_est_jamais_modifiee(self):
        brut = avec(iu_ac=" 0012 ", q="x")
        copie = dict(brut)
        traiter([brut])
        self.assertEqual(brut, copie)


class OrdreDesRegles(unittest.TestCase):
    def test_une_ligne_est_refusee_pour_la_premiere_regle_violee(self):
        ligne = avec(iu_ac="", q="-1", t_1h="2011-01-01T00:30:00+00:00", k="100", etat_trafic="Fluide")
        (resultat,), nettoyeur = traiter([ligne])
        self.assertEqual(resultat.regle, q.MISSING_REQUIRED)
        self.assertEqual(dict(nettoyeur.bilan.par_regle), {q.MISSING_REQUIRED: 1}, "un seul rejet par ligne")

    def test_l_ordre_suit_la_table_des_regles(self):
        self.assertEqual([r.code for r in q.REGLES], [q.MISSING_REQUIRED, q.TYPE_INVALID, q.OUT_OF_RANGE, q.NOT_ON_THE_HOUR,
                                                     q.FUTURE_TIMESTAMP, q.STATE_MISMATCH, q.DUPLICATE_KEY])

    def test_hors_borne_passe_avant_heure_pleine_et_futur(self):
        (resultat,), _ = traiter([avec(t_1h="2031-06-01T10:30:00+00:00")], maintenant=datetime(2020, 1, 1, tzinfo=UTC))
        self.assertEqual(resultat.regle, q.OUT_OF_RANGE)


class BilanDuLot(unittest.TestCase):
    def test_le_bilan_reconcilie_lues_propres_et_rejetees(self):
        lignes = [avec(), avec(iu_ac="2"), avec(iu_ac="3", q=""), avec(), avec(iu_ac="4", q="x"), avec(iu_ac="5", k="", etat_trafic="Inconnu")]
        _, nettoyeur = traiter(lignes)
        bilan = nettoyeur.bilan
        bilan.verifier()
        self.assertEqual((bilan.lues, bilan.propres, bilan.rejetees), (6, 3, 3))
        self.assertEqual(dict(bilan.par_regle), {q.MISSING_REQUIRED: 1, q.TYPE_INVALID: 1, q.DUPLICATE_KEY: 1})
        self.assertAlmostEqual(bilan.taux_rejet, 0.5)
        self.assertEqual(bilan.en_dict(), {
            "rows_read": 6, "rows_clean": 3, "rows_rejected": 3, "reject_rate": 0.5,
            "by_rule": {"DUPLICATE_KEY": 1, "MISSING_REQUIRED": 1, "TYPE_INVALID": 1}, "flags": {"MISSING_OCCUPANCY": 1}})

    def test_un_lot_vide_a_un_taux_nul(self):
        bilan = q.Bilan()
        bilan.verifier()
        self.assertEqual(bilan.taux_rejet, 0.0)

    def test_un_bilan_qui_ne_tombe_pas_juste_est_refuse(self):
        regles = Counter({q.TYPE_INVALID: 1})  # les décomptes par règle sont justes : seul le total des lignes cloche
        for bilan in (q.Bilan(lues=3, propres=1, rejetees=1, par_regle=regles), q.Bilan(lues=1, propres=1, rejetees=1, par_regle=regles)):
            with self.subTest(bilan=bilan), self.assertRaisesRegex(q.ErreurBilan, "lues"):
                bilan.verifier()
        q.Bilan(lues=2, propres=1, rejetees=1, par_regle=regles).verifier()

    def test_les_decomptes_par_regle_doivent_egaler_les_rejets(self):
        bilan = q.Bilan(lues=2, propres=1, rejetees=1)  # un rejet sans règle
        with self.assertRaises(q.ErreurBilan):
            bilan.verifier()

    def test_taux_de_rejet_d_un_fichier_entierement_refuse(self):
        _, nettoyeur = traiter([avec(q=""), avec(iu_ac="2", q="")])
        self.assertEqual(nettoyeur.bilan.taux_rejet, 1.0)


class Utilitaires(unittest.TestCase):
    def test_etats_attendus_aux_seuils(self):
        self.assertEqual(q.etats_attendus(0), {"Fluide"})
        self.assertEqual(q.etats_attendus(14.999), {"Fluide"})
        self.assertEqual(q.etats_attendus(15), {"Fluide", "Pré-saturé"})
        self.assertEqual(q.etats_attendus(29.9), {"Pré-saturé"})
        self.assertEqual(q.etats_attendus(30), {"Pré-saturé", "Saturé"})
        self.assertEqual(q.etats_attendus(50), {"Saturé", "Bloqué"})
        self.assertEqual(q.etats_attendus(100), {"Bloqué"})

    def test_la_tolerance_du_futur_vaut_cinq_secondes(self):
        self.assertEqual(q.TOLERANCE_FUTUR, timedelta(seconds=5))


if __name__ == "__main__":
    unittest.main()
