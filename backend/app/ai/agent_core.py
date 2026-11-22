"""Inbox agent: understand → act with ERP tools → write → propose a task (Plan.md §9.4).

A planned workflow, not a free tool loop: a 3B model is unreliable at multi-step tool calling.
The LLM does two small jobs (understand, write an English reply); Python calls the tools in a
fixed order. Every LLM step has a template fallback, so the agent works with no model at all.

A run only PROPOSES (reply, task, draft order). Nothing is written until a human approves.
"""
import json
import re
import time
from datetime import timedelta

from .. import config
from ..config import DEMO_TODAY
from ..db import fetch
from ..routers.erp_mock import customer_credit, material_stock, sales_order
from .lang import bn_digits, normalize
from .llm import LLMUnavailable, chat
from .rules_fallback import find_product, money

INTENTS = ("order_status", "stock_order", "credit", "complaint", "price_list", "no_action")
PATTERNS = {  # checked in this order; the first hit is the primary intent
    "no_action": r"unsubscribe|newsletter|digest|webinar",
    "complaint": r"damaged|broken|crushed|complain|replacement|leak|ক্ষতিগ্রস্ত|নষ্ট|ভাঙা",
    "credit": r"credit|outstanding|payment|balance|dues|বকেয়া|ক্রেডিট|পেমেন্ট|হিসাব",
    "order_status": r"where is|status|track|কোথায়|অবস্থা",
    "price_list": r"price list|pricelist|rate list|দামের তালিকা|মূল্য তালিকা",
    "stock_order": r"stock|need|require|cartons?|স্টক|লাগবে|কার্টন",
}
URGENT = r"asap|as soon as possible|urgent|immediately|empty|দ্রুত|জরুরি"
STATUS_EN = {"Dispatched": "It has left our depot and should reach you within 1–2 days.",
             "Placed": "It has been received and is being processed.", "Approved": "It is approved and will be dispatched soon.",
             "Delivered": "Our records show it has been delivered.", "On hold": "It is on hold pending a credit review."}
STATUS_BN = {"Dispatched": "অর্ডারটি ডিপো থেকে রওনা হয়েছে, ১–২ দিনের মধ্যে পৌঁছাবে।", "Placed": "অর্ডারটি গ্রহণ করা হয়েছে এবং প্রক্রিয়াধীন।",
             "Approved": "অর্ডারটি অনুমোদিত, শীঘ্রই পাঠানো হবে।", "Delivered": "আমাদের রেকর্ড অনুযায়ী অর্ডারটি পৌঁছে গেছে।",
             "On hold": "ক্রেডিট পর্যালোচনার জন্য অর্ডারটি স্থগিত আছে।"}


def load_inbox() -> list[dict]:
    return json.loads((config.DATA_DIR / "inbox.json").read_text(encoding="utf-8"))


# ---------- understand ----------

def extract(email: dict) -> dict:
    """Regex/keyword extraction (EN + BN). Also fills gaps in the LLM's answer."""
    text = normalize(f"{email['subject']}\n{email['body']}")
    low = text.lower()
    intent = next((i for i, p in PATTERNS.items() if re.search(p, low)), "no_action")
    if not email.get("distributor_code"):
        intent = "no_action"
    products = []
    m = re.search(r"(\d+)\s*(?:cartons?|ctns?|কার্টন)", low)
    if m and intent not in ("no_action", "complaint"):
        if p := find_product(low, fetch("SELECT id, name, name_bn, category FROM products")):
            products.append({"name": p["name"], "cartons": int(m.group(1))})
    return {"intent": intent, "order_ids": sorted({int(x) for x in re.findall(r"#\s*(\d{3,6})", text)}), "products": products,
            "urgency": "high" if re.search(URGENT, low) else "normal", "summary_en": ""}


def understand_llm(email: dict, fallback: dict) -> dict:
    prompt = ("Extract from this distributor email. Reply JSON only: {\"intent\": one of " + "|".join(INTENTS) +
              ", \"order_ids\": [int], \"products\": [{\"name\": str, \"cartons\": int}], \"urgency\": \"high|normal\", "
              "\"summary_en\": one English sentence}.\n\nEmail:\n" + email["subject"] + "\n" + email["body"])
    data = json.loads(chat([{"role": "user", "content": prompt}], num_predict=200))
    # Validate field by field; anything wrong keeps the regex value. The intent always comes from the
    # keyword rules: qwen2.5:3b called the damaged-cartons complaint "order_status" in testing.
    out = dict(fallback)
    if data.get("intent") in INTENTS and data["intent"] != out["intent"]:
        out["llm_intent"] = data["intent"]  # shown in the trace, not used
    if isinstance(data.get("order_ids"), list) and all(isinstance(x, int) for x in data["order_ids"]):
        out["order_ids"] = sorted(set(out["order_ids"]) | set(data["order_ids"]))
    if isinstance(data.get("summary_en"), str):
        out["summary_en"] = data["summary_en"][:300]
    if data.get("urgency") in ("high", "normal"):
        out["urgency"] = data["urgency"]
    return out


