"""Rule-based EN/BN question parser → SQL templates → template answer (Plan.md §9.3 step 6-7).

Works with no LLM at all. Every SQL it writes runs through sql_guard, and only values from
whitelists (names from the DB, dates, integers) are put into it, never user text.
"""
import re
from datetime import date, timedelta

from ..config import DEMO_TODAY
from ..db import fetch
from ..periods import last_n_weeks, month_start, period_range
from .lang import bn_digits, is_bangla, normalize
from .sql_guard import run_sql

KW = {
    "revenue": ["revenue", "sales", "sale", "income", "বিক্রি", "বিক্রয়", "আয়"],
    "cartons": ["carton", "volume", "quantity", "units", "কার্টন", "পরিমাণ"],
    "orders": ["order", "অর্ডার"],
    "g_division": ["division", "region", "অঞ্চল", "বিভাগ"],
    "g_product": ["product", "item", "sku", "পণ্য"],
    "g_category": ["category", "categories", "ক্যাটাগরি", "শ্রেণি"],
    "g_distributor": ["distributor", "ডিস্ট্রিবিউটর"],
    "g_week": ["weekly", "per week", "by week", "সাপ্তাহিক"],
    "g_month": ["monthly", "by month", "per month", "মাসিক"],
    "highest": ["highest", "most", "best", "largest", "maximum", "biggest", "সবচেয়ে বেশি", "সর্বোচ্চ"],
    "lowest": ["lowest", "least", "worst", "minimum", "smallest", "সবচেয়ে কম", "সর্বনিম্ন"],
    "compare": ["compare", "comparison", "growth", " vs", "versus", "grew", "তুলনা", "প্রবৃদ্ধি"],
    "forecast": ["forecast", "predict", "projection", "next ", "upcoming", "আগামী", "পূর্বাভাস"],
    "stockout": ["stock-out", "stock out", "stockout", "out of stock", "low stock", "run out", "running out",
                 "স্টক শেষ", "কম স্টক", "স্টক-আউট", "স্টক আউট"],
    "credit": ["receivable", "credit", "owe", "outstanding", "overdue", "dues", "বকেয়া", "ক্রেডিট", "পাওনা"],
    "trend": ["trend", "প্রবণতা"],
    "count": ["how many", "number of", "count", "কতটি", "কয়টি", "কতগুলো", "কত অর্ডার"],
}
# Short words that must match as whole words (e.g. "ors" inside "distributors").
CATEGORIES = {"ors": "ORS", "beverage": "Beverage", "nutrition": "Nutrition", "food": "Food", "hygiene": "Hygiene",
              "family planning": "Family Planning", "pharma": "Pharma / OTC"}
DIVISION_ALIASES = {"chittagong": "Chattogram", "barisal": "Barishal", "jessore": "Khulna"}
PRODUCT_ALIASES = {
    "orsaline": "ORSaline-N", "ওরস্যালাইন": "ORSaline-N", "ors-n": "ORSaline-N", "smc plus": "SMC Plus Electrolyte Drink",
    "এসএমসি প্লাস": "SMC Plus Electrolyte Drink", "zinc": "SMC Zinc", "জিংক": "SMC Zinc", "biscuit": "MoniBiscuit",
    "বিস্কুট": "MoniBiscuit", "honey": "SMC Honey", "মধু": "SMC Honey", "diaper": "Smile Baby Diaper M",
    "ডায়াপার": "Smile Baby Diaper M", "wipes": "Smile Baby Wipes", "hand wash": "Germ Kill Hand Wash",
    "jelly": "Petroleum Jelly", "জেলি": "Petroleum Jelly", "condom": "Panther Condom", "femicon": "Femicon Oral Pill",
    "noret": "Noret-28", "forbon": "Forbon Calcium", "monimix": "MoniMix Micronutrient", "taste me": "Taste Me Drink Powder",
    "joya": "Joya Sanitary Napkin Regular", "জয়া": "Joya Sanitary Napkin Regular",
}
SUGGESTIONS = {
    "en": ["Top 5 products by revenue in Chattogram last month", "Which division had the highest sales this month?",
           "Which distributors are above 80% of their credit limit?", "Forecast ORSaline-N demand in Rangpur for the next 4 weeks"],
    "bn": ["গত মাসে কোন অঞ্চলে বিক্রি সবচেয়ে বেশি?", "চট্টগ্রামে শীর্ষ ৫টি পণ্য কোনগুলো?",
           "কোন ডিস্ট্রিবিউটরদের বকেয়া সবচেয়ে বেশি?", "আগামী ৪ সপ্তাহে রংপুরে ওরস্যালাইনের চাহিদা কত হবে?"],
}
for _k, _v in list(KW.items()):  # NFC on the dictionary too, so both sides compare the same code points
    KW[_k] = [normalize(w).lower() for w in _v]
