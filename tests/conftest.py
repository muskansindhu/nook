import pytest

from nook.config import Config
from nook.service import Nook


@pytest.fixture
def nook(tmp_path):
    return Nook(Config(db_path=tmp_path / "t.db"))
