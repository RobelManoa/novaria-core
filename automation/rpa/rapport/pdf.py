"""Écrivain de PDF minimal : du texte, des titres et des tableaux à chasse fixe, en pages A4.

Bibliothèque standard seulement. Le fichier produit est un PDF 1.4 sans compression, en ASCII pur
(les accents passent par des codes octaux de l'encodage WinAnsi), lisible par tout lecteur de PDF.
"""

import textwrap
from datetime import datetime

LARGEUR, HAUTEUR, MARGE = 595, 842, 56
POLICES = {"normal": ("F1", "Helvetica"), "gras": ("F2", "Helvetica-Bold"), "chasse": ("F3", "Courier")}
CARACTERES_PAR_LIGNE = {"normal": 92, "gras": 84, "chasse": 86}


def chaine(texte: str) -> str:
    """Chaîne PDF littérale : cp1252, parenthèses et barre échappées, tout octet non ASCII en octal."""
    sortie = []
    for octet in texte.encode("cp1252", errors="replace"):
        caractere = chr(octet)
        if caractere in "\\()":
            sortie.append("\\" + caractere)
        elif 32 <= octet < 127:
            sortie.append(caractere)
        else:
            sortie.append(f"\\{octet:03o}")
    return "(" + "".join(sortie) + ")"


def chaine_unicode(texte: str) -> str:
    """Chaîne hexadécimale UTF-16BE (métadonnées du document : titre avec accents)."""
    return "<FEFF" + texte.encode("utf-16-be").hex().upper() + ">"


class Document:
    def __init__(self, titre: str, cree_le: datetime) -> None:
        self.titre = titre
        self.cree_le = cree_le
        self._pages: list[list[str]] = [[]]
        self._y = HAUTEUR - MARGE

    def _ligne(self, texte: str, police: str, taille: int, interligne: int, decalage: int = 0) -> None:
        if self._y - interligne < MARGE:
            self._pages.append([])
            self._y = HAUTEUR - MARGE
        self._y -= interligne
        nom = POLICES[police][0]
        self._pages[-1].append(f"BT /{nom} {taille} Tf 1 0 0 1 {MARGE + decalage} {self._y} Tm {chaine(texte)} Tj ET")

    def _texte(self, texte: str, police: str, taille: int, interligne: int) -> None:
        largeur = CARACTERES_PAR_LIGNE[police] if taille <= 11 else int(CARACTERES_PAR_LIGNE[police] * 11 / taille)
        for ligne in textwrap.wrap(texte, width=largeur) or [""]:
            self._ligne(ligne, police, taille, interligne)

    def titre_principal(self, texte: str) -> None:
        self._texte(texte, "gras", 17, 22)
        self._y -= 4

    def section(self, texte: str) -> None:
        self._y -= 10
        self._texte(texte, "gras", 12, 16)

    def paragraphe(self, texte: str, *, gras: bool = False) -> None:
        self._texte(texte, "gras" if gras else "normal", 10, 14)

    def tableau(self, lignes: list[str]) -> None:
        """Lignes déjà alignées (chasse fixe) : le tableau ne se coupe jamais au milieu d'une ligne."""
        for ligne in lignes:
            self._ligne(ligne[: CARACTERES_PAR_LIGNE["chasse"]], "chasse", 9, 12)

    def octets(self) -> bytes:
        objets: list[bytes] = []

        def ajouter(corps: str | bytes) -> int:
            objets.append(corps.encode("ascii") if isinstance(corps, str) else corps)
            return len(objets)

        catalogue = ajouter("")  # remplacé plus bas (il référence l'arbre des pages)
        arbre = ajouter("")
        polices = " ".join(
            f"/{nom} {ajouter(f'<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>')} 0 R"
            for nom, base in POLICES.values()
        )
        pages = []
        for contenu in self._pages:
            flux = "\n".join(contenu).encode("ascii")
            identifiant_flux = ajouter(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(flux), flux))
            pages.append(
                ajouter(
                    f"<< /Type /Page /Parent {arbre} 0 R /MediaBox [0 0 {LARGEUR} {HAUTEUR}] "
                    f"/Resources << /Font << {polices} >> >> /Contents {identifiant_flux} 0 R >>"
                )
            )
        date = self.cree_le.strftime("D:%Y%m%d%H%M%SZ")
        info = ajouter(
            f"<< /Title {chaine_unicode(self.titre)} /Producer {chaine('Novaria RPA')} "
            f"/CreationDate {chaine(date)} >>"
        )
        objets[catalogue - 1] = f"<< /Type /Catalog /Pages {arbre} 0 R >>".encode("ascii")
        objets[arbre - 1] = (
            f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in pages)}] /Count {len(pages)} >>".encode("ascii")
        )
        sortie = bytearray(b"%PDF-1.4\n")
        positions = []
        for numero, corps in enumerate(objets, start=1):
            positions.append(len(sortie))
            sortie += f"{numero} 0 obj\n".encode("ascii") + corps + b"\nendobj\n"
        debut_xref = len(sortie)
        sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode("ascii")
        for position in positions:
            sortie += f"{position:010d} 00000 n \n".encode("ascii")
        sortie += (
            f"trailer\n<< /Size {len(objets) + 1} /Root {catalogue} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{debut_xref}\n%%EOF\n"
        ).encode("ascii")
        return bytes(sortie)
