"""Mesure du délai d'apparition d'une alerte chez le citoyen (CIT-05) : le verdict, la lecture de la base, le câblage de la commande.

La mesure elle-même demande la pile locale et un navigateur (`dev.py citoyen delai`) : elle n'est pas rejouée ici.
Ces tests vérifient que le **verdict** ne peut pas réussir par défaut (alerte jamais vue, trop lente, horloges incohérentes).

Lancement : python3 -m unittest discover -s scripts/dev -p "test_citoyen_delai.py"  (Windows : py -3 ...).
"""

import unittest
from pathlib import Path

import citoyen_delai as delai
import dev

RACINE = Path(__file__).resolve().parents[2]


def resultat(troncon: str, secondes: float | None) -> dict:
    return {"alert_id": f"id-{troncon}", "troncon": troncon, "creee_ms": 1000.0, "vue_ms": None if secondes is None else 1000.0 + secondes * 1000,
            "delai_s": secondes}


def quatre(*secondes: float | None) -> list[dict]:
    return [resultat(f"ROAD_0{i}", s) for i, s in enumerate(secondes, start=17)]


class Verdict(unittest.TestCase):
    def test_reussit_quand_les_quatre_alertes_sont_vues_sous_le_seuil(self):
        reussi, texte = delai.verdict(quatre(4.0, 4.0, 3.9, 4.1))
        self.assertTrue(reussi)
        self.assertIn("4.1 s", texte)

    def test_le_plus_lent_decide(self):
        self.assertFalse(delai.verdict(quatre(2.0, 2.0, 2.0, 10.0))[0], "10,0 s n'est pas « moins de 10 secondes »")
        self.assertTrue(delai.verdict(quatre(2.0, 2.0, 2.0, 9.9))[0])

    def test_une_alerte_jamais_vue_est_un_echec(self):
        reussi, texte = delai.verdict(quatre(3.0, None, 3.0, 3.0))
        self.assertFalse(reussi)
        self.assertIn("ROAD_018", texte)

    def test_moins_de_quatre_alertes_creees_est_un_echec(self):
        self.assertFalse(delai.verdict(quatre(1.0, 1.0, 1.0))[0])
        self.assertFalse(delai.verdict([])[0])

    def test_un_delai_negatif_rend_la_mesure_inutilisable(self):
        reussi, texte = delai.verdict(quatre(-1.0, 2.0, 2.0, 2.0))
        self.assertFalse(reussi)
        self.assertIn("horloges", texte)

    def test_le_seuil_est_celui_du_critere(self):
        self.assertEqual(delai.SEUIL_S, 10.0)


class LectureDeLaBase(unittest.TestCase):
    class PileFausse:
        def __init__(self, lignes):
            self.lignes, self.requetes = lignes, []

        def psql(self, requete):
            self.requetes.append(requete)
            return self.lignes

    def test_lit_l_instant_de_creation_dans_l_evenement_created_de_l_outbox_pas_dans_les_dates_des_mesures(self):
        pile = self.PileFausse([["id-1", "ROAD_017", "1763646635800"]])
        self.assertEqual(delai.creations(pile, "cit05-abc"), {"id-1": ("ROAD_017", 1763646635800.0)})
        requete = pile.requetes[0]
        self.assertIn("alertes.outbox_event", requete)
        self.assertIn("-created", requete)
        self.assertIn("o.created_at", requete)
        self.assertNotIn("opened_at", requete, "opened_at est la date de la mesure, souvent dans le passé")
        self.assertIn("cit05-abc", requete)

    def test_aucune_alerte_donne_un_dictionnaire_vide(self):
        self.assertEqual(delai.creations(self.PileFausse([]), "x"), {})


class Cablage(unittest.TestCase):
    def test_l_action_est_declaree_dans_dev_py(self):
        self.assertIn("delai", dev.CITIZEN_ACTIONS)

    def test_le_scenario_envoie_d_abord_des_minutes_congestionnees_puis_des_fluides(self):
        self.assertTrue(all(delai.CONGESTIONNEES) and len(delai.CONGESTIONNEES) >= 3)
        self.assertFalse(any(delai.FLUIDES), "les minutes fluides referment les alertes d'essai")

    def test_l_observateur_note_les_alertes_nouvelles_dans_la_page(self):
        script = (RACINE / "citizen" / "scripts" / "delai-alerte.mjs").read_text(encoding="utf-8")
        for attendu in ("data-alerte", "MutationObserver", "Date.now()", '"vue"', "isMobile: true"):
            self.assertIn(attendu, script)

    def test_aucun_carrefour_du_parcours_nominal(self):
        self.assertNotIn(1, delai.CARREFOURS, "INT_01 est réservé au parcours nominal (dev.py flux-complet)")


if __name__ == "__main__":
    unittest.main()
