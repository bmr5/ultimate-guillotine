import threading
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from fastapi.testclient import TestClient

from ultimate_guillotine.agent.trigger import FollowUpResolver, league_agent_trigger
from ultimate_guillotine.listener.app import create_app
from ultimate_guillotine.listener.polling import POLL_INTERVAL_SECONDS, InboxRecovery
from ultimate_guillotine.listener.processing import InboundProcessor, TriggerRegistry
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient, InboundMessage

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def message(guid="question", chat="test", sent_at=NOW):
    return InboundMessage(guid=guid, chat_guid=chat, sender_address=None,
                          text="@daddy who has the most FAAB?", is_from_me=True,
                          is_group=True, sent_at=sent_at)


def real_processor():
    seen = set()

    def record(guid, status):
        if guid in seen:
            return False
        seen.add(guid)
        return True

    worker, delivery, runs = Mock(), Mock(), Mock()
    runs.reserve.side_effect = range(1, 100)
    registry = TriggerRegistry()
    for chat in ("test", "production"):
        registry.register(league_agent_trigger(
            worker=worker, contacts=Mock(), resolver=FollowUpResolver(Mock(), runs, Mock()),
            runs=runs, delivery=delivery, chat_guid=chat,
        ))
    processor = InboundProcessor({"test", "production"}, registry,
                                 SimpleNamespace(record=record), Mock())
    return processor, worker, delivery, runs


def test_missed_webhooks_ack_both_chats_before_model_and_dedupe():
    processor, worker, delivery, runs = real_processor()
    worker.submit.side_effect = lambda job: delivery.react.assert_any_call(
        job.run_id, job.message
    )
    client = Mock()
    client.messages_page.side_effect = lambda chat, **kw: ([message(chat, chat)], 1)
    recovery = InboxRecovery(client, ("test", "production"), processor.process,
                             now=lambda: NOW)
    for chat in ("test", "production"):
        recovery.scan(chat)
        assert processor.process(message(chat, chat), chat) == "duplicate"
        recovery.scan(chat)
    assert delivery.react.call_count == worker.submit.call_count == runs.reserve.call_count == 2


def test_paging_uses_raw_count_retains_cursor_and_overlaps_delayed_records():
    clock = [NOW]
    client, process = Mock(), Mock(return_value="duplicate")
    client.messages_page.side_effect = [([], 100), ([message()], 100), ([], 0), ([], 0)]
    recovery = InboxRecovery(client, ("test",), process, now=lambda: clock[0],
                             max_pages=2)
    recovery.scan("test")
    assert [call.kwargs["offset"] for call in client.messages_page.call_args_list] == [0, 100]
    clock[0] += timedelta(seconds=10)
    recovery.scan("test")
    assert client.messages_page.call_args.kwargs["offset"] == 200
    assert client.messages_page.call_args.kwargs["before"] == NOW
    clock[0] += timedelta(seconds=200)
    recovery.scan("test")
    call = client.messages_page.call_args.kwargs
    assert call["offset"] == 0
    assert call["after"] == NOW - timedelta(seconds=30)
    assert call["before"] == clock[0]


def test_failure_retries_same_page_without_logging_private_data(caplog):
    client = Mock()
    client.messages_page.side_effect = [RuntimeError("secret URL and chat"), ([], 0)]
    recovery = InboxRecovery(client, ("test",), Mock(), now=lambda: NOW)
    recovery.scan("test")
    recovery.scan("test")
    assert client.messages_page.call_count == 2
    assert "RuntimeError" in caplog.text
    assert "secret URL and chat" not in caplog.text


def test_one_blocked_chat_does_not_block_other_chat_or_shutdown():
    blocked, release, healthy = threading.Event(), threading.Event(), threading.Event()

    def page(chat, **kwargs):
        if chat == "test":
            blocked.set()
            release.wait(3)
        else:
            healthy.set()
        return [], 0

    recovery = InboxRecovery(SimpleNamespace(messages_page=page), ("test", "production"),
                             Mock(), now=lambda: NOW)
    recovery.start()
    try:
        assert blocked.wait(1) and healthy.wait(1)
        started = monotonic()
        recovery.stop()
        assert monotonic() - started < 1.5
        assert recovery.stopped.is_set()
    finally:
        release.set()
    for thread in recovery.threads:
        thread.join(1)
        assert not thread.is_alive()


def test_http_page_filters_reactions_without_losing_offset_count():
    def respond(request):
        assert request.url.params["offset"] == "100"
        assert request.url.params["before"] == str(int(NOW.timestamp() * 1000))
        assert request.extensions["timeout"]["read"] == 3.0
        return httpx.Response(200, json={"data": [
            {"guid": "reaction", "associatedMessageGuid": "old"},
            {"guid": "question", "text": "@daddy hi", "dateCreated": NOW.timestamp() * 1000},
        ]})

    client = BlueBubblesClient("http://example.test", "fake", httpx.Client(
        transport=httpx.MockTransport(respond)))
    messages, count = client.messages_page("test", after=NOW - timedelta(seconds=30),
                                           before=NOW, offset=100)
    assert count == 2
    assert [(msg.guid, msg.chat_guid) for msg in messages] == [("question", "test")]


