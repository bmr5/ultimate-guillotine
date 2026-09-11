"""One job through the worker: envelope, session, verification, artifact, delivery, record."""

import json
import threading
from datetime import UTC, datetime

import pytest

from ultimate_guillotine.agent.artifact import external_references
from ultimate_guillotine.agent.envelope import PROMPT_VERSION
from ultimate_guillotine.agent.records import Session
from ultimate_guillotine.agent.session import AgentReply, SessionNotFound
from ultimate_guillotine.agent.tools.source import FixtureSource
from ultimate_guillotine.agent.worker import (
    AGENT,
    ATTACHMENT_FAILED,
    COULD_NOT_FINISH,
    LOST_THREAD,
    AgentWorker,
    Job,
)
from ultimate_guillotine.ai.structured import AIUnavailable
from ultimate_guillotine.data.repositories import chat_guid_hash
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.models import MemberRef

CHAT = "iMessage;+;chat-test"
NOW = datetime(2026, 10, 8, 15, 5, tzinfo=UTC)
ASKER = MemberRef(5, "joinkey05", (), nickname="Member05")
MODEL = "fake-model"


def _msg(text: str, guid: str = "g1", thread: str | None = None) -> InboundMessage:
    return InboundMessage(guid=guid, chat_guid=CHAT, sender_address="+15555550100", text=text,
                          is_from_me=False, is_group=True, sent_at=NOW,
                          thread_originator_guid=thread)


def _reply(answer: dict, session_id: str = "sess-1") -> AgentReply:
    return AgentReply("Sure.\n```json\n" + json.dumps(answer) + "\n```", session_id, MODEL)


LOOKUP = {
    "kind": "answer", "chat_text": "Member01 has the most FAAB: 960.", "report": None,
    "facts": {"players": [], "faab": [{"member": "Member01", "amount": 960,
                                      "claim": "balance"}], "proposals": []},
    "source_line": "Source: FAAB as of 3:00pm",
}
RESEARCH = {
    **LOOKUP,
    "chat_text": "Holding Bowers — 1 idea\n1) Member02 holds Bench 05-0 for 40 FAAB\n"
                 "full write-up attached",
    "report": {"title": "Holding Bowers", "question": "Who could hold him?",
               "html_body": "<h2>Option</h2><p class='card'>Member02 for 40 FAAB.</p>",
               "sources": [{"url": "https://example.com/x", "claim": "out 1-2 weeks"}]},
    "facts": {"players": [{"player_id": "p05b0", "name": "Bench 05-0", "holder": "Member05"}],
              "faab": [{"member": "Member05", "amount": 40, "claim": "offer"}],
              "proposals": []},
}
WRONG = {**LOOKUP, "facts": {"players": [], "proposals": [],
                             "faab": [{"member": "Member01", "amount": 1, "claim": "balance"}]}}


class FakeClient:
    def __init__(self, *replies, on_run=None):
        self.replies = list(replies)
        self.calls: list[tuple[str, str | None]] = []
        self.on_run = on_run

    def run(self, query, *, resume=None):
        self.calls.append((query, resume))
        if self.on_run:
            self.on_run()
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeDelivery:
    def __init__(self, attachment_error=None):
        self.texts: list[str] = []
        self.files: list[tuple[str, bytes]] = []
        #: ``reply_to`` of every call, texts and files alike, in the order they were made.
        self.reply_tos: list[str | None] = []
        self.attachment_error = attachment_error

    def deliver(self, run_id, agent, content, *, reply_to=None):
        assert agent == AGENT
        self.reply_tos.append(reply_to)
        self.texts.append(content)
        return type("R", (), {"status": "sent", "outbound_id": len(self.texts),
                              "message_guid": f"p:0/BOT-{len(self.texts)}"})()

    def deliver_attachment(self, run_id, agent, filename, data, *, reply_to=None):
        self.reply_tos.append(reply_to)
        if self.attachment_error:
            raise self.attachment_error
        self.files.append((filename, data))
        return type("R", (), {"status": "sent", "outbound_id": 99, "message_guid": "p:0/ATT"})()


class FakeRuns:
    def __init__(self, running=()):
        self.finished: list[dict] = []
        self.sessions: dict[int, int] = {}
        self._running = list(running)

    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        self.finished.append({"run_id": run_id, "status": status, "error": error,
                              "input_version": input_version, "output_hash": output_hash})

    def set_session(self, run_id, session_id):
        self.sessions[run_id] = session_id

    def session_id_for(self, run_id):
        return self.sessions.get(run_id)

    def running_ids(self, agent):
        return list(self._running)


