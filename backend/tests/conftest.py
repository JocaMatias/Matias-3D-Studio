import os
import shutil
import tempfile
from pathlib import Path


# These variables must be set before any test imports app.config/app.database.
# The test suite must never migrate the user's studio.db or write into the real
# project storage directory.
TEST_ROOT = Path(tempfile.mkdtemp(prefix="matias3d-tests-"))
TEST_DATABASE = TEST_ROOT / "studio-test.db"
TEST_STORAGE = TEST_ROOT / "storage"

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE.as_posix()}"
os.environ["STORAGE_ROOT"] = str(TEST_STORAGE)
os.environ["QUEUE_MODE"] = "inline"
os.environ["RECONSTRUCTION_MODE"] = "mock"
os.environ["MOCK_STAGE_SECONDS"] = "0"


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
