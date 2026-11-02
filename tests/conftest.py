"""A test process must never recover or mutate the user's live control-plane DB."""

import atexit
import os
from pathlib import Path
import tempfile

_test_runtime_directory = tempfile.TemporaryDirectory(prefix="xiaoyi-pytest-runtime-")
_test_runtime_database = Path(_test_runtime_directory.name) / "xiaoyi_runtime.test.db"
# Set before importing any app module: linked/Harness startup recovery scans this DB.
# Even a shell pointing at a live DB is deliberately overridden for test execution.
os.environ["XIAOYI_RUNTIME_DB"] = str(_test_runtime_database)
atexit.register(_test_runtime_directory.cleanup)