class FakeSessions:
    def __init__(self):
        self.created: list[tuple[str, str]] = []

    def create(self, hermes_session_id, chat_guid_hash):
        self.created.append((hermes_session_id, chat_guid_hash))
        return len(self.created)

    def get(self, session_id):
        hermes, chat = self.created[session_id - 1]
        return Session(session_id, hermes, chat, 1)


class FakeAnswers:
    def __init__(self):
        self.recorded = []

    def record(self, answer):
        self.recorded.append(answer)
        return len(self.recorded)


class FakeNotifier:
    def __init__(self):
        self.ops_sent, self.alerts_sent = [], []

    def ops(self, text):
        self.ops_sent.append(text)
        return True

    def alerts(self, text):
        self.alerts_sent.append(text)
        return True


def _worker(*replies, delivery=None, runs=None, on_run=None):
    parts = {
        "client": FakeClient(*replies, on_run=on_run), "source": FixtureSource(),
        "delivery": delivery or FakeDelivery(), "notifier": FakeNotifier(),
        "runs": runs or FakeRuns(), "sessions": FakeSessions(), "answers": FakeAnswers(),
        "clock": lambda: NOW,
    }
    return AgentWorker(**parts), parts


def test_a_lookup_is_answered_recorded_and_finished() -> None:
    worker, parts = _worker(_reply(LOOKUP))
    outcome = worker.run_job(Job(7, _msg("@bot who has the most FAAB"), ASKER, None))
    assert outcome == "answer"
    assert parts["delivery"].texts == [LOOKUP["chat_text"]] and parts["delivery"].files == []
    query, resume = parts["client"].calls[0]
    assert resume is None and "Asker: Member05" in query and "who has the most FAAB" in query
    assert "Local time Thu 10:05am (America/Chicago)" in query
    record = parts["answers"].recorded[0]
    assert record.question == "@bot who has the most FAAB" and record.report_html is None
    assert parts["sessions"].created[0][0] == "sess-1"
    assert parts["runs"].sessions == {7: 1}
    finished = parts["runs"].finished[0]
    assert finished["status"] == "succeeded"
    assert finished["input_version"] == f"{PROMPT_VERSION}:{MODEL}"


def test_a_research_answer_sends_the_text_then_the_artifact() -> None:
    worker, parts = _worker(_reply(RESEARCH))
    worker.run_job(Job(7, _msg("@bot who could hold Bowers for me"), ASKER, None))
    delivery = parts["delivery"]
    assert delivery.texts == [RESEARCH["chat_text"]]
    filename, data = delivery.files[0]
    assert filename == "holding-bowers-week-6.html"
    html = data.decode()
    assert "Member02 for 40 FAAB." in html and external_references(html) == []
    assert parts["answers"].recorded[0].report_html == html


def test_a_wrong_fact_goes_back_into_the_session_once() -> None:
    worker, parts = _worker(_reply(WRONG), _reply(LOOKUP, "sess-1"))
    worker.run_job(Job(7, _msg("@bot who has the most FAAB"), ASKER, None))
    retry_query, resume = parts["client"].calls[1]
    assert resume == "sess-1" and "Member01's FAAB is 960, not 1" in retry_query
    assert parts["delivery"].texts == [LOOKUP["chat_text"]]
    assert any("failed verification" in note for note in parts["notifier"].ops_sent)


def test_a_reply_without_a_session_id_retries_fresh_with_the_whole_turn() -> None:
    worker, parts = _worker(_reply(WRONG, session_id=""), _reply(LOOKUP, session_id=""))
    worker.run_job(Job(7, _msg("@bot who has the most FAAB"), ASKER, None))
    retry_query, resume = parts["client"].calls[1]
    assert resume is None
    assert "<<<MESSAGE\n@bot who has the most FAAB\nMESSAGE>>>" in retry_query
    assert "Member01's FAAB is 960, not 1" in retry_query
    assert parts["delivery"].texts == [LOOKUP["chat_text"]]
    # No session id, no session row: the run and the record point at nothing.
    assert parts["sessions"].created == [] and parts["runs"].sessions == {}
    assert parts["answers"].recorded[0].session_id is None


