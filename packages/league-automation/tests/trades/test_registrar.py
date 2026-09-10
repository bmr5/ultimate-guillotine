"""The Trade Registrar handler, driven entirely through fakes.

No database, no HTTP, no model call: every collaborator is a fake, so these
tests pin the handler's control flow -- which status each path returns, what it
delivers, and how it finishes the run -- rather than any storage detail.
"""

import hashlib
from datetime import UTC, datetime

from ultimate_guillotine.ai.structured import AIUnavailable, AIUsage
from ultimate_guillotine.config import Settings
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.registrar import TradeRegistrar, trade_trigger
from ultimate_guillotine.trades.repository import TradeAcceptance
from ultimate_guillotine.trades.resolve import MemberRef

CHAT = "iMessage;+;chat-test"


def msg(text: str, guid: str = "g1", from_me: bool = False, chat: str = CHAT) -> InboundMessage:
    return InboundMessage(guid=guid, chat_guid=chat, sender_address="+15555550100", text=text,
                          is_from_me=from_me, is_group=True, sent_at=datetime.now(UTC))


def good_extraction() -> ExtractedTrade:
    return ExtractedTrade(
        kind="permanent", parties=[ExtractedParty(name="Member01"), ExtractedParty(name="Member02")],
        assets=[ExtractedAsset(kind="player", from_party="Member01", to_party="Member02", player_name="Player Alpha", amount=None, unit=None, description=None),
                ExtractedAsset(kind="faab", from_party="Member02", to_party="Member01", player_name=None, amount=450, unit="faab", description=None)],
        effective_week=2, rental_return_condition=None, special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )


class FakeAI:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def parse(self, system, user, schema, name):
        if self.error:
            raise self.error
        return self.result, AIUsage("gen", 1, 1, "m")


class FakeDelivery:
    def __init__(self):
        self.sent = []

    def deliver(self, run_id, agent, content):
        self.sent.append((agent, content))
        return type("R", (), {"status": "sent", "outbound_id": 1, "message_guid": "x"})()


class FakeRuns:
    def __init__(self):
        self.reserved, self.finished = [], []

    def reserve(self, agent, trigger, key, invoked_by=None):
        self.reserved.append(key)
        return len(self.reserved)

    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        self.finished.append((run_id, status, error, output_hash, input_version))


class FakeTrades:
    def __init__(self, status="created"):
        self.status, self.accepted, self.rescinded = status, [], []

    def accept(self, proposal):
        self.accepted.append(proposal)
        return TradeAcceptance(self.status, 7, "T-2026-001", 1 if self.status != "revised" else 2, {"assets": []} if self.status == "revised" else None)

    def rescind(self, code, source_guid, occurred_at):
        self.rescinded.append(code)
        return True

    def find_by_context(self, key):
        return None

    def find_by_id(self, trade_id):
        return None


class FakeNotifier:
    def __init__(self):
        self.alerts_sent, self.ops_sent = [], []

    def alerts(self, text):
        self.alerts_sent.append(text); return True

    def ops(self, text):
        self.ops_sent.append(text); return True


class FakeMembers:
    def all_members(self):
        return [MemberRef(1, "Member01", ()), MemberRef(2, "Member02", ())]


class FakePlayers:
    def all_active(self):
        return [Player("p1", "Player Alpha", "WR", "KC", True)]


class FakeSources:
    """Source messages that have never seen this announcement before."""

    def __init__(self, repost=False):
        self.repost, self.asked = repost, []

    def find_repost(self, chat_hash, fingerprint, exclude_guid, since):
        self.asked.append((chat_hash, fingerprint, exclude_guid, since))
        return self.repost


class FakeConn:
    """A connection that records its transaction calls in a shared journal."""

    def __init__(self, journal):
        self.journal = journal

    def commit(self):
        self.journal.append("commit")

    def rollback(self):
        self.journal.append("rollback")


class SeasonCursor:
    """A cursor that answers each query the registrar actually issues.

    ``execute`` notes the SQL so ``fetchone`` can answer in kind: the season
    lookup gets the year row, and ``build_roster_index``'s ``max(synced_at)``
    probe gets ``(None,)`` -- no holdings rows for the season, which is the case
    that still reaches Sleeper. ``fetchall`` is empty for the same reason.
    """

    def __init__(self, row):
        self._row = row
        self._sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchone(self):
        if "from public.seasons" in self._sql:
            return self._row
        return (None,)

    def fetchall(self):
        return []


