"""Sessions, answers, and the two lookups a follow-up needs, against the real schema."""

from dataclasses import replace

import pytest

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


@pytest.mark.parametrize("state", ["sending", "sent"])
@pytest.mark.parametrize("origin,foreign", [("test", "league"), ("league", "test")])
def test_an_outbound_message_guid_resolves_only_in_its_chat(conn, state, origin, foreign) -> None:
    runs = RunRepository(conn)
    run_id = runs.reserve("league-agent", "webhook", "agent:records-2")
    outbound = OutboundRepository(conn)
    target = TargetRepository(conn).upsert_listen(origin, "records")
    outbound_id = outbound.reserve(run_id, target, "hello", "h" * 64)
    outbound.set_state(outbound_id, state, bluebubbles_guid="p:0/BOT-9")
    assert runs.session_id_for(run_id) is None  # Pending receipts need no session.
    assert outbound.run_id_for_guid("p:0/BOT-9", origin) == run_id
    assert outbound.run_id_for_guid("p:0/BOT-9", foreign) is None
    assert outbound.run_id_for_guid("p:0/NOBODY", origin) is None


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


def test_recent_questions_are_scoped_to_one_member_and_chat(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values ('Derek Context') returning id")
        derek_id = cur.fetchone()[0]
        cur.execute("insert into public.members (display_name) values ('Other Context') returning id")
        other_id = cur.fetchone()[0]
    runs = RunRepository(conn)
    answers = AgentAnswerRepository(conn)
    base = AnswerRecord(
        run_id=0, session_id=None, chat_guid_hash=CHAT_HASH, asker_member_id=derek_id,
        question="First Derek question", is_follow_up=False, kind="answer",
        chat_text="First answer", source_line="", report_title=None, report_html=None,
        facts={}, sources=[], prompt_version="2026.9", model="fake-model",
    )
    for number, (chat_hash, member_id, question) in enumerate((
        (CHAT_HASH, derek_id, "First Derek question"),
        (CHAT_HASH, other_id, "Other member question"),
        ("d" * 64, derek_id, "Other chat question"),
        (CHAT_HASH, derek_id, "Latest Derek question"),
    )):
        run_id = runs.reserve("league-agent", "webhook", f"agent:member-context-{number}")
        answers.record(replace(base, run_id=run_id, chat_guid_hash=chat_hash,
                               asker_member_id=member_id, question=question))
    result = answers.recent_for_member(CHAT_HASH, derek_id)
    assert [row.question for row in result] == ["Latest Derek question", "First Derek question"]
