"""Le port PySpark contre l'ETL de production : mêmes décisions, ligne à ligne, sur des cas limites et sur un jeu généré.

Demande Java et PySpark (l'image `novaria-bigdata`) ; sans eux, tout est ignoré. Lancement :
    python3 scripts/dev/dev.py bigdata-test
"""

import csv
import io
import tempfile
import unittest
import warnings
from datetime import UTC, date, datetime
from pathlib import Path

from tests import support

from bigdata import empreinte, generer, nettoyage_python
from transforms import paris_qualite as qualite

if support.PYSPARK:
    from bigdata import nettoyage_spark

MAINTENANT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
PAR_DEFAUT = {
    "iu_ac": "100", "libelle": "Rue_A", "t_1h": "2026-10-18T10:00:00+00:00", "q": "100.0", "k": "5.0", "etat_trafic": "Fluide",
    "iu_nd_amont": "1", "libelle_nd_amont": "a", "iu_nd_aval": "2", "libelle_nd_aval": "b", "etat_barre": "Ouvert",
    "date_debut": "1996-10-03", "date_fin": "2023-01-01", "geo_point_2d": "48.8, 2.3", "geo_shape": generer.FORME,
}
SESSION = None
DOSSIER = None


def setUpModule():
    global SESSION, DOSSIER
    warnings.simplefilter("ignore", ResourceWarning)  # les connexions de py4j se ferment à l'arrêt de la session
    if support.PYSPARK:
        DOSSIER = tempfile.TemporaryDirectory()
        SESSION = nettoyage_spark.ouvrir_session(2, "1g", str(Path(DOSSIER.name) / "tmp"))


def tearDownModule():
    if SESSION is not None:
        SESSION.stop()
        DOSSIER.cleanup()


def ecrire_csv(chemin: Path, lignes: list[dict]) -> Path:
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(generer.COLONNES)
    for ligne in lignes:
        ecrivain.writerow([ligne[c] for c in generer.COLONNES])
    chemin.write_bytes(b"\xef\xbb\xbf" + sortie.getvalue().encode("utf-8"))
    return chemin


def decision_python(lignes: list[dict]) -> list[tuple]:
    """Pour chaque ligne : ("rejet", règle) ou ("propre", colonnes propres), d'après l'ETL de production."""
    nettoyeur = qualite.Nettoyeur(MAINTENANT)
    decisions = []
    for rang, ligne in enumerate(lignes, start=1):
        resultat = nettoyeur.traiter(rang, ligne)
        if isinstance(resultat, qualite.Rejet):
            decisions.append(("rejet", resultat.regle))
        else:
            decisions.append(("propre", (
                resultat.road_segment_id, resultat.libelle, resultat.heure.strftime("%Y-%m-%dT%H:%M:%SZ"), resultat.vehicle_count,
                resultat.occupancy_pct, resultat.traffic_state, resultat.barrier_state, resultat.upstream_node_id,
                resultat.downstream_node_id, ",".join(resultat.flags),
            )))
    return decisions


def decision_spark(chemin: Path) -> list[tuple]:
    lignes = nettoyage_spark.classer(nettoyage_spark.lire(SESSION, str(chemin)), MAINTENANT).orderBy("source_line").collect()
    decisions = []
    for ligne in lignes:
        if ligne["statut"] == "rejet":
            decisions.append(("rejet", ligne["regle"]))
        else:
            decisions.append(("propre", (
                ligne["road_segment_id"], ligne["label"], ligne["hour_utc"], ligne["vehicle_count"], ligne["occupancy_pct"],
                ligne["traffic_state"], ligne["barrier_state"], ligne["upstream_node_id"], ligne["downstream_node_id"],
                ligne["quality_flags"],
            )))
    return decisions


def cas(numero: int, **champs) -> dict:
    return PAR_DEFAUT | {"iu_ac": str(1000 + numero)} | champs


