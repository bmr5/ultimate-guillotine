"""Registered chats share one queue and retain their reply destinations."""

import pytest

from tests.agent.test_trigger import FakeContacts, FakeDelivery, FakeOutbound, FakeRuns
from tests.agent.test_worker import LOOKUP, RESEARCH, _reply, _worker
from tests.listener.test_processing import FakeReceipts, FakeSources, msg
from tests.listener.test_run import EmptyConnection, RecordingNotifier, _settings, _target
from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.listener import run as run_module

TEST = "iMessage;+;chat-test"
LEAGUE = "iMessage;+;chat-league"
LISTEN = "iMessage;+;listen-only"
UNREGISTERED = "iMessage;+;unregistered-env"


class Runs(FakeRuns):
    def is_agent_run(self, run_id, agent):
        return agent == "league-agent" and 1 <= run_id <= len(self.reserved)

    def reserve(self, agent, trigger, key, invoked_by=None):
        if any(item[2] == key for item in self.reserved):
            return None
        return super().reserve(agent, trigger, key, invoked_by)


@pytest.fixture
def configure(monkeypatch):
    runs, receipts, sources = Runs(), FakeReceipts(), FakeSources()
    monkeypatch.setattr(run_module, "find_hermes_binary", lambda: "/fake/hermes")
    monkeypatch.setattr(run_module, "RunRepository", lambda conn: runs)
    monkeypatch.setattr(run_module, "ReceiptRepository", lambda conn: receipts)
    monkeypatch.setattr(run_module, "SourceMessageRepository", lambda conn: sources)
    monkeypatch.setattr(run_module, "MemberContactRepository", lambda conn: FakeContacts())

    def build(mode, registered, worker, delivery, *, default_factory=False, outbound=None):
        class Targets:
            def __init__(self, conn):
                pass

            def get(self, mode):
                guid = {DeliveryMode.TEST: TEST, DeliveryMode.PRODUCTION: LEAGUE}[mode]
                return _target(mode.value, guid) if guid in registered else None

            def listen_chat_guids(self):
                return [LISTEN]

        monkeypatch.setattr(run_module, "TargetRepository", Targets)
        if outbound is not None:
            monkeypatch.setattr(run_module, "OutboundRepository", lambda conn: outbound)
        calls = []

        def factory(chat_guid):
            calls.append(chat_guid)
            return worker

        def default(settings, client, notifier, chat_guid, *, reconcile):
            calls.append((chat_guid, reconcile))
            return worker

        monkeypatch.setattr(run_module, "build_agent_worker", default)
        processor, allowed = run_module.build_processor(
            _settings(delivery_mode=mode, production_chat_guid=UNREGISTERED,
                      production_participant_fingerprint="fp"),
            EmptyConnection(), None, delivery, RecordingNotifier(),
            agent_worker_factory=None if default_factory else factory,
            reconcile_agent_runs=True,
        )
        return processor, allowed, calls

    return build


@pytest.mark.parametrize("mode,registered,expected", [
    ("production", (TEST, LEAGUE), (TEST, LEAGUE)),
    ("production", (TEST,), (TEST,)),
    ("production", (LEAGUE,), (LEAGUE,)),
    ("production", (), ()),
    ("test", (TEST, LEAGUE), (TEST,)),
    ("test", (TEST,), (TEST,)),
    ("test", (LEAGUE,), ()),
    ("test", (), ()),
    ("disabled", (TEST, LEAGUE), ()),
    ("disabled", (), ()),
])
def test_mode_and_missing_targets_gate_questions(configure, mode, registered, expected):
    worker, _ = _worker()
    delivery = FakeDelivery()
    processor, allowed, calls = configure(mode, registered, worker, delivery)
    assert calls == list(expected[:1])
    assert allowed == {*registered, LISTEN}
    for index, chat in enumerate((TEST, LEAGUE, LISTEN, UNREGISTERED)):
        question = msg("@daddy who has the most FAAB?", chat=chat, guid=f"g-{index}")
        matches = [t for t in processor._registry.match(question) if t.name == "league-agent"]
        assert len(matches) == int(chat in expected)
        outcome = processor.process(question, f"event-{index}")
        if chat in expected:
            assert outcome == "handled:league-agent"
        else:
            assert outcome in {"no_trigger", "ignored_chat"}
    assert [item[2] for item in delivery.reactions] == list(expected)
    assert worker._queue.qsize() == len(expected)


