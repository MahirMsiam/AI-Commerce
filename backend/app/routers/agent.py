"""Agent inbox, run, approve/discard, and the task board (Plan.md §8, §9.4)."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import cache, db
from ..ai.agent_core import load_inbox, run_agent
from ..ai.llm import ollama_ok
from .orders import demo_now, insert_order

router = APIRouter(prefix="/api")


@router.get("/agent/inbox")
def inbox() -> list[dict]:
    runs = {r["email_id"]: r for r in db.fetch("SELECT id, email_id, trace_json FROM agent_runs ORDER BY id")}
    out = []
    for e in load_inbox():
        run = runs.get(e["id"])
        status = json.loads(run["trace_json"])["status"] if run else "new"
        out.append({**e, "status": status, "run_id": run["id"] if run else None})
    return sorted(out, key=lambda e: e["received_at"], reverse=True)


@router.post("/agent/run/{email_id}")
def run(email_id: str) -> dict:
    email = next((e for e in load_inbox() if e["id"] == email_id), None)
    if not email:
        raise HTTPException(404, "unknown email")
    result = cache.get_agent(email_id) or run_agent(email, use_llm=ollama_ok())
    result["status"] = "no_action" if result["intent"] == "no_action" else "awaiting_approval"
    with db.rw() as conn:
        cur = conn.execute("INSERT INTO agent_runs (email_id, trace_json, created_at) VALUES (?,?,?)",
                           (email_id, json.dumps(result, ensure_ascii=False), demo_now()))
    return {"run_id": cur.lastrowid, **result}


class ApproveIn(BaseModel):
    body: str | None = Field(default=None, max_length=5000)  # the reviewer's edited reply


def _load_run(conn, run_id: int) -> dict:
    row = conn.execute("SELECT trace_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "unknown run")
    result = json.loads(row["trace_json"])
    if result["status"] != "awaiting_approval":
        raise HTTPException(409, f"run is {result['status']}")
    return result


@router.post("/agent/approve/{run_id}")
def approve(run_id: int, body: ApproveIn | None = None) -> dict:
    """The human click: only now is the reply 'sent', the task saved and the draft order created (On hold)."""
    with db.rw() as conn:
        result = _load_run(conn, run_id)
        d, t, now = result["draft"], result["task"], demo_now()
        reply = body.body if body and body.body else d["body"]
        conn.execute('INSERT INTO outbox (email_id, "to", subject, body, status, created_at) VALUES (?,?,?,?,?,?)',
                     (t["source_email_id"], d["to"], d["subject"], reply, "approved_sent", now))
        task_id = conn.execute("""INSERT INTO tasks (title, description, assignee, due_date, priority, status,
                                  source_email_id, created_by) VALUES (?,?,?,?,?,?,?,?)""",
                               (t["title"], t["description"], t["assignee"], t["due_date"], t["priority"], "To do",
                                t["source_email_id"], "agent")).lastrowid
        order = None
        if result["order"]:
            did = conn.execute("SELECT id FROM distributors WHERE code = ?",
                               (result["order"]["distributor_code"],)).fetchone()["id"]
            order = insert_order(conn, did, [(l["product_id"], l["cartons"]) for l in result["order"]["lines"]],
                                 "On hold", "agent")  # agent orders never auto-approve
        result["status"] = "approved"
        conn.execute("UPDATE agent_runs SET trace_json = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), run_id))
    return {"ok": True, "task_id": task_id, "order": order}


@router.post("/agent/discard/{run_id}")
def discard(run_id: int) -> dict:
    with db.rw() as conn:
        result = _load_run(conn, run_id)
        result["status"] = "discarded"
        conn.execute("UPDATE agent_runs SET trace_json = ? WHERE id = ?", (json.dumps(result, ensure_ascii=False), run_id))
    return {"ok": True}


@router.get("/tasks")
def tasks() -> list[dict]:
    return db.fetch("SELECT * FROM tasks ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id DESC")


class TaskPatch(BaseModel):
    status: Literal["To do", "In progress", "Done"]


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch) -> dict:
    with db.rw() as conn:
        if conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (body.status, task_id)).rowcount == 0:
            raise HTTPException(404, "unknown task")
    return {"ok": True}