# (nom, champs modifiés) : les bornes de chaque règle, de chaque côté.
CAS_LIMITES = [
    ("valide", {}),
    ("q vide", {"q": ""}), ("iu_ac vide", {"iu_ac": ""}), ("t_1h vide", {"t_1h": ""}), ("q en espaces", {"q": "   "}),
    ("q et k vides", {"q": "", "k": ""}),
    ("q = 0", {"q": "0", "k": "0"}), ("q = 15000", {"q": "15000"}), ("q = 15000.1", {"q": "15000.1"}), ("q = -0.1", {"q": "-0.1"}),
    ("k = 100", {"k": "100", "etat_trafic": "Bloqué"}), ("k = 100.1", {"k": "100.1", "etat_trafic": "Bloqué"}),
    ("q avec exposant", {"q": "1e2"}), ("q avec exposant majuscule", {"q": "1E2"}), ("q signé", {"q": "+5"}),
    ("q sans partie entière", {"q": ".5"}), ("q sans décimales", {"q": "5."}), ("q = nan", {"q": "nan"}), ("q = inf", {"q": "inf"}),
    ("q débordant", {"q": "1e999"}), ("k à virgule", {"k": "1,5"}), ("q entouré d'espaces", {"q": "  12.5  "}),
    ("iu_ac avec zéros", {"iu_ac": "0012"}), ("iu_ac de 10 chiffres", {"iu_ac": "1234567890"}), ("iu_ac de 9 chiffres", {"iu_ac": "123456789"}),
    ("iu_ac négatif", {"iu_ac": "-5"}), ("iu_ac alphanumérique", {"iu_ac": "12a"}),
    ("t_1h sans fuseau", {"t_1h": "2026-10-18T10:00:00"}), ("t_1h texte", {"t_1h": "hier"}),
    ("t_1h avec Z", {"t_1h": "2026-10-18T10:00:00Z"}), ("t_1h décalé +02:00", {"t_1h": "2026-10-18T12:00:00+02:00"}),
    ("t_1h décalé +05:30 heure pleine UTC", {"t_1h": "2026-10-18T10:30:00+05:30"}),
    ("t_1h décalé +05:30 heure non pleine UTC", {"t_1h": "2026-10-18T10:00:00+05:30"}),
    ("t_1h minute non nulle", {"t_1h": "2026-10-18T10:30:00+00:00"}), ("t_1h seconde non nulle", {"t_1h": "2026-10-18T10:00:01+00:00"}),
    ("t_1h le 30 février", {"t_1h": "2026-02-30T10:00:00+00:00"}), ("t_1h à 24 h", {"t_1h": "2026-10-18T24:00:00+00:00"}),
    ("t_1h au début du calendrier", {"t_1h": "2012-01-01T00:00:00+00:00"}),
    ("t_1h avant le calendrier", {"t_1h": "2011-12-31T23:00:00+00:00"}),
    ("t_1h à la fin du calendrier", {"t_1h": "2031-01-01T00:00:00+00:00"}),
    ("t_1h juste avant la fin du calendrier", {"t_1h": "2030-12-31T23:00:00+00:00"}),
    ("t_1h à l'horloge", {"t_1h": "2026-11-15T12:00:00+00:00"}), ("t_1h une heure après l'horloge", {"t_1h": "2026-11-15T13:00:00+00:00"}),
    ("t_1h futur lointain", {"t_1h": "2027-01-15T10:00:00+00:00"}),
    ("état en rang", {"etat_trafic": "1"}), ("état en rang avec zéro", {"etat_trafic": "01"}), ("état hors rang", {"etat_trafic": "5"}),
    ("état négatif", {"etat_trafic": "-1"}), ("état en minuscules", {"etat_trafic": "fluide"}), ("état inconnu du portail", {"etat_trafic": "Fluidissime"}),
    ("état vide", {"etat_trafic": ""}), ("barre en rang", {"etat_barre": "1"}), ("barre hors liste", {"etat_barre": "Ouvertement"}),
    ("barre vide", {"etat_barre": ""}),
    ("k = 15 et Fluide", {"k": "15.0", "etat_trafic": "Fluide"}), ("k = 15 et Pré-saturé", {"k": "15.0", "etat_trafic": "Pré-saturé"}),
    ("k = 15 et Saturé", {"k": "15.0", "etat_trafic": "Saturé"}),
    ("k = 30 et Pré-saturé", {"k": "30.0", "etat_trafic": "Pré-saturé"}), ("k = 30 et Saturé", {"k": "30.0", "etat_trafic": "Saturé"}),
    ("k = 50 et Saturé", {"k": "50.0", "etat_trafic": "Saturé"}), ("k = 50 et Bloqué", {"k": "50.0", "etat_trafic": "Bloqué"}),
    ("k = 50 et Fluide", {"k": "50.0", "etat_trafic": "Fluide"}),
    ("k = 14.999 et Pré-saturé", {"k": "14.999", "etat_trafic": "Pré-saturé"}), ("k = 29.99 et Pré-saturé", {"k": "29.99", "etat_trafic": "Pré-saturé"}),
    ("k = 0 et Fluide", {"k": "0", "etat_trafic": "Fluide"}),
    ("k vide et Inconnu", {"k": "", "etat_trafic": "Inconnu"}), ("k vide et état vide", {"k": "", "etat_trafic": ""}),
    ("k vide et Fluide", {"k": "", "etat_trafic": "Fluide"}), ("k vide et rang 0", {"k": "", "etat_trafic": "0"}),
    ("k = 10 et Inconnu", {"k": "10", "etat_trafic": "Inconnu"}), ("k = 10 et rang 0", {"k": "10", "etat_trafic": "0"}),
    ("k = 10 et état vide", {"k": "10", "etat_trafic": ""}),
    ("date_debut du 29 février bissextile", {"date_debut": "1996-02-29"}), ("date_debut du 29 février non bissextile", {"date_debut": "1997-02-29"}),
    ("date_debut sur deux chiffres", {"date_debut": "96-01-01"}), ("date_fin impossible", {"date_fin": "2023-13-01"}),
    ("date_debut vide", {"date_debut": ""}),
    ("libellé accentué", {"libelle": "Av_de_la_Républi"}), ("libellé entouré d'espaces", {"libelle": "  Rue_B  "}),
    ("nœuds entourés d'espaces", {"iu_nd_amont": " 7 ", "iu_nd_aval": " 8 "}),
]


