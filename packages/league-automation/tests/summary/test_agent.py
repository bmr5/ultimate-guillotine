"""The agent: build, simulate, compose, store, deliver -- and every way it stops short.

Fakes stand in for the repository, the delivery service, the notifier and the
model, each one recording what it was asked, so a test asserts on what the agent
did rather than on what a mock was told to say.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.summary.helpers import NOW, done_team, snapshot, starter, team
from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable, AIUsage
from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.messages.delivery import DeliveryResult, TargetMismatch
from ultimate_guillotine.summary.agent import (
    AGENT,
    EodSummaryAgent,
    build_packet,
    input_version,
    recap_kind,
)
from ultimate_guillotine.summary.color import PROMPT_VERSION, EodColor
from ultimate_guillotine.summary.survival import MODEL_VERSION


def _league():
    return snapshot((done_team(1, "100"), done_team(2, "90"), done_team(3, "80"),
                     team(4, points="60", starters=(starter("remaining", projected="10"),))))


@dataclass
class FakeRepo:
    already_sent: bool = False
    snapshots: list = field(default_factory=list)
    recaps: list = field(default_factory=list)
    sent: list = field(default_factory=list)
    versions: list = field(default_factory=list)

    def sent_today(self, season_id, week, kind) -> bool:
        return self.already_sent

    def record_snapshot(self, season_id, week, window, snap, result, now) -> bool:
        self.snapshots.append((season_id, week, window, result.input_hash))
        return True

    def record_recap(self, season_id, week, kind, prompt_version, facts_hash, body) -> int:
        self.recaps.append((season_id, week, kind, prompt_version, facts_hash, body))
        return len(self.recaps)

    def mark_sent(self, recap_id) -> None:
        self.sent.append(recap_id)

    def set_input_version(self, run_id, version) -> None:
        self.versions.append((run_id, version))


@dataclass
class FakeDelivery:
    failure: Exception | None = None
    attachment_failure: Exception | None = None
    calls: list = field(default_factory=list)
    attachments: list = field(default_factory=list)

    def deliver(self, run_id, agent, content):
        self.calls.append((run_id, agent, content))
        if self.failure is not None:
            raise self.failure
        return DeliveryResult("sent", 1, "guid-1")

    def deliver_attachment(self, run_id, agent, filename, data):
        self.attachments.append((run_id, agent, filename, len(data)))
        if self.attachment_failure is not None:
            raise self.attachment_failure
        return DeliveryResult("sent", 2, "guid-2")


@dataclass
class FakeNotifier:
    ops_notes: list = field(default_factory=list)
    drafts_notes: list = field(default_factory=list)
    alerts_notes: list = field(default_factory=list)

    def ops(self, text) -> bool:
        self.ops_notes.append(text)
        return True

    def drafts(self, text) -> bool:
        self.drafts_notes.append(text)
        return True

    def alerts(self, text) -> bool:
        self.alerts_notes.append(text)
        return True


class FakeAI:
    def __init__(self, answer=None, failure: Exception | None = None) -> None:
        self.answer = answer or EodColor(headline="Knives out", blurb="Member04 is at 60.")
        self.failure = failure
        self.calls = 0

    def parse(self, system, user, schema, schema_name):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.answer, AIUsage("s", 0, 0, "fake-model")


class FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _agent(*, mode=DeliveryMode.TEST, ai=None, repo=None, delivery=None, notifier=None,
           conn=None):
    return EodSummaryAgent(
        SimpleNamespace(delivery_mode=mode),
        conn if conn is not None else FakeConn(),
        ai,
        delivery if delivery is not None else FakeDelivery(),
        notifier if notifier is not None else FakeNotifier(),
        repo if repo is not None else FakeRepo(),
    )


# -- the packet -----------------------------------------------------------


def test_the_packet_carries_odds_when_the_schedule_and_the_coverage_allow() -> None:
    packet = build_packet(_league(), simulations=50)
    assert packet.result is not None
    assert packet.no_odds_reason is None
    assert packet.coverage_pct == Decimal(100)


def test_no_schedule_means_no_odds_and_says_so() -> None:
    packet = build_packet(snapshot(_league().teams, schedule_available=False,
                                   day_state="unknown"), simulations=50)
    assert packet.result is None
    assert packet.no_odds_reason == "game status unavailable"


def test_coverage_under_the_gate_means_no_odds_and_names_the_coverage() -> None:
    teams = (
        done_team(1, "100"),
        team(2, starters=tuple(starter("remaining", pid=f"a{i}") for i in range(10))),
        team(3, starters=(starter("remaining", projected=None),)),
    )
    packet = build_packet(snapshot(teams), simulations=50)
    assert packet.result is None
    assert packet.coverage_pct == Decimal("90.91")
    assert packet.no_odds_reason == (
        "projections cover 90.91% of the starters still to play, under the 95% gate"
    )


# -- composing -------------------------------------------------------------


def test_compose_without_a_model_is_the_deterministic_message() -> None:
    composed = _agent().compose(_league(), NOW, simulations=50)
    assert "🔥" not in composed.text
    assert composed.color is None
    assert composed.model is None
    assert composed.facts in composed.text


def test_compose_also_yields_the_short_text_and_the_artifact() -> None:
    """The chat gets the short text and the file; the full text is the record."""
    composed = _agent(ai=FakeAI()).compose(_league(), NOW, simulations=50)
    assert composed.short.startswith("🗡️ GUILLOTINE EOD · Week 1 · Sunday")
    assert "🔥 Knives out" in composed.short
    assert "Full board attached" in composed.short
    assert "📊 THE BOARD" not in composed.short
    assert composed.html.startswith("<!doctype html>")
    assert "Knives out" in composed.html and "The board" in composed.html
    assert composed.filename == "guillotine-eod-week-1-2026-09-13.html"


def test_compose_with_a_faithful_model_adds_the_colour_and_records_the_model() -> None:
    composed = _agent(ai=FakeAI()).compose(_league(), NOW, simulations=50)
    assert "🔥 Knives out" in composed.text
    assert composed.model == "fake-model"


def test_a_colour_that_invents_a_number_is_dropped_and_said_in_ops() -> None:
    notifier = FakeNotifier()
    ai = FakeAI(EodColor(headline="Knives out", blurb="Member04 is at 61.7."))
    composed = _agent(ai=ai, notifier=notifier).compose(_league(), NOW, simulations=50)
    assert "🔥" not in composed.text
    assert composed.model is None
    assert notifier.ops_notes == ["EOD summary colour declined: a number not in the facts: 61.7"]


@pytest.mark.parametrize("failure", [AIUnavailable("down"), AIInvalidOutput("junk")])
def test_a_model_outage_is_no_colour_and_no_failure(failure: Exception) -> None:
    notifier = FakeNotifier()
    composed = _agent(ai=FakeAI(failure=failure), notifier=notifier).compose(
        _league(), NOW, simulations=50
    )
    assert "🔥" not in composed.text
    assert notifier.ops_notes == [
        f"EOD summary colour unavailable: {failure.__class__.__name__}"
    ]


def test_use_ai_false_never_calls_the_model() -> None:
    ai = FakeAI()
    _agent(ai=ai).compose(_league(), NOW, use_ai=False, simulations=50)
    assert ai.calls == 0


# -- running ---------------------------------------------------------------


def test_a_test_mode_run_stores_previews_delivers_and_records() -> None:
    repo, delivery, notifier, conn = FakeRepo(), FakeDelivery(), FakeNotifier(), FakeConn()
    agent = _agent(ai=FakeAI(), repo=repo, delivery=delivery, notifier=notifier, conn=conn)

    outcome = agent.run(_league(), NOW, run_id=7, simulations=50)

    assert outcome.status == "sent"
    assert outcome.odds is True
    assert outcome.model == "fake-model"
    kind = recap_kind(NOW)
    assert kind == "eod:2026-09-13"
    assert repo.snapshots[0][:3] == (1, 1, kind)
    assert repo.recaps[0][:4] == (1, 1, kind, PROMPT_VERSION)
    assert repo.recaps[0][5] == outcome.text
    assert repo.sent == [1]
    assert repo.versions == [(7, f"{MODEL_VERSION}:{PROMPT_VERSION}:fake-model")]
    # The short text goes first, then the file, under the same run.
    assert outcome.text.startswith("🗡️ GUILLOTINE EOD") and "Full board attached" in outcome.text
    assert delivery.calls == [(7, AGENT, outcome.text)]
    assert len(delivery.attachments) == 1
    run_id, agent, filename, size = delivery.attachments[0]
    assert (run_id, agent, filename) == (7, AGENT, "guillotine-eod-week-1-2026-09-13.html")
    assert size > 1000
    assert notifier.drafts_notes[0].startswith(f"[{AGENT}] [test] preview · {filename}\n")
    assert outcome.text in notifier.drafts_notes[0]
    assert conn.commits >= 2


def test_a_night_already_posted_is_left_alone() -> None:
    repo, delivery, ai = FakeRepo(already_sent=True), FakeDelivery(), FakeAI()
    outcome = _agent(ai=ai, repo=repo, delivery=delivery).run(_league(), NOW, run_id=7)
    assert outcome.status == "already_sent"
    assert delivery.calls == [] and repo.recaps == [] and ai.calls == 0


def test_force_posts_again_the_same_night() -> None:
    repo, delivery = FakeRepo(already_sent=True), FakeDelivery()
    outcome = _agent(repo=repo, delivery=delivery).run(_league(), NOW, run_id=7, force=True,
                                                       simulations=50)
    assert outcome.status == "sent"
    assert len(delivery.calls) == 1


def test_a_disabled_run_keeps_the_draft_and_the_preview_and_sends_nothing() -> None:
    repo, delivery, notifier = FakeRepo(), FakeDelivery(), FakeNotifier()
    outcome = _agent(mode=DeliveryMode.DISABLED, repo=repo, delivery=delivery,
                     notifier=notifier).run(_league(), NOW, run_id=7, simulations=50)
    assert outcome.status == "draft"
    assert delivery.calls == [] and delivery.attachments == []
    assert repo.sent == []
    assert len(repo.recaps) == 1
    assert notifier.drafts_notes[0].startswith(f"[{AGENT}] [disabled] preview · ")


def test_a_production_run_posts_no_preview() -> None:
    notifier, delivery = FakeNotifier(), FakeDelivery()
    outcome = _agent(mode=DeliveryMode.PRODUCTION, delivery=delivery, notifier=notifier).run(
        _league(), NOW, run_id=7, simulations=50
    )
    assert outcome.status == "sent"
    assert notifier.drafts_notes == []
    assert len(delivery.calls) == 1 and len(delivery.attachments) == 1


def test_a_delivery_that_cannot_find_its_chat_alerts_and_fails_the_run() -> None:
    repo, notifier = FakeRepo(), FakeNotifier()
    delivery = FakeDelivery(failure=TargetMismatch("stored target does not match"))
    with pytest.raises(TargetMismatch):
        _agent(repo=repo, delivery=delivery, notifier=notifier).run(
            _league(), NOW, run_id=7, simulations=50
        )
    assert repo.sent == []
    assert delivery.attachments == []
    assert notifier.alerts_notes == [
        "EOD summary could not deliver: stored target does not match"
    ]


def test_a_failed_attachment_after_the_text_is_said_in_ops_and_the_run_still_succeeds() -> None:
    """The chat already has the answer; the file not arriving is one ops line,
    not a failed night and not a second text."""
    repo, notifier = FakeRepo(), FakeNotifier()
    delivery = FakeDelivery(attachment_failure=RuntimeError("boom"))
    outcome = _agent(repo=repo, delivery=delivery, notifier=notifier).run(
        _league(), NOW, run_id=7, simulations=50
    )
    assert outcome.status == "sent"
    assert len(delivery.calls) == 1
    assert repo.sent == [1]
    assert notifier.ops_notes == [
        "EOD summary attachment failed after the text went out: RuntimeError"
    ]


def test_a_factual_run_records_no_survival_snapshot() -> None:
    repo = FakeRepo()
    outcome = _agent(repo=repo).run(
        snapshot(_league().teams, schedule_available=False, day_state="unknown"), NOW,
        run_id=7, simulations=50,
    )
    assert outcome.status == "sent"
    assert outcome.odds is False
    assert repo.snapshots == []
    assert len(repo.recaps) == 1


def test_the_input_version_names_the_model_only_when_one_wrote_something() -> None:
    assert input_version(None) == MODEL_VERSION
    assert input_version("some-model") == f"{MODEL_VERSION}:{PROMPT_VERSION}:some-model"
