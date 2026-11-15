"""Historique simulé du comptage routier de Paris, au format brut du portail, avec des défauts injectés en proportions connues.

Un fichier par jour (comme l'ingestion DAT-03) : en-tête et ordre des colonnes du portail, BOM, fins de ligne CRLF,
séparateur « ; », forme géographique entre guillemets doublés, nom `<début>_<fin>_<12 caractères du SHA-256>.csv`.
Chaque fichier est **déterministe** : mêmes graine, jour et capteurs, mêmes octets.

Chaque ligne porte au plus **un** défaut, d'un type connu : le générateur sait donc, sans rien nettoyer, combien de
lignes chaque règle de `transforms.paris_qualite` doit refuser (`Attendu`). Cette vérité terrain est indépendante des
deux moteurs : un moteur qui s'en écarte se trompe, même si l'autre se trompe pareil.

Bibliothèque standard seulement.
"""

import csv
import hashlib
import io
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

COLONNES = (
    "iu_ac", "libelle", "t_1h", "q", "k", "etat_trafic", "iu_nd_amont", "libelle_nd_amont", "iu_nd_aval",
    "libelle_nd_aval", "etat_barre", "date_debut", "date_fin", "geo_point_2d", "geo_shape",
)  # en-tête du portail (data/etl/pipelines/paris_comptages.py)
ETATS = ("Inconnu", "Fluide", "Pré-saturé", "Saturé", "Bloqué")
BARRES = ("Inconnu", "Ouvert", "Barré", "Invalide")
SEUILS = (15.0, 30.0, 50.0)
FORME = '{"coordinates": [[2.3103, 48.8625], [2.3111, 48.8627]], "type": "LineString"}'
LIBELLES = ("Quai_d'Orsay", "Pt_Alexandre_III", "Bd_St_Germain", "Sts_Peres", "Av_de_la_Républi", "Bd_Peripherique", "Rue_de_Rivoli")
CAPTEURS_PAR_DEFAUT = 2960  # 71 040 lignes par jour : un jour du portail compte environ 71 000 lignes
DEBUT_PAR_DEFAUT = date(2026, 9, 1)
GRAINE_PAR_DEFAUT = 20261115
MAINTENANT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)  # l'horloge des deux moteurs : la règle FUTURE_TIMESTAMP en dépend

# Part des lignes (par ligne, tirage unique) : de quoi chaque règle voit passer quelques centaines de lignes par jour.
PROPORTIONS = (
    ("DEBIT_ABSENT", 0.18),  # MISSING_REQUIRED : le cas de loin le plus fréquent dans le vrai fichier
    ("CHAMP_OBLIGATOIRE_VIDE", 0.004),  # MISSING_REQUIRED : iu_ac ou t_1h vide
    ("TYPE", 0.004),  # TYPE_INVALID
    ("BORNE", 0.004),  # OUT_OF_RANGE
    ("HEURE_NON_PLEINE", 0.003),  # NOT_ON_THE_HOUR
    ("FUTUR", 0.002),  # FUTURE_TIMESTAMP
    ("ETAT", 0.006),  # STATE_MISMATCH
)
REGLE_DE = {
    "DEBIT_ABSENT": "MISSING_REQUIRED", "CHAMP_OBLIGATOIRE_VIDE": "MISSING_REQUIRED", "TYPE": "TYPE_INVALID",
    "BORNE": "OUT_OF_RANGE", "HEURE_NON_PLEINE": "NOT_ON_THE_HOUR", "FUTUR": "FUTURE_TIMESTAMP", "ETAT": "STATE_MISMATCH",
}
PART_DOUBLONS = 0.01  # lignes valides recopiées en fin de fichier : DUPLICATE_KEY
PART_OCCUPATION_ABSENTE = 0.05  # lignes valides sans k (état « Inconnu ») : retenues avec le drapeau MISSING_OCCUPANCY
PART_SEUIL_EXACT = 0.002  # lignes valides dont k tombe pile sur un seuil (15, 30, 50) : les deux états voisins passent


@dataclass
class Attendu:
    """Ce que le nettoyage doit rendre pour un fichier, d'après les défauts injectés."""

    lues: int = 0
    propres: int = 0
    rejetees: int = 0
    par_regle: Counter = field(default_factory=Counter)
    drapeaux: Counter = field(default_factory=Counter)

    def ajouter(self, autre: "Attendu") -> None:
        self.lues += autre.lues
        self.propres += autre.propres
        self.rejetees += autre.rejetees
        self.par_regle.update(autre.par_regle)
        self.drapeaux.update(autre.drapeaux)

    def en_dict(self) -> dict:
        return {
            "rows_read": self.lues, "rows_clean": self.propres, "rows_rejected": self.rejetees,
            "by_rule": dict(sorted(self.par_regle.items())), "flags": dict(sorted(self.drapeaux.items())),
        }