@unittest.skipUnless(support.PYSPARK, "PySpark absent : lancer dans l'image novaria-bigdata")
class PariteSurLesCasLimites(unittest.TestCase):
    def test_chaque_cas_limite_recoit_la_meme_decision(self):
        lignes = [cas(numero, **champs) for numero, (_, champs) in enumerate(CAS_LIMITES, start=1)]
        chemin = ecrire_csv(Path(DOSSIER.name) / "limites.csv", lignes)
        python, spark = decision_python(lignes), decision_spark(chemin)
        self.assertEqual(len(python), len(spark))
        ecarts = [(CAS_LIMITES[i][0], python[i], spark[i]) for i in range(len(python)) if python[i] != spark[i]]
        self.assertEqual(ecarts, [], "décisions différentes entre l'ETL Python et PySpark")
        regles = {decision[1] for decision in python if decision[0] == "rejet"}
        self.assertEqual(regles, {"MISSING_REQUIRED", "TYPE_INVALID", "OUT_OF_RANGE", "NOT_ON_THE_HOUR", "FUTURE_TIMESTAMP", "STATE_MISMATCH"})
        self.assertGreater(sum(1 for d in python if d[0] == "propre"), 20, "le corpus compte aussi des lignes propres")

    def test_les_doublons_se_cherchent_par_fichier_et_ignorent_les_lignes_deja_refusees(self):
        cle = {"iu_ac": "77", "t_1h": "2026-10-18T10:00:00+00:00"}
        lignes = [
            PAR_DEFAUT | cle,  # 1 : propre, première occurrence
            PAR_DEFAUT | cle | {"q": "250.0"},  # 2 : doublon
            PAR_DEFAUT | cle | {"t_1h": "2026-10-18T10:00:00Z"},  # 3 : le même instant écrit autrement : doublon
            PAR_DEFAUT | {"iu_ac": "78", "q": "n/a"},  # 4 : refusée (type)
            PAR_DEFAUT | {"iu_ac": "78"},  # 5 : même clé que la 4, mais la 4 est refusée : celle-ci est la première
            PAR_DEFAUT | {"iu_ac": "0078"},  # 6 : « 0078 » et « 78 » sont le même capteur : doublon de la 5
            PAR_DEFAUT | {"iu_ac": "79", "t_1h": "2026-10-18T11:00:00+00:00"},  # 7 : autre heure : propre
        ]
        chemin = ecrire_csv(Path(DOSSIER.name) / "doublons.csv", lignes)
        python, spark = decision_python(lignes), decision_spark(chemin)
        self.assertEqual(python, spark)
        self.assertEqual([d[0:2] if d[0] == "rejet" else d[0] for d in python],
                         ["propre", ("rejet", "DUPLICATE_KEY"), ("rejet", "DUPLICATE_KEY"), ("rejet", "TYPE_INVALID"), "propre",
                          ("rejet", "DUPLICATE_KEY"), "propre"])

    def test_les_numeros_de_ligne_repartent_de_un_dans_chaque_fichier(self):
        premier = ecrire_csv(Path(DOSSIER.name) / "un.csv", [cas(i) for i in range(1, 6)])
        second = ecrire_csv(Path(DOSSIER.name) / "deux.csv", [cas(i) for i in range(1, 4)])
        classe = nettoyage_spark.classer(nettoyage_spark.lire(SESSION, [str(premier), str(second)]), MAINTENANT).collect()
        par_fichier = {}
        for ligne in classe:
            par_fichier.setdefault(ligne["fichier"], []).append(ligne["source_line"])
        self.assertEqual({nom: sorted(lignes) for nom, lignes in par_fichier.items()}, {"un.csv": [1, 2, 3, 4, 5], "deux.csv": [1, 2, 3]})

    def test_chaque_fichier_est_lu_en_une_partition(self):
        fichiers = [ecrire_csv(Path(DOSSIER.name) / f"p{i}.csv", [cas(i)]) for i in range(1, 5)]
        self.assertEqual(nettoyage_spark.lire(SESSION, [str(f) for f in fichiers]).rdd.getNumPartitions(), 4)


