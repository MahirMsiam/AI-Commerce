# AI Commerce & Insights – Prototype (SMC EL demo)

An offline, one-laptop demo of one connected loop:
**field order → live management insight → AI answers questions → AI agent handles routine work.**

Everything runs locally with open-source models (Ollama). No internet, no API keys, no data leaves the machine.
**All numbers are fictional sample data.** They are not SMC's figures.

Full specification: [Plan.md](Plan.md).

---

## Quick start

Requirements: Python 3.11+, Node 18+. Optional but recommended: [Ollama](https://ollama.com).

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```

**macOS / Linux**

```bash
./run.sh
```

Open **http://localhost:8000**. The first run creates the Python environment, builds the frontend and
generates the sample database (2–5 minutes). Later runs start in seconds.

The app works fully **without Ollama**: questions are answered by the rule-based engine (badge "Rules") and the
agent uses templates. With Ollama running, the status dot turns green ("Local AI on").

## Local AI (Ollama)

```bash
ollama pull qwen2.5:3b      # primary, ~1.9 GB
ollama pull qwen2.5:1.5b    # backup if 3b is too slow
```

On an 8 GB RAM laptop, set these **system environment variables**, then restart Ollama:

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | one request at a time |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | never two models in memory |
| `OLLAMA_KEEP_ALIVE` | `30m` | no 20 s reload mid-demo |
| `OLLAMA_FLASH_ATTENTION` | `1` | less memory |
| `OLLAMA_MODELS` | `E:\Models` | where models are stored (keeps them off C:) |

App settings (environment variables, defaults shown):

| Variable | Default | |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `qwen2.5:3b` | switch to `qwen2.5:1.5b` if answers take > 25 s |
| `OLLAMA_NUM_CTX` | `2048` | |
| `OLLAMA_TIMEOUT_S` | `40` | after this, the rules engine answers |
| `USE_LLM` | `true` | `false` = rules/templates only |
| `DEMO_TODAY` | `2026-11-22` | all "today / this month" logic uses this date |

**Speed check:** ask one new question on the Ask page. 5–15 s is normal. Over 25 s: use `qwen2.5:1.5b`.
Over 60 s or crashes: set `USE_LLM=false` and demo the rules engine plus cached answers.

## The night before

With Ollama running:

```powershell
cd backend
.venv\Scripts\python scripts\warm_cache.py
```

This runs the rehearsed questions and the 6 agent emails through the model once and stores the answers in
`data/answer_cache.json` (badge "Cached AI answer"). Each model answer is checked against the rules engine;
if they disagree, the rules answer is pinned instead (badge "Rules"), so a rehearsed question never shows a
wrong answer. **Reset demo never deletes this file.** Rerun it after changing any AI code.
"How many orders were placed today?" is never cached, so it always counts orders placed during the demo.

## Demo script (~15 min)

1. **Distributor.** Top bar → *Distributor* → *Rangpur Distributor 01*. Click **AI suggested order ready**:
   products, quantities and a reason per line. Change one quantity → *Add all to cart* → *Submit order* → **Placed**.
2. **Second distributor.** Pick *Sylhet Distributor 02*, add ~100 cartons of ORSaline-N, submit → **credit warning**
   with limit, outstanding, overdue and amount over limit. *Submit for approval* puts it **On hold**.
3. **Manager.** *Manager* → Dashboard. Orders today and revenue include the new order (refreshes every 10 s).
   Alerts: **ORSaline-N stock-out risk in Rangpur in about 6 days** (critical). Click it → actual vs forecast, 8 weeks ahead.
4. **Ask your data.** Use the chips: at least one **Bangla** question. Click **Show query** to show the real SQL.
   Then type one **new** question live, so they see it is real.
5. **Agent inbox.** Open *Order #1043 status and new requirement* → **Run agent**. The trace shows:
   read email → classify → `get_order_status` → `check_stock` → `get_credit_status` → draft order → draft reply → task.
   Review/edit the draft → **Approve & send (simulated)** → the task appears on **Tasks** with the Agent badge.
6. **Architecture.** Where SAP, email and their custom systems plug in, and the Pilot → Scale → Factories roadmap. End here.

Click **Reset demo** right before starting. Ready answers and the meeting checklist: [Plan.md §15](Plan.md).

## Development

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # API (dev only: no --reload in the demo)
cd frontend && npm run dev                                                         # http://localhost:5173, proxies /api
cd backend && .venv/Scripts/python -m pytest -q                                    # 63 tests, Ollama not needed
cd backend && .venv/Scripts/python scripts/generate_data.py                       # rebuild sample data (prints a checksum)
```

| Where | What |
|---|---|
| `backend/scripts/generate_data.py` | deterministic sample data (seed 42) and the 6 scripted scenarios, self-checked |
| `backend/app/routers/` | REST API: catalogue, orders + credit check, dashboard, forecasts/alerts, ask, agent, mock SAP (`/api/erp`) |
| `backend/app/ai/forecasting.py` | damped Holt forecast, 80% band, suggested order |
| `backend/app/ai/rules_fallback.py` | EN/BN question parser → SQL templates → template answers |
| `backend/app/ai/text_to_sql.py` | local-LLM text-to-SQL with few-shot examples and one retry |
| `backend/app/ai/sql_guard.py` | SELECT-only, table whitelist (SQLite authorizer), read-only connection, 200-row cap, 3 s limit |
| `backend/app/ai/agent_core.py` | inbox agent: understand → ERP tools → write → task; nothing is saved until approval |
| `frontend/src/pages/` | Portal, Dashboard, Ask, Agent, Tasks, Architecture |

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Backend not reachable" banner | Start `run.ps1` / `run.sh`; check nothing else uses port 8000. |
| Grey "Rules mode" dot | Ollama is not running: start the Ollama app (or `ollama serve`), or `USE_LLM=false`. The demo still works. |
| First AI answer after a reboot is slow | The model loads from the hard disk once; the backend pre-loads it at startup. Wait ~1 min after starting before the first question. |
| AI answers slow (> 25 s) | `OLLAMA_MODEL=qwen2.5:1.5b`, close other apps, rely on the cache. |
| Bangla shows as boxes | Windows: the *Nirmala UI* font ships with Windows 10/11. Other OS: install Noto Sans Bengali. |
| Frontend changes not showing | `run.ps1 -Rebuild` (or `./run.sh --rebuild`). |
| Data looks wrong after experiments | Click **Reset demo** (or rerun `generate_data.py`). |
| `run.ps1` blocked | Run it as `powershell -ExecutionPolicy Bypass -File run.ps1`. |