PRODUCT_ALIASES = {normalize(k).lower(): v for k, v in PRODUCT_ALIASES.items()}

FROM_SALES = """FROM v_sales v
JOIN distributors d ON d.id = v.distributor_id
JOIN divisions dv ON dv.id = d.division_id
JOIN products p ON p.id = v.product_id"""
GROUPS = {  # key → (select expression, column name)
    "division": ("dv.name_en", "division"), "product": ("p.name", "product"), "category": ("p.category", "category"),
    "distributor": ("d.code || ' ' || d.name", "distributor"),
    "week": ("date(v.day, '-6 days', 'weekday 1')", "week"), "month": ("strftime('%Y-%m', v.day)", "month"),
}
GROUP_BN = {"division": "বিভাগ", "product": "পণ্য", "category": "ক্যাটাগরি", "distributor": "ডিস্ট্রিবিউটর"}
METRIC_BN = {"revenue_bdt": "বিক্রি", "cartons": "কার্টন বিক্রি", "orders": "অর্ডার"}
METRIC_EN = {"revenue_bdt": "revenue", "cartons": "cartons sold", "orders": "orders"}


# ---------- formatting ----------

def money(n: float, lang: str) -> str:
    a = abs(n or 0)
    if a >= 1e7:
        s, unit = f"{n / 1e7:.2f}", ("crore", "কোটি")
    elif a >= 1e5:
        s, unit = f"{n / 1e5:.1f}", ("lakh", "লাখ")
    else:
        return f"৳ {bn_digits(f'{n:,.0f}') if lang == 'bn' else f'{n:,.0f}'}"
    return f"৳ {bn_digits(s)} {unit[1]}" if lang == "bn" else f"৳ {s} {unit[0]}"


def number(n: float, lang: str) -> str:
    s = f"{n:,.0f}"
    return bn_digits(s) if lang == "bn" else s


def fmt_value(col: str, v: float, lang: str) -> str:
    return money(v, lang) if col.endswith("bdt") else number(v, lang)


# ---------- parsing ----------

def has(q: str, key: str) -> bool:
    return any(w in q for w in KW[key])


def _names() -> tuple[list[dict], list[dict]]:
    return (fetch("SELECT id, name_en, name_bn FROM divisions"),
            fetch("SELECT id, name, name_bn, category FROM products"))


def find_division(q: str, divisions: list[dict]) -> dict | None:
    for d in divisions:
        if d["name_en"].lower() in q or normalize(d["name_bn"]) in q:
            return d
    for alias, name in DIVISION_ALIASES.items():
        if alias in q:
            return next(d for d in divisions if d["name_en"] == name)
    return None


def find_product(q: str, products: list[dict]) -> dict | None:
    full = sorted(products, key=lambda p: -len(p["name"]))
    for p in full:
        if p["name"].lower() in q or normalize(p["name_bn"]) in q:
            return p
    for alias in sorted(PRODUCT_ALIASES, key=len, reverse=True):
        if alias in q:
            return next(p for p in products if p["name"] == PRODUCT_ALIASES[alias])
    return None