@unittest.skipUnless(support.PYSPARK, "PySpark absent : lancer dans l'image novaria-bigdata")
class DivergencesConnues(unittest.TestCase):
    """Ce que le port ne reproduit pas, écrit pour que le rapport ne puisse pas le taire : ces écarts sont voulus et dits."""

    def decisions(self, **champs):
        lignes = [cas(1, **champs)]
        chemin = ecrire_csv(Path(DOSSIER.name) / "divergence.csv", lignes)
        return decision_python(lignes)[0], decision_spark(chemin)[0]

    def test_horodatage_avec_espace_au_lieu_de_T(self):
        python, spark = self.decisions(t_1h="2026-10-18 10:00:00+00:00")
        self.assertEqual(python[0], "propre")
        self.assertEqual(spark, ("rejet", "TYPE_INVALID"))

    def test_horodatage_avec_fraction_de_seconde(self):
        python, spark = self.decisions(t_1h="2026-10-18T10:00:00.5+00:00")
        self.assertEqual(python, ("rejet", "NOT_ON_THE_HOUR"))
        self.assertEqual(spark, ("rejet", "TYPE_INVALID"))

    def test_espace_insecable_autour_d_un_nombre(self):
        python, spark = self.decisions(q=" 12.5 ")
        self.assertEqual(python[0], "propre")
        self.assertEqual(spark, ("rejet", "TYPE_INVALID"))

    def test_libelle_non_normalise(self):
        python, spark = self.decisions(libelle="République")  # « e » suivi de l'accent combinant (NFD)
        self.assertEqual(python[1][1], "République")  # Python normalise en NFC
        self.assertEqual(spark[1][1], "République")  # PySpark garde le texte tel qu'il est


@unittest.skipUnless(support.PYSPARK, "PySpark absent : lancer dans l'image novaria-bigdata")
class DeBoutEnBout(unittest.TestCase):
    def test_pyspark_rend_le_bilan_et_les_empreintes_de_l_etl_python_et_la_verite_terrain(self):
        dossier = Path(DOSSIER.name) / "jeu"
        fichiers = [generer.ecrire_le_jour(dossier, date(2026, 10, jour), capteurs=80) for jour in (1, 2, 3)]
        chemins = [f.chemin for f in fichiers]
        noms = [c.name for c in chemins]
        attendu = {"rows_read": 0, "rows_clean": 0, "rows_rejected": 0}
        for fichier in fichiers:
            for cle in attendu:
                attendu[cle] += fichier.attendu.en_dict()[cle]

        python = nettoyage_python.sequentiel(chemins, generer.MAINTENANT)
        sortie = Path(DOSSIER.name) / "sortie"
        spark = nettoyage_spark.nettoyer(SESSION, [str(c) for c in chemins], sortie, generer.MAINTENANT)

        for cle in ("rows_read", "rows_clean", "rows_rejected", "by_rule", "flags"):
            self.assertEqual(spark[cle], python[cle], cle)
        for cle, valeur in attendu.items():
            self.assertEqual(spark[cle], valeur, cle)
        self.assertEqual(spark["rows_read"], spark["rows_clean"] + spark["rows_rejected"])
        self.assertEqual(sum(spark["by_rule"].values()), spark["rows_rejected"])
        self.assertEqual(
            empreinte.depuis_la_sortie_spark(SESSION, sortie, noms),
            empreinte.depuis_les_sorties_python(dossier, noms),
        )
        self.assertGreater(spark["seconds_job"], 0)

    def test_la_sortie_est_partitionnee_par_statut(self):
        dossier = Path(DOSSIER.name) / "jeu2"
        chemin = generer.ecrire_le_jour(dossier, date(2026, 10, 5), capteurs=30).chemin
        sortie = Path(DOSSIER.name) / "sortie2"
        nettoyage_spark.nettoyer(SESSION, [str(chemin)], sortie, generer.MAINTENANT)
        self.assertEqual({p.name for p in sortie.iterdir() if p.is_dir()}, {"statut=propre", "statut=rejet"})

    def test_la_bom_n_est_pas_dans_le_nom_de_la_premiere_colonne(self):
        chemin = ecrire_csv(Path(DOSSIER.name) / "bom.csv", [cas(1)])
        self.assertEqual(nettoyage_spark.lire(SESSION, str(chemin)).columns[0], "iu_ac")


if __name__ == "__main__":
    unittest.main()
