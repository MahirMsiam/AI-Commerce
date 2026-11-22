"""Cart → order with credit check (Plan.md §8)."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..config import DEMO_TODAY

router = APIRouter(prefix="/api")


class Line(BaseModel):
    product_id: int
    cartons: int = Field(gt=0, le=10_000)


class OrderIn(BaseModel):
    distributor_id: int
    lines: list[Line] = Field(min_length=1, max_length=50)
    submit_on_hold: bool = False  # user accepted the credit warning
    source: Literal["portal", "ai_suggested"] = "portal"


def demo_now() -> str:
    """DEMO_TODAY plus the real time of day (Plan.md §11 rule 5)."""
    return datetime.combine(DEMO_TODAY, datetime.now().time()).isoformat(timespec="seconds")


def insert_order(conn, distributor_id: int, lines: list[tuple[int, int]], status: str, source: str) -> dict:
    prices = dict(conn.execute("SELECT id, price_per_carton_bdt FROM products").fetchall())
    unknown = [pid for pid, _ in lines if pid not in prices]
    if unknown:
        raise HTTPException(422, f"unknown product ids {unknown}")
    total = sum(prices[pid] * c for pid, c in lines)
    cur = conn.execute("INSERT INTO orders (distributor_id, created_at, status, total_bdt, source) VALUES (?,?,?,?,?)",
                       (distributor_id, demo_now(), status, total, source))
    conn.executemany("INSERT INTO order_lines VALUES (?,?,?,?)",
                     [(cur.lastrowid, pid, c, prices[pid]) for pid, c in lines])
    return {"id": cur.lastrowid, "status": status, "total_bdt": total}


@router.post("/orders")
def place_order(body: OrderIn) -> dict:
    lines = [(l.product_id, l.cartons) for l in body.lines]
    with db.rw() as conn:
        credit = conn.execute("""SELECT d.credit_limit_bdt, r.outstanding_bdt, r.overdue_bdt FROM distributors d
                                 JOIN receivables r ON r.distributor_id = d.id WHERE d.id = ?""",
                              (body.distributor_id,)).fetchone()
        if credit is None:
            raise HTTPException(404, "unknown distributor")
        prices = dict(conn.execute("SELECT id, price_per_carton_bdt FROM products").fetchall())
        total = sum(prices.get(pid, 0) * c for pid, c in lines)
        projected = credit["outstanding_bdt"] + total
        over = projected > credit["credit_limit_bdt"]
        if over and not body.submit_on_hold:
            return {"credit_warning": {
                "credit_limit_bdt": credit["credit_limit_bdt"], "outstanding_bdt": credit["outstanding_bdt"],
                "overdue_bdt": credit["overdue_bdt"], "order_total_bdt": total, "projected_bdt": projected,
                "over_by_bdt": projected - credit["credit_limit_bdt"]}}
        order = insert_order(conn, body.distributor_id, lines, "On hold" if over else "Placed", body.source)
    return {"order": order}


@router.get("/orders")
def list_orders(distributor_id: int | None = None, limit: int = 50) -> list[dict]:
    return db.fetch("""SELECT o.id, o.created_at, o.status, o.total_bdt, o.source, d.code, d.name AS distributor,
                              (SELECT COUNT(*) FROM order_lines l WHERE l.order_id = o.id) AS lines
                       FROM orders o JOIN distributors d ON d.id = o.distributor_id
                       WHERE ? IS NULL OR o.distributor_id = ?
                       ORDER BY o.created_at DESC LIMIT ?""", (distributor_id, distributor_id, min(limit, 500)))