def find_category(q: str) -> str | None:
    for word, cat in CATEGORIES.items():
        if re.search(rf"\b{word}\b", q):
            return cat
    return None


def find_period(q: str) -> tuple[date, date, str, str]:
    """(start, end, english label, bangla label). Default: this month."""
    if m := re.search(r"(?:last|past|গত)\s*(\d+)\s*(?:weeks?|সপ্তাহ)", q):
        n = int(m.group(1))
        return *last_n_weeks(n), f"in the last {n} weeks", f"গত {bn_digits(str(n))} সপ্তাহে"
    if m := re.search(r"(?:last|past|গত)\s*(\d+)\s*(?:months?|মাস)", q):
        n, start = int(m.group(1)), month_start(DEMO_TODAY)
        for _ in range(n - 1):
            start = month_start(start - timedelta(days=1))
        return start, DEMO_TODAY, f"in the last {n} months", f"গত {bn_digits(str(n))} মাসে"
    table = [
        (["today", "আজ"], "today", "today", "আজ"),
        (["this week", "এই সপ্তাহ"], "this_week", "this week", "এই সপ্তাহে"),
        (["last week", "previous week", "গত সপ্তাহ"], "last_week", "last week", "গত সপ্তাহে"),
        (["last month", "previous month", "গত মাস"], "last_month", "last month", "গত মাসে"),
        (["this month", "month to date", "mtd", "এই মাস", "এ মাস"], "mtd", "this month", "এই মাসে"),
    ]
    for words, key, en, bn in table:
        if any(w in q for w in words):
            return *period_range(key), en, bn
    return *period_range("mtd"), "this month", "এই মাসে"


def find_group(q: str) -> str | None:
    for g in ("week", "month", "category", "distributor", "product", "division"):
        if has(q, f"g_{g}"):
            return g
    return None


def find_top_n(q: str) -> int | None:
    m = re.search(r"(?:top|শীর্ষ)\s*(\d+)", q) or re.search(r"(\d+)\s*(?:টি|best|top)", q)
    return int(m.group(1)) if m else None


# ---------- intents ----------

def _resp(text: str, sql: str, columns: list[str], rows: list[list], chart: dict, lang: str, **extra) -> dict:
    return {"answer_text": text, "sql": sql.strip(), "columns": columns, "rows": rows, "chart": chart,
            "engine": "rules", "lang": lang, **extra}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def intent_forecast(q: str, lang: str, divisions, products) -> dict | None:
    from ..routers.forecast import forecast_payload  # late import: router imports ai modules

    product = find_product(q, products)
    if not product:
        return None
    div = find_division(q, divisions)
    m = re.search(r"(\d+)\s*(?:weeks?|সপ্তাহ)", q)
    weeks = min(int(m.group(1)), 26) if m else 4
    where = f"WHERE d.division_id = {div['id']}" if div else ""
    dist_ids = [r["id"] for r in fetch(f"SELECT d.id FROM distributors d {where}")]
    f = forecast_payload(product["id"], dist_ids, weeks, div["name_en"] if div else "All")
    total = f["total_forecast"]
    sql = f"""-- History fed to the forecast (damped Holt, forecasting.py); the forecast itself is computed in Python.
SELECT s.week_start, SUM(s.cartons) AS cartons
FROM sales_weekly s JOIN distributors d ON d.id = s.distributor_id
WHERE s.product_id = {product['id']}{f' AND d.division_id = {div["id"]}' if div else ''}
GROUP BY s.week_start ORDER BY s.week_start DESC LIMIT 26"""
    if lang == "bn":
        place = f"{div['name_bn']}-এ " if div else ""
        text = (f"আগামী {bn_digits(str(weeks))} সপ্তাহে {place}{product['name_bn']}-এর পূর্বাভাসিত চাহিদা প্রায় "
                f"{number(total, 'bn')} কার্টন (সপ্তাহে গড়ে {number(total / weeks, 'bn')})।")
    else:
        place = f" in {div['name_en']}" if div else ""
        text = (f"Forecast for {product['name']}{place}: about {total:,} cartons over the next {weeks} weeks "
                f"({total / weeks:,.0f} per week).")
    rows = [[r["week"], r["forecast"], r["lower"], r["upper"]] for r in f["forecast"]]
    return _resp(text, sql, ["week", "forecast_cartons", "low_80", "high_80"], rows,
                 {"type": "forecast", "x": "week", "y": "forecast_cartons"}, lang, forecast=f)