# ---------- write ----------

def reply_en(email: dict, info: dict, r: dict) -> str:
    name = r["distributor_name"]
    parts = [f"Dear {name},", "", "Thank you for your email."]
    for o in r["orders"]:
        f = o["friendly"]
        parts.append(f"Order #{f['order_id']} (placed {f['created']}) is {f['status']}. {STATUS_EN.get(f['status'], '')} "
                     f"Items: {', '.join(f['lines'])}.")
    for oid in r["orders_not_found"]:
        parts.append(f"We could not find order #{oid} on your account. Could you please check the number?")
    for s in r["stock"]:
        f = s["friendly"]
        parts.append(f"Regarding {s['requested']} cartons of {f['product']}: your current stock is {f['cartons_on_hand']} "
                     f"cartons. We have prepared an order for {s['requested']} cartons "
                     f"({money(s['requested'] * f['price_per_carton_bdt'], 'en')}), which our team will confirm shortly.")
    if r["credit"] and (info["intent"] == "credit" or r["over_limit"]):
        c = r["credit"]["friendly"]
        parts.append(f"Your credit limit is {money(c['credit_limit_bdt'], 'en')}; outstanding {money(c['outstanding_bdt'], 'en')} "
                     f"({c['used_pct']}%), of which {money(c['overdue_bdt'], 'en')} is overdue. Available credit: "
                     f"{money(c['available_bdt'], 'en')}. Last payment recorded: {c['last_payment_date']}.")
        if info["intent"] == "credit":
            parts.append("If you paid recently, please share the transaction reference so we can reconcile your account.")
        if r["over_limit"]:
            parts.append("As this order would exceed your credit limit, it needs credit approval before dispatch.")
    if info["intent"] == "complaint":
        oid = info["order_ids"][0] if info["order_ids"] else None
        parts.append(f"We are sorry that cartons{f' in order #{oid}' if oid else ''} arrived damaged. We have logged a "
                     "complaint with our Quality team; they will contact you within 2 working days to arrange a replacement.")
    if info["intent"] == "price_list":
        parts.append("Our current price list (per carton) is below:")
        parts += [f"- {p['name']}: {money(p['price_per_carton_bdt'], 'en')}" for p in r["price_list"]]
    parts += ["", "Best regards,", "SMC EL Sales Support"]
    return "\n".join(parts)


def reply_bn(email: dict, info: dict, r: dict) -> str:
    """Bangla replies always come from templates: small models write Bangla poorly (Plan.md §9.4)."""
    parts = ["প্রিয় গ্রাহক,", "", "আপনার ইমেইলের জন্য ধন্যবাদ।"]
    for o in r["orders"]:
        f = o["friendly"]
        parts.append(f"অর্ডার #{f['order_id']} ({f['created']}) এর বর্তমান অবস্থা: {f['status']}। {STATUS_BN.get(f['status'], '')}")
    for oid in r["orders_not_found"]:
        parts.append(f"আপনার অ্যাকাউন্টে অর্ডার #{oid} পাওয়া যায়নি। অনুগ্রহ করে নম্বরটি যাচাই করুন।")
    for s in r["stock"]:
        f = s["friendly"]
        parts.append(f"{f['product_bn']}: আপনার বর্তমান স্টক {f['cartons_on_hand']} কার্টন। {s['requested']} কার্টনের একটি অর্ডার "
                     f"({money(s['requested'] * f['price_per_carton_bdt'], 'bn')}) তৈরি করা হয়েছে, আমাদের টিম শীঘ্রই নিশ্চিত করবে।")
    if r["credit"] and (info["intent"] == "credit" or r["over_limit"]):
        c = r["credit"]["friendly"]
        parts.append(f"আপনার ক্রেডিট লিমিট {money(c['credit_limit_bdt'], 'bn')}; বর্তমান বকেয়া {money(c['outstanding_bdt'], 'bn')} "
                     f"({c['used_pct']}%), যার মধ্যে মেয়াদোত্তীর্ণ {money(c['overdue_bdt'], 'bn')}। ব্যবহারযোগ্য ক্রেডিট: "
                     f"{money(c['available_bdt'], 'bn')}। সর্বশেষ পেমেন্ট: {c['last_payment_date']}।")
        if info["intent"] == "credit":
            parts.append("সম্প্রতি পেমেন্ট করে থাকলে লেনদেনের রেফারেন্স নম্বর পাঠান, আমরা হিসাব মিলিয়ে দেব।")
        if r["over_limit"]:
            parts.append("এই অর্ডারে ক্রেডিট লিমিট অতিক্রম হবে, তাই পাঠানোর আগে ক্রেডিট অনুমোদন লাগবে।")
    if info["intent"] == "complaint":
        parts.append("ক্ষতিগ্রস্ত কার্টনের জন্য আমরা দুঃখিত। কোয়ালিটি টিম ২ কার্যদিবসের মধ্যে যোগাযোগ করে বদলে দেবে।")
    if info["intent"] == "price_list":
        parts.append("আমাদের বর্তমান মূল্য তালিকা (প্রতি কার্টন):")
        parts += [f"- {p['name_bn']}: {money(p['price_per_carton_bdt'], 'bn')}" for p in r["price_list"]]
    parts += ["", "শুভেচ্ছান্তে,", "এসএমসি ইএল সেলস সাপোর্ট"]
    return bn_digits("\n".join(parts))


