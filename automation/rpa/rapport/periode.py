"""Période d'un rapport : une semaine ISO (lundi 00:00 UTC inclus, lundi suivant exclu)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


class PeriodeInvalide(ValueError):
    pass


@dataclass(frozen=True)
class Periode:
    debut: datetime  # inclus
    fin: datetime  # exclu

    @property
    def etiquette(self) -> str:
        """`2026-S43` : année et numéro de la semaine ISO du début."""
        annee, semaine, _ = self.debut.isocalendar()
        return f"{annee}-S{semaine:02d}"

    @property
    def libelle(self) -> str:
        dernier = self.fin - timedelta(days=1)
        return f"du {self.debut:%d/%m/%Y} au {dernier:%d/%m/%Y}"

    def api(self, instant: datetime) -> str:
        return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def lundi(jour: date) -> datetime:
    return datetime(jour.year, jour.month, jour.day, tzinfo=UTC) - timedelta(days=jour.weekday())


def semaine_de(jour: date) -> Periode:
    debut = lundi(jour)
    return Periode(debut, debut + timedelta(days=7))


def semaine_precedente(maintenant: datetime) -> Periode:
    """La semaine ISO complète qui précède celle de `maintenant` (le déclencheur du lundi)."""
    debut = lundi(maintenant.astimezone(UTC).date()) - timedelta(days=7)
    return Periode(debut, debut + timedelta(days=7))


def choisir(debut: str | None, fin: str | None, maintenant: datetime) -> Periode:
    """Période demandée (`AAAA-MM-JJ`, fin exclue) ou, sans date, la semaine précédente."""
    if not debut and not fin:
        return semaine_precedente(maintenant)
    if not debut:
        raise PeriodeInvalide("la fin est donnée sans le début")
    try:
        premier = datetime.strptime(debut, "%Y-%m-%d").replace(tzinfo=UTC)
        dernier = (
            datetime.strptime(fin, "%Y-%m-%d").replace(tzinfo=UTC)
            if fin
            else premier + timedelta(days=7)
        )
    except ValueError as erreur:
        raise PeriodeInvalide("les dates s'écrivent AAAA-MM-JJ") from erreur
    if dernier <= premier:
        raise PeriodeInvalide("la fin doit suivre le début")
    if dernier - premier > timedelta(days=31):
        raise PeriodeInvalide("une période dépasse 31 jours au plus")
    return Periode(premier, dernier)
