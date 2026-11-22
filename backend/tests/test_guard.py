import pytest

from app.ai.sql_guard import GuardError, run_sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "UPDATE orders SET status='x'",
    "DROP TABLE orders",
    "SELECT 1; DROP TABLE orders",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA table_info(orders)",
    "SELECT * FROM tasks",
    "SELECT * FROM outbox",
    "SELECT name FROM sqlite_master",
    "WITH x AS (SELECT 1) DELETE FROM orders",
])
def test_rejects(sql):
    with pytest.raises(Exception):
        run_sql(sql)


def test_allows_columns_named_like_keywords():
    """Plain keyword search would reject these (UPDATE in updated_at, CREATE in created_at)."""
    cols, rows = run_sql("SELECT COUNT(*) AS n FROM orders WHERE date(created_at) = '2026-11-22'")
    assert rows[0][0] >= 5
    run_sql("SELECT updated_at FROM stock LIMIT 1")


def test_row_cap():
    _, rows = run_sql("SELECT * FROM sales_weekly")
    assert len(rows) == 200


def test_runaway_query_is_stopped():
    with pytest.raises(GuardError, match="too long"):
        run_sql("SELECT COUNT(*) FROM sales_weekly a, sales_weekly b, sales_weekly c")
