"""Distributors and product catalogue."""
from fastapi import APIRouter

from ..db import fetch

router = APIRouter(prefix="/api")


@router.get("/distributors")
def distributors() -> list[dict]:
    return fetch("""SELECT d.id, d.code, d.name, d.lang_pref, d.credit_limit_bdt, d.division_id,
                           dv.name_en AS division, dv.name_bn AS division_bn
                    FROM distributors d JOIN divisions dv ON dv.id = d.division_id ORDER BY d.id""")


@router.get("/products")
def products(distributor_id: int | None = None) -> list[dict]:
    return fetch("""SELECT p.*, s.cartons_on_hand FROM products p
                    LEFT JOIN stock s ON s.product_id = p.id AND s.distributor_id = ?
                    ORDER BY p.category, p.name""", (distributor_id,))
