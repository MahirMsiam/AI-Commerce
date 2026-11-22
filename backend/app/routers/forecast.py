"""Forecasts, alerts and the AI suggested order (Plan.md §9.1-9.2).

History never changes during the demo, so series and alerts are computed once and cleared on reset.
"""
import threading
from datetime import date, timedelta
from functools import cache

from fastapi import APIRouter, HTTPException, Query

from ..ai.forecasting import HISTORY_WEEKS, avg_weekly_demand, forecast, severity, suggested_cartons
from ..db import fetch

router = APIRouter(prefix="/api")
SEVERITY_RANK = {"critical": 0, "serious": 1, "warning": 2, "slow-moving": 3}


@cache
def _series() -> dict[tuple[int, int], list[float]]:
    out: dict[tuple[int, int], list[float]] = {}
    for r in fetch("SELECT distributor_id, product_id, cartons FROM sales_weekly ORDER BY week_start"):
        out.setdefault((r["distributor_id"], r["product_id"]), []).append(r["cartons"])
    return out


@cache
def _weeks() -> list[str]:
    return [r["week_start"] for r in fetch("SELECT DISTINCT week_start FROM sales_weekly ORDER BY week_start")]


def series_for(product_id: int, distributor_ids: list[int]) -> list[float]:
    parts = [_series()[(d, product_id)] for d in distributor_ids if (d, product_id) in _series()]
    return [sum(v) for v in zip(*parts)] if parts else []


@cache
def compute_alerts() -> tuple[dict, ...]:
    dists = {d["id"]: d for d in fetch("""SELECT d.id, d.code, d.name, d.division_id, dv.name_en AS division,
                                                 dv.name_bn AS division_bn
                                          FROM distributors d JOIN divisions dv ON dv.id = d.division_id""")}
    prods = {p["id"]: p for p in fetch("SELECT id, name, name_bn FROM products")}
    alerts = []
    for s in fetch("SELECT distributor_id, product_id, cartons_on_hand FROM stock"):
        d, p = dists[s["distributor_id"]], prods[s["product_id"]]
        demand = avg_weekly_demand(_series()[(d["id"], p["id"])])
        cover = s["cartons_on_hand"] / demand if demand > 0 else float("inf")
        sev = severity(cover)
        if not sev:
            continue
        if sev == "slow-moving":
            msg = (f"{p['name']}: slow-moving stock at {d['name']} ({d['code']}). "
                   f"{s['cartons_on_hand']} cartons is about {cover:.0f} weeks of demand.")
        else:
            msg = (f"{p['name']}: stock-out risk in {d['division']} ({d['code']}) in about {round(cover * 7)} days. "
                   f"Stock {s['cartons_on_hand']} cartons, forecast {demand:.0f}/week.")
        alerts.append({"type": "stock", "severity": sev, "product_id": p["id"], "product": p["name"],
                       "product_bn": p["name_bn"], "distributor_id": d["id"], "distributor_code": d["code"],
                       "division": d["division"], "division_bn": d["division_bn"], "division_id": d["division_id"],
                       "stock": s["cartons_on_hand"], "weekly_demand": round(demand, 1),
                       "cover_weeks": round(cover, 2), "days_of_cover": round(cover * 7), "message": msg})
    for r in fetch("""SELECT d.id, d.code, d.name, r.outstanding_bdt, r.overdue_bdt, d.credit_limit_bdt
                      FROM receivables r JOIN distributors d ON d.id = r.distributor_id
                      WHERE r.outstanding_bdt >= 0.8 * d.credit_limit_bdt"""):
        pct = 100 * r["outstanding_bdt"] / r["credit_limit_bdt"]
        alerts.append({"type": "credit", "severity": "serious" if pct >= 90 else "warning", "distributor_id": r["id"],
                       "distributor_code": r["code"], "used_pct": round(pct),
                       "message": f"{r['name']} ({r['code']}) has used {pct:.0f}% of its credit limit; "
                                  f"overdue ৳ {r['overdue_bdt'] / 1e5:.1f} lakh."})
    alerts.sort(key=lambda a: (SEVERITY_RANK[a["severity"]], a.get("cover_weeks", 0)))
    return tuple(alerts)


def clear_caches() -> None:
    for f in (_series, _weeks, compute_alerts):
        f.cache_clear()


def warm_caches() -> None:
    """Fit all 432 series in the background so the first dashboard load is instant."""
    threading.Thread(target=compute_alerts, daemon=True).start()


def forecast_payload(product_id: int, distributor_ids: list[int], weeks: int, scope: str) -> dict:
    y = series_for(product_id, distributor_ids)
    if not y:
        raise HTTPException(404, "no history")
    f = forecast(y, weeks)
    hist_weeks = _weeks()[-HISTORY_WEEKS:]
    last = date.fromisoformat(hist_weeks[-1])
    future = [(last + timedelta(weeks=i + 1)).isoformat() for i in range(weeks)]
    product = fetch("SELECT name, name_bn FROM products WHERE id = ?", (product_id,))[0]
    return {
        "product": product["name"], "product_bn": product["name_bn"], "scope": scope,
        "actual": [{"week": w, "cartons": c} for w, c in zip(hist_weeks, y[-HISTORY_WEEKS:])],
        "forecast": [{"week": w, "forecast": v, "lower": lo, "upper": hi}
                     for w, v, lo, hi in zip(future, f["forecast"], f["lower"], f["upper"])],
        "total_forecast": round(sum(f["forecast"])),
    }


@router.get("/alerts")
def alerts() -> list[dict]:
    return list(compute_alerts())


@router.get("/forecast")
def get_forecast(product_id: int, distributor_id: int | None = None, division_id: int | None = None,
                 weeks: int = Query(8, ge=1, le=26)) -> dict:
    if distributor_id:
        d = fetch("SELECT id, code FROM distributors WHERE id = ?", (distributor_id,))
        if not d:
            raise HTTPException(404, "unknown distributor")
        return forecast_payload(product_id, [distributor_id], weeks, d[0]["code"])
    where, params = ("WHERE d.division_id = ?", (division_id,)) if division_id else ("", ())
    rows = fetch(f"SELECT d.id, dv.name_en FROM distributors d JOIN divisions dv ON dv.id = d.division_id {where}",
                 params)
    return forecast_payload(product_id, [r["id"] for r in rows], weeks, rows[0]["name_en"] if division_id else "All")


@router.get("/distributors/{distributor_id}/suggested-order")
def suggested_order(distributor_id: int) -> dict:
    lines = []
    for r in fetch("""SELECT p.id, p.name, p.name_bn, p.price_per_carton_bdt, s.cartons_on_hand FROM products p
                      JOIN stock s ON s.product_id = p.id WHERE s.distributor_id = ?""", (distributor_id,)):
        y = _series().get((distributor_id, r["id"]))
        if not y:
            continue
        s = suggested_cartons(y, r["cartons_on_hand"])
        if s["cartons"] < 1:
            continue
        lines.append({"product_id": r["id"], "product": r["name"], "product_bn": r["name_bn"],
                      "price_per_carton_bdt": r["price_per_carton_bdt"], **s,
                      "reason": f"Forecast {s['forecast_2w']} cartons for next 2 weeks; you have {s['stock']}; "
                                f"safety buffer {s['safety']} → order {s['cartons']}."})
    lines.sort(key=lambda l: -l["cartons"] * l["price_per_carton_bdt"])
    return {"distributor_id": distributor_id, "lines": lines}
