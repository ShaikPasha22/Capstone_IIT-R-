import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from src.api import app, ADMIN_TOKEN, STORAGE_DIR, EXPOSE_ADMIN_TOKEN_ENDPOINT
from src.admin import resume

client = TestClient(app)


def teardown_function(_fn):
    # Never leave the shared storage/HALT file behind for other tests or a
    # dev server pointed at the same STORAGE_DIR.
    resume(STORAGE_DIR)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_console_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "CloudServe Support Console" in res.text


def test_samples_lists_validation_tickets():
    res = client.get("/api/samples")
    assert res.status_code == 200
    body = res.json()
    assert len(body) > 0
    assert "ticket_id" in body[0]


def test_ticket_decision_runs_the_pipeline():
    samples = client.get("/api/samples").json()
    ticket_id = samples[0]["ticket_id"]
    res = client.get(f"/api/ticket/{ticket_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["outcome"]["action"] in ("auto_respond", "escalate")
    assert isinstance(body["trace"], list)
    assert len(body["trace"]) >= 2


def test_ticket_decision_404_for_unknown_ticket():
    res = client.get("/api/ticket/DOES-NOT-EXIST")
    assert res.status_code == 404


def test_admin_status_defaults_to_not_halted():
    res = client.get("/admin/status")
    assert res.status_code == 200
    assert res.json() == {"halted": False}


def test_admin_halt_requires_token():
    res = client.post("/admin/halt")
    assert res.status_code == 403


def test_admin_halt_rejects_wrong_token():
    res = client.post("/admin/halt", headers={"X-Admin-Token": "not-the-token"})
    assert res.status_code == 403


def test_admin_halt_and_resume_with_correct_token():
    halt_res = client.post("/admin/halt", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert halt_res.status_code == 200
    assert client.get("/admin/status").json() == {"halted": True}

    resume_res = client.post("/admin/resume", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert resume_res.status_code == 200
    assert client.get("/admin/status").json() == {"halted": False}


def test_halted_ticket_escalates_end_to_end():
    client.post("/admin/halt", headers={"X-Admin-Token": ADMIN_TOKEN})
    samples = client.get("/api/samples").json()
    ticket_id = samples[0]["ticket_id"]
    res = client.get(f"/api/ticket/{ticket_id}")
    assert res.json()["outcome"]["action"] == "escalate"
    assert "halted" in res.json()["outcome"]["reason"].lower()


def test_stats_reports_unavailable_when_no_run_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = client.get("/api/stats")
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_reveal_token_returns_the_real_token_when_enabled():
    res = client.get("/admin/reveal-token")
    if EXPOSE_ADMIN_TOKEN_ENDPOINT:
        assert res.status_code == 200
        assert res.json() == {"token": ADMIN_TOKEN}
    else:
        assert res.status_code == 404