def intent_stockout(q: str, lang: str, divisions, products) -> dict:
    from ..routers.forecast import compute_alerts

    div, product = find_division(q, divisions), find_product(q, products)
    alerts = [a for a in compute_alerts() if a["type"] == "stock" and a["severity"] in ("critical", "serious", "warning")
              and (not div or a["division_id"] == div["id"]) and (not product or a["product_id"] == product["id"])]
    sql = """-- Stock on hand vs damped-Holt demand forecast (forecasting.py); weeks of cover < 3 is flagged.
SELECT d.code, p.name, s.cartons_on_hand
FROM stock s JOIN distributors d ON d.id = s.distributor_id JOIN products p ON p.id = s.product_id"""
    rows = [[a["product"], a["distributor_code"], a["division"], a["stock"], a["weekly_demand"], a["days_of_cover"],
             a["severity"]] for a in alerts]
    cols = ["product", "distributor", "division", "stock_cartons", "weekly_demand", "days_of_cover", "severity"]
    if not alerts:
        text = "কোনো পণ্যে এখন স্টক শেষ হওয়ার ঝুঁকি নেই।" if lang == "bn" else "No products are at risk of stock-out right now."
    elif lang == "bn":
        a = alerts[0]
        text = (f"{bn_digits(str(len(alerts)))}টি ক্ষেত্রে স্টক শেষ হওয়ার ঝুঁকি আছে। সবচেয়ে জরুরি: {a['product_bn']}, "
                f"{a['division_bn']} ({a['distributor_code']}) — প্রায় {bn_digits(str(a['days_of_cover']))} দিনের স্টক।")
    else:
        a = alerts[0]
        text = (f"{len(alerts)} product/distributor pairs are at risk of stock-out. Most urgent: {a['product']} at "
                f"{a['distributor_code']} ({a['division']}), about {a['days_of_cover']} days of stock left.")
    return _resp(text, sql, cols, rows, {"type": "table", "x": "product", "y": "days_of_cover"}, lang)


def intent_credit(q: str, lang: str, divisions) -> dict:
    div = find_division(q, divisions)
    m = re.search(r"(\d+)\s*%", q)
    where = [f"dv.id = {div['id']}"] if div else []
    if m:
        where.append(f"r.outstanding_bdt >= {int(m.group(1)) / 100} * d.credit_limit_bdt")
    sql = f"""SELECT d.code, d.name AS distributor, dv.name_en AS division, r.outstanding_bdt, r.overdue_bdt,
       ROUND(100.0 * r.outstanding_bdt / d.credit_limit_bdt, 1) AS pct_of_limit
FROM receivables r
JOIN distributors d ON d.id = r.distributor_id
JOIN divisions dv ON dv.id = d.division_id
{('WHERE ' + ' AND '.join(where)) if where else ''}
ORDER BY {'pct_of_limit' if m else 'r.outstanding_bdt'} DESC
LIMIT {find_top_n(q) or (50 if m else 5)}"""
    cols, rows = run_sql(sql)
    if not rows:
        text = "কোনো ডিস্ট্রিবিউটর পাওয়া যায়নি।" if lang == "bn" else "No distributors match."
    elif m:
        p, lst = int(m.group(1)), ", ".join(f"{r[0]} ({r[5]:.0f}%)" for r in rows)
        text = (f"{bn_digits(str(len(rows)))}টি ডিস্ট্রিবিউটর ক্রেডিট লিমিটের {bn_digits(str(p))}%-এর বেশি ব্যবহার করছে: {lst}।"
                if lang == "bn" else f"{len(rows)} distributor(s) are above {p}% of their credit limit: {lst}.")
    else:
        r = rows[0]
        text = (f"সবচেয়ে বেশি বকেয়া {r[1]} ({r[0]})-এর: {money(r[3], 'bn')} (মেয়াদোত্তীর্ণ {money(r[4], 'bn')})।"
                if lang == "bn" else f"{r[1]} ({r[0]}) owes the most: {money(r[3], 'en')} outstanding, {money(r[4], 'en')} overdue.")
    return _resp(text, sql, cols, rows, {"type": "bar", "x": "code", "y": "outstanding_bdt"}, lang)


