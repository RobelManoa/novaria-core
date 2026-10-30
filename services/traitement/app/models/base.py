"""Base déclarative du schéma `app` (API métier, ADR-024) et nommage des contraintes."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "app"

# Les noms sont fixés par la convention : le modèle et la migration produisent les mêmes, donc
# `alembic revision --autogenerate` ne voit aucune différence et une contrainte se retrouve
# par son nom.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Toutes les tables du modèle métier vivent dans le schéma `app`, propriété de `svc_app`."""

    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