def test_lifespan_recovery_uses_webhook_serialization_and_health_stays_responsive():
    entered, release = threading.Event(), threading.Event()
    active = []

    class Processor:
        def process(self, msg, event_id):
            active.append(event_id)
            if event_id == "polled":
                entered.set()
                release.wait(3)
            return "no_trigger"

    poll_client = Mock()
    poll_client.messages_page.return_value = ([message("polled")], 1)
    app = create_app(Processor(), Mock(), "secret", poll_client=poll_client,
                     poll_chat_guids=("test",))
    with TestClient(app) as client:
        assert entered.wait(1)
        assert client.get("/healthz").status_code == 200
        result = []
        post = threading.Thread(target=lambda: result.append(client.post(
            "/bluebubbles-webhook?password=secret", json={"type": "new-message", "data": {
                "guid": "webhook", "chatGuid": "test", "dateCreated": NOW.timestamp() * 1000,
            }})))
        post.start()
        assert active == ["polled"]
        release.set()
        post.join(2)
        assert result[0].status_code == 200
    assert active == ["polled", "webhook"]


def test_recent_overlap_catches_delayed_insert_and_skips_history_and_cached_receipts():
    clock = [NOW]
    records = [message("old", sent_at=NOW - timedelta(days=1)),
               message("outside-startup", sent_at=NOW - timedelta(seconds=31)),
               message("first", sent_at=NOW - timedelta(seconds=29))]
    processor, worker, delivery, runs = real_processor()
    process = Mock(wraps=processor.process)

    def page(chat, after, before, offset, limit):
        result = [msg for msg in records if after <= msg.sent_at <= before]
        return result[offset:offset + limit], len(result[offset:offset + limit])

    recovery = InboxRecovery(SimpleNamespace(messages_page=page), ("test",), process,
                             now=lambda: clock[0])
    recovery.scan("test")
    clock[0] += timedelta(seconds=10)
    records.append(message("delayed", sent_at=NOW - timedelta(seconds=20)))
    recovery.scan("test")
    recovery.scan("test")
    assert [call.args[0].guid for call in process.call_args_list] == ["first", "delayed"]
    assert runs.reserve.call_count == delivery.react.call_count == worker.submit.call_count == 2


def test_equal_timestamp_backlog_beyond_page_budget_is_not_dropped():
    records = [message(str(i)) for i in range(601)]
    process = Mock(return_value="no_trigger")

    def page(chat, after, before, offset, limit):
        return records[offset:offset + limit], len(records[offset:offset + limit])

    recovery = InboxRecovery(SimpleNamespace(messages_page=page), ("test",), process,
                             now=lambda: NOW)
    recovery.scan("test")
    assert process.call_count == 500
    recovery.scan("test")
    assert process.call_count == 601
    recovery.scan("test")
    assert process.call_count == 601


def test_loop_checks_every_ten_seconds_without_waiting_for_model():
    processor, worker, delivery, _runs = real_processor()
    clock = [NOW]
    arrival = NOW + timedelta(seconds=1)
    client = Mock()
    client.messages_page.side_effect = lambda *args, **kwargs: (
        ([message(sent_at=arrival)], 1) if clock[0] >= arrival else ([], 0)
    )
    recovery = InboxRecovery(client, ("test",), processor.process, now=lambda: clock[0])
    waits = []

    class FakeStop:
        def is_set(self):
            return len(waits) == 2

        def wait(self, seconds):
            waits.append(seconds)
            clock[0] += timedelta(seconds=POLL_INTERVAL_SECONDS)

    recovery.stopped = FakeStop()
    recovery._loop("test")
    assert all(9 <= seconds <= 10 for seconds in waits)
    delivery.react.assert_called_once_with(1, worker.submit.call_args.args[0].message)
    delivery.deliver.assert_not_called()
    assert worker.submit.call_count == 1
    assert (clock[0] - arrival).total_seconds() < 30


def test_http_poll_does_not_hold_processing_lock():
    entered, release = threading.Event(), threading.Event()

    def page(*args, **kwargs):
        entered.set()
        release.wait(3)
        return [], 0

    processor = Mock()
    processor.process.return_value = "no_trigger"
    app = create_app(processor, Mock(), "secret",
                     poll_client=SimpleNamespace(messages_page=page), poll_chat_guids=("test",))
    with TestClient(app) as client:
        try:
            assert entered.wait(1)
            response = client.post("/bluebubbles-webhook?password=secret", json={
                "type": "new-message", "data": {"guid": "webhook", "chatGuid": "test"},
            })
            assert response.status_code == 200
            assert client.get("/healthz").status_code == 200
        finally:
            release.set()
    processor.process.assert_called_once()
