"""Écriture et lecture de fichiers Parquet, bibliothèque standard seulement (sous-ensemble volontairement étroit).

Pourquoi : l'empreinte SHA-256 d'un jeu (ADR-027, règle 5) doit être la même sur Linux et sur Windows, avec ou sans
`pyarrow`. Ici le format est entièrement maîtrisé : colonnes PLAIN, sans compression, sans dictionnaire, sans date
d'écriture. Deux écritures des mêmes lignes donnent les mêmes octets. Les fichiers sont lisibles par tout lecteur
Parquet (essayé avec `pyarrow` : voir `ml/tests/test_parquet.py`).

Types : `int32`, `int64`, `double`, `bool`, `string` (UTF-8) et `timestamp` (microsecondes, UTC). Une colonne peut
être facultative (valeurs `None`). Un groupe de lignes = une page de données par colonne.
"""

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAGIC = b"PAR1"
CREATED_BY = "novaria-core jeu_entrainement parquet-stdlib 1.0"
ROW_GROUP_SIZE = 50_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Types physiques de Parquet
BOOLEAN, INT32, INT64, DOUBLE, BYTE_ARRAY = 0, 1, 2, 5, 6
PHYSICAL = {"int32": INT32, "int64": INT64, "double": DOUBLE, "bool": BOOLEAN, "string": BYTE_ARRAY, "timestamp": INT64}
LOGICAL_NAMES = {value: key for key, value in PHYSICAL.items() if key != "timestamp"}
UTF8, TIMESTAMP_MICROS = 0, 10  # types convertis (lecteurs anciens)
REQUIRED, OPTIONAL = 0, 1
PLAIN, RLE = 0, 3

# Protocole compact de Thrift : types de champ
T_TRUE, T_FALSE, T_I32, T_I64, T_BINARY, T_LIST, T_STRUCT = 1, 2, 5, 6, 8, 9, 12


class ParquetError(ValueError):
    pass


@dataclass(frozen=True)
class Colonne:
    nom: str
    type: str
    facultative: bool = True


# ------------------------------------------------------------------------------------ Thrift (compact)


def varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(number: int) -> int:
    return (number << 1) ^ (number >> 63)


def unzigzag(number: int) -> int:
    return (number >> 1) ^ -(number & 1)


class Struct:
    """Une structure Thrift en cours d'écriture : les champs s'ajoutent dans l'ordre croissant des numéros."""

    def __init__(self) -> None:
        self._out = bytearray()
        self._last = 0

    def _header(self, field: int, kind: int) -> None:
        delta = field - self._last
        if not 0 < delta <= 15:
            raise ParquetError("champs Thrift à écrire dans l'ordre, par pas de 15 au plus")
        self._out.append((delta << 4) | kind)
        self._last = field

    def i32(self, field: int, value: int) -> "Struct":
        self._header(field, T_I32)
        self._out += varint(zigzag(value))
        return self

    def i64(self, field: int, value: int) -> "Struct":
        self._header(field, T_I64)
        self._out += varint(zigzag(value))
        return self

    def boolean(self, field: int, value: bool) -> "Struct":
        self._header(field, T_TRUE if value else T_FALSE)
        return self

    def string(self, field: int, value: str) -> "Struct":
        data = value.encode("utf-8")
        self._header(field, T_BINARY)
        self._out += varint(len(data)) + data
        return self

    def struct(self, field: int, inner: "Struct") -> "Struct":
        self._header(field, T_STRUCT)
        self._out += inner.end()
        return self

    def list_of_i32(self, field: int, values: Sequence[int]) -> "Struct":
        self._list_header(field, T_I32, len(values))
        for value in values:
            self._out += varint(zigzag(value))
        return self

    def list_of_strings(self, field: int, values: Sequence[str]) -> "Struct":
        self._list_header(field, T_BINARY, len(values))
        for value in values:
            data = value.encode("utf-8")
            self._out += varint(len(data)) + data
        return self

    def list_of_structs(self, field: int, items: Sequence["Struct"]) -> "Struct":
        self._list_header(field, T_STRUCT, len(items))
        for item in items:
            self._out += item.end()
        return self

    def _list_header(self, field: int, kind: int, size: int) -> None:
        self._header(field, T_LIST)
        if size < 15:
            self._out.append((size << 4) | kind)
        else:
            self._out.append(0xF0 | kind)
            self._out += varint(size)

    def end(self) -> bytes:
        return bytes(self._out) + b"\x00"


