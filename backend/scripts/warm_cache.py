"""Run the rehearsed questions and agent emails through the local model once and store the answers.

Run the night before the demo, with Ollama running:  .venv/Scripts/python scripts/warm_cache.py
Q12 ("orders today") is never cached: it must count orders placed during the demo.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import cache, config  # noqa: E402
from app.ai import rules_fallback  # noqa: E402
from app.ai.agent_core import load_inbox, run_agent  # noqa: E402
from app.ai.llm import ollama_ok  # noqa: E402
from app.routers.ask import ask_question  # noqa: E402

QUESTIONS = [
    "Top 5 products by revenue in Chattogram last month",
    "Which division had the highest sales this month?",
    "Compare revenue this month vs last month by division",
    "Which distributors are above 80% of their credit limit?",
    "Show weekly revenue trend for the last 12 weeks",
    "Forecast ORSaline-N demand in Rangpur for the next 4 weeks",
    "Which products are at risk of stock-out?",
    "গত মাসে কোন অঞ্চলে বিক্রি সবচেয়ে বেশি?",
    "চট্টগ্রামে শীর্ষ ৫টি পণ্য কোনগুলো?",
    "কোন ডিস্ট্রিবিউটরদের বকেয়া সবচেয়ে বেশি?",
    "আগামী ৪ সপ্তাহে রংপুরে ওরস্যালাইনের চাহিদা কত হবে?",
]


def agrees(llm: dict, rules: dict) -> bool:
    """Same top result: the first rows share a label (division, product, code...)."""
    if not llm["rows"] or not rules["rows"]:
        return False
    labels = lambda row: {v for v in row if isinstance(v, str)}  # noqa: E731
    return bool(labels(llm["rows"][0]) & labels(rules["rows"][0]))


def main() -> int:
    if not ollama_ok():
        print(f"Ollama is not reachable at {config.OLLAMA_URL} (or USE_LLM=false). Start it and retry.")
        return 1
    if not config.DB_PATH.exists():
        print("No database yet: run scripts/generate_data.py first.")
        return 1
    stored = 0
    for q in QUESTIONS:
        t = time.perf_counter()
        r = ask_question(q, use_cache=False)
        status = "skipped"
        if r["engine"] == "llm":
            if agrees(r, rules_fallback.answer(q)):
                status = "cached " if cache.put(q, r) else status
            else:  # a rehearsed question must never show a wrong answer: pin the rules answer
                status = "PINNED rules (model disagreed)" if cache.put(q, rules_fallback.answer(q), pin_rules=True) else status
        stored += status != "skipped"
        print(f"{status:7} {r['engine']:5} {time.perf_counter() - t:5.1f}s  {q}")
    for e in load_inbox():
        t = time.perf_counter()
        r = run_agent(e, use_llm=True)
        ok = cache.put_agent(e["id"], r)
        stored += ok
        print(f"{'cached ' if ok else 'skipped'} agent {time.perf_counter() - t:5.1f}s  {e['id']} {e['subject']}")
    print(f"\n{stored} answers stored in {config.CACHE_PATH}. Rule-based and special-intent answers are instant anyway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
