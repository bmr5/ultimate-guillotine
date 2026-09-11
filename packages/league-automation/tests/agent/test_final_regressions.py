"""Confirmed final-review failures exercised at their delivery boundary."""

from dataclasses import replace

import pytest

from tests.agent.test_worker import (
    ASKER,
    CHAT,
    LOOKUP,
    RESEARCH,
    WRONG,
    FakeRuns,
    Job,
    Session,
    _msg,
    _reply,
    _worker,
)
from ultimate_guillotine.agent.session import SessionNotFound
from ultimate_guillotine.agent.tools.names import PlayerInfo
from ultimate_guillotine.agent.worker import (
    COULD_NOT_FINISH,
    LOST_THREAD,
)
from ultimate_guillotine.ai.structured import AIUnavailable
from ultimate_guillotine.data.repositories import chat_guid_hash
from ultimate_guillotine.trades.models import MemberRef


@pytest.mark.parametrize("body,url", [
    ("<p>ben<span>@</span>example.com</p>", "https://example.com/x"),
    ("<p>d<span>ues</span> overdue</p>", "https://example.com/x"),
    ("<p><span>55555</span><span>50100</span></p>", "https://example.com/x"),
    ("<p>Source</p>", "https://example.com/?contact=ben@example.com"),
    ("<p>Source</p>", "https://example.com/?contact=ben%40example.com"),
    ("<p>Source</p>", "https://example.com/?contact=ben%2540example.com"),
    ("<p>Source</p>", "https://example.com/?name=O%27Neil"),
    ("<p>O'Neil</p>", "https://example.com/x"),
])
def test_private_artifact_is_rejected_before_record_or_delivery(body, url):
    answer = {**RESEARCH, "report": {
        "title": "Report", "html_body": body, "sources": [{"url": url, "claim": "source"}],
    }}
    worker, parts = _worker(_reply(answer), _reply(answer))
    parts["source"].members = lambda: [MemberRef(5, "O'Neil", (), nickname="Member05")]
    assert worker.run_job(Job(7, _msg("@bot question"), ASKER, None)) == "rejected"
    assert parts["delivery"].files == []
    assert parts["delivery"].texts == [COULD_NOT_FINISH]
    assert parts["answers"].recorded == []


@pytest.mark.parametrize("correction", [False, True])
def test_verification_refreshes_data_after_each_model_attempt(correction):
    attempt = 2 if correction else 1
    balance = 700 if correction else 960
    final = {**LOOKUP, "facts": {
        "faab": [{"member": f"fresh alias {attempt}", "amount": balance}],
        "players": [{"player_id": f"new{attempt}", "name": f"New Player {attempt}",
                     "holder": "free agent"}],
    }}
    worker, parts = _worker(*([_reply(WRONG)] if correction else []), _reply(final))
    original = parts["source"].snapshot()
    changed = replace(original, teams=tuple(
        replace(t, faab_remaining=1) if t.member_id == 1 else t for t in original.teams
    ))
    state = {"snapshot": changed, "members": [], "players": {}}
    reads = []
    parts["source"].snapshot = lambda *a, **kw: state["snapshot"]
    parts["source"].members = lambda: (reads.append("members"), state["members"])[1]
    parts["source"].players = lambda: (reads.append("players"), state["players"])[1]

    def during():
        call = len(parts["client"].calls)
        state["snapshot"] = replace(original, teams=tuple(
            replace(t, faab_remaining=960 if call == 1 else 700)
            if t.member_id == 1 else t for t in original.teams
        ))
        state["members"] = [MemberRef(1, "private-key", (f"fresh alias {call}",),
                                      nickname="Member01")]
        state["players"] = {f"new{call}": PlayerInfo(f"new{call}", f"New Player {call}",
                                                    "RB", "FIX", None)}
    parts["client"].on_run = during
    assert worker.run_job(Job(7, _msg("@bot balance"), ASKER, None)) == "answer"
    assert len(parts["client"].calls) == 1 + int(correction)
    assert reads.count("members") >= 1 + int(correction)
    assert reads.count("players") >= 1 + int(correction)


