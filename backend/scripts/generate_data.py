"""Build the demo database and inbox (Plan.md §6-7). Deterministic: same output every run.

Run from backend/:  .venv/Scripts/python scripts/generate_data.py
The reset endpoint calls generate() on the existing file instead of replacing it (Windows file locks).
"""
import hashlib
import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.ai.forecasting import avg_weekly_demand  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS divisions (id INTEGER PRIMARY KEY, name_en TEXT, name_bn TEXT);
CREATE TABLE IF NOT EXISTS distributors (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT,
  division_id INTEGER, credit_limit_bdt REAL, contact_email TEXT, lang_pref TEXT);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, sku TEXT, name TEXT, name_bn TEXT,
  category TEXT, pack TEXT, price_per_carton_bdt REAL, units_per_carton INTEGER, is_rx_restricted INTEGER);
CREATE TABLE IF NOT EXISTS sales_weekly (week_start TEXT, distributor_id INTEGER, product_id INTEGER,
  cartons INTEGER, revenue_bdt REAL);
CREATE INDEX IF NOT EXISTS ix_sales ON sales_weekly (distributor_id, product_id, week_start);
CREATE TABLE IF NOT EXISTS stock (distributor_id INTEGER, product_id INTEGER, cartons_on_hand INTEGER,
  updated_at TEXT, PRIMARY KEY (distributor_id, product_id));
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, distributor_id INTEGER, created_at TEXT,
  status TEXT, total_bdt REAL, source TEXT);
CREATE TABLE IF NOT EXISTS order_lines (order_id INTEGER, product_id INTEGER, cartons INTEGER, price_bdt REAL);
CREATE TABLE IF NOT EXISTS receivables (distributor_id INTEGER PRIMARY KEY, outstanding_bdt REAL,
  overdue_bdt REAL, last_payment_date TEXT);
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT, description TEXT, assignee TEXT,
  due_date TEXT, priority TEXT, status TEXT, source_email_id TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, email_id TEXT, "to" TEXT, subject TEXT,
  body TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS agent_runs (id INTEGER PRIMARY KEY, email_id TEXT, trace_json TEXT, created_at TEXT);
