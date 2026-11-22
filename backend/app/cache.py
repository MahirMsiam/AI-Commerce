"""Answer cache for rehearsed questions: its own file, so "Reset demo" never wipes it (Plan.md §9.3 step 2)."""
import json

from . import config
from .ai.lang import normalize


def _key(question: str) -> str:
    return " ".join(normalize(question).lower().rstrip("?।. ").split())


def _load() -> dict:
    try:
        return json.loads(config.CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get(question: str) -> dict | None:
    hit = _load().get(_key(question))
    if not hit:
        return None
    return {**hit, "engine": "cache"} if hit["engine"] == "llm" else hit  # a pinned rules answer keeps its badge


def put(question: str, response: dict, pin_rules: bool = False) -> bool:
    """Store model answers (or, when pinned, the rules answer); never ones that read live orders."""
    allowed = "rules" if pin_rules else "llm"
    if response.get("engine") != allowed or "orders" in response.get("sql", "").lower():
        return False
    data = _load()
    data[_key(question)] = response
    config.CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def get_agent(email_id: str) -> dict | None:
    return _load().get(f"agent:{email_id}")


def put_agent(email_id: str, result: dict) -> bool:
    """Store only runs where the model did the writing (sample data is fixed, so the facts stay true)."""
    if not result.get("draft") or result["draft"].get("writer") != "llm":
        return False
    data = _load()
    data[f"agent:{email_id}"] = result
    config.CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True
