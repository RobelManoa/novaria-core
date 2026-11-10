"""Fixtures communes : le service entier sur des faux, et des réglages neufs à chaque test."""

import pytest

from app.core.config import get_settings
from tests.support import Rig


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def rig() -> Rig:
    return Rig()
