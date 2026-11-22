import math

from app.ai.forecasting import forecast


def test_forecast_shape_and_values():
    f = forecast([50, 52, 48, 55, 60, 58, 62, 65, 61, 59, 63, 66, 70, 68, 72, 75, 71, 69, 73, 76, 80, 78, 82, 85, 81, 79], 8)
    assert len(f["forecast"]) == 8 and len(f["lower"]) == 8
    assert all(math.isfinite(v) and v >= 0 for v in f["forecast"] + f["lower"])


def test_falling_series_never_negative():
    f = forecast([100 - 4 * i for i in range(26)], 8)
    assert min(f["forecast"]) >= 0 and min(f["lower"]) >= 0


def test_rangpur_ors_critical(client):
    alerts = client.get("/api/alerts").json()
    crit = [a for a in alerts if a["severity"] == "critical"]
    assert crit[0]["distributor_code"] == "RNG-01" and crit[0]["product"] == "ORSaline-N"
    assert any(a["severity"] == "slow-moving" and a["distributor_code"] == "KHL-01" for a in alerts)


def test_suggested_order_rangpur(client):
    lines = client.get("/api/distributors/19/suggested-order").json()["lines"]
    assert lines[0]["product"] == "ORSaline-N" and lines[0]["cartons"] > 0


def _id(client, code):
    return next(d["id"] for d in client.get("/api/distributors").json() if d["code"] == code)


def test_sylhet_credit_warning_then_on_hold(client):
    did = _id(client, "SYL-02")
    body = {"distributor_id": did, "lines": [{"product_id": 1, "cartons": 100}]}
    r = client.post("/api/orders", json=body).json()
    assert r["credit_warning"]["over_by_bdt"] > 0
    r = client.post("/api/orders", json={**body, "submit_on_hold": True}).json()
    assert r["order"]["status"] == "On hold"


def test_order_updates_dashboard(client):
    """Freshness: a placed order raises orders today and revenue MTD by its total."""
    before = client.get("/api/dashboard/kpis").json()
    r = client.post("/api/orders", json={"distributor_id": _id(client, "RNG-01"),
                                         "lines": [{"product_id": 1, "cartons": 10}]}).json()
    assert r["order"]["status"] == "Placed"
    after = client.get("/api/dashboard/kpis").json()
    assert after["orders_today"] == before["orders_today"] + 1
    assert round(after["revenue_mtd_bdt"] - before["revenue_mtd_bdt"]) == r["order"]["total_bdt"]


def test_order_validation(client):
    assert client.post("/api/orders", json={"distributor_id": 1, "lines": []}).status_code == 422
    assert client.post("/api/orders", json={"distributor_id": 1, "lines": [{"product_id": 1, "cartons": -5}]}).status_code == 422
    assert client.post("/api/orders", json={"distributor_id": 1, "lines": [{"product_id": 999, "cartons": 5}]}).status_code == 422


def test_erp_mock(client):
    so = client.get("/api/erp/SalesOrder/1043").json()
    assert so["VBELN"] == "0000001043" and so["KUNNR"] == "CTG-02" and so["GBSTK"] == "Dispatched"
    assert client.get("/api/erp/MaterialStock", params={"distributor": "CTG-02", "material": "SMC Plus"}).json()["MAKTX"] == "SMC Plus Electrolyte Drink"
    assert client.get("/api/erp/CustomerCredit/SYL-02").json()["friendly"]["used_pct"] == 92