def intent_growth(q: str, lang: str, divisions, products) -> dict:
    group = find_group(q) or "division"
    if group in ("week", "month"):
        group = "division"
    expr, col = GROUPS[group]
    metric = "cartons" if has(q, "cartons") else "revenue_bdt"
    (s1, e1), (s0, e0) = period_range("mtd"), period_range("prev_same_days")
    filters = _filters(q, divisions, products)
    sql = f"""SELECT {expr} AS {col},
       ROUND(SUM(CASE WHEN v.day BETWEEN '{s1}' AND '{e1}' THEN v.{metric} END)) AS this_month,
       ROUND(SUM(CASE WHEN v.day BETWEEN '{s0}' AND '{e0}' THEN v.{metric} END)) AS last_month_same_days,
       ROUND(100.0 * (SUM(CASE WHEN v.day BETWEEN '{s1}' AND '{e1}' THEN v.{metric} END) /
             SUM(CASE WHEN v.day BETWEEN '{s0}' AND '{e0}' THEN v.{metric} END) - 1), 1) AS growth_pct
{FROM_SALES}
WHERE v.day BETWEEN '{s0}' AND '{e1}'{filters}
GROUP BY 1 ORDER BY growth_pct DESC"""
    cols, rows = run_sql(sql)
    top = rows[0]
    name = _bn_name(group, top[0], divisions, products) if lang == "bn" else top[0]
    if lang == "bn":
        text = (f"গত মাসের একই সময়ের ({bn_digits('1')}–{bn_digits(str(DEMO_TODAY.day))} তারিখ) তুলনায় সবচেয়ে বেশি প্রবৃদ্ধি "
                f"{name}{' বিভাগে' if group == 'division' else '-এ'}: {bn_digits(f'{top[3]:+.1f}')}%।")
    else:
        text = (f"{top[0]} grew fastest: {top[3]:+.1f}% vs the same days last month (1–{DEMO_TODAY.day}). "
                f"Lowest: {rows[-1][0]} at {rows[-1][3]:+.1f}%.")
    return _resp(text, sql, cols, rows, {"type": "bar", "x": col, "y": "growth_pct"}, lang)


def intent_order_count(q: str, lang: str, divisions) -> dict:
    start, end, en, bn = find_period(q)
    div = find_division(q, divisions)
    group = "division" if has(q, "g_division") and not div else ("distributor" if has(q, "g_distributor") else None)
    sel = {"division": "dv.name_en AS division, ", "distributor": "d.code AS distributor, "}.get(group or "", "")
    sql = f"""SELECT {sel}COUNT(*) AS orders, ROUND(SUM(o.total_bdt)) AS value_bdt
FROM orders o
JOIN distributors d ON d.id = o.distributor_id
JOIN divisions dv ON dv.id = d.division_id
WHERE date(o.created_at) BETWEEN '{start}' AND '{end}'{f" AND dv.id = {div['id']}" if div else ''}
{'GROUP BY 1 ORDER BY orders DESC' if group else ''}"""
    cols, rows = run_sql(sql)
    if group:
        text = (f"{bn} সবচেয়ে বেশি অর্ডার: {rows[0][0]} ({bn_digits(str(rows[0][1]))}টি)।" if lang == "bn"
                else f"Most orders {en}: {rows[0][0]} ({rows[0][1]}).")
        return _resp(text, sql, cols, rows, {"type": "bar", "x": cols[0], "y": "orders"}, lang)
    n, value = rows[0][0], rows[0][1] or 0
    text = (f"{bn} {bn_digits(str(n))}টি অর্ডার হয়েছে, মোট মূল্য {money(value, 'bn')}।" if lang == "bn"
            else f"{n} orders were placed {en}, worth {money(value, 'en')} in total.")
    return _resp(text, sql, cols, rows, {"type": "number", "x": "orders", "y": "orders"}, lang)