@dataclass(frozen=True)
class FichierGenere:
    chemin: Path
    jour: date
    sha256: str
    octets: int
    attendu: Attendu


def etat_pour(occupation: float) -> str:
    """L'état de trafic d'après k : < 15 fluide, 15 à 30 pré-saturé, 30 à 50 saturé, 50 et plus bloqué."""
    rang = sum(1 for seuil in SEUILS if occupation >= seuil)
    return ETATS[1 + rang]


def _texte_instant(instant: datetime, forme: int) -> str:
    """Le même instant, écrit de trois façons valides : +00:00 (le portail), Z, ou un décalage de deux heures."""
    if forme == 0:
        return instant.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if forme == 1:
        return instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (instant + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+02:00")


def _ligne_valide(hasard: random.Random, capteur: int, instant: datetime, jour: date) -> tuple[list[str], str]:
    """Une ligne qui passe toutes les règles ; rend aussi son drapeau (« MISSING_OCCUPANCY » ou « »)."""
    heure = instant.hour
    profil = 0.25 + 0.75 * max(0.0, 1 - abs(heure - 8.5) / 6) + 0.6 * max(0.0, 1 - abs(heure - 17.5) / 6)
    debit = round(hasard.uniform(20, 900) * profil, 1)
    tirage = hasard.random()
    flag = ""
    if tirage < PART_OCCUPATION_ABSENTE:
        occupation_texte, etat_texte, flag = "", "Inconnu", "MISSING_OCCUPANCY"
    else:
        if tirage < PART_OCCUPATION_ABSENTE + PART_SEUIL_EXACT:
            occupation = hasard.choice(SEUILS)
            etat = hasard.choice([etat_pour(occupation), etat_pour(occupation - 0.001)])  # la notice laisse les deux
        else:
            occupation = round(min(99.9, hasard.uniform(0, 60) * profil), 5)
            etat = etat_pour(occupation)
        occupation_texte = repr(occupation)
        etat_texte = str(ETATS.index(etat)) if hasard.random() < 0.03 else etat  # le rang entier est permis
    barre = hasard.choice(("Ouvert", "Ouvert", "Ouvert", "Barré", "1"))
    libelle = LIBELLES[capteur % len(LIBELLES)]
    ligne = [
        str(capteur), f"{libelle}_{capteur}", _texte_instant(instant, hasard.choice((0, 0, 0, 0, 0, 0, 0, 0, 1, 2))), repr(debit),
        occupation_texte, etat_texte, str(capteur + 1), f"{libelle}_amont", str(capteur + 2), f"{libelle}_aval", barre,
        "1996-10-03", "2023-01-01", "48.8627, 2.3118", FORME,
    ]
    return ligne, flag


def _ligne_defectueuse(hasard: random.Random, genre: str, capteur: int, instant: datetime, jour: date) -> list[str]:
    ligne, _ = _ligne_valide(hasard, capteur, instant, jour)
    iu_ac, t_1h, debit, occupation, etat = 0, 2, 3, 4, 5
    if genre == "DEBIT_ABSENT":
        ligne[debit] = ""
    elif genre == "CHAMP_OBLIGATOIRE_VIDE":
        ligne[hasard.choice((iu_ac, t_1h))] = ""
    elif genre == "TYPE":
        variante = hasard.randrange(6)
        if variante == 0:
            ligne[debit] = "n/a"
        elif variante == 1:
            ligne[iu_ac] = f"A{capteur}"
        elif variante == 2:
            ligne[t_1h] = instant.strftime("%Y-%m-%dT%H:%M:%S")  # sans fuseau : refusé
        elif variante == 3:
            ligne[occupation] = "1,5"
        elif variante == 4:
            ligne[11] = "1996-13-45"  # date_debut
        else:
            ligne[etat] = "Fluidissime"
    elif genre == "BORNE":
        variante = hasard.randrange(4)
        if variante == 0:
            ligne[debit] = "99999.0"
        elif variante == 1:
            ligne[debit] = "-5.0"
        elif variante == 2:
            ligne[occupation], ligne[etat] = "120.0", "Bloqué"
        else:
            ligne[t_1h] = "2005-01-01T00:00:00+00:00"
    elif genre == "HEURE_NON_PLEINE":
        ligne[t_1h] = instant.strftime("%Y-%m-%dT%H:30:00+00:00")
    elif genre == "FUTUR":
        ligne[t_1h] = "2027-01-15T10:00:00+00:00"
    elif genre == "ETAT":
        variante = hasard.randrange(3)
        if variante == 0:
            ligne[occupation], ligne[etat] = repr(round(hasard.uniform(0, 14), 5)), "Saturé"
        elif variante == 1:
            ligne[occupation], ligne[etat] = "", "Fluide"
        else:
            ligne[occupation], ligne[etat] = repr(round(hasard.uniform(1, 60), 5)), "Inconnu"
    return ligne


def contenu_du_jour(jour: date, capteurs: int = CAPTEURS_PAR_DEFAUT, graine: int = GRAINE_PAR_DEFAUT) -> tuple[bytes, Attendu]:
    """Les octets du fichier d'un jour, et ce que le nettoyage doit en tirer."""
    if datetime(jour.year, jour.month, jour.day, tzinfo=UTC) + timedelta(days=1) > MAINTENANT:
        # Après l'horloge du nettoyage, toute ligne serait refusée (FUTURE_TIMESTAMP) : la vérité terrain serait fausse.
        raise ValueError(f"le jour {jour.isoformat()} dépasse l'horloge du nettoyage ({MAINTENANT:%Y-%m-%d %H:%M} UTC) : choisir un début plus ancien")
    hasard = random.Random(f"{graine}|{jour.isoformat()}|{capteurs}")
    attendu = Attendu()
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES)
    valides: list[list[str]] = []
    debut = datetime(jour.year, jour.month, jour.day, tzinfo=UTC)
    for heure in range(24):
        instant = debut + timedelta(hours=heure)
        for capteur in range(1, capteurs + 1):
            tirage, cumul, genre = hasard.random(), 0.0, None
            for nom, part in PROPORTIONS:
                cumul += part
                if tirage < cumul:
                    genre = nom
                    break
            if genre is None:
                ligne, drapeau = _ligne_valide(hasard, capteur, instant, jour)
                attendu.propres += 1
                if drapeau:
                    attendu.drapeaux[drapeau] += 1
                if hasard.random() < PART_DOUBLONS:
                    valides.append(ligne)
            else:
                ligne = _ligne_defectueuse(hasard, genre, capteur, instant, jour)
                attendu.rejetees += 1
                attendu.par_regle[REGLE_DE[genre]] += 1
            attendu.lues += 1
            ecrivain.writerow(ligne)
    hasard.shuffle(valides)
    for ligne in valides:  # recopiées en fin de fichier : la première occurrence est gardée, la copie est refusée
        copie = list(ligne)
        if hasard.random() < 0.5:
            copie[3] = repr(round(float(copie[3]) + 1, 1))  # « valeurs différentes »
        ecrivain.writerow(copie)
        attendu.lues += 1
        attendu.rejetees += 1
        attendu.par_regle["DUPLICATE_KEY"] += 1
    return b"\xef\xbb\xbf" + sortie.getvalue().encode("utf-8"), attendu