"""
TABLES = ["divisions", "distributors", "products", "sales_weekly", "stock", "orders", "order_lines",
          "receivables", "tasks", "outbox", "agent_runs"]

# code prefix, English, Bangla, demand weight, credit limit range (lakh)
DIVISIONS = [
    ("DHK", "Dhaka", "ঢাকা", 1.6, (22, 30)), ("CTG", "Chattogram", "চট্টগ্রাম", 1.3, (20, 28)),
    ("RAJ", "Rajshahi", "রাজশাহী", 0.9, (10, 18)), ("KHL", "Khulna", "খুলনা", 0.9, (10, 18)),
    ("SYL", "Sylhet", "সিলেট", 0.8, (8, 14)), ("BAR", "Barishal", "বরিশাল", 0.7, (8, 14)),
    ("RNG", "Rangpur", "রংপুর", 0.8, (8, 14)), ("MYM", "Mymensingh", "ময়মনসিংহ", 0.75, (8, 14)),
]
# Monthly multipliers, Jan..Dec.
SEASON = {
    "ors": [0.7, 0.75, 0.9, 1.2, 1.4, 1.5, 1.6, 1.5, 1.3, 1.0, 0.8, 0.7],
    "winter": [1.6, 1.3, 0.9, 0.6, 0.5, 0.5, 0.5, 0.5, 0.6, 0.9, 1.3, 1.6],
    "worldcup": [1, 1, 1, 1, 1, 1.8, 1.8, 1, 1, 1, 1, 1],
    "flat": [1] * 12,
}
# name, name_bn, category, price/carton, units/carton, rx, season, base weekly cartons per distributor
PRODUCTS = [
    ("ORSaline-N", "ওরস্যালাইন-এন", "ORS", 1250, 200, 0, "ors", 40),
    ("ORSaline-Fruity", "ওরস্যালাইন-ফ্রুটি", "ORS", 1400, 200, 0, "ors", 18),
    ("SMC Plus Electrolyte Drink", "এসএমসি প্লাস ইলেক্ট্রোলাইট ড্রিংক", "Beverage", 1800, 24, 0, "ors", 22),
    ("MoniMix Micronutrient", "মনিমিক্স মাইক্রোনিউট্রিয়েন্ট", "Nutrition", 2200, 300, 0, "flat", 10),
    ("SMC Zinc", "এসএমসি জিংক", "Nutrition", 1600, 100, 0, "ors", 14),
    ("MoniBiscuit", "মনি বিস্কুট", "Food", 900, 48, 0, "worldcup", 26),
    ("Taste Me Drink Powder", "টেস্ট মি ড্রিংক পাউডার", "Food", 1100, 48, 0, "ors", 15),
    ("SMC Honey", "এসএমসি মধু", "Food", 2500, 24, 0, "winter", 8),
    ("Joya Sanitary Napkin Regular", "জয়া স্যানিটারি ন্যাপকিন রেগুলার", "Hygiene", 2000, 48, 0, "flat", 20),
    ("Joya Ultra", "জয়া আল্ট্রা", "Hygiene", 2600, 48, 0, "flat", 12),
    ("Smile Baby Diaper M", "স্মাইল বেবি ডায়াপার এম", "Hygiene", 3200, 6, 0, "flat", 10),
    ("Smile Baby Wipes", "স্মাইল বেবি ওয়াইপস", "Hygiene", 1500, 24, 0, "flat", 9),
    ("Germ Kill Hand Wash", "জার্ম কিল হ্যান্ড ওয়াশ", "Hygiene", 1300, 24, 0, "flat", 12),
    ("Petroleum Jelly", "পেট্রোলিয়াম জেলি", "Hygiene", 800, 72, 0, "winter", 16),
    ("Femicon Oral Pill", "ফেমিকন ওরাল পিল", "Family Planning", 1700, 300, 1, "flat", 14),
    ("Noret-28", "নরেট-২৮", "Family Planning", 1650, 300, 1, "flat", 9),
    ("Panther Condom", "প্যান্থার কনডম", "Family Planning", 1200, 144, 0, "flat", 16),
    ("Forbon Calcium", "ফরবন ক্যালসিয়াম", "Pharma / OTC", 1900, 50, 0, "flat", 8),
]
STATUSES_BY_AGE = [(3, ["Placed", "Approved"]), (10, ["Approved", "Dispatched"]), (10**6, ["Delivered"])]


def week_starts(today: date) -> list[date]:
    """52 Monday buckets; the last one is the current week (it includes DEMO_TODAY)."""
    last = today - timedelta(days=today.weekday())
    return [last - timedelta(weeks=51 - i) for i in range(52)]


def v_sales_sql(today: date) -> str:
    """History spread evenly over 7 days per week, plus live orders from DEMO_TODAY on (Plan.md §6)."""
    days = " UNION ALL ".join(f"SELECT {k} AS k" for k in range(7))
    return f"""
DROP VIEW IF EXISTS v_sales;
CREATE VIEW v_sales AS
SELECT date(s.week_start, '+' || d.k || ' days') AS day, s.distributor_id, s.product_id,
       s.cartons / 7.0 AS cartons, s.revenue_bdt / 7.0 AS revenue_bdt
