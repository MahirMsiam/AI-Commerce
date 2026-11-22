"""Mock SAP objects with SAP-style field names (VBELN, KUNNR, MATNR, KLIMK...).

The agent tools call these functions directly (no HTTP to our own server); the routes show the seam.
"""
from fastapi import APIRouter, HTTPException

from ..db import fetch

router = APIRouter(prefix="/api/erp")


def find_product(material: str) -> dict | None:
    """Match by SKU, exact name, or the longest product name contained in / containing the text."""
    m = material.strip().lower()
    rows = fetch("SELECT * FROM products")
    for p in rows:
        if m in (p["sku"].lower(), p["name"].lower(), p["name_bn"]):
            return p
    hits = [p for p in rows if p["name"].lower() in m or m in p["name"].lower() or p["name_bn"] in m or m in p["name_bn"]]
    return min(hits, key=lambda p: len(p["name"])) if hits else None  # "orsaline" → ORSaline-N


def sales_order(order_id: int) -> dict | None:
    rows = fetch("""SELECT o.*, d.code, d.name AS distributor FROM orders o
                    JOIN distributors d ON d.id = o.distributor_id WHERE o.id = ?""", (order_id,))
    if not rows:
        return None
    o = rows[0]
    items = fetch("""SELECT p.sku, p.name, l.cartons, l.price_bdt FROM order_lines l
                     JOIN products p ON p.id = l.product_id WHERE l.order_id = ?""", (order_id,))
    return {
        "VBELN": f"{order_id:010d}", "KUNNR": o["code"], "ERDAT": o["created_at"][:10], "GBSTK": o["status"],
        "NETWR": o["total_bdt"], "WAERK": "BDT",
        "ITEMS": [{"POSNR": 10 * (i + 1), "MATNR": it["sku"], "ARKTX": it["name"], "KWMENG": it["cartons"],
                   "VRKME": "CAR"} for i, it in enumerate(items)],
        "friendly": {"order_id": order_id, "distributor": o["distributor"], "created": o["created_at"][:10],
                     "status": o["status"], "total_bdt": o["total_bdt"],
                     "lines": [f'{it["cartons"]} × {it["name"]}' for it in items]},
    }


def material_stock(distributor_code: str, material: str) -> dict | None:
    p = find_product(material)
    if not p:
        return None
    rows = fetch("""SELECT s.cartons_on_hand FROM stock s JOIN distributors d ON d.id = s.distributor_id
                    WHERE d.code = ? AND s.product_id = ?""", (distributor_code, p["id"]))
    if not rows:
        return None
    return {"KUNNR": distributor_code, "MATNR": p["sku"], "MAKTX": p["name"], "LABST": rows[0]["cartons_on_hand"],
            "MEINS": "CAR",
            "friendly": {"product": p["name"], "product_bn": p["name_bn"], "product_id": p["id"],
                         "cartons_on_hand": rows[0]["cartons_on_hand"], "price_per_carton_bdt": p["price_per_carton_bdt"]}}


def customer_credit(distributor_code: str) -> dict | None:
    rows = fetch("""SELECT d.code, d.name, d.credit_limit_bdt, r.outstanding_bdt, r.overdue_bdt, r.last_payment_date
                    FROM distributors d JOIN receivables r ON r.distributor_id = d.id WHERE d.code = ?""",
                 (distributor_code,))
    if not rows:
        return None
    r = rows[0]
    available = r["credit_limit_bdt"] - r["outstanding_bdt"]
    return {"KUNNR": r["code"], "KLIMK": r["credit_limit_bdt"], "SKFOR": r["outstanding_bdt"],
            "OVERDUE": r["overdue_bdt"], "AVAILABLE": available, "WAERS": "BDT",
            "friendly": {"distributor": r["name"], "credit_limit_bdt": r["credit_limit_bdt"],
                         "outstanding_bdt": r["outstanding_bdt"], "overdue_bdt": r["overdue_bdt"],
                         "available_bdt": available, "used_pct": round(100 * r["outstanding_bdt"] / r["credit_limit_bdt"]),
                         "last_payment_date": r["last_payment_date"]}}


def _or_404(obj: dict | None) -> dict:
    if obj is None:
        raise HTTPException(404, "not found")
    return obj


@router.get("/SalesOrder/{order_id}")
def get_sales_order(order_id: int) -> dict:
    return _or_404(sales_order(order_id))


@router.get("/MaterialStock")
def get_material_stock(distributor: str, material: str) -> dict:
    return _or_404(material_stock(distributor, material))


@router.get("/CustomerCredit/{code}")
def get_customer_credit(code: str) -> dict:
    return _or_404(customer_credit(code))