def ecrire_le_jour(dossier: Path, jour: date, capteurs: int = CAPTEURS_PAR_DEFAUT, graine: int = GRAINE_PAR_DEFAUT) -> FichierGenere:
    """Écrit le fichier d'un jour dans `dossier` (nommé comme DAT-03) ; un fichier déjà là n'est pas réécrit."""
    octets, attendu = contenu_du_jour(jour, capteurs, graine)
    sha = hashlib.sha256(octets).hexdigest()
    suivant = jour + timedelta(days=1)
    nom = f"{jour:%Y%m%d}T000000Z_{suivant:%Y%m%d}T000000Z_{sha[:12]}.csv"
    chemin = dossier / nom
    dossier.mkdir(parents=True, exist_ok=True)
    if not chemin.exists():
        provisoire = chemin.with_suffix(".csv.part")
        provisoire.write_bytes(octets)
        provisoire.replace(chemin)
    return FichierGenere(chemin, jour, sha, len(octets), attendu)


def _travail(arguments: tuple) -> tuple[str, str, int, dict]:
    dossier, jour, capteurs, graine = arguments
    fichier = ecrire_le_jour(Path(dossier), jour, capteurs, graine)
    return fichier.jour.isoformat(), fichier.chemin.name, fichier.octets, fichier.attendu.en_dict()
