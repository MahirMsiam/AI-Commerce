"""LLM path for Ask: compact prompt → JSON {sql, chart, x, y} → guard → one retry (Plan.md §9.3 step 3-5)."""
import json
import re
import sqlite3

from ..config import DEMO_TODAY
from ..periods import period_range
from ..db import fetch
from .lang import bn_digits, is_bangla, normalize
from .llm import LLMUnavailable, chat
from .rules_fallback import fmt_value
from .sql_guard import GuardError, run_sql

SCHEMA = """v_sales(day DATE, distributor_id, product_id, cartons REAL, revenue_bdt REAL)  -- ALL sales; use for revenue/cartons
distributors(id, code e.g. 'RNG-01', name, division_id, credit_limit_bdt)
divisions(id, name_en, name_bn)
products(id, sku, name, name_bn, category, price_per_carton_bdt)
orders(id, distributor_id, created_at ISO datetime, status, total_bdt, source)
receivables(distributor_id, outstanding_bdt, overdue_bdt, last_payment_date)
stock(distributor_id, product_id, cartons_on_hand)"""

NAMES = ("Divisions: Dhaka=ঢাকা, Chattogram=চট্টগ্রাম, Rajshahi=রাজশাহী, Khulna=খুলনা, Sylhet=সিলেট, Barishal=বরিশাল, "
         "Rangpur=রংপুর, Mymensingh=ময়মনসিংহ. Product names are in products.name (e.g. 'ORSaline-N', 'SMC Plus Electrolyte Drink').")

# Pool of 20 examples; the 6 most similar (keyword overlap, ≥2 Bangla) go into the prompt.
POOL = [
    ("Total revenue this month", "SELECT ROUND(SUM(revenue_bdt)) AS revenue_bdt FROM v_sales WHERE day BETWEEN '{mtd0}' AND '{today}'", "number"),
    ("Revenue by division last month", "SELECT dv.name_en AS division, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE v.day BETWEEN '{lm0}' AND '{lm1}' GROUP BY 1 ORDER BY 2 DESC", "bar"),
    ("Top 3 products by cartons in Dhaka this month", "SELECT p.name AS product, ROUND(SUM(v.cartons)) AS cartons FROM v_sales v JOIN products p ON p.id=v.product_id JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Dhaka' AND v.day BETWEEN '{mtd0}' AND '{today}' GROUP BY 1 ORDER BY 2 DESC LIMIT 3", "bar"),
    ("Which category sells the most this month?", "SELECT p.category, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN products p ON p.id=v.product_id WHERE v.day BETWEEN '{mtd0}' AND '{today}' GROUP BY 1 ORDER BY 2 DESC", "bar"),
    ("Monthly revenue for ORSaline-N in the last 6 months", "SELECT strftime('%Y-%m', v.day) AS month, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN products p ON p.id=v.product_id WHERE p.name='ORSaline-N' AND v.day >= date('{today}', 'start of month', '-5 months') GROUP BY 1 ORDER BY 1", "line"),
    ("Weekly cartons sold in Sylhet for the last 8 weeks", "SELECT date(v.day, '-6 days', 'weekday 1') AS week, ROUND(SUM(v.cartons)) AS cartons FROM v_sales v JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Sylhet' AND v.day >= date('{today}', '-55 days') GROUP BY 1 ORDER BY 1", "line"),
    ("Which distributor has the lowest revenue this month?", "SELECT d.code, d.name, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN distributors d ON d.id=v.distributor_id WHERE v.day BETWEEN '{mtd0}' AND '{today}' GROUP BY d.id ORDER BY 3 ASC LIMIT 5", "bar"),
    ("Total overdue amount by division", "SELECT dv.name_en AS division, SUM(r.overdue_bdt) AS overdue_bdt FROM receivables r JOIN distributors d ON d.id=r.distributor_id JOIN divisions dv ON dv.id=d.division_id GROUP BY 1 ORDER BY 2 DESC", "bar"),
    ("How many orders are on hold?", "SELECT COUNT(*) AS orders FROM orders WHERE status='On hold'", "number"),
    ("Orders by status this month", "SELECT status, COUNT(*) AS orders FROM orders WHERE date(created_at) BETWEEN '{mtd0}' AND '{today}' GROUP BY 1 ORDER BY 2 DESC", "bar"),
    ("Compare cartons this month vs last month by category", "SELECT p.category, ROUND(SUM(CASE WHEN v.day BETWEEN '{mtd0}' AND '{today}' THEN v.cartons END)) AS this_month, ROUND(SUM(CASE WHEN v.day BETWEEN '{lm0}' AND '{lms}' THEN v.cartons END)) AS last_month_same_days, ROUND(100.0 * (SUM(CASE WHEN v.day BETWEEN '{mtd0}' AND '{today}' THEN v.cartons END) / SUM(CASE WHEN v.day BETWEEN '{lm0}' AND '{lms}' THEN v.cartons END) - 1), 1) AS growth_pct FROM v_sales v JOIN products p ON p.id=v.product_id WHERE v.day BETWEEN '{lm0}' AND '{today}' GROUP BY 1 ORDER BY growth_pct DESC", "bar"),
    ("ঢাকায় শীর্ষ ৩টি পণ্য কোনগুলো?", "SELECT p.name AS product, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN products p ON p.id=v.product_id JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Dhaka' AND v.day BETWEEN '{mtd0}' AND '{today}' GROUP BY 1 ORDER BY 2 DESC LIMIT 3", "bar"),
    ("Stock on hand of SMC Zinc by distributor in Rangpur", "SELECT d.code, s.cartons_on_hand FROM stock s JOIN distributors d ON d.id=s.distributor_id JOIN divisions dv ON dv.id=d.division_id JOIN products p ON p.id=s.product_id WHERE p.name='SMC Zinc' AND dv.name_en='Rangpur' ORDER BY 2", "bar"),
    ("Which Khulna distributors use more than 50% of their credit limit?", "SELECT d.code, d.name, ROUND(100.0*r.outstanding_bdt/d.credit_limit_bdt,1) AS pct_of_limit FROM receivables r JOIN distributors d ON d.id=r.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Khulna' AND r.outstanding_bdt > 0.5*d.credit_limit_bdt ORDER BY 3 DESC", "bar"),
    ("Weekly revenue trend for the last 8 weeks", "SELECT date(v.day, '-6 days', 'weekday 1') AS week, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v WHERE v.day > date('{today}', '-56 days') GROUP BY 1 ORDER BY 1", "line"),
    ("এই মাসে মোট বিক্রি কত?", "SELECT ROUND(SUM(revenue_bdt)) AS revenue_bdt FROM v_sales WHERE day BETWEEN '{mtd0}' AND '{today}'", "number"),
    ("ঢাকায় গত মাসে কোন পণ্য সবচেয়ে বেশি বিক্রি হয়েছে?", "SELECT p.name AS product, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN products p ON p.id=v.product_id JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Dhaka' AND v.day BETWEEN '{lm0}' AND '{lm1}' GROUP BY 1 ORDER BY 2 DESC LIMIT 5", "bar"),
    ("বিভাগ অনুযায়ী এই মাসের কার্টন বিক্রি", "SELECT dv.name_en AS division, ROUND(SUM(v.cartons)) AS cartons FROM v_sales v JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE v.day BETWEEN '{mtd0}' AND '{today}' GROUP BY 1 ORDER BY 2 DESC", "bar"),
    ("সিলেটের ডিস্ট্রিবিউটরদের বকেয়া কত?", "SELECT d.code, r.outstanding_bdt, r.overdue_bdt FROM receivables r JOIN distributors d ON d.id=r.distributor_id JOIN divisions dv ON dv.id=d.division_id WHERE dv.name_en='Sylhet' ORDER BY 2 DESC", "bar"),
    ("গত সপ্তাহে কয়টি অর্ডার হয়েছে?", "SELECT COUNT(*) AS orders FROM orders WHERE date(created_at) BETWEEN date('{today}', 'weekday 1', '-14 days') AND date('{today}', 'weekday 1', '-8 days')", "number"),
    ("ক্যাটাগরি অনুযায়ী গত মাসের বিক্রি", "SELECT p.category, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v JOIN products p ON p.id=v.product_id WHERE v.day BETWEEN '{lm0}' AND '{lm1}' GROUP BY 1 ORDER BY 2 DESC", "bar"),
]