FROM sales_weekly s CROSS JOIN ({days}) d
UNION ALL
SELECT date(o.created_at), o.distributor_id, l.product_id, l.cartons, l.cartons * l.price_bdt
FROM orders o JOIN order_lines l ON l.order_id = o.id
WHERE o.status <> 'On hold' AND date(o.created_at) >= '{today.isoformat()}';
"""


def _series(conn, dist_id: int, prod_id: int) -> list[float]:
    rows = conn.execute("SELECT cartons FROM sales_weekly WHERE distributor_id=? AND product_id=? "
                        "ORDER BY week_start", (dist_id, prod_id)).fetchall()
    return [r[0] for r in rows]


def _growth(conn, today: date) -> dict[str, float]:
    """Revenue growth per division, same days this month vs last month."""
    start = today.replace(day=1)
    prev_start = (start - timedelta(days=1)).replace(day=1)
    prev_end = prev_start.replace(day=today.day)
    rows = conn.execute("""
        SELECT dv.name_en,
          SUM(CASE WHEN v.day BETWEEN ? AND ? THEN v.revenue_bdt END) /
          SUM(CASE WHEN v.day BETWEEN ? AND ? THEN v.revenue_bdt END) - 1
        FROM v_sales v JOIN distributors d ON d.id = v.distributor_id JOIN divisions dv ON dv.id = d.division_id
        GROUP BY dv.name_en""", (start.isoformat(), today.isoformat(), prev_start.isoformat(),
                                 prev_end.isoformat())).fetchall()
    return {r[0]: r[1] for r in rows}


def generate(conn: sqlite3.Connection, today: date = config.DEMO_TODAY) -> dict:
    """Rewrite every table inside conn. Caller owns the transaction. Returns the inbox."""
    rnd, rng = random.Random(42), np.random.default_rng(42)
    conn.executescript(SCHEMA)
    for t in TABLES:
        conn.execute(f"DELETE FROM {t}")

    # Divisions and distributors
    dist = []  # (id, code, division index)
    for i, (code, en, bn, _w, (lo, hi)) in enumerate(DIVISIONS, start=1):
        conn.execute("INSERT INTO divisions VALUES (?,?,?)", (i, en, bn))
        for n in range(1, 4):
            did = len(dist) + 1
            dcode = f"{code}-0{n}"
            limit = rnd.randint(lo, hi) * 100_000
            lang = "bn" if code in ("RNG", "SYL", "MYM", "BAR") or n == 3 else "en"
            conn.execute("INSERT INTO distributors VALUES (?,?,?,?,?,?,?)",
                         (did, dcode, f"{en} Distributor 0{n}", i, limit, f"{dcode.lower()}@example.com", lang))
            dist.append((did, dcode, i - 1))
    by_code = {c: d for d, c, _ in dist}

    for pid, (name, name_bn, cat, price, units, rx, _s, _b) in enumerate(PRODUCTS, start=1):
        conn.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                     (pid, f"SMC-{pid:03d}", name, name_bn, cat, f"{units} units/carton", price, units, rx))

    # Weekly sales: base x division weight x season x trend x noise
    weeks = week_starts(today)
    rows = []
    for did, _code, di in dist:
        weight = DIVISIONS[di][3] * rnd.uniform(0.85, 1.15)
        for pid, (_n, _nb, _c, price, _u, _rx, season, base) in enumerate(PRODUCTS, start=1):
            growth = rnd.uniform(0.08, 0.15)
            noise = rng.uniform(-0.12, 0.12, len(weeks))
            for w, ws in enumerate(weeks):
                trend = 1 + growth * (w - 51) / 52
                cartons = max(0, round(base * weight * SEASON[season][ws.month - 1] * trend * (1 + noise[w])))
                rows.append((ws.isoformat(), did, pid, cartons, cartons * price))
    conn.executemany("INSERT INTO sales_weekly VALUES (?,?,?,?,?)", rows)

    # Live orders: ~300 over the past 90 days, plus a few placed earlier today.
    oid = 1000
    for k in range(305):
        oid += 1
        if k < 300:
            created = datetime.combine(today - timedelta(days=rnd.randint(1, 90)), datetime.min.time())
        else:
            created = datetime.combine(today, datetime.min.time())
        created += timedelta(minutes=rnd.randint(8 * 60, 9 * 60 + 30) if k >= 300 else rnd.randint(8 * 60, 18 * 60))
        did = rnd.randint(1, len(dist))
        age = (today - created.date()).days
        status = rnd.choice(next(s for a, s in STATUSES_BY_AGE if age <= a))
        if rnd.random() < 0.04:
            status = "On hold"
        if oid == 1043:  # scenario 5: the agent email's order
            did, status = by_code["CTG-02"], "Dispatched"
            created = datetime.combine(today - timedelta(days=3), datetime.min.time()) + timedelta(hours=10, minutes=15)
        total = 0
        for pid in rnd.sample(range(1, len(PRODUCTS) + 1), rnd.randint(1, 4)):
            cartons, price = rnd.randint(5, 60), PRODUCTS[pid - 1][3]
            conn.execute("INSERT INTO order_lines VALUES (?,?,?,?)", (oid, pid, cartons, price))
            total += cartons * price
        conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                     (oid, did, created.isoformat(timespec="seconds"), status, total, "portal"))

    conn.executescript(v_sales_sql(today))

    # Scenario 3: Chattogram growth = +18% (same days). Scale its weeks that lie fully in this month.
    month_start = today.replace(day=1)
    ctg_ids = [d for d, _c, di in dist if di == 1]
    cur = _growth(conn, today)["Chattogram"]
    marks = ",".join("?" * len(ctg_ids))
    scaled_part = conn.execute(
        f"SELECT SUM(revenue_bdt / 7.0 * (julianday(min(date(week_start, '+6 days'), ?)) - julianday(week_start) + 1)) "
        f"FROM sales_weekly WHERE week_start >= ? AND distributor_id IN ({marks})",
        (today.isoformat(), month_start.isoformat(), *ctg_ids)).fetchone()[0]
    # Solve (nov_total - B + f*B) / oct_total = 1.18 for f, where B = scaled_part.
    prev_start = (month_start - timedelta(days=1)).replace(day=1)
    oct_total = conn.execute(
        f"SELECT SUM(revenue_bdt) FROM v_sales WHERE day BETWEEN ? AND ? AND distributor_id IN ({marks})",
        (prev_start.isoformat(), prev_start.replace(day=today.day).isoformat(), *ctg_ids)).fetchone()[0]
    nov_total = oct_total * (1 + cur)
    f = (1.18 * oct_total - nov_total + scaled_part) / scaled_part
    conn.execute(f"UPDATE sales_weekly SET cartons = ROUND(cartons * ?), revenue_bdt = ROUND(cartons * ?) * "
                 f"(revenue_bdt / MAX(cartons, 1)) WHERE week_start >= ? AND distributor_id IN ({marks})",
                 (f, f, month_start.isoformat(), *ctg_ids))

    # Stock: 3.5-8 weeks of cover, then the scripted scenarios set from the real forecast.
    stock_rows = []
    for did, _code, _di in dist:
        for pid in range(1, len(PRODUCTS) + 1):
            recent = float(np.mean(_series(conn, did, pid)[-4:]))
            stock_rows.append([did, pid, round(recent * rnd.uniform(3.5, 8.0))])
    scenario_cover = {
        ("RNG-01", "ORSaline-N"): 0.85,  # scenario 1: critical (~6 days)
        ("RNG-01", "SMC Zinc"): 1.5,  # serious
        ("RNG-01", "SMC Plus Electrolyte Drink"): 2.5,  # warning
        ("DHK-02", "MoniBiscuit"): 1.6,  # serious elsewhere
        ("KHL-01", "Joya Ultra"): 14.0,  # scenario 4: slow-moving
    }
    pid_of = {p[0]: i for i, p in enumerate(PRODUCTS, start=1)}
    for (code, pname), cover in scenario_cover.items():
        did, pid = by_code[code], pid_of[pname]
        need = avg_weekly_demand(_series(conn, did, pid))
        for row in stock_rows:
            if row[0] == did and row[1] == pid:
                row[2] = round(need * cover)
    conn.executemany("INSERT INTO stock VALUES (?,?,?,?)",
                     [(d, p, c, today.isoformat()) for d, p, c in stock_rows])

    # Receivables: 30-70% of limit; scenario 2 SYL-02 at 92%, BAR-03 at 84% (second row for the credit question).
    limits = dict(conn.execute("SELECT code, credit_limit_bdt FROM distributors").fetchall())
    special = {"SYL-02": 0.92, "BAR-03": 0.84, "RNG-01": 0.40}
    for did, code, _di in dist:
        pct = special.get(code, rnd.uniform(0.30, 0.70))
        outstanding = round(limits[code] * pct, -3)
        overdue = round(outstanding * (0.35 if code == "SYL-02" else rnd.uniform(0, 0.25)), -3)
        paid = today - timedelta(days=45 if code == "SYL-02" else rnd.randint(3, 25))
        conn.execute("INSERT INTO receivables VALUES (?,?,?,?)", (did, outstanding, overdue, paid.isoformat()))

    for t in [("Prepare monsoon ORS stock plan", "Review ORS stock cover for all divisions.", "Supply chain",
               (today + timedelta(days=5)).isoformat(), "medium", "To do", None, "user"),
              ("Follow up overdue payment: SYL-02", "Overdue balance above 30 days.", "Finance",
               (today + timedelta(days=2)).isoformat(), "high", "In progress", None, "user"),
              ("Distributor meeting Rajshahi", "Quarterly review.", "Area sales manager – Rajshahi",
               (today - timedelta(days=1)).isoformat(), "low", "Done", None, "user")]:
        conn.execute("INSERT INTO tasks (title, description, assignee, due_date, priority, status, "
                     "source_email_id, created_by) VALUES (?,?,?,?,?,?,?,?)", t)

    _check_scenarios(conn, today)
    khl_order = conn.execute("SELECT MAX(id) FROM orders WHERE distributor_id = ? AND status = 'Delivered'",
                             (by_code["KHL-02"],)).fetchone()[0]
    return _inbox(today, khl_order)


def _check_scenarios(conn: sqlite3.Connection, today: date) -> None:
    """Fail loudly if the demo story's numbers are not there."""
    g = _growth(conn, today)
    assert abs(g["Chattogram"] - 0.18) < 0.02 and max(g, key=g.get) == "Chattogram", g
    syl = conn.execute("SELECT r.outstanding_bdt / d.credit_limit_bdt FROM receivables r "
                       "JOIN distributors d ON d.id = r.distributor_id WHERE d.code = 'SYL-02'").fetchone()[0]
    assert 0.91 < syl < 0.93, syl
    assert tuple(conn.execute("SELECT d.code, o.status FROM orders o JOIN distributors d ON d.id = o.distributor_id "
                              "WHERE o.id = 1043").fetchone()) == ("CTG-02", "Dispatched")