class SeasonConn(FakeConn):
    """A connection whose `public.seasons` table answers with one year."""

    def __init__(self, journal, row):
        super().__init__(journal)
        self._row = row

    def cursor(self):
        return SeasonCursor(self._row)


class JournalRuns(FakeRuns):
    """FakeRuns that notes each finish in the same journal as the connection,
    so a test can assert what happened before what."""

    def __init__(self, journal):
        super().__init__()
        self.journal = journal

    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        self.journal.append("finish")
        super().finish(run_id, status, output_hash, error, input_version)


class ExplodingMembers:
    """A repository that fails the way a dropped connection would."""

    def all_members(self):
        raise RuntimeError("connection is dead")


class ExplodingSleeper:
    def get_rosters(self, league_id):
        raise TimeoutError("sleeper is down")


class ContextTrades(FakeTrades):
    """Trades whose context lookup names an already-logged trade."""

    def find_by_context(self, key):
        return 7

    def find_by_id(self, trade_id):
        return {"trade_code": "T-2026-002"}


class RefusingTrades(FakeTrades):
    """Trades that carry no such code, as `rescind` reports with False."""

    def rescind(self, code, source_guid, occurred_at):
        self.rescinded.append(code)
        return False


def build(ai, trades=None, delivery=None, conn=None, members=None, runs=None, sleeper=None,
          sources=None, season=None):
    settings = Settings(database_url="postgresql://x:y@example.invalid/db", delivery_mode="test",
                        test_chat_guid=CHAT, _env_file=None)
    runs, notifier = runs or FakeRuns(), FakeNotifier()
    reg = TradeRegistrar(settings, conn, ai, delivery or FakeDelivery(), notifier,
                         members or FakeMembers(), FakePlayers(),
                         trades or FakeTrades(), runs,
                         sources_repo=sources if sources is not None else FakeSources(),
                         sleeper_client=sleeper, season=season,
                         clock=lambda: datetime(2026, 9, 10, tzinfo=UTC))
    return reg, runs, notifier