# Bangla word → English keyword, so the small model also gets an English version of a Bangla question.
BN_TO_EN = {"বিক্রি": "sales", "আয়": "revenue", "কার্টন": "cartons", "অর্ডার": "orders", "অঞ্চল": "division",
            "বিভাগ": "division", "পণ্য": "product", "ডিস্ট্রিবিউটর": "distributor", "সবচেয়ে বেশি": "highest",
            "সবচেয়ে কম": "lowest", "শীর্ষ": "top", "গত মাস": "last month", "এই মাস": "this month",
            "গত সপ্তাহ": "last week", "আজ": "today", "বকেয়া": "outstanding", "ক্রেডিট": "credit",
            "তুলনা": "compare", "প্রবৃদ্ধি": "growth", "ক্যাটাগরি": "category", "কত": "how much",
            "ঢাকা": "Dhaka", "চট্টগ্রাম": "Chattogram", "রাজশাহী": "Rajshahi", "খুলনা": "Khulna", "সিলেট": "Sylhet",
            "বরিশাল": "Barishal", "রংপুর": "Rangpur", "ময়মনসিংহ": "Mymensingh", "ওরস্যালাইন": "ORSaline-N"}
BN_TO_EN = {normalize(k): v for k, v in BN_TO_EN.items()}


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"\w+", normalize(s).lower()))


def pick_examples(question: str, k: int = 6) -> list[tuple]:
    qt = _tokens(question)
    ranked = sorted(POOL, key=lambda ex: -len(qt & _tokens(ex[0])))
    bn = [ex for ex in ranked if is_bangla(ex[0])][:2]  # always at least 2 Bangla examples
    return [ex for ex in ranked if ex not in bn][: k - 2] + bn


