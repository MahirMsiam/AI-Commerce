"""Management dashboard. All revenue comes from v_sales (Plan.md §6)."""
from datetime import timedelta

from fastapi import APIRouter, Query

from ..config import DEMO_TODAY
from ..db import fetch
from ..periods import last_n_weeks, period_range

router = APIRouter(prefix="/api/dashboard")
Period = Query("mtd", pattern="^(mtd|last_month|this_week|last_week|last_3_months)$")


def _revenue(start, end) -> float:
    return fetch("SELECT COALESCE(SUM(revenue_bdt), 0) AS r FROM v_sales WHERE day BETWEEN ? AND ?",
                 (start.isoformat(), end.isoformat()))[0]["r"]


@router.get("/kpis")
def kpis() -> dict:
    mtd = _revenue(*period_range("mtd"))
    prev = _revenue(*period_range("prev_same_days"))
    today = DEMO_TODAY.isoformat()
    rec = fetch("SELECT SUM(outstanding_bdt) AS o, SUM(overdue_bdt) AS od FROM receivables")[0]
    return {
        "revenue_mtd_bdt": mtd,
        "vs_last_month_pct": round(100 * (mtd / prev - 1), 1) if prev else None,
        "orders_today": fetch("SELECT COUNT(*) AS n FROM orders WHERE date(created_at) = ?", (today,))[0]["n"],
        "active_distributors": fetch("SELECT COUNT(DISTINCT distributor_id) AS n FROM orders WHERE date(created_at) > ?",
                                     ((DEMO_TODAY - timedelta(days=30)).isoformat(),))[0]["n"],
        "receivables_bdt": rec["o"],
        "overdue_bdt": rec["od"],
    }


@router.get("/revenue-trend")
def revenue_trend(weeks: int = Query(26, ge=1, le=52)) -> list[dict]:
    start, end = last_n_weeks(weeks)
    return fetch("""SELECT date(day, '-6 days', 'weekday 1') AS week, ROUND(SUM(revenue_bdt)) AS revenue_bdt
                    FROM v_sales WHERE day BETWEEN ? AND ? GROUP BY week ORDER BY week""",
                 (start.isoformat(), end.isoformat()))


@router.get("/by-division")
def by_division(period: str = Period) -> list[dict]:
    start, end = period_range(period)
    return fetch("""SELECT dv.name_en AS division, dv.name_bn AS division_bn, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt
                    FROM v_sales v JOIN distributors d ON d.id = v.distributor_id
                    JOIN divisions dv ON dv.id = d.division_id
                    WHERE v.day BETWEEN ? AND ? GROUP BY dv.id ORDER BY revenue_bdt DESC""",
                 (start.isoformat(), end.isoformat()))


@router.get("/top-products")
def top_products(period: str = Period, limit: int = Query(5, ge=1, le=18)) -> list[dict]:
    start, end = period_range(period)
    return fetch("""SELECT p.name AS product, p.name_bn AS product_bn, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt,
                           ROUND(SUM(v.cartons)) AS cartons
                    FROM v_sales v JOIN products p ON p.id = v.product_id
                    WHERE v.day BETWEEN ? AND ? GROUP BY p.id ORDER BY revenue_bdt DESC LIMIT ?""",
                 (start.isoformat(), end.isoformat(), limit))


@router.get("/receivables")
def receivables() -> list[dict]:
    return fetch("""SELECT d.code, d.name, dv.name_en AS division, d.credit_limit_bdt, r.outstanding_bdt, r.overdue_bdt,
                           ROUND(100.0 * r.outstanding_bdt / d.credit_limit_bdt, 1) AS pct_of_limit, r.last_payment_date
                    FROM receivables r JOIN distributors d ON d.id = r.distributor_id
                    JOIN divisions dv ON dv.id = d.division_id ORDER BY pct_of_limit DESC""")