def write_llm(email: dict, info: dict, r: dict, template: str) -> str:
    facts = {"orders": [o["friendly"] for o in r["orders"]], "orders_not_found": r["orders_not_found"],
             "stock_and_new_order": [{**s["friendly"], "requested_cartons": s["requested"]} for s in r["stock"]],
             "credit": r["credit"]["friendly"] if r["credit"] else None, "over_credit_limit": r["over_limit"],
             "intent": info["intent"]}
    prompt = (f"Write a short, polite reply (max 120 words) from 'SMC EL Sales Support' to {r['distributor_name']}. "
              "Rephrase the reference reply below in a warm, professional tone. Copy every number, amount and date "
              "exactly as written there; add no other numbers, amounts, dates or promises. Plain text, no subject line."
              f"\n\nCustomer email:\n{email['body']}\n\nFacts (JSON):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
              f"Reference reply:\n{template}")
    text = chat([{"role": "user", "content": prompt}], json_mode=False, num_predict=256).strip()
    if len(text) < 40:
        raise LLMUnavailable("reply too short")
    if invented := numbers(text) - numbers(template):
        raise LLMUnavailable(f"reply has numbers not in the ERP data: {sorted(invented)}")
    return text


def numbers(text: str) -> set[str]:
    """Every digit group, so '90,000', '2026-11-19' and '36.30' are all checked."""
    return set(re.findall(r"\d+", text))


# ---------- run ----------

class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, type_: str, name: str, input_=None, output=None, started: float | None = None):
        ms = round((time.perf_counter() - started) * 1000) if started else 0
        self.steps.append({"step": len(self.steps) + 1, "type": type_, "name": name, "input": input_,
                           "output": output, "ms": ms})

    def tool(self, name: str, fn, *args):
        t = time.perf_counter()
        self.add("tool_call", name, list(args))
        out = fn(*args)
        self.add("tool_result", name, None, out if out is not None else {"error": "not found"}, t)
        return out


