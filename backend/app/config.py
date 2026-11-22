"""Settings. Environment variables override the defaults (Plan.md §14)."""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "smc_demo.db"
CACHE_PATH = DATA_DIR / "answer_cache.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))
OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT_S", "40"))
USE_LLM = os.getenv("USE_LLM", "true").lower() == "true"
DEMO_TODAY = date.fromisoformat(os.getenv("DEMO_TODAY", "2026-11-22"))
