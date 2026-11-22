"""The only way model- or rule-written SQL reaches the database (Plan.md §9.3 step 4).

Layers: SELECT/WITH only · stdlib authorizer allows reads of whitelisted tables only ·
read-only connection · row cap · 3 s time limit.
"""
import re
import sqlite3
import time

from .. import config

ALLOWED_TABLES = {"divisions", "distributors", "products", "v_sales", "orders", "order_lines", "receivables",
                  "stock", "sales_weekly"}  # sales_weekly/orders/order_lines are also read through v_sales
MAX_ROWS = 200
TIME_LIMIT_S = 3.0


class GuardError(ValueError):
    pass


def _authorizer(action, arg1, _arg2, _db, _trigger):
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in ALLOWED_TABLES else sqlite3.SQLITE_DENY
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def run_sql(sql: str) -> tuple[list[str], list[list]]:
    """Execute one guarded SELECT. Raises GuardError for policy violations, sqlite3.Error for bad SQL."""
    body = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", body):
        raise GuardError("only SELECT or WITH queries are allowed")
    conn = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        conn.set_authorizer(_authorizer)
        deadline = time.monotonic() + TIME_LIMIT_S
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        try:
            cur = conn.execute(f"SELECT * FROM ({body}) LIMIT {MAX_ROWS}")
            rows = [list(r) for r in cur.fetchall()]
        except sqlite3.DatabaseError as e:
            if "not authorized" in str(e):
                raise GuardError("query touches a table or action that is not allowed") from e
            if "interrupted" in str(e):
                raise GuardError("query took too long") from e
            raise
        return [d[0] for d in cur.description], rows
    finally:
        conn.close()
