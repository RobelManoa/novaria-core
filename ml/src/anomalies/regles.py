"""Les règles robustes : des seuils sur les variables de `variables.py`, plus l'horloge pour le silence.

| Règle | Se déclenche quand | Cible |
|---|---|---|
| `ecart_mediane` | vitesse ou comptage à 6,0 (vitesse) / 7,5 (comptage) échelles robustes de la médiane glissante ; ou vitesse nulle alors que des véhicules sont comptés | valeur aberrante |
| `plateau` | 12 mesures de suite exactement identiques (au moins un véhicule), soit 2 minutes | capteur figé |
| `capteur_muet` | aucune livraison du capteur depuis plus de 60 s (règle DQ-08, `alert_rule` `capteur.muet`) | capteur muet |
| `chute_de_debit` | le débit moyen de 2 minutes tombe sous 25 % du débit moyen précédent (au moins 2,5 véhicules par mesure), sans que la vitesse baisse (donc sans congestion) | chute inexpliquée |
| `livraison_en_retard` | un message arrive plus de 30 s après sa mesure (règle DQ-04) | retard |
| `doublon` | un identifiant déjà livré revient | doublon |

La vitesse nulle avec des véhicules est un cas d'incohérence ajouté à `ecart_mediane` : sur 284 522 mesures normales de la
validation il n'y en a aucune (la vitesse la plus basse est de 1,5 km/h), alors que l'écart à la médiane ne la
sépare pas d'un ralentissement réel (écarts de 3,0 à 5,5 pour un seuil de 6,0).

Les deux dernières ne figurent pas dans la liste de l'issue : sans elles, le simulateur injecte deux anomalies (retard et
doublon) que le flux d'entrée verrait mais que les autres règles ne regardent pas. Ce sont des règles d'une ligne.

Les seuils ont été fixés sur les runs de **validation** (`campagne.py`), avant de lire l'évaluation : sur 24 h de trafic
simulé sans anomalie, ils donnent moins d'une fausse alerte par heure de réseau (le budget commun aux règles et à
Isolation Forest, voir `evaluation.py`). Une règle d'écart à la médiane déclenche aussi sur un vrai changement brutal de
régime ; c'est son défaut connu, dit dans le rapport.
"""

from dataclasses import dataclass
from typing import NamedTuple

from anomalies.campagne import Banc, Mesure
from anomalies.variables import NOMS, Suivi

INDEX = {nom: rang for rang, nom in enumerate(NOMS)}
REGLES = ("ecart_mediane", "plateau", "capteur_muet", "chute_de_debit", "livraison_en_retard", "doublon")


class Alerte(NamedTuple):
    detecteur: str  # une règle de REGLES, ou « isolation_forest »
    capteur: str
    a: float  # secondes Unix : l'instant où l'alerte peut partir
    detail: str = ""


@dataclass(frozen=True)
class Parametres:
    ecart_vitesse: float = 6.0
    ecart_debit: float = 7.5
    chute_debit: float = 0.25
    chute_vitesse_min: float = 0.85
    plateau: int = 12
    silence_s: float = 60.0
    retard_s: float = 30.0


PARAMETRES = Parametres()


class DetecteurRegles:
    def __init__(self, parametres: Parametres = PARAMETRES) -> None:
        self.p = parametres
        self.suivi = Suivi()
        self.derniere: dict[str, float] = {}
        self.muets: set[str] = set()

    def _silences(self, horloge: float) -> list[Alerte]:
        alertes = []
        for capteur, derniere in self.derniere.items():
            if capteur not in self.muets and horloge - derniere > self.p.silence_s:
                self.muets.add(capteur)
                alertes.append(Alerte("capteur_muet", capteur, derniere + self.p.silence_s, f"silence de plus de {self.p.silence_s:g} s"))
        return alertes

    def traiter(self, m: Mesure) -> list[Alerte]:
        alertes = self._silences(m.livre)
        self.muets.discard(m.capteur)
        self.derniere[m.capteur] = m.livre
        x = self.suivi.observer(m)
        valeur = {nom: x[rang] for nom, rang in INDEX.items()}
        p = self.p
        if valeur["copies"] > 1:
            return [*alertes, Alerte("doublon", m.capteur, m.livre, f"identifiant livré {valeur['copies']:g} fois")]
        if valeur["retard_s"] > p.retard_s:
            alertes.append(Alerte("livraison_en_retard", m.capteur, m.livre, f"{valeur['retard_s']:g} s de retard"))
        if m.vehicules >= 1 and abs(m.vitesse) < 1e-9:  # des véhicules sont passés à vitesse nulle : impossible (jamais vu en trafic normal)
            alertes.append(Alerte("ecart_mediane", m.capteur, m.livre, "vitesse nulle malgré des véhicules comptés"))
        elif valeur["ecart_vitesse"] >= p.ecart_vitesse or valeur["ecart_debit"] >= p.ecart_debit:
            alertes.append(Alerte("ecart_mediane", m.capteur, m.livre, f"vitesse {valeur['ecart_vitesse']:.1f}, comptage {valeur['ecart_debit']:.1f}"))
        if valeur["plateau"] >= p.plateau:
            alertes.append(Alerte("plateau", m.capteur, m.livre, f"{valeur['plateau']:g} mesures identiques"))
        if valeur["ratio_debit"] <= p.chute_debit and valeur["ratio_vitesse"] >= p.chute_vitesse_min:
            alertes.append(Alerte("chute_de_debit", m.capteur, m.livre, f"débit à {valeur['ratio_debit']:.0%} de la médiane"))
        return alertes

    def fin(self, instant: float) -> list[Alerte]:
        return self._silences(instant)


def alertes_des_regles(banc: Banc, parametres: Parametres = PARAMETRES) -> list[Alerte]:
    detecteur = DetecteurRegles(parametres)
    alertes: list[Alerte] = []
    for m in sorted(banc.mesures, key=lambda mesure: (mesure.livre, mesure.capteur)):
        alertes += detecteur.traiter(m)
    return alertes + detecteur.fin(banc.fin)