@pytest.mark.parametrize("chat", [TEST, LEAGUE])
def test_question_gets_one_receipt_then_answer_without_twenty_second_ack(configure, chat):
    worker, parts = _worker(_reply(LOOKUP))
    receipt = FakeDelivery()
    processor, _, _ = configure("production", (TEST, LEAGUE), worker, receipt)
    question = msg("@daddy who has the most FAAB?", chat=chat, guid="one-receipt")
    assert processor.process(question, question.guid) == "handled:league-agent"
    assert receipt.sent == []
    assert receipt.reactions == [(1, "one-receipt", chat)]
    assert parts["delivery"].texts == []
    assert worker.run_job(worker._queue.get_nowait()) == "answer"
    assert len(receipt.reactions) == 1
    assert parts["delivery"].texts == [LOOKUP["chat_text"]]
    assert parts["delivery"].reply_tos == [chat]


def test_two_chat_receipts_queue_pacing_answers_and_artifacts_keep_their_origin(configure):
    worker, parts = _worker(_reply(RESEARCH), _reply(RESEARCH, "sess-2"))
    receipt = FakeDelivery()
    processor, _, calls = configure("production", (TEST, LEAGUE), worker, receipt,
                                    default_factory=True)
    assert calls == [(TEST, True)]  # Build/start/reconcile entry point is called once.
    for index, chat in enumerate((TEST, LEAGUE)):
        question = msg("@daddy who could hold Bowers?", chat=chat, guid=f"g-{index}")
        assert processor.process(question, f"event-{index}") == "handled:league-agent"
        assert processor.process(question, f"event-{index}") == "duplicate"
        # A new webhook event for the same message also cannot reserve another run.
        assert processor.process(question, f"redelivery-{index}") == "handled:league-agent"
    assert receipt.sent == []
    assert receipt.reactions == [(1, "g-0", TEST), (2, "g-1", LEAGUE)]
    assert worker._queue.qsize() == 2
    assert parts["delivery"].texts == []
    for chat in (TEST, LEAGUE):
        job = worker._queue.get_nowait()
        assert job.message.chat_guid == chat
        assert worker.run_job(job) == "answer"
    assert parts["delivery"].texts == [
        RESEARCH["chat_text"], RESEARCH["chat_text"],
    ]
    assert len(parts["delivery"].files) == 2
    assert parts["delivery"].reply_tos == [TEST, TEST, LEAGUE, LEAGUE]
    assert worker._queue.empty()
    for chat in (TEST, LEAGUE):
        signed = msg(sign("@daddy hello"), chat=chat, from_me=True, guid=f"signed-{chat}")
        assert processor.process(signed, signed.guid) == "ignored_bot"
    assert len(receipt.reactions) == 2


@pytest.mark.parametrize("origin,foreign", [(TEST, LEAGUE), (LEAGUE, TEST)])
@pytest.mark.parametrize("completed", [False, True])
def test_completed_and_queued_parents_cannot_transfer_context_between_chats(
    configure, origin, foreign, completed,
):
    worker, parts = _worker(_reply(LOOKUP, "parent-session"),
                            _reply(LOOKUP, "foreign-fresh"), _reply(LOOKUP, "parent-session"))
    receipt = FakeDelivery()
    outbound = FakeOutbound({"parent-receipt": 1}, chat=origin)
    processor, _, calls = configure("production", (TEST, LEAGUE), worker, receipt,
                                    outbound=outbound)
    assert calls == [TEST]
    assert processor.process(msg("@daddy balance", chat=origin, guid="parent"), "p") == (
        "handled:league-agent"
    )
    if completed:
        assert worker.run_job(worker._queue.get_nowait()) == "answer"
    for tagged in (False, True):
        question = msg("@daddy follow up" if tagged else "follow up", chat=foreign,
                       guid=f"foreign-{tagged}").model_copy(
                           update={"thread_originator_guid": "parent-receipt"})
        result = processor.process(question, question.guid)
        assert result == ("handled:league-agent" if tagged else "no_trigger")
    same_chat = msg("follow up", chat=origin, guid="same-chat").model_copy(
        update={"thread_originator_guid": "parent-receipt"})
    assert processor.process(same_chat, same_chat.guid) == "handled:league-agent"
    while not worker._queue.empty():
        job = worker._queue.get_nowait()
        if job.message.chat_guid == foreign:
            assert job.parent_run_id is None and job.session is None
        elif job.message.guid == "same-chat":
            assert job.parent_run_id == 1
        assert worker.run_job(job) == "answer"
    assert [resume for _, resume in parts["client"].calls] == [None, None, "parent-session"]
    assert parts["delivery"].reply_tos == [origin, foreign, origin]
    assert [item[2] for item in receipt.reactions] == [origin, foreign, origin]
