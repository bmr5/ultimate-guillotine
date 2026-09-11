from datetime import UTC, datetime
from types import SimpleNamespace

from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.video.trigger import (
    AGENT,
    HELP,
    VideoRequests,
    code_variants,
    help_text,
    is_video_request,
    match_trade,
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
    def __init__(self, by_guid=None, by_code=None, recent=None) -> None:
        self.by_guid = by_guid or {}
        self.by_code = by_code or {}
        self.recent = recent or []

    def find_by_source_guid(self, guid):
        return self.by_guid.get(guid)

    def find_by_code(self, code):
        return self.by_code.get(code)

    def list_recent(self, limit=10):
        return self.recent[:limit]


class FakeJobs:
    def __init__(self, existing: set[int] | None = None) -> None:
        self.enqueued: list[tuple] = []
        self.existing = existing or set()

    def enqueue(self, trade_id, trade_code, requested_guid, chat_guid=None):
        self.enqueued.append((trade_id, trade_code, requested_guid, chat_guid))
        return (7, False) if trade_id in self.existing else (1, True)


class FakeDelivery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def deliver(self, run_id, agent, content, reply_to=None, reply_to_message=None):
        self.sent.append((agent, content))
        self.reply_to = reply_to
        self.reply_to_message = reply_to_message


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
    assert is_video_request("@daddy create trade video")
    assert is_video_request("@daddy make the video for this one")
    assert not is_video_request("@daddy who should I trade for a RB")
    assert not is_video_request("create trade video")
    assert not is_video_request("@daddytle video")


def test_a_reply_to_the_alert_queues_that_trade_and_says_so() -> None:
    jobs, delivery, conn = FakeJobs(), FakeDelivery(), FakeConn()
    requests(FakeTrades(by_guid={"alert-1": TRADE}), jobs, delivery, conn).handle(
        msg("@daddy create trade video", guid="reply-1", thread="alert-1")
    )
    assert jobs.enqueued == [(5, "T-2026-003", "reply-1", CHAT)]
    assert conn.commits == 1
    assert delivery.sent == [(AGENT, "On it kitten, hold on for 10 minutes")]
    # Answered in the chat that asked, when the delivery service allows it.
    assert delivery.reply_to == CHAT
    # Reply to the video request itself, not the alert it replied to.
    assert delivery.reply_to_message.guid == "reply-1"
    assert delivery.reply_to_message.thread_originator_guid == "alert-1"


def test_a_code_in_the_text_works_without_a_reply() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    requests(FakeTrades(by_code={"TEST-2026-002": TRADE}), jobs, delivery).handle(
        msg("@daddy video for TEST-2026-002 please")
    )
    assert jobs.enqueued[0][1] == "T-2026-003"
    assert delivery.sent[0][1] == "On it kitten, hold on for 10 minutes"
    assert delivery.reply_to_message.guid == "m1"


def test_a_reply_to_the_bots_confirmation_resolves_through_the_outbound_lookup() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    trades = FakeTrades(by_code={"T-2026-003": TRADE})
    requests(
        trades, jobs, delivery, lookup=lambda guid: "T-2026-003" if guid == "bot-1" else None
    ).handle(msg("@daddy create trade video", thread="bot-1"))
    assert jobs.enqueued[0][1] == "T-2026-003"


def test_no_trade_found_asks_for_a_reply_or_a_code() -> None:
    jobs, delivery, conn = FakeJobs(), FakeDelivery(), FakeConn()
    requests(FakeTrades(), jobs, delivery, conn).handle(msg("@daddy create trade video"))
    assert jobs.enqueued == [] and conn.commits == 0
    assert (
        delivery.sent == [(AGENT, HELP)] and delivery.reply_to == CHAT and delivery.reply_to == CHAT
    )


def test_a_rescinded_trade_gets_no_video() -> None:
    jobs, delivery = FakeJobs(), FakeDelivery()
    requests(FakeTrades(by_guid={"alert-2": RESCINDED}), jobs, delivery).handle(
        msg("@daddy create trade video", thread="alert-2")
    )
    assert jobs.enqueued == []
    assert delivery.sent == [(AGENT, "T-2026-004 was rescinded, kitten, so no video for it.")]


def test_asking_twice_does_not_queue_twice() -> None:
    jobs, delivery = FakeJobs(existing={5}), FakeDelivery()
    requests(FakeTrades(by_guid={"alert-1": TRADE}), jobs, delivery).handle(
        msg("@daddy create trade video", thread="alert-1")
    )
    assert delivery.sent == [
        (AGENT, "Patience, kitten, the video for T-2026-003 is already in the works.")
    ]


def test_the_trigger_listens_only_in_the_alert_chats_and_ignores_its_own_posts() -> None:
    handled: list[str] = []

    class Recorder:
        def handle(self, m):
            handled.append(m.guid)

    trigger = video_trigger(Recorder(), frozenset({CHAT}))
    assert trigger.name == AGENT
    assert trigger.matches(msg("@daddy create trade video"))
    assert not trigger.matches(msg("@daddy create trade video", chat=OTHER_CHAT))
    assert not trigger.matches(msg("@daddy advice please"))
    signed = "On it kitten, hold on for 10 minutes"
    assert not is_signed(signed) or not trigger.matches(msg(signed))
    trigger.handle(msg("@daddy create trade video", guid="g9"))
    assert handled == ["g9"]


def test_a_test_code_still_resolves_after_the_trade_went_live() -> None:
    """Going live re-codes TEST-2026-002 to T-2026-002; the bot's old confirmation in
    the chat still says TEST, and a reply to it must find the trade (2026-09-10)."""
    assert code_variants("TEST-2026-002") == ["TEST-2026-002", "T-2026-002"]
    assert code_variants("T-2026-002") == ["T-2026-002", "TEST-2026-002"]
    live = {"trade_id": 4, "trade_code": "T-2026-002", "status": "accepted", "terms": {}}
    jobs, delivery = FakeJobs(), FakeDelivery()
    trades = FakeTrades(by_code={"T-2026-002": live})
    requests(
        trades, jobs, delivery, lookup=lambda guid: "TEST-2026-002" if guid == "bot-1" else None
    ).handle(msg("@daddy create trade video", thread="bot-1"))
    assert jobs.enqueued[0][:2] == (4, "T-2026-002")
    assert delivery.sent[0][1] == "On it kitten, hold on for 10 minutes"
    requests(trades, FakeJobs(), delivery).handle(msg("@daddy video for TEST-2026-002"))
    assert delivery.sent[-1][1] == "On it kitten, hold on for 10 minutes"


MEMBERS = [
    MemberRef(
        1, "DaOneTrueKING", ("derek",), nickname="Derek", sleeper_display_name="DaOneTrueKING"
    ),
    MemberRef(
        2, "chobes", ("charlie", "chobes"), nickname="Charlie", sleeper_display_name="chobes"
    ),
    MemberRef(3, "RylandRad", ("ryland",), nickname="Ryland", sleeper_display_name="RylandRad"),
    MemberRef(4, "benray887", ("ben r",), nickname="Ben R", sleeper_display_name="benray887"),
]
RENTAL = {
    "trade_id": 4,
    "trade_code": "T-2026-002",
    "status": "accepted",
    "terms": {
        "parties": [
            {"member_id": 1, "display_name": "DaOneTrueKING"},
            {"member_id": 2, "display_name": "chobes"},
        ],
        "assets": [
            {"kind": "player", "player_name": "Rhamondre Stevenson", "to_member_id": 2},
            {"kind": "player", "player_name": "Michael Wilson", "to_member_id": 1},
        ],
    },
}
OTHER = {
    "trade_id": 3,
    "trade_code": "T-2026-001",
    "status": "accepted",
    "terms": {
        "parties": [
            {"member_id": 3, "display_name": "RylandRad"},
            {"member_id": 4, "display_name": "benray887"},
        ],
        "assets": [{"kind": "player", "player_name": "Josh Jacobs", "to_member_id": 4}],
    },
}


def test_an_alerts_wording_picks_the_trade_by_the_names_in_it() -> None:
    alert = (
        "Trade alert 🚨\n\nDerek sends a 1 week Rhamondre rental to Charlie (no gulag protections)"
    )
    assert match_trade(alert, [OTHER, RENTAL], MEMBERS)["trade_code"] == "T-2026-002"
    assert match_trade("Trade alert 🚨 a rental to Charlie", [OTHER, RENTAL], MEMBERS) is None
    # Two names from each trade: a tie, so no guess.
    assert match_trade("Derek and Charlie and Ryland and Ben R", [OTHER, RENTAL], MEMBERS) is None
    assert match_trade("nothing here", [], MEMBERS) is None


def test_a_reply_to_a_reposted_alert_resolves_by_its_wording() -> None:
    sources = SimpleNamespace(
        get=lambda guid: (
            SimpleNamespace(
                excerpt="Trade alert 🚨\n\nDerek sends a 1 week Rhamondre rental to Charlie"
            )
            if guid == "repost-1"
            else None
        )
    )
    members = SimpleNamespace(all_members=lambda: MEMBERS)
    jobs, delivery = FakeJobs(), FakeDelivery()
    VideoRequests(
        FakeTrades(recent=[RENTAL, OTHER]),
        jobs,
        delivery,
        FakeConn(),
        sources=sources,
        members=members,
    ).handle(msg("@bot create trade video", thread="repost-1"))
    assert jobs.enqueued[0][:2] == (4, "T-2026-002")
    assert delivery.sent[0][1] == "On it kitten, hold on for 10 minutes"


def test_the_help_names_the_recent_trades_when_nothing_matched() -> None:
    labels = {1: "Derek", 2: "Charlie", 3: "Ryland", 4: "Ben R"}
    assert help_text([RENTAL, OTHER], labels) == (
        "I couldn't tie that to a logged trade, kitten. Recent: T-2026-002 (Derek ↔ Charlie); "
        "T-2026-001 (Ryland ↔ Ben R). Reply with the code and I'll make the video."
    )
    assert help_text([], labels) == HELP
    members = SimpleNamespace(all_members=lambda: MEMBERS)
    delivery = FakeDelivery()
    VideoRequests(
        FakeTrades(recent=[RENTAL, OTHER]), FakeJobs(), delivery, FakeConn(), members=members
    ).handle(msg("@bot create trade video"))
    assert delivery.sent[0][1].startswith(
        "I couldn't tie that to a logged trade, kitten. Recent: T-2026-002 (Derek ↔ Charlie)"
    )