def test_created_trade_sends_confirmation_and_records_run() -> None:
    delivery = FakeDelivery()
    reg, runs, _ = build(FakeAI(good_extraction()), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")) == "created"
    assert delivery.sent[0][0] == "trade-registrar"
    assert delivery.sent[0][1].startswith("🚨 Trade T-2026-001 logged")
    assert runs.reserved == ["trade:g1"] and runs.finished[0][1] == "succeeded"
    # The run records which prompt and model produced it, and hashes what was sent.
    assert runs.finished[0][4] == "2026.2:m"
    assert runs.finished[0][3] == hashlib.sha256(delivery.sent[0][1].encode()).hexdigest()


def test_a_redelivered_message_is_skipped_without_calling_the_model() -> None:
    delivery = FakeDelivery()
    reg, runs, _ = build(FakeAI(error=AssertionError("model must not be called")),
                         delivery=delivery)
    runs.reserve = lambda agent, trigger, key, invoked_by=None: None
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02")) == "skipped"
    assert delivery.sent == [] and runs.finished == []


def test_retry_uses_a_per_attempt_idempotency_key() -> None:
    reg, runs, _ = build(FakeAI(good_extraction()))
    reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB"), retry=True)
    assert runs.reserved == [f"trade:g1:retry:{int(datetime(2026, 9, 10, tzinfo=UTC).timestamp())}"]


def test_duplicate_sends_nothing_and_marks_run_duplicate() -> None:
    delivery = FakeDelivery()
    reg, runs, _ = build(FakeAI(good_extraction()), trades=FakeTrades("duplicate"), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")) == "duplicate"
    assert delivery.sent == [] and runs.finished[0][1] == "duplicate"


def test_revised_sends_updated_message() -> None:
    delivery = FakeDelivery()
    reg, _, _ = build(FakeAI(good_extraction()), trades=FakeTrades("revised"), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 500 FAAB")) == "revised"
    assert delivery.sent[0][1].startswith("🚨 Trade T-2026-001 updated")


def test_unclear_sends_clarification_and_logs_no_trade() -> None:
    delivery, trades = FakeDelivery(), FakeTrades()
    unclear = good_extraction().model_copy(update={"kind": "unclear", "unclear_reason": "No counterparty named"})
    reg, runs, _ = build(FakeAI(unclear), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Player Alpha rented for 10")) == "clarification"
    assert trades.accepted == [] and "No counterparty named" in delivery.sent[0][1]
    assert runs.finished[0][1] == "succeeded"


def test_not_a_trade_stays_silent() -> None:
    delivery, trades = FakeDelivery(), FakeTrades()
    joke = good_extraction().model_copy(update={"kind": "not_a_trade", "parties": [], "assets": []})
    reg, runs, _ = build(FakeAI(joke), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Trade Alert 🚨 jk nobody is trading Member01 anything")) == "not_a_trade"
    assert delivery.sent == [] and trades.accepted == [] and runs.finished[0][1] == "succeeded"


def test_ai_unavailable_alerts_and_fails_run_without_sending() -> None:
    delivery = FakeDelivery()
    reg, runs, notifier = build(FakeAI(error=AIUnavailable("down")), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02")) == "failed"
    assert delivery.sent == [] and runs.finished[0][1] == "failed" and notifier.alerts_sent


def test_rescission_by_code_rescinds_without_calling_the_model() -> None:
    delivery, trades = FakeDelivery(), FakeTrades()
    reg, _, _ = build(FakeAI(error=AssertionError("model must not be called")), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Trade T-2026-001 is rescinded")) == "rescinded"
    assert trades.rescinded == ["T-2026-001"] and delivery.sent[0][1] == "🚨 Trade T-2026-001 rescinded"


def test_trigger_matches_alerts_and_ignores_signed_bot_text() -> None:
    reg, _, _ = build(FakeAI(good_extraction()))
    trigger = trade_trigger(reg, CHAT)
    assert trigger.name == "trade-registrar"
    assert trigger.matches(msg("🚨 Member01 sends Player Alpha to Member02"))
    assert not trigger.matches(msg("🚨 Trade T-2026-001 logged\nMember02 receives: Player Alpha\n— 🤖 Guillotine Bot", from_me=True))
    assert not trigger.matches(msg("no alert here"))


def test_a_failure_rolls_back_before_finishing_the_run() -> None:
    """The connection is not autocommit, so the failed statement left the
    transaction aborted: without a rollback first, `finish` itself raises and the
    run is stranded in `running` with nobody alerted."""
    journal, delivery = [], FakeDelivery()
    runs = JournalRuns(journal)
    reg, _, notifier = build(FakeAI(good_extraction()), delivery=delivery,
                             conn=FakeConn(journal), members=ExplodingMembers(), runs=runs)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02")) == "failed"
    assert [f[1] for f in runs.finished] == ["failed"]
    assert notifier.alerts_sent == ["Trade Registrar failed on a candidate: RuntimeError"]
    assert delivery.sent == []
    assert journal.index("rollback") < journal.index("finish")


def test_an_uncoded_rescission_resolves_its_target_by_context() -> None:
    delivery, trades = FakeDelivery(), ContextTrades()
    rescission = good_extraction().model_copy(update={"kind": "rescission"})
    reg, runs, _ = build(FakeAI(rescission), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 that Player Alpha deal is off")) == "rescinded"
    assert trades.rescinded == ["T-2026-002"]
    assert delivery.sent[0][1] == "🚨 Trade T-2026-002 rescinded"
    assert runs.finished[0][1] == "succeeded"


def test_rescinding_a_code_with_no_trade_asks_instead_of_claiming_it_happened() -> None:
    delivery, trades = FakeDelivery(), RefusingTrades()
    reg, runs, _ = build(FakeAI(error=AssertionError("model must not be called")),
                         trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Trade T-2026-009 is rescinded")) == "clarification"
    assert trades.rescinded == ["T-2026-009"]
    assert "T-2026-009" in delivery.sent[0][1]
    assert runs.finished[0][1] == "succeeded"


def test_a_sleeper_outage_degrades_to_an_empty_roster_index() -> None:
    """Roster evidence only disambiguates duplicate names: losing it must not stop
    a trade being logged."""
    delivery = FakeDelivery()
    reg, runs, notifier = build(FakeAI(good_extraction()), delivery=delivery,
                                conn=SeasonConn([], (2026,)), sleeper=ExplodingSleeper())
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")) == "created"
    assert notifier.ops_sent == ["Trade Registrar could not load rosters: TimeoutError"]
    assert runs.finished[0][1] == "succeeded"


def test_trigger_ignores_alerts_from_another_chat() -> None:
    """The registrar answers in one chat only: an alert in any other conversation
    the listener can see must never reach it."""
    reg, _, _ = build(FakeAI(error=AssertionError("model must not be called")))
    trigger = trade_trigger(reg, CHAT)
    assert not trigger.matches(
        msg("🚨 Member01 sends Player Alpha to Member02", chat="iMessage;+;chat-elsewhere")
    )


def test_rescission_by_a_test_mode_code_is_recognised() -> None:
    """Gate trades carry `TEST-` codes; rescinding one must work like any other."""
    delivery, trades = FakeDelivery(), FakeTrades()
    reg, _, _ = build(FakeAI(error=AssertionError("model must not be called")),
                      trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Trade TEST-2026-001 is rescinded")) == "rescinded"
    assert trades.rescinded == ["TEST-2026-001"]
    assert delivery.sent[0][1] == "🚨 Trade TEST-2026-001 rescinded"


ALERT_TEXT = "🚨 Member01 sends Player Alpha to Member02 for 450 FAAB"


def test_the_season_comes_from_the_seasons_table() -> None:
    """The league's season is a row, not the calendar year: a trade announced in
    January belongs to the season that is still running."""
    trades = FakeTrades()
    reg, _, _ = build(FakeAI(good_extraction()), trades=trades, conn=SeasonConn([], (2025,)))
    assert reg.handle(msg(ALERT_TEXT)) == "created"
    assert trades.accepted[0].season == 2025


def test_the_season_falls_back_to_the_clock_with_no_seasons_row() -> None:
    trades = FakeTrades()
    reg, _, _ = build(FakeAI(good_extraction()), trades=trades, conn=SeasonConn([], None))
    assert reg.handle(msg(ALERT_TEXT)) == "created"
    assert trades.accepted[0].season == 2026


def test_an_explicit_season_wins_over_the_table() -> None:
    """`ug trades replay` walks a past season and says so outright."""
    trades = FakeTrades()
    reg, _, _ = build(FakeAI(good_extraction()), trades=trades,
                      conn=SeasonConn([], (2026,)), season=2025)
    assert reg.handle(msg(ALERT_TEXT)) == "created"
    assert trades.accepted[0].season == 2025


def test_a_repost_of_a_recent_alert_is_a_duplicate_without_calling_the_model() -> None:
    """The same text posted twice under two GUIDs is one announcement: the
    fingerprint match is enough, and the model never sees the second copy."""
    delivery, trades = FakeDelivery(), FakeTrades()
    sources = FakeSources(repost=True)
    reg, runs, _ = build(FakeAI(error=AssertionError("model must not be called")),
                         trades=trades, delivery=delivery, sources=sources)
    assert reg.handle(msg(ALERT_TEXT, guid="g2")) == "duplicate"
    assert delivery.sent == [] and trades.accepted == []
    assert runs.finished[0][1] == "duplicate"
    # The message's own row is already recorded by the processor, so the lookup
    # has to exclude it or every alert would look like a repost of itself.
    assert sources.asked[0][2] == "g2"


class FinishThenFailConn(FakeConn):
    """A connection whose commit fails once the run has been finished.

    Stands in for a link that drops between `finish` and its commit: the run is
    already recorded `succeeded`, and marking it `failed` afterwards would be a
    lie about what happened.
    """

    def commit(self):
        super().commit()
        if "finish" in self.journal:
            raise RuntimeError("connection is dead")


def test_a_commit_failure_after_finishing_leaves_the_run_succeeded() -> None:
    journal = []
    runs = JournalRuns(journal)
    delivery = FakeDelivery()
    reg, _, notifier = build(FakeAI(good_extraction()), delivery=delivery,
                             conn=FinishThenFailConn(journal), runs=runs, season=2026)
    assert reg.handle(msg(ALERT_TEXT)) == "failed"
    assert [f[1] for f in runs.finished] == ["succeeded"]
    assert notifier.alerts_sent == ["Trade Registrar failed on a candidate: RuntimeError"]