def test_two_failures_end_in_the_fixed_line() -> None:
    worker, parts = _worker(_reply(WRONG), _reply(WRONG))
    outcome = worker.run_job(Job(7, _msg("@bot who has the most FAAB"), ASKER, None))
    assert outcome == "rejected"
    assert parts["delivery"].texts == [COULD_NOT_FINISH]
    assert parts["delivery"].reply_tos == [CHAT]
    assert parts["runs"].finished[0]["status"] == "failed"
    assert parts["answers"].recorded == []


def test_verbose_research_chat_is_retried_without_truncating_the_report() -> None:
    report = {**RESEARCH["report"], "html_body":
              "<h2>Top option</h2><p>Hold plus DEF.</p><h2>Alternatives</h2><p>TE rental.</p>"}
    verbose = {**RESEARCH, "chat_text": "x" * 134, "report": report}
    concise = {**RESEARCH, "chat_text": "One top option. full write-up attached", "report": report}
    worker, parts = _worker(_reply(verbose), _reply(concise))
    assert worker.run_job(Job(7, _msg("@daddy help with my injured TE"), ASKER, None)) == "answer"
    assert len(parts["client"].calls) == 2
    assert "133" in parts["client"].calls[1][0]
    assert parts["delivery"].texts == [concise["chat_text"]]
    assert "Alternatives" in parts["delivery"].files[0][1].decode()


def test_a_hermes_failure_is_the_fixed_line_and_an_alert() -> None:
    worker, parts = _worker(AIUnavailable("hermes exited with code 1"))
    assert worker.run_job(Job(7, _msg("@bot hi"), ASKER, None)) == "failed"
    assert parts["delivery"].texts == [COULD_NOT_FINISH]
    assert parts["runs"].finished[0] == {"run_id": 7, "status": "failed",
                                         "error": "AIUnavailable", "input_version": None,
                                         "output_hash": None}
    assert parts["notifier"].alerts_sent


def test_a_follow_up_resumes_and_a_lost_thread_starts_fresh() -> None:
    session = Session(3, "sess-old", chat_guid_hash(CHAT), 2)
    worker, parts = _worker(_reply(LOOKUP, "sess-old"))
    worker.run_job(Job(8, _msg("what about Joel", thread="p:0/BOT-1"), ASKER, session))
    query, resume = parts["client"].calls[0]
    assert resume == "sess-old" and "follow-up" in query

    worker, parts = _worker(SessionNotFound("gone"), _reply(LOOKUP, "sess-new"))
    worker.run_job(Job(9, _msg("what about Joel", thread="p:0/BOT-1"), ASKER, session))
    assert [c[1] for c in parts["client"].calls] == ["sess-old", None]
    assert parts["delivery"].texts == [LOST_THREAD + LOOKUP["chat_text"]]


@pytest.mark.parametrize("origin,foreign", [(CHAT, "league"), ("league", CHAT)])
@pytest.mark.parametrize("parent_lookup", [False, True])
def test_foreign_session_never_reaches_the_model_even_if_parent_lookup_is_supplied(
    origin, foreign, parent_lookup,
):
    worker, parts = _worker(_reply(LOOKUP, "fresh-session"))
    session_id = parts["sessions"].create("foreign-session", chat_guid_hash(origin))
    parts["runs"].sessions[41] = session_id
    session = None if parent_lookup else parts["sessions"].get(session_id)
    question = _msg("@daddy follow up").model_copy(update={"chat_guid": foreign})
    job = Job(8, question, ASKER, session, parent_run_id=41 if parent_lookup else None)
    assert worker.run_job(job) == "answer"
    assert [resume for _, resume in parts["client"].calls] == [None]
    assert parts["delivery"].reply_tos == [foreign]
    assert not parts["answers"].recorded[0].is_follow_up


def test_running_question_sends_only_the_answer(monkeypatch) -> None:
    def no_timer(*args, **kwargs):
        raise AssertionError("must not schedule progress messages")
    monkeypatch.setattr(threading, "Timer", no_timer)
    def during_run():
        assert parts["delivery"].texts == []
    worker, parts = _worker(_reply(LOOKUP), on_run=during_run)
    worker.run_job(Job(7, _msg("@bot hi"), ASKER, None))
    assert parts["delivery"].texts == [LOOKUP["chat_text"]]


def test_every_send_replies_to_the_chat_that_asked() -> None:
    delivery = FakeDelivery(attachment_error=RuntimeError("boom"))
    worker, _ = _worker(_reply(RESEARCH), delivery=delivery)
    worker.run_job(Job(7, _msg("@bot hold Bowers"), ASKER, None))
    assert delivery.texts == [RESEARCH["chat_text"], ATTACHMENT_FAILED]
    assert delivery.reply_tos == [CHAT] * 3


