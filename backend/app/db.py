"""SQLite connections, one per use and always closed: Windows can't rewrite a file that is open."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from . import config


@contextmanager
def rw() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commit on success, rollback on error
            yield conn
    finally:
        conn.close()


@contextmanager
def ro() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def fetch(sql: str, params: tuple | dict = ()) -> list[dict]:
    with ro() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
