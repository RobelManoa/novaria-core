"""Notification par courriel (facultative) : un message court au sujet du rapport, jamais le rapport lui-même.

Désactivée par défaut : sans `NOVARIA_RPA_SMTP`, seul le journal `notifications.log` reçoit la notification. Réglages par
l'environnement (jamais par la ligne de commande, qui se voit dans la liste des processus) :

| variable | sens |
|---|---|
| `NOVARIA_RPA_SMTP` | `hôte:port` du serveur de courrier (`127.0.0.1:1025` pour un serveur d'essai local) |
| `NOVARIA_RPA_DESTINATAIRE` | une adresse, obligatoire avec le serveur |
| `NOVARIA_RPA_EXPEDITEUR` | adresse d'expédition (`novaria-rpa@localhost` par défaut) |
| `NOVARIA_RPA_SMTP_UTILISATEUR`, `NOVARIA_RPA_SMTP_MOT_DE_PASSE` | compte du serveur, facultatif ; **jamais** dans `.env.example`, jamais dans un journal |

Chiffrement : STARTTLS est **exigé** dès que le serveur n'est pas sur la machine ; un compte n'est jamais présenté en clair ;
le mot de passe d'un compte ne part que sur un canal chiffré. Un échec d'envoi ne fait jamais échouer le rapport.
"""

import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

ADRESSE = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}")
HOTE = re.compile(r"[A-Za-z0-9.-]{1,255}")
LOCAUX = frozenset({"127.0.0.1", "localhost", "::1"})
DELAI_S = 15


class CourrielNonConfigure(Exception):
    pass


class ErreurCourriel(Exception):
    """L'envoi a échoué ; le message ne contient ni mot de passe ni contenu du courriel."""


@dataclass(frozen=True)
class Reglages:
    hote: str
    port: int
    destinataire: str
    expediteur: str
    utilisateur: str | None
    mot_de_passe: str | None

    @property
    def chiffre(self) -> bool:
        return self.hote not in LOCAUX  # un serveur local d'essai n'est pas chiffré ; tout autre serveur doit l'être


def reglages(environnement: dict[str, str]) -> Reglages | None:
    """Les réglages, ou `None` si le courriel n'est pas demandé. Un réglage invalide lève `CourrielNonConfigure`."""
    serveur = environnement.get("NOVARIA_RPA_SMTP", "").strip()
    if not serveur:
        return None
    hote, separateur, port_texte = serveur.rpartition(":")
    if not separateur or not HOTE.fullmatch(hote) or not port_texte.isdigit() or not 0 < int(port_texte) < 65536:
        raise CourrielNonConfigure("NOVARIA_RPA_SMTP doit être « hôte:port »")
    destinataire = environnement.get("NOVARIA_RPA_DESTINATAIRE", "").strip()
    expediteur = environnement.get("NOVARIA_RPA_EXPEDITEUR", "novaria-rpa@localhost").strip()
    for nom, adresse in (("NOVARIA_RPA_DESTINATAIRE", destinataire), ("NOVARIA_RPA_EXPEDITEUR", expediteur)):
        if not ADRESSE.fullmatch(adresse):
            raise CourrielNonConfigure(f"{nom} doit être une seule adresse de courriel")
    utilisateur = environnement.get("NOVARIA_RPA_SMTP_UTILISATEUR") or None
    mot_de_passe = environnement.get("NOVARIA_RPA_SMTP_MOT_DE_PASSE") or None
    if bool(utilisateur) != bool(mot_de_passe):
        raise CourrielNonConfigure("le compte du serveur de courrier demande l'utilisateur et le mot de passe ensemble")
    return Reglages(hote, int(port_texte), destinataire, expediteur, utilisateur, mot_de_passe)


def composer(r: Reglages, sujet: str, corps: str) -> EmailMessage:
    message = EmailMessage()
    message["From"], message["To"] = r.expediteur, r.destinataire
    message["Subject"] = " ".join(sujet.split())[:200]  # une seule ligne : pas d'en-tête injecté par un saut de ligne
    message.set_content(corps)
    return message


def envoyer(r: Reglages, sujet: str, corps: str, *, fabrique=smtplib.SMTP) -> None:
    """Envoie le message. Chiffrement exigé hors de la machine ; jamais de mot de passe sur un canal en clair."""
    if r.utilisateur and not r.chiffre:
        raise ErreurCourriel("un compte n'est jamais présenté sur un canal en clair : serveur non chiffré refusé")
    message = composer(r, sujet, corps)
    try:
        with fabrique(r.hote, r.port, timeout=DELAI_S) as serveur:
            serveur.ehlo()
            if r.chiffre:
                serveur.starttls(context=ssl.create_default_context())
                serveur.ehlo()
            if r.utilisateur:
                serveur.login(r.utilisateur, r.mot_de_passe)
            serveur.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as erreur:
        raise ErreurCourriel(f"envoi impossible ({type(erreur).__name__})") from erreur