def english_keywords(question: str) -> str:
    q = normalize(question)
    words = [en for bn, en in BN_TO_EN.items() if bn in q]
    if not any(w in ("last month", "this month", "last week", "today") for w in words):
        words.append("this month")  # the model otherwise guesses a period
    return " ".join(words)


def build_messages(question: str, lang: str) -> list[dict]:
    mtd0, today = period_range("mtd")
    lm0, lm1 = period_range("last_month")
    lms = period_range("prev_same_days")[1]
    dates = {"mtd0": mtd0, "today": today, "lm0": lm0, "lm1": lm1, "lms": lms}
    system = f"""You write ONE SQLite SELECT query that answers the user's question. Reply with JSON only:
{{"sql": "...", "chart": "bar|line|table|number", "x": "<label column>", "y": "<value column>"}}
Rules: use only these tables/columns. Revenue and cartons ALWAYS come from v_sales. Today is {today}.
"This month" = '{mtd0}' to '{today}'. "Last month" = '{lm0}' to '{lm1}'. Use English names in WHERE clauses.
No time mentioned = this month. Round money with ROUND(). Never modify data.
Ranking (top, highest, most, শীর্ষ): always SELECT the value column and ORDER BY it DESC (revenue unless cartons are asked).
Week: GROUP BY date(v.day, '-6 days', 'weekday 1'). Last N weeks: v.day > date('{today}', '-(7*N) days'), e.g. 12 weeks = '-84 days'.
Compare / growth this month vs last month: SAME days only, last month = '{lm0}' to '{lms}'; one row per group with both values and growth_pct.
Schema:
{SCHEMA}
{NAMES}"""
    msgs = [{"role": "system", "content": system}]
    for q, sql, chart in pick_examples(question):
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps({"sql": sql.format(**dates), "chart": chart}, ensure_ascii=False)})
    content = question
    if lang == "bn":  # small models read Bangla poorly: add the English keywords
        content = f"{question}\n(English keywords: {english_keywords(question)})"
    msgs.append({"role": "user", "content": content})
    return msgs


def _parse(reply: str) -> dict:
    data = json.loads(reply)
    if not isinstance(data, dict) or not isinstance(data.get("sql"), str):
        raise ValueError("reply has no sql string")
    return data


def answer_text(columns: list[str], rows: list[list], lang: str) -> str:
    """A template sentence built from the result (the small model never writes the answer text)."""
    if not rows:
        return "কোনো তথ্য পাওয়া যায়নি।" if lang == "bn" else "The query returned no rows."
    nums = [i for i, v in enumerate(rows[0]) if isinstance(v, (int, float))]
    texts = [i for i, v in enumerate(rows[0]) if isinstance(v, str)]
    if not nums:
        names = ", ".join(_name(r[texts[0]], lang) for r in rows[:5]) if texts else ""
        return f"ফলাফল: {names}।" if lang == "bn" else f"Result: {names}."
    vi = columns.index("growth_pct") if "growth_pct" in columns else nums[-1]

    def val(r):
        if "pct" in columns[vi]:
            s = f"{r[vi]:+.1f}" if columns[vi] == "growth_pct" else f"{r[vi]:.0f}"
            return f"{bn_digits(s) if lang == 'bn' else s}%"
        return fmt_value(columns[vi], r[vi], lang)

    if not texts:
        return f"উত্তর: {val(rows[0])}।" if lang == "bn" else f"Answer: {val(rows[0])}."
    first = f"{_name(rows[0][texts[0]], lang)} ({val(rows[0])})"
    rest = ", ".join(f"{_name(r[texts[0]], lang)} ({val(r)})" for r in rows[1:3])
    if lang == "bn":
        return f"শীর্ষে {first}" + (f"; এরপর {rest}" if rest else "") + "।"
    return f"{first} is first" + (f", then {rest}" if rest else "") + "."


def _name(value: str, lang: str) -> str:
    """Bangla answers show Bangla division/product names."""
    if lang != "bn":
        return value
    names = {r["name_en"]: r["name_bn"] for r in fetch("SELECT name_en, name_bn FROM divisions")}
    names |= {r["name"]: r["name_bn"] for r in fetch("SELECT name, name_bn FROM products")}
    return names.get(value, value)


def answer(question: str, lang: str) -> dict | None:
    """Try the LLM path. Returns None (caller falls back to rules) on any failure."""
    msgs = build_messages(question, lang)
    for _attempt in range(2):
        reply = "{}"
        try:
            reply = chat(msgs)
            data = _parse(reply)
            columns, rows = run_sql(data["sql"])
        except LLMUnavailable:
            return None
        except (ValueError, GuardError, sqlite3.Error) as e:  # one retry, with the error message
            msgs += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"That failed: {e}. Fix it and reply with JSON only."}]
            continue
        chart = data.get("chart") if data.get("chart") in ("bar", "line", "table", "number") else "table"
        x = data.get("x") if data.get("x") in columns else columns[0]
        y = data.get("y") if data.get("y") in columns else columns[-1]
        return {"answer_text": answer_text(columns, rows, lang), "sql": data["sql"].strip(), "columns": columns,
                "rows": rows, "chart": {"type": chart, "x": x, "y": y}, "engine": "llm", "lang": lang}
    return None

