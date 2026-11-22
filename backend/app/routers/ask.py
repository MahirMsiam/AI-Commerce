"""Ask your data: cache → special intents (rules) → LLM → rules fallback (Plan.md §9.3).

Plain `def`: FastAPI runs it in a thread pool, so a slow model call never freezes other requests.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import cache
from ..ai import rules_fallback, text_to_sql
from ..ai.lang import is_bangla
from ..ai.llm import ollama_ok

router = APIRouter(prefix="/api")


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


def ask_question(question: str, use_cache: bool = True) -> dict:
    lang = "bn" if is_bangla(question) else "en"
    if use_cache and (hit := cache.get(question)):
        return hit
    if rules_fallback.special_intent(question) is None and ollama_ok():
        if r := text_to_sql.answer(question, lang):
            return r
        result = rules_fallback.answer(question)
        result["note"] = "answered by rules engine"  # the model failed or timed out
        return result
    return rules_fallback.answer(question)


@router.post("/ask")
def ask(body: AskIn) -> dict:
    return ask_question(body.question.strip())
