"""Agent fallback pipeline: all 6 emails, the #1043 demo run, approval, and the LLM steps with a fake model."""
import json

import pytest

from app import config
from app.ai import agent_core

EXPECTED = {"e1": "order_status", "e2": "stock_order", "e3": "credit", "e4": "complaint", "e5": "price_list",
            "e6": "no_action"}


@pytest.mark.parametrize("email_id,intent", EXPECTED.items())
def test_all_emails_fallback(client, email_id, intent):
    r = client.post(f"/api/agent/run/{email_id}").json()
    assert r["intent"] == intent
    names = [s["name"] for s in r["trace"]]
    assert names[:2] == ["read_email", "classify_intent"]
    if intent == "no_action":
        assert r["draft"] is None and r["task"] is None and r["status"] == "no_action"
    else:
        assert r["draft"]["body"] and r["task"]["title"] and r["status"] == "awaiting_approval"


def test_1043_run_and_approve(client):
    r = client.post("/api/agent/run/e1").json()
    names = [s["name"] for s in r["trace"] if s["type"] == "tool_call"]
    assert names == ["get_order_status", "check_stock", "get_credit_status", "create_order_draft"]
    body = r["draft"]["body"]
    assert "#1043" in body and "Dispatched" in body and "50 cartons of SMC Plus" in body
    assert r["task"]["assignee"] == "Area sales manager – Chattogram" and r["task"]["priority"] == "high"

    tasks_before = len(client.get("/api/tasks").json())
    a = client.post(f"/api/agent/approve/{r['run_id']}", json={"body": body + "\nEdited by reviewer."}).json()
    assert a["order"]["status"] == "On hold"  # agent orders never auto-approve
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == tasks_before + 1 and any(t["created_by"] == "agent" for t in tasks)
    assert client.post(f"/api/agent/approve/{r['run_id']}").status_code == 409  # no double send
    inbox = {e["id"]: e for e in client.get("/api/agent/inbox").json()}
    assert inbox["e1"]["status"] == "approved"


def test_bangla_email_gets_bangla_reply(client):
    r = client.post("/api/agent/run/e2").json()
    assert r["draft"]["lang"] == "bn" and "কার্টন" in r["draft"]["body"]
    assert r["order"]["lines"][0]["product"] == "ORSaline-N" and r["order"]["lines"][0]["cartons"] == 120


def test_credit_email_numbers(client):
    r = client.post("/api/agent/run/e3").json()
    assert "৯২%" in r["draft"]["body"] and r["task"]["assignee"] == "Finance"


def test_other_distributors_order_is_not_disclosed(client):
    email = {"id": "x", "from": "rng-01@example.com", "distributor_code": "RNG-01", "subject": "status",
             "body": "Where is my order #1043?", "lang": "en"}
    r = agent_core.run_agent(email, use_llm=False)
    assert "could not find order #1043" in r["draft"]["body"] and "Dispatched" not in r["draft"]["body"]


def test_discard(client):
    r = client.post("/api/agent/run/e4").json()
    assert client.post(f"/api/agent/discard/{r['run_id']}").json()["ok"]
    assert client.post(f"/api/agent/approve/{r['run_id']}").status_code == 409


def test_llm_steps_with_fake_model(client, monkeypatch):
    calls = []

    def fake_chat(messages, json_mode=True, num_predict=256):
        calls.append(json_mode)
        if json_mode:  # understand: a bad intent must be replaced by the regex one
            return json.dumps({"intent": "banana", "order_ids": [1043], "summary_en": "Asks about #1043 and 50 SMC Plus.",
                               "urgency": "high"})
        return "Dear Chattogram Distributor 02, order #1043 is Dispatched and will arrive in 1-2 days. Regards."

    monkeypatch.setattr(agent_core, "chat", fake_chat)
    email = next(e for e in agent_core.load_inbox() if e["id"] == "e1")
    r = agent_core.run_agent(email, use_llm=True)
    assert calls == [True, False]
    assert r["intent"] == "order_status" and r["draft"]["writer"] == "llm"
    assert r["task"]["description"].startswith("Asks about #1043")


def test_llm_timeout_falls_back_per_step(client, monkeypatch):
    def down(*a, **k):
        raise agent_core.LLMUnavailable("timeout")

    monkeypatch.setattr(agent_core, "chat", down)
    email = next(e for e in agent_core.load_inbox() if e["id"] == "e1")
    r = agent_core.run_agent(email, use_llm=True)
    assert r["draft"]["writer"] == "template" and sum(s["name"] == "llm_fallback" for s in r["trace"]) == 2


def test_task_board_patch(client):
    t = client.get("/api/tasks").json()[0]
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "Done"}).json()["ok"]
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "Nope"}).status_code == 422


def test_cached_agent_run_is_reused(client, tmp_path, monkeypatch):
    from app import cache

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "c.json")
    email = next(e for e in agent_core.load_inbox() if e["id"] == "e1")
    fake = agent_core.run_agent(email, use_llm=False)
    assert not cache.put_agent("e1", fake)  # template runs are not cached
    fake["draft"]["writer"] = "llm"
    fake["draft"]["body"] = "CACHED BODY"
    assert cache.put_agent("e1", fake)
    assert client.post("/api/agent/run/e1").json()["draft"]["body"] == "CACHED BODY"


def test_reply_with_invented_number_falls_back(client, monkeypatch):
    def fake_chat(messages, json_mode=True, num_predict=256):
        if json_mode:
            return json.dumps({"summary_en": "x"})
        return "Dear Chattogram Distributor 02, order #1043 total is 36.30 lakh BDT and is Dispatched. Regards."

    monkeypatch.setattr(agent_core, "chat", fake_chat)
    email = next(e for e in agent_core.load_inbox() if e["id"] == "e1")
    r = agent_core.run_agent(email, use_llm=True)
    assert r["draft"]["writer"] == "template"
    assert any("not in the ERP data" in str(s["output"]) for s in r["trace"] if s["name"] == "llm_fallback")
