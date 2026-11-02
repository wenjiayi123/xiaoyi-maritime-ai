import os
from pathlib import Path

from app.config import RUNTIME_DB_PATH
from app.runtime_store import runtime_store


def test_pytest_default_runtime_is_separate_from_the_live_gateway():
    expected = Path(os.environ["XIAOYI_RUNTIME_DB"])
    assert expected.name == "xiaoyi_runtime.test.db"
    assert runtime_store.path == expected
    assert expected.resolve() != RUNTIME_DB_PATH.resolve()