def run_agent(email: dict, use_llm: bool) -> dict:
    tr = Trace()
    tr.add("tool_result", "read_email", email["id"], {"from": email["from"], "subject": email["subject"]})

    t = time.perf_counter()
    info, engine = extract(email), "rules"
    if use_llm and info["intent"] != "no_action":
        try:
            info, engine = understand_llm(email, info), "llm"
        except (LLMUnavailable, ValueError, json.JSONDecodeError) as e:
            tr.add("thought", "llm_fallback", None, f"Model unavailable for 'understand' ({e}); using rules.")
    tr.add("thought", "classify_intent", None, {**info, "engine": engine}, t)

    if info["intent"] == "no_action":
        tr.add("thought", "decision", None, "Not a customer request (newsletter / no distributor). No reply, no task.")
        return {"trace": tr.steps, "intent": "no_action", "draft": None, "task": None, "order": None}

    code = email["distributor_code"]
    r = {"orders": [], "orders_not_found": [], "stock": [], "credit": None, "over_limit": False, "price_list": []}
    for oid in info["order_ids"]:
        so = tr.tool("get_order_status", sales_order, oid)
        # A distributor only sees its own orders.
        (r["orders"].append(so) if so and so["KUNNR"] == code else r["orders_not_found"].append(oid))
    for p in info["products"]:
        st = tr.tool("check_stock", material_stock, code, p["name"])
        if st:
            r["stock"].append({**st, "requested": p["cartons"]})
    if r["stock"] or info["intent"] == "credit":
        r["credit"] = tr.tool("get_credit_status", customer_credit, code)
    order = None
    if r["stock"]:
        lines = [{"product_id": s["friendly"]["product_id"], "product": s["friendly"]["product"], "cartons": s["requested"],
                  "price_bdt": s["friendly"]["price_per_carton_bdt"]} for s in r["stock"]]
        total = sum(l["cartons"] * l["price_bdt"] for l in lines)
        r["over_limit"] = bool(r["credit"]) and r["credit"]["SKFOR"] + total > r["credit"]["KLIMK"]
        order = {"distributor_code": code, "lines": lines, "total_bdt": total, "status": "On hold"}
        tr.add("tool_call", "create_order_draft", {"distributor_code": code, "lines": lines},
               {"proposed": True, "status": "On hold", "total_bdt": total, "note": "created only after approval"})
    if info["intent"] == "price_list":
        r["price_list"] = fetch("SELECT name, name_bn, price_per_carton_bdt FROM products ORDER BY category, name")
        tr.add("tool_result", "get_price_list", None, {"products": len(r["price_list"])})
    r["distributor_name"] = (r["credit"]["friendly"]["distributor"] if r["credit"]
                             else fetch("SELECT name FROM distributors WHERE code = ?", (code,))[0]["name"])

    # Write: Bangla (or mixed) → template; English → LLM with the template as reference.
    t = time.perf_counter()
    lang = "bn" if email["lang"] == "bn" else "en"
    body, writer = (reply_bn if lang == "bn" else reply_en)(email, info, r), "template"
    if use_llm and lang == "en" and info["intent"] != "price_list":  # an 18-line table overflows num_predict
        try:
            body, writer = write_llm(email, info, r, body), "llm"
        except LLMUnavailable as e:
            tr.add("thought", "llm_fallback", None, f"Model unavailable for 'write' ({e}); using template.")
    subject = f"Re: {email['subject']}"
    draft = {"to": email["from"], "subject": subject, "body": body, "lang": lang, "writer": writer}
    tr.add("draft", "draft_reply", {"to": email["from"], "lang": lang}, {**draft, "status": "draft"}, t)

    task = make_task(email, info, r)
    tr.add("task", "create_task", None, {**task, "status": "pending approval"})
    return {"trace": tr.steps, "intent": info["intent"], "draft": draft, "task": task, "order": order}


def make_task(email: dict, info: dict, r: dict) -> dict | None:
    code = email["distributor_code"]
    division = fetch("SELECT dv.name_en FROM distributors d JOIN divisions dv ON dv.id = d.division_id WHERE d.code = ?",
                     (code,))[0]["name_en"]
    asm = f"Area sales manager – {division}"
    req = "; ".join(f"{s['requested']} × {s['friendly']['product']}" for s in r["stock"])
    intent, oids = info["intent"], ", ".join(f"#{o}" for o in info["order_ids"])
    if intent == "complaint":
        title, assignee, prio = f"Replace damaged cartons {oids} ({code})".replace("  ", " "), "Quality team", "high"
    elif intent == "credit":
        title, assignee, prio = f"Reconcile account and payment of {code}", "Finance", "medium"
    elif intent == "price_list":
        title, assignee, prio = f"Send updated price list follow-up to {code}", asm, "low"
    elif intent == "order_status":
        title = f"Follow up order {oids} for {code}" + (f" + new request: {req}" if req else "")
        assignee, prio = asm, "high" if info["urgency"] == "high" else "medium"
    else:
        title, assignee = f"Process order request from {code}: {req or 'see email'}", asm
        prio = "high" if info["urgency"] == "high" else "medium"
    summary = info["summary_en"] or f"{intent.replace('_', ' ').capitalize()} email from {code}: “{email['subject']}”."
    if r["over_limit"]:
        summary += " New order exceeds credit limit: needs credit approval."
    due = DEMO_TODAY + timedelta(days=1 if prio == "high" else 2 if prio == "medium" else 5)
    return {"title": title, "description": summary, "assignee": assignee, "due_date": due.isoformat(), "priority": prio,
            "source_email_id": email["id"]}
