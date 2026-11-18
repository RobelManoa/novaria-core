"""Les variables calculées message par message : ce que lisent les règles et ce que reçoit Isolation Forest.

Un `Suivi` garde, pour chaque capteur, les 30 dernières mesures (5 minutes) et calcule, à chaque message livré, le
même vecteur de dix variables. Les règles en prennent des seuils ; Isolation Forest les prend telles quelles : la
comparaison porte donc sur la façon de décider, pas sur l'information disponible.

| Variable | Sens | Valeur normale |
|---|---|---|
| `vehicules`, `vitesse`, `occupation` | les trois valeurs du message (vitesse 0 si aucun véhicule) | |
| `ecart_vitesse`, `ecart_debit` | écart à la médiane glissante, en échelles robustes (MAD) | proche de 0 |
| `ratio_debit`, `ratio_vitesse` | débit moyen des 12 dernières mesures (vitesse : médiane des 12) sur les mesures plus anciennes de la fenêtre (1 si ce débit est sous 2,5 véhicules par mesure) | proche de 1 |
| `plateau` | nombre de mesures de suite avec exactement les mêmes valeurs (au moins un véhicule) | 1 |
| `silence_s` | secondes écoulées depuis la dernière livraison du même capteur | 10 |
| `retard_s` | secondes entre l'instant de la mesure et sa livraison | 0 |
| `copies` | nombre de fois que cet identifiant a été livré | 1 |

Le champ `quality` du message (VALID, SUSPECT) n'est **jamais lu** : le simulateur le renseigne d'après l'anomalie
qu'il vient d'injecter, ce qui reviendrait à lire la réponse.
"""

import statistics
from collections import OrderedDict, deque

from anomalies.campagne import Mesure

NOMS = ("vehicules", "vitesse", "occupation", "ecart_vitesse", "ecart_debit", "ratio_debit", "ratio_vitesse", "plateau", "silence_s", "retard_s", "copies")
FENETRE = 30  # mesures gardées par capteur (5 minutes)
RECENT = 12  # mesures (2 minutes) comparées à la médiane des plus anciennes
HISTORIQUE_MIN = 24  # sans 4 minutes d'historique, aucun écart n'est calculé
MEMOIRE_IDENTIFIANTS = 3000  # identifiants gardés pour compter les copies (plus de 10 minutes de tout le réseau)
REFERENCE_MIN = 2.5  # véhicules par mesure : en dessous (route peu chargée), « chute de débit » n'a pas de sens
ECHELLE_MAD = 1.4826  # rend le MAD comparable à un écart type pour une loi normale


def echelle(valeurs: list[float], mediane: float, plancher_relatif: float, plancher: float, *, poisson: bool = False) -> float:
    """Échelle robuste : MAD normalisé, jamais sous un plancher (un signal très calme n'a pas un MAD de zéro qui explose)."""
    mad = statistics.median(abs(v - mediane) for v in valeurs) * ECHELLE_MAD
    return max(mad, plancher_relatif * abs(mediane), statistics.fmean([mediane, 0.0]) ** 0.5 if poisson else 0.0, plancher)


class _Capteur:
    def __init__(self) -> None:
        self.vitesses: deque[float] = deque(maxlen=FENETRE)
        self.debits: deque[int] = deque(maxlen=FENETRE)
        self.derniere_livraison: float | None = None
        self.derniere_valeur: tuple | None = None
        self.plateau = 0


class Suivi:
    def __init__(self) -> None:
        self.capteurs: dict[str, _Capteur] = {}
        self.vus: OrderedDict[str, int] = OrderedDict()

    def observer(self, m: Mesure) -> tuple[float, ...]:
        capteur = self.capteurs.setdefault(m.capteur, _Capteur())
        copies = self.vus.get(m.ident, 0) + 1
        self.vus[m.ident] = copies
        self.vus.move_to_end(m.ident)
        if len(self.vus) > MEMOIRE_IDENTIFIANTS:
            self.vus.popitem(last=False)
        silence = 10.0 if capteur.derniere_livraison is None else m.livre - capteur.derniere_livraison
        capteur.derniere_livraison = m.livre
        vitesse = m.vitesse if m.vitesse is not None else 0.0
        if copies > 1:  # une copie ne dit rien de plus sur la mesure : elle ne touche ni l'historique ni le plateau
            return (m.vehicules, vitesse, m.occupation, 0.0, 0.0, 1.0, 1.0, 1.0, silence, m.livre - m.instant, copies)

        ecart_vitesse = ecart_debit = 0.0
        ratio_debit = ratio_vitesse = 1.0
        vitesses, debits = list(capteur.vitesses), list(capteur.debits)
        if m.vitesse is not None and len(vitesses) >= HISTORIQUE_MIN:
            mediane = statistics.median(vitesses)
            ecart_vitesse = abs(m.vitesse - mediane) / echelle(vitesses, mediane, 0.15, 5.0)
        if len(debits) >= HISTORIQUE_MIN:
            mediane = statistics.median(debits)
            ecart_debit = abs(m.vehicules - mediane) / echelle(debits, mediane, 0.0, 1.0, poisson=True)
            recents = [*debits[-(RECENT - 1):], m.vehicules]
            reference = statistics.fmean(debits[:-(RECENT - 1)])
            ratio_debit = statistics.fmean(recents) / reference if reference >= REFERENCE_MIN else 1.0
            vitesses_recentes = [*vitesses[-(RECENT - 1):], *([m.vitesse] if m.vitesse is not None else [])]
            anciennes = vitesses[:-(RECENT - 1)]
            if len(vitesses_recentes) >= 3 and len(anciennes) >= 8:
                ratio_vitesse = statistics.median(vitesses_recentes) / max(statistics.median(anciennes), 1.0)

        valeur = (m.vehicules, m.vitesse, m.occupation)
        capteur.plateau = capteur.plateau + 1 if (valeur == capteur.derniere_valeur and m.vehicules >= 1) else 1
        capteur.derniere_valeur = valeur
        capteur.debits.append(m.vehicules)
        if m.vitesse is not None:
            capteur.vitesses.append(m.vitesse)
        return (m.vehicules, vitesse, m.occupation, ecart_vitesse, ecart_debit, ratio_debit, ratio_vitesse, capteur.plateau, silence, m.livre - m.instant, copies)
