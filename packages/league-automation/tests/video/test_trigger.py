from datetime import UTC, datetime

from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.video.trigger import (
    AGENT,
    HELP,
    VideoRequests,
    is_video_request,
    video_trigger,
)

CHAT = "iMessage;+;chat123"
OTHER_CHAT = "iMessage;+;chat999"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TRADE = {"trade_id": 5, "trade_code": "T-2026-003", "status": "accepted", "terms": {}}
RESCINDED = {"trade_id": 6, "trade_code": "T-2026-004", "status": "rescinded", "terms": {}}


def msg(text: str, guid: str = "m1", thread: str | None = None, chat: str = CHAT):
    return InboundMessage(
        guid=guid,
        chat_guid=chat,
        sender_address="+15555550100",
        text=text,
        is_from_me=False,
        is_group=True,
        sent_at=NOW,
        thread_originator_guid=thread,
    )


class FakeTrades:
    def __init__(self, by_guid=None, by_code=None) -> None:
        self.by_guid = by_guid or {}
        self.by_code = by_code or {}

    def find_by_source_guid(self, guid):
        return self.by_guid.get(guid)

    def find_by_code(self, code):
        return self.by_code.get(code)


class FakeJobs:
    def __init__(self, existing: set[int] | None = None) -> None:
        self.enqueued: list[tuple] = []
        self.existing = existing or set()

    def enqueue(self, trade_id, trade_code, requested_guid):
        self.enqueued.append((trade_id, trade_code, requested_guid))
        return (7, False) if trade_id in self.existing else (1, True)


class FakeDelivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, run_id, agent, content):
        self.sent.append((agent, content))


class FakeConn:
    commits = 0

    def commit(self) -> None:
        self.commits += 1


def requests(trades=None, jobs=None, delivery=None, conn=None, lookup=None) -> VideoRequests:
    kwargs = {}
    if lookup is not None:
        kwargs["code_for_outbound_guid"] = lookup
    return VideoRequests(
        trades or FakeTrades(),
        jobs or FakeJobs(),
        delivery or FakeDelivery(),
        conn or FakeConn(),
        **kwargs,
    )


def test_a_request_is_tagged_and_about_a_video() -> None:
    assert is_video_request("@bot create trade video")
    assert is_video_request("@Bot make the video for this one")
    assert not is_video_request("@bot who should I trade for a RB")
    assert not is_video_request("create trade video")
    assert not is_video_request("@bottle video")


def test_a_reply_to_the_alert_queues_that_trade_and_says_so() -> None:
    jobs, delivery, conn = FakeJobs(), FakeDelivery(), FakeConn()
    requests(FakeTrades(by_guid={"alert-1": TRADE}), jobs, delivery, conn).handle(
        msg("@bot create trade video", guid="reply-1", thread="alert-1")
    )
    assert jobs.enqueued == [(5, "T-2026-003", "reply-1")]
    assert conn.commits == 1
    assert delivery.sent == [
        (AGENT, "🎬 Making the video for T-2026-003 — usually 5 to 10 minutes.")
    ]


def test_a_code_in_the_text_works_without_a_reply() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    requests(FakeTrades(by_code={"TEST-2026-002": TRADE}), jobs, delivery).handle(
        msg("@bot video for TEST-2026-002 please")
    )
    assert jobs.enqueued[0][1] == "T-2026-003"
    assert delivery.sent[0][1].startswith("🎬 Making the video for T-2026-003")


def test_a_reply_to_the_bots_confirmation_resolves_through_the_outbound_lookup() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    trades = FakeTrades(by_code={"T-2026-003": TRADE})
    requests(
        trades, jobs, delivery, lookup=lambda guid: "T-2026-003" if guid == "bot-1" else None
    ).handle(msg("@bot create trade video", thread="bot-1"))
    assert jobs.enqueued[0][1] == "T-2026-003"


def test_no_trade_found_asks_for_a_reply_or_a_code() -> None:
    jobs, delivery, conn = FakeJobs(), FakeDelivery(), FakeConn()
    requests(FakeTrades(), jobs, delivery, conn).handle(msg("@bot create trade video"))
    assert jobs.enqueued == [] and conn.commits == 0
    assert delivery.sent == [(AGENT, HELP)]


def test_a_rescinded_trade_gets_no_video() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    requests(FakeTrades(by_guid={"alert-2": RESCINDED}), jobs, delivery).handle(
        msg("@bot create trade video", thread="alert-2")
    )
    assert jobs.enqueued == []
    assert delivery.sent == [(AGENT, "T-2026-004 was rescinded, so no video for it.")]


def test_asking_twice_does_not_queue_twice() -> None:
    jobs, delivery = FakeJobs(existing={5}), FakeDelivery()
    requests(FakeTrades(by_guid={"alert-1": TRADE}), jobs, delivery).handle(
        msg("@bot create trade video", thread="alert-1")
    )
    assert delivery.sent == [(AGENT, "🎬 The video for T-2026-003 is already in the works.")]


def test_the_trigger_listens_only_in_the_alert_chats_and_ignores_its_own_posts() -> None:
    handled: list[str] = []

    class Recorder:
        def handle(self, m):
            handled.append(m.guid)

    trigger = video_trigger(Recorder(), frozenset({CHAT}))
    assert trigger.name == AGENT
    assert trigger.matches(msg("@bot create trade video"))
    assert not trigger.matches(msg("@bot create trade video", chat=OTHER_CHAT))
    assert not trigger.matches(msg("@bot advice please"))
    signed = "🎬 Making the video for T-2026-003 — usually 5 to 10 minutes."
    assert not is_signed(signed) or not trigger.matches(msg(signed))
    trigger.handle(msg("@bot create trade video", guid="g9"))
    assert handled == ["g9"]