def _filters(q: str, divisions, products) -> str:
    out = ""
    if div := find_division(q, divisions):
        out += f"\n  AND dv.name_en = {_q(div['name_en'])}"
    if product := find_product(q, products):
        out += f"\n  AND p.name = {_q(product['name'])}"
    elif cat := find_category(q):
        out += f"\n  AND p.category = {_q(cat)}"
    return out


def _bn_name(group: str, value: str, divisions, products) -> str:
    if group == "division":
        return next((d["name_bn"] for d in divisions if d["name_en"] == value), value)
    if group == "product":
        return next((p["name_bn"] for p in products if p["name"] == value), value)
    return value


def intent_aggregate(q: str, lang: str, divisions, products, trend: bool = False) -> dict:
    metric = "cartons" if has(q, "cartons") else "revenue_bdt"
    top_n = find_top_n(q)
    highest, lowest = has(q, "highest"), has(q, "lowest")
    group = "week" if trend else find_group(q)
    if trend and m_weeks(q) is None:
        q += " last 12 weeks"
    start, end, en, bn = find_period(q)
    filters = _filters(q, divisions, products)
    if group is None and (top_n or highest or lowest):
        group = "division"
    if group is None:  # single number
        sql = f"""SELECT ROUND(SUM(v.{metric})) AS {metric}
{FROM_SALES}
WHERE v.day BETWEEN '{start}' AND '{end}'{filters}"""
        cols, rows = run_sql(sql)
        val = fmt_value(metric, rows[0][0] or 0, lang)
        div, prod, cat = find_division(q, divisions), find_product(q, products), find_category(q)
        scope_en = " ".join(x for x in [prod and prod["name"] or cat, div and f"in {div['name_en']}"] if x)
        scope_bn = " ".join(x for x in [div and f"{div['name_bn']}-এ", prod and prod["name_bn"] or cat] if x)
        text = (f"{bn} {scope_bn} মোট {METRIC_BN[metric]}: {val}।" if lang == "bn"
                else f"Total {METRIC_EN[metric]} {'for ' + scope_en + ' ' if scope_en else ''}{en}: {val}.")
        return _resp(text, sql, cols, rows, {"type": "number", "x": metric, "y": metric}, lang)

    expr, col = GROUPS[group]
    order = "ASC" if lowest and not highest else "DESC"
    time_series = group in ("week", "month")
    limit = f"\nLIMIT {top_n}" if top_n else ""
    sql = f"""SELECT {expr} AS {col}, ROUND(SUM(v.{metric})) AS {metric}
{FROM_SALES}
WHERE v.day BETWEEN '{start}' AND '{end}'{filters}
GROUP BY 1
ORDER BY {'1' if time_series else f'2 {order}'}{limit}"""
    cols, rows = run_sql(sql)
    if not rows:
        return _resp("কোনো তথ্য পাওয়া যায়নি।" if lang == "bn" else "No data for that question.", sql, cols, rows,
                     {"type": "table", "x": col, "y": metric}, lang)
    place_en = f" in {find_division(q, divisions)['name_en']}" if find_division(q, divisions) else ""
    place_bn = f"{find_division(q, divisions)['name_bn']}-এ " if find_division(q, divisions) else ""
    if time_series:
        first, last = rows[0][1] or 0, rows[-1][1] or 0
        change = (last / first - 1) * 100 if first else 0
        text = (f"{bn} সাপ্তাহিক {METRIC_BN[metric]}: {fmt_value(metric, first, 'bn')} থেকে {fmt_value(metric, last, 'bn')} "
                f"({bn_digits(f'{change:+.0f}')}%)।" if lang == "bn" else
                f"Weekly {METRIC_EN[metric]}{place_en} {en}: from {fmt_value(metric, first, 'en')} to "
                f"{fmt_value(metric, last, 'en')} ({change:+.0f}% first to last week).")
        return _resp(text, sql, cols, rows, {"type": "line", "x": col, "y": metric}, lang)

    top_name = _bn_name(group, rows[0][0], divisions, products) if lang == "bn" else rows[0][0]
    val = fmt_value(metric, rows[0][1] or 0, lang)
    word_en, word_bn = ("lowest", "সবচেয়ে কম") if order == "ASC" else ("highest", "সবচেয়ে বেশি")
    if top_n and len(rows) > 1:
        names = [(_bn_name(group, r[0], divisions, products) if lang == "bn" else r[0]) for r in rows]
        text = (f"{place_bn}{bn} শীর্ষ {bn_digits(str(len(rows)))}টি {GROUP_BN[group]} ({METRIC_BN[metric]} অনুযায়ী): "
                f"{', '.join(names)}। প্রথম: {names[0]} — {val}।" if lang == "bn" else
                f"Top {len(rows)} {col}s by {METRIC_EN[metric]}{place_en} {en}: {', '.join(names)}. "
                f"#1 {names[0]} with {val}.")
    elif lang == "bn":
        where = " বিভাগে" if group == "division" else ""
        text = f"{place_bn}{bn} {word_bn} {METRIC_BN[metric]} হয়েছে {top_name}{where}: {val}।"
    else:
        text = f"{rows[0][0]} had the {word_en} {METRIC_EN[metric]}{place_en} {en}: {val}."
    return _resp(text, sql, cols, rows, {"type": "bar", "x": col, "y": metric}, lang)


