"""Ollama client: one call at a time (8 GB laptop), JSON mode, hard timeout (Plan.md §16)."""
import threading

import httpx

from .. import config

_lock = threading.Lock()


class LLMUnavailable(RuntimeError):
    pass


def ollama_ok() -> bool:
    if not config.USE_LLM:
        return False
    try:
        return httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def chat(messages: list[dict], json_mode: bool = True, num_predict: int = 256) -> str:
    """Return the model's reply text. Raises LLMUnavailable if busy, off, slow or failing."""
    if not config.USE_LLM:
        raise LLMUnavailable("LLM disabled")
    if not _lock.acquire(timeout=0):  # a second request uses the fallback instead of queueing
        raise LLMUnavailable("local AI is busy")
    try:
        body = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": False,
                "options": {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX, "num_predict": num_predict}}
        if json_mode:
            body["format"] = "json"
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=config.OLLAMA_TIMEOUT_S)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMUnavailable(str(e) or type(e).__name__) from e
    finally:
        _lock.release()