def test_orphan_reconciliation_never_delivers_to_a_chat():
    worker, parts = _worker(runs=FakeRuns(running=[1, 2]))
    worker.reconcile_startup()
    assert not parts["delivery"].texts and not parts["delivery"].reply_tos
    assert len(parts["notifier"].ops_sent) == 1


@pytest.mark.parametrize("reason", ["authentication failed", "process failed", "TimeoutExpired"])
def test_general_resume_failure_does_not_start_another_model_call(reason):
    worker, parts = _worker(AIUnavailable(reason), _reply(LOOKUP))
    session = Session(1, "old", chat_guid_hash(CHAT), 1)
    assert worker.run_job(Job(7, _msg("follow up"), ASKER, session)) == "failed"
    assert [c[1] for c in parts["client"].calls] == ["old"]
    assert parts["delivery"].texts == [COULD_NOT_FINISH]


def test_lost_thread_notice_is_budgeted_before_recording_or_delivery():
    long = {**LOOKUP, "chat_text": "x" * 1200}
    worker, parts = _worker(SessionNotFound("gone"), _reply(long), _reply(LOOKUP))
    session = Session(1, "old", chat_guid_hash(CHAT), 1)
    assert worker.run_job(Job(7, _msg("follow up"), ASKER, session)) == "answer"
    assert [c[1] for c in parts["client"].calls] == ["old", None, "sess-1"]
    assert "1200" in parts["client"].calls[2][0]
    assert parts["delivery"].texts == [LOST_THREAD + LOOKUP["chat_text"]]
    assert parts["answers"].recorded[0].chat_text == parts["delivery"].texts[0]
    assert len(parts["delivery"].texts[0]) <= 1200


def test_pending_progress_reply_resumes_completed_parent_once():
    from tests.agent.test_trigger import FakeContacts, FakeOutbound
    from tests.agent.test_trigger import FakeRuns as TriggerRuns
    from ultimate_guillotine.agent.trigger import FollowUpResolver, league_agent_trigger

    worker, parts = _worker(_reply(LOOKUP), _reply(LOOKUP))
    outbound = FakeOutbound({"p:0/BOT-1": 7})
    resolver_runs = TriggerRuns()
    resolver_runs.is_agent_run = lambda run, agent: run == 7
    trigger = league_agent_trigger(
        worker=worker, contacts=FakeContacts(), resolver=FollowUpResolver(
            outbound, resolver_runs, parts["sessions"],
        ), runs=TriggerRuns(), delivery=parts["delivery"], chat_guid=_msg("").chat_guid,
    )
    original_deliver = parts["delivery"].deliver

    def deliver(run, agent, text, **kwargs):
        result = original_deliver(run, agent, text, **kwargs)
        outbound.runs_by_guid[result.message_guid] = run
        return result
    parts["delivery"].deliver = deliver

    def during():
        if len(parts["client"].calls) != 1:
            return
        assert parts["delivery"].texts == []
        assert parts["runs"].sessions == {}
        reply = _msg("@bot what about next week", guid="g2", thread="p:0/BOT-1")
        assert trigger.matches(reply)
        trigger.handle(reply)
    parts["client"].on_run = during
    worker.submit(Job(7, _msg("@bot balance"), ASKER, None))
    worker.start()
    worker.wait_until_idle()
    assert [c[1] for c in parts["client"].calls] == [None, "sess-1"]
    assert len(parts["answers"].recorded) == 2
    assert parts["answers"].recorded[1].is_follow_up


def test_pending_parent_without_session_starts_fresh_with_notice():
    worker, parts = _worker(_reply(LOOKUP))
    assert worker.run_job(Job(7, _msg("follow up"), ASKER, None, parent_run_id=4)) == "answer"
    assert [c[1] for c in parts["client"].calls] == [None]
    assert parts["delivery"].texts == [LOST_THREAD + LOOKUP["chat_text"]]


def test_block_separators_do_not_fuse_separate_words_into_private_content():
    answer = {**RESEARCH, "report": {
        "title": "Report", "html_body": "<p>d</p><p>ues</p>", "sources": [],
    }}
    worker, parts = _worker(_reply(answer))
    assert worker.run_job(Job(7, _msg("@bot question"), ASKER, None)) == "answer"
    assert len(parts["delivery"].files) == 1