def test_an_unknown_sender_is_said_to_the_agent() -> None:
    worker, parts = _worker(_reply({**LOOKUP, "kind": "clarification",
                                    "chat_text": "Which team are you?"}))
    worker.run_job(Job(7, _msg("@bot hi"), None, None))
    assert "unknown sender" in parts["client"].calls[0][0]
    assert parts["delivery"].texts == ["Which team are you?"]


def test_a_former_members_label_is_one_line() -> None:
    worker, parts = _worker(_reply(LOOKUP))
    former = MemberRef(99, "joinkey99", (), nickname="Old\n  Timer")
    worker.run_job(Job(7, _msg("@bot hi"), former, None))
    query = parts["client"].calls[0][0]
    assert "Asker: Old Timer\n" in query and "joinkey99" not in query
    assert parts["answers"].recorded[0].asker_member_id == 99


def test_an_attachment_failure_is_said_and_the_run_still_succeeds() -> None:
    delivery = FakeDelivery(attachment_error=RuntimeError("boom"))
    worker, parts = _worker(_reply(RESEARCH), delivery=delivery)
    worker.run_job(Job(7, _msg("@bot hold Bowers"), ASKER, None))
    assert delivery.texts == [RESEARCH["chat_text"], ATTACHMENT_FAILED]
    assert parts["runs"].finished[0]["status"] == "succeeded"
    assert parts["runs"].finished[0]["error"] == "attachment: RuntimeError"


def test_startup_settles_runs_the_restart_orphaned() -> None:
    worker, parts = _worker(runs=FakeRuns(running=(4, 5)))
    assert worker.reconcile_startup() == [4, 5]
    assert [f["status"] for f in parts["runs"].finished] == ["failed", "failed"]
    assert parts["delivery"].texts == []
    assert parts["notifier"].ops_sent == ["League Agent orphaned runs marked failed."]


def test_queued_questions_do_not_send_status_texts(monkeypatch) -> None:
    def no_timer(*args, **kwargs):
        raise AssertionError("must not schedule queue messages")
    monkeypatch.setattr(threading, "Timer", no_timer)
    worker, parts = _worker(_reply(LOOKUP), _reply(LOOKUP))
    for run in (7, 8):
        worker.submit(Job(run, _msg("@bot hi", guid=f"g{run}"), ASKER, None))
    assert parts["delivery"].texts == []
    while not worker._queue.empty():
        worker.run_job(worker._queue.get_nowait())
    assert parts["delivery"].texts == [LOOKUP["chat_text"]] * 2


def test_wait_until_idle_finishes_running_and_queued_answers() -> None:
    started, release, idle = threading.Event(), threading.Event(), threading.Event()

    def block():
        started.set()
        assert release.wait(5)

    worker, parts = _worker(_reply(LOOKUP), _reply(LOOKUP), on_run=block)
    wait = worker.wait_until_idle
    worker.submit(Job(7, _msg("@bot hi"), ASKER, None))
    worker.submit(Job(8, _msg("@bot again", guid="g2"), ASKER, None))
    worker.start()

    def drain():
        wait()
        idle.set()

    waiter = threading.Thread(target=drain, daemon=True)
    waiter.start()
    try:
        assert started.wait(2)
        assert not idle.wait(0.1)
    finally:
        release.set()
        waiter.join(2)
    assert idle.is_set()
    assert [run["run_id"] for run in parts["runs"].finished] == [7, 8]
    assert parts["delivery"].texts == [LOOKUP["chat_text"]] * 2


def test_unexpected_run_job_error_does_not_hang_drain_or_stop_next_job(monkeypatch, caplog):
    worker, _parts = _worker()
    wait = worker.wait_until_idle
    attempted = []

    def run_job(job):
        attempted.append(job.run_id)
        if job.run_id == 7:
            raise RuntimeError("private question must not be logged")

    monkeypatch.setattr(worker, "run_job", run_job)
    worker.submit(Job(7, _msg("@bot hi"), ASKER, None))
    worker.submit(Job(8, _msg("@bot again", guid="g2"), ASKER, None))
    worker.start()
    waiter = threading.Thread(target=wait, daemon=True)
    waiter.start()
    waiter.join(2)
    assert not waiter.is_alive()
    assert attempted == [7, 8]
    assert "RuntimeError" in caplog.text
    assert "private question" not in caplog.text