def read_varint(data: bytes, position: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7


def read_struct(data: bytes, position: int) -> tuple[dict[int, object], int]:
    """Lit une structure Thrift compacte en dictionnaire `numéro de champ -> valeur`."""
    fields: dict[int, object] = {}
    last = 0
    while True:
        header = data[position]
        position += 1
        if header == 0:
            return fields, position
        kind, delta = header & 0x0F, header >> 4
        if delta:
            field = last + delta
        else:
            raw, position = read_varint(data, position)
            field = unzigzag(raw)
        last = field
        fields[field], position = read_value(data, position, kind)


def read_value(data: bytes, position: int, kind: int) -> tuple[object, int]:
    if kind == T_TRUE:
        return True, position
    if kind == T_FALSE:
        return False, position
    if kind in (3, 4, T_I32, T_I64):
        raw, position = read_varint(data, position)
        return unzigzag(raw), position
    if kind == T_BINARY:
        size, position = read_varint(data, position)
        return data[position : position + size], position + size
    if kind == T_STRUCT:
        return read_struct(data, position)
    if kind == T_LIST:
        header = data[position]
        position += 1
        size, element = header >> 4, header & 0x0F
        if size == 15:
            size, position = read_varint(data, position)
        items = []
        for _ in range(size):
            item, position = read_value(data, position, element)
            items.append(item)
        return items, position
    raise ParquetError(f"type Thrift non géré : {kind}")


# --------------------------------------------------------------------------------------- valeurs


def encode_values(kind: str, values: Sequence[object]) -> bytes:
    if kind == "int32":
        return struct.pack(f"<{len(values)}i", *values)
    if kind == "int64":
        return struct.pack(f"<{len(values)}q", *values)
    if kind == "double":
        return struct.pack(f"<{len(values)}d", *values)
    if kind == "bool":
        out = bytearray((len(values) + 7) // 8)
        for index, value in enumerate(values):
            if value:
                out[index // 8] |= 1 << (index % 8)
        return bytes(out)
    if kind == "string":
        out = bytearray()
        for value in values:
            data = str(value).encode("utf-8")
            out += struct.pack("<I", len(data)) + data
        return bytes(out)
    if kind == "timestamp":
        return struct.pack(f"<{len(values)}q", *(microseconds(value) for value in values))
    raise ParquetError(f"type inconnu : {kind}")


def microseconds(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ParquetError("un horodatage doit porter un fuseau (UTC)")
    return (moment - EPOCH) // timedelta(microseconds=1)


def encode_levels(present: Sequence[bool]) -> bytes:
    """Niveaux de définition (0 : absent, 1 : présent) en RLE, précédés de leur longueur sur 4 octets."""
    out = bytearray()
    index = 0
    while index < len(present):
        run = 1
        while index + run < len(present) and present[index + run] == present[index]:
            run += 1
        out += varint(run << 1) + bytes([1 if present[index] else 0])
        index += run
    return struct.pack("<I", len(out)) + bytes(out)


def check(kind: str, value: object) -> None:
    ok = {
        "int32": lambda v: isinstance(v, int) and not isinstance(v, bool) and -(2**31) <= v < 2**31,
        "int64": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "double": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v == v,
        "bool": lambda v: isinstance(v, bool),
        "string": lambda v: isinstance(v, str),
        "timestamp": lambda v: isinstance(v, datetime),
    }[kind]
    if not ok(value):
        raise ParquetError(f"valeur {value!r} refusée pour une colonne {kind}")


# ------------------------------------------------------------------------------------- écriture


def schema_element(column: Colonne) -> Struct:
    element = Struct().i32(1, PHYSICAL[column.type]).i32(3, OPTIONAL if column.facultative else REQUIRED)
    element.string(4, column.nom)
    if column.type == "string":
        element.i32(6, UTF8).struct(10, Struct().struct(1, Struct()))
    elif column.type == "timestamp":
        unit = Struct().struct(2, Struct())  # MICROS
        element.i32(6, TIMESTAMP_MICROS).struct(10, Struct().struct(8, Struct().boolean(1, True).struct(2, unit)))
    return element


def column_chunk(column: Colonne, values: Sequence[object], offset: int) -> tuple[bytes, Struct, int]:
    """La page de données d'une colonne pour un groupe de lignes, et la description du morceau de colonne."""
    present = [value is not None for value in values]
    if not column.facultative and not all(present):
        raise ParquetError(f"la colonne {column.nom} n'accepte pas de valeur absente")
    kept = [value for value in values if value is not None]
    for value in kept:
        check(column.type, value)
    body = (encode_levels(present) if column.facultative else b"") + encode_values(column.type, kept)
    page_header = (
        Struct()
        .i32(1, 0)
        .i32(2, len(body))
        .i32(3, len(body))
        .struct(5, Struct().i32(1, len(values)).i32(2, PLAIN).i32(3, RLE).i32(4, RLE))
        .end()
    )
    chunk = page_header + body
    meta = (
        Struct()
        .i32(1, PHYSICAL[column.type])
        .list_of_i32(2, [PLAIN, RLE])
        .list_of_strings(3, [column.nom])
        .i32(4, 0)
        .i64(5, len(values))
        .i64(6, len(chunk))
        .i64(7, len(chunk))
        .i64(9, offset)
    )
    return chunk, Struct().i64(2, offset).struct(3, meta), len(chunk)


def encoder(colonnes: Sequence[Colonne], lignes: Sequence[Sequence[object]], *, taille_groupe: int = ROW_GROUP_SIZE) -> bytes:
    """Les octets d'un fichier Parquet de `lignes` (tuples dans l'ordre des colonnes) ; identiques à chaque appel."""
    if not colonnes:
        raise ParquetError("au moins une colonne")
    if len({c.nom for c in colonnes}) != len(colonnes):
        raise ParquetError("noms de colonnes en double")
    if taille_groupe < 1:
        raise ParquetError("un groupe de lignes contient au moins une ligne")
    for ligne in lignes:
        if len(ligne) != len(colonnes):
            raise ParquetError(f"ligne de {len(ligne)} valeurs pour {len(colonnes)} colonnes")
    out = bytearray(MAGIC)
    groups = []
    for start in range(0, len(lignes), taille_groupe):
        block = lignes[start : start + taille_groupe]
        chunks, total = [], 0
        for index, column in enumerate(colonnes):
            data, description, size = column_chunk(column, [row[index] for row in block], len(out))
            out += data
            chunks.append(description)
            total += size
        groups.append(Struct().list_of_structs(1, chunks).i64(2, total).i64(3, len(block)))
    footer = (
        Struct()
        .i32(1, 1)
        .list_of_structs(2, [Struct().string(4, "schema").i32(5, len(colonnes))] + [schema_element(c) for c in colonnes])
        .i64(3, len(lignes))
        .list_of_structs(4, groups)
        .string(6, CREATED_BY)
        .end()
    )
    out += footer + struct.pack("<I", len(footer)) + MAGIC
    return bytes(out)


# -------------------------------------------------------------------------------------- lecture


def decode_levels(data: bytes, count: int) -> tuple[list[bool], int]:
    size = struct.unpack_from("<I", data, 0)[0]
    present: list[bool] = []
    position = 4
    while position < 4 + size:
        header, position = read_varint(data, position)
        run, value = header >> 1, data[position]
        position += 1
        present += [bool(value)] * run
    return present[:count], 4 + size


def decode_values(kind: str, data: bytes, position: int, count: int) -> list[object]:
    if kind == "int32":
        return list(struct.unpack_from(f"<{count}i", data, position))
    if kind == "int64":
        return list(struct.unpack_from(f"<{count}q", data, position))
    if kind == "double":
        return list(struct.unpack_from(f"<{count}d", data, position))
    if kind == "bool":
        return [bool(data[position + i // 8] >> (i % 8) & 1) for i in range(count)]
    if kind == "timestamp":
        return [EPOCH + timedelta(microseconds=v) for v in struct.unpack_from(f"<{count}q", data, position)]
    values = []
    for _ in range(count):
        size = struct.unpack_from("<I", data, position)[0]
        values.append(data[position + 4 : position + 4 + size].decode("utf-8"))
        position += 4 + size
    return values


def decoder(data: bytes) -> tuple[list[Colonne], list[tuple]]:
    """Relit les octets écrits par `encoder` : colonnes et lignes (toutes les pages sont PLAIN, sans compression)."""
    if data[:4] != MAGIC or data[-4:] != MAGIC:
        raise ParquetError("ce n'est pas un fichier Parquet (signature PAR1 absente)")
    footer_size = struct.unpack_from("<I", data, len(data) - 8)[0]
    meta, _ = read_struct(data, len(data) - 8 - footer_size)
    elements = meta[2][1:]  # le premier élément décrit la racine
    columns = []
    for element in elements:
        physical, repetition, name = element[1], element[3], element[4].decode("utf-8")
        kind = "timestamp" if element.get(6) == TIMESTAMP_MICROS else LOGICAL_NAMES[physical]
        if element.get(6) == UTF8:
            kind = "string"
        columns.append(Colonne(name, kind, repetition == OPTIONAL))
    values: list[list[object]] = [[] for _ in columns]
    for group in meta[4]:
        for index, chunk in enumerate(group[1]):
            description = chunk[3]
            header, body = read_struct(data, description[9])
            page = data[body : body + header[2]]
            count = header[5][1]
            position, present = 0, [True] * count
            if columns[index].facultative:
                present, position = decode_levels(page, count)
            found = decode_values(columns[index].type, page, position, sum(present))
            iterator = iter(found)
            values[index] += [next(iterator) if flag else None for flag in present]
    return columns, list(zip(*values, strict=True)) if values and values[0] else []
