"""Sessions, answers, and the two lookups a follow-up needs, against the real schema."""

from ultimate_guillotine.agent.records import (
    AgentAnswerRepository,
    AgentSessionRepository,
    AnswerRecord,
)
from ultimate_guillotine.data.repositories import (
    OutboundRepository,
    RunRepository,
    TargetRepository,
)

CHAT_HASH = "c" * 64


def _target_id(conn) -> int:
    return TargetRepository(conn).upsert_listen("iMessage;+;chat-records", "records")


def test_a_session_is_created_touched_and_read_back(conn) -> None:
    sessions = AgentSessionRepository(conn)
    session_id = sessions.create("hermes-abc", CHAT_HASH)
    sessions.touch(session_id)
    session = sessions.get(session_id)
    assert session is not None
    assert session.hermes_session_id == "hermes-abc"
    assert session.chat_guid_hash == CHAT_HASH
    assert session.turns == 2


def test_a_run_remembers_its_session_and_running_runs_are_listed(conn) -> None:
    runs = RunRepository(conn)
    run_id = runs.reserve("league-agent", "webhook", "agent:records-1")
    assert runs.running_ids("league-agent") == [run_id]
    session_id = AgentSessionRepository(conn).create("hermes-def", CHAT_HASH)
    runs.set_session(run_id, session_id)
    assert runs.session_id_for(run_id) == session_id
    runs.finish(run_id, "succeeded")
    assert runs.running_ids("league-agent") == []


def test_an_outbound_message_guid_resolves_to_its_run(conn) -> None:
    runs = RunRepository(conn)
    run_id = runs.reserve("league-agent", "webhook", "agent:records-2")
    outbound = OutboundRepository(conn)
    outbound_id = outbound.reserve(run_id, _target_id(conn), "hello", "h" * 64)
    outbound.set_state(outbound_id, "sent", bluebubbles_guid="p:0/BOT-9")
    assert outbound.run_id_for_guid("p:0/BOT-9") == run_id
    assert outbound.run_id_for_guid("p:0/NOBODY") is None


def test_an_answer_is_recorded_and_listed_newest_first(conn) -> None:
    runs = RunRepository(conn)
    run_id = runs.reserve("league-agent", "webhook", "agent:records-3")
    answers = AgentAnswerRepository(conn)
    record = AnswerRecord(
        run_id=run_id, session_id=None, chat_guid_hash=CHAT_HASH, asker_member_id=None,
        question="@bot who has the most FAAB", is_follow_up=False, kind="answer",
        chat_text="Member01, with 960.", source_line="Source: FAAB as of 3:00pm",
        report_title=None, report_html=None, facts={"faab": []}, sources=[],
        prompt_version="2026.1", model="fake-model",
    )
    answers.record(record)
    latest = answers.recent(1)
    assert len(latest) == 1
    assert latest[0].question == record.question
    assert latest[0].chat_text == record.chat_text
    assert latest[0].facts == {"faab": []}
