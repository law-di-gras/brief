"""A failed model call must never delete the facts we already have."""
import pytest

from backend import db
from backend.pipeline import llm, run
from tests.test_pipeline import FakeClio, ScriptedModel


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    model = ScriptedModel()
    state = {"fail": False}

    def call(model_name, system, user, tool_name, *a, **k):
        if state["fail"] and tool_name == "record_facts":
            raise llm.LLMError("simulated outage")
        return model(model_name, system, user, tool_name, *a, **k)

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "call_json", call)
    monkeypatch.setattr(run, "make_client", lambda user_id=None: FakeClio())
    return state


def test_failed_extraction_keeps_facts_and_retries(env):
    first = run.run_pipeline("7")
    assert first["status"] == "ok" and first["facts_kept"] == 2
    conn = db.connect()
    before = conn.execute("SELECT COUNT(*) n FROM facts").fetchone()["n"]
    assert before == 2

    env["fail"] = True
    second = run.run_pipeline("7", reextract=True)           # model is down for every batch
    assert second["status"] == "partial" and second["extraction_failed"] > 0
    assert conn.execute("SELECT COUNT(*) n FROM facts").fetchone()["n"] == before   # nothing deleted
    assert conn.execute("SELECT error FROM runs ORDER BY id DESC LIMIT 1").fetchone()["error"]

    env["fail"] = False
    third = run.run_pipeline("7")                              # nothing changed in Clio, but failed items retry
    assert third["status"] == "ok" and third["items_changed"] > 0 and third["facts_kept"] == 2
    assert conn.execute("SELECT COUNT(*) n FROM facts").fetchone()["n"] == before
