"""The 12 must-pass questions (Plan.md §9.3) with Ollama off, plus the LLM path with a fake model."""
import json
import unicodedata

import pytest

from app import cache, config
from app.ai import llm, text_to_sql
from app.routers.ask import ask_question

MUST_PASS = [
    ("Top 5 products by revenue in Chattogram last month", "bar", "Chattogram"),
    ("Which division had the highest sales this month?", "bar", "highest"),
    ("Compare revenue this month vs last month by division", "bar", "Chattogram grew fastest"),
    ("Which distributors are above 80% of their credit limit?", "bar", "SYL-02"),
    ("Show weekly revenue trend for the last 12 weeks", "line", "Weekly revenue"),
    ("Forecast ORSaline-N demand in Rangpur for the next 4 weeks", "forecast", "Rangpur"),
    ("Which products are at risk of stock-out?", "table", "ORSaline-N at RNG-01"),
    ("গত মাসে কোন অঞ্চলে বিক্রি সবচেয়ে বেশি?", "bar", "বিভাগে"),
    ("চট্টগ্রামে শীর্ষ ৫টি পণ্য কোনগুলো?", "bar", "শীর্ষ ৫টি"),
    ("কোন ডিস্ট্রিবিউটরদের বকেয়া সবচেয়ে বেশি?", "bar", "সবচেয়ে বেশি বকেয়া"),
    ("আগামী ৪ সপ্তাহে রংপুরে ওরস্যালাইনের চাহিদা কত হবে?", "forecast", "রংপুর"),
    ("How many orders were placed today?", "number", "orders were placed today"),
]


@pytest.mark.parametrize("question,chart,expect", MUST_PASS)
def test_must_pass_rules(question, chart, expect):
    r = ask_question(question)
    assert r["engine"] == "rules" and r["sql"]
    assert r["chart"]["type"] == chart, r
    assert expect in r["answer_text"], r["answer_text"]
    assert r["lang"] == ("bn" if any("ঀ" <= c <= "৿" for c in question) else "en")


def test_specific_rows():
    q1 = ask_question("Top 5 products by revenue in Chattogram last month")
    assert len(q1["rows"]) == 5
    q3 = ask_question("Compare revenue this month vs last month by division")
    assert q3["rows"][0][0] == "Chattogram" and 16 < q3["rows"][0][3] < 20
    q4 = ask_question("Which distributors are above 80% of their credit limit?")
    assert [r[0] for r in q4["rows"]] == ["SYL-02", "BAR-03"]


def test_bangla_decomposed_ya_still_matches():
    """য় typed as য + nukta (two code points) must parse like the single code point."""
    q = "গত মাসে কোন অঞ্চলে বিক্রি সবচেয়ে বেশি?"
    decomposed = unicodedata.normalize("NFD", q)
    assert decomposed != q
    assert ask_question(decomposed)["answer_text"] == ask_question(q)["answer_text"]


def test_orders_today_counts_new_order(client):
    before = ask_question("How many orders were placed today?")["rows"][0][0]
    client.post("/api/orders", json={"distributor_id": 1, "lines": [{"product_id": 2, "cartons": 3}]})
    assert ask_question("How many orders were placed today?")["rows"][0][0] == before + 1


def test_unknown_question_gives_suggestions():
    r = ask_question("what is the weather like")
    assert r["chart"]["type"] == "none" and len(r["suggestions"]) == 4


def test_llm_path_with_fake_model(monkeypatch):
    replies = iter([
        json.dumps({"sql": "SELEC broken"}),  # first try fails → retry with the error
        json.dumps({"sql": "SELECT dv.name_en AS division, ROUND(SUM(v.revenue_bdt)) AS revenue_bdt FROM v_sales v "
                           "JOIN distributors d ON d.id=v.distributor_id JOIN divisions dv ON dv.id=d.division_id "
                           "GROUP BY 1 ORDER BY 2 DESC", "chart": "bar", "x": "division", "y": "revenue_bdt"}),
    ])
    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(text_to_sql, "chat", lambda msgs: next(replies))
    monkeypatch.setattr("app.routers.ask.ollama_ok", lambda: True)
    r = ask_question("Revenue per division all time", use_cache=False)
    assert r["engine"] == "llm" and r["chart"] == {"type": "bar", "x": "division", "y": "revenue_bdt"}
    assert r["answer_text"].startswith(("Dhaka (", "Chattogram (")) and "is first, then" in r["answer_text"]


def test_llm_never_runs_writes(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(text_to_sql, "chat", lambda msgs: json.dumps({"sql": "DELETE FROM orders"}))
    monkeypatch.setattr("app.routers.ask.ollama_ok", lambda: True)
    r = ask_question("Which division had the highest sales this month?", use_cache=False)
    assert r["engine"] == "rules" and r["note"] == "answered by rules engine"


def test_prompt_has_two_bangla_examples_and_fits():
    msgs = text_to_sql.build_messages("Top 5 products in Dhaka", "en")
    users = [m["content"] for m in msgs[1:-1] if m["role"] == "user"]
    assert len(users) == 6 and sum(any("ঀ" <= c <= "৿" for c in u) for u in users) >= 2
    assert sum(len(m["content"]) for m in msgs) < 6000  # ~1,500 tokens


def test_cache_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "c.json")
    assert not cache.put("q", {"engine": "rules", "sql": "SELECT 1"})
    assert not cache.put("orders today", {"engine": "llm", "sql": "SELECT COUNT(*) FROM orders"})
    assert cache.put("Which division?", {"engine": "llm", "sql": "SELECT 1 FROM v_sales", "answer_text": "x"})
    assert cache.get("which division")["engine"] == "cache"


def test_llm_busy_falls_back(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", True)
    assert llm._lock.acquire()
    try:
        with pytest.raises(llm.LLMUnavailable, match="busy"):
            llm.chat([{"role": "user", "content": "hi"}])
    finally:
        llm._lock.release()


@pytest.mark.parametrize("q", ["Compare revenue this month vs last month by division", "Which forecast ORSaline-N Rangpur next 4 weeks",
                               "Which products are at risk of stock-out?", "বিভাগ অনুযায়ী প্রবৃদ্ধি তুলনা"])
def test_special_intents_never_reach_the_model(q, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(text_to_sql, "chat", boom)
    monkeypatch.setattr("app.routers.ask.ollama_ok", lambda: True)
    r = ask_question(q, use_cache=False)
    assert r["engine"] == "rules" and "note" not in r


def test_pinned_rules_answer_keeps_its_badge(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "c.json")
    rules = ask_question("কোন ডিস্ট্রিবিউটরদের বকেয়া সবচেয়ে বেশি?", use_cache=False)
    assert not cache.put("q", rules)  # rules answers are only cached when pinned
    assert cache.put("q", rules, pin_rules=True)
    assert cache.get("q")["engine"] == "rules"