def _inbox(today: date, khl_order: int) -> list[dict]:
    def at(days: int, hm: str) -> str:
        return f"{(today - timedelta(days=days)).isoformat()}T{hm}:00"

    return [
        {"id": "e1", "from": "ctg-02@example.com", "distributor_code": "CTG-02", "received_at": at(0, "08:12"),
         "subject": "Order #1043 status and new requirement", "lang": "en",
         "body": "Dear SMC team,\n\nWhere is my order #1043? Our shelves are getting empty.\n"
                 "Also need 50 cartons of SMC Plus as soon as possible.\n\nRegards,\nChattogram Distributor 02"},
        {"id": "e2", "from": "rng-01@example.com", "distributor_code": "RNG-01", "received_at": at(0, "07:45"),
         "subject": "ওরস্যালাইন স্টক", "lang": "bn",
         "body": "আসসালামু আলাইকুম,\n\nওরস্যালাইন-এন এর স্টক কেমন আছে? আমাদের ১২০ কার্টন লাগবে, দ্রুত পাঠাবেন।\n\n"
                 "ধন্যবাদ,\nরংপুর ডিস্ট্রিবিউটর ০১"},
        {"id": "e3", "from": "syl-02@example.com", "distributor_code": "SYL-02", "received_at": at(1, "16:30"),
         "subject": "বকেয়া ও ক্রেডিট লিমিট", "lang": "bn",
         "body": "আমাদের বর্তমান বকেয়া কত এবং ক্রেডিট লিমিট কত বাকি আছে? গত সপ্তাহে পেমেন্ট করেছি, "
                 "হিসাবটা মিলিয়ে জানাবেন।\n\nসিলেট ডিস্ট্রিবিউটর ০২"},
        {"id": "e4", "from": "khl-02@example.com", "distributor_code": "KHL-02", "received_at": at(1, "11:05"),
         "subject": f"Damaged cartons in order #{khl_order}", "lang": "en",
         "body": f"Hello,\n\n12 cartons in order #{khl_order} arrived damaged (crushed boxes, wet packs). "
                 "Please arrange replacement.\n\nKhulna Distributor 02"},
        {"id": "e5", "from": "mym-01@example.com", "distributor_code": "MYM-01", "received_at": at(2, "10:20"),
         "subject": "Price list / দামের তালিকা", "lang": "mixed",
         "body": "Assalamu alaikum,\n\nPlease send the updated price list. নতুন দামের তালিকা পাঠালে ভালো হয়।\n\n"
                 "Mymensingh Distributor 01"},
        {"id": "e6", "from": "digest@pharmaweekly.example", "distributor_code": None, "received_at": at(2, "06:00"),
         "subject": "Pharma Weekly: industry digest", "lang": "en",
         "body": "This week's industry digest: market updates, regulatory news and upcoming events. "
                 "Unsubscribe at any time."},
    ]


def checksum(conn: sqlite3.Connection) -> str:
    return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()[:16]


def main() -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        with conn:
            inbox = generate(conn)
        (config.DATA_DIR / "inbox.json").write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
        print("checksum", checksum(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