def m_weeks(q: str):
    return re.search(r"(\d+)\s*(?:weeks?|সপ্তাহ)", q)


def special_intent(question: str) -> str | None:
    """Intents that never go to the LLM: not plain SQL, or a fixed business definition a 3B model gets wrong."""
    q = normalize(question).lower()
    if has(q, "stockout"):
        return "stockout"
    if has(q, "forecast") and (find_product(q, _names()[1]) and ("forecast" in q or "পূর্বাভাস" in q or m_weeks(q))):
        return "forecast"
    if has(q, "compare") and not has(q, "credit"):  # growth = same days this vs last month (Plan.md §7)
        return "compare"
    return None


def answer(question: str) -> dict:
    q = normalize(question).lower()
    lang = "bn" if is_bangla(question) else "en"
    divisions, products = _names()
    special = special_intent(question)
    if special == "stockout":
        return intent_stockout(q, lang, divisions, products)
    if special == "forecast" and (r := intent_forecast(q, lang, divisions, products)):
        return r
    if has(q, "credit"):
        return intent_credit(q, lang, divisions)
    if has(q, "compare"):
        return intent_growth(q, lang, divisions, products)
    if has(q, "orders") and not has(q, "revenue") and (has(q, "count") or "placed" in q or "হয়েছে" in q):
        return intent_order_count(q, lang, divisions)
    if has(q, "trend"):
        return intent_aggregate(q, lang, divisions, products, trend=True)
    if has(q, "revenue") or has(q, "cartons") or find_group(q) or find_top_n(q):
        return intent_aggregate(q, lang, divisions, products)
    return unknown(lang)


def unknown(lang: str) -> dict:
    text = ("দুঃখিত, প্রশ্নটি বুঝতে পারিনি। এগুলো চেষ্টা করুন:" if lang == "bn"
            else "Sorry, I could not understand that question. Try one of these:")
    return {"answer_text": text, "sql": "", "columns": [], "rows": [], "chart": {"type": "none", "x": "", "y": ""},
            "engine": "rules", "lang": lang, "suggestions": SUGGESTIONS[lang]}
