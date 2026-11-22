"""Every test session runs on its own freshly generated DB in a temp folder."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture(scope="session", autouse=True)
def demo_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("data")
    config.DATA_DIR, config.DB_PATH, config.CACHE_PATH = tmp, tmp / "test.db", tmp / "answer_cache.json"
    config.USE_LLM = False  # tests never depend on Ollama
    from app.main import reset_data
    reset_data()
    yield tmp


@pytest.fixture(scope="session")
def client(demo_db):
    from app.main import app
    return TestClient(app)  # no "with": skips lifespan, the DB is already built


@pytest.fixture
def rw_conn(demo_db):
    conn = sqlite3.connect(config.DB_PATH)
    yield conn
    conn.close()
