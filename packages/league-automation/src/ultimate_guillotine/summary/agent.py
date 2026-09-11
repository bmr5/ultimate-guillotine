"""The EOD Summary agent: build, simulate, compose, store, deliver.

One snapshot in, one HTML attachment out, or one honest reason it stopped short.
The pieces are the modules beside this one; this is where they are assembled
around the run, and where every path settles what it leaves behind:

- the odds are computed only when the schedule could be read and projections
  cover at least :data:`COVERAGE_GATE` percent of the starters still to play --
  the Game Pulse spec's gate -- and otherwise the message is factual and says why;
- the colour is optional, verified, and never the reason a run fails;
- the survival snapshot and the recap are written before anything is sent, so a
  crash after the send leaves a draft the record can be reconciled against;
- one post a night: a recap of tonight's kind already marked ``sent`` stops a
  second, and ``force`` is the rehearsal override.

**Nothing here logs the message.** Ops and alerts notes carry statuses, exception
names and rejection reasons; the preview to ``#guillotine-drafts`` carries the
message because that channel is Ben's and exists for exactly that.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable
from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.messages.delivery import TargetMismatch
from ultimate_guillotine.summary.artifact import artifact_filename, render_html, short_text
from ultimate_guillotine.summary.color import (
    PROMPT_VERSION,
    ColorRejected,
    EodColor,
    verify_color,
    write_color,
)
from ultimate_guillotine.summary.lineup import coverage_pct
from ultimate_guillotine.summary.models import LOCAL_TZ, EodPacket, EodSnapshot
from ultimate_guillotine.summary.render import facts_text, render
from ultimate_guillotine.summary.survival import DEFAULT_SIMULATIONS, MODEL_VERSION, simulate

AGENT = "eod-summary"

#: The Game Pulse gate: projections for at least this share of rostered unplayed
#: starters, or no percentages are posted.
COVERAGE_GATE = Decimal(95)

NO_SCHEDULE = "game status unavailable"

Status = Literal["sent", "draft", "already_sent"]


@dataclass(frozen=True)
class Composed:
    """One night's post, with everything that went into it.

    ``text`` is the full deterministic message with the colour: the record, and
    what the facts hash covers. ``short`` is the internal recap and draft preview,
    never a chat message. ``html`` is the only delivered item, named ``filename``.
    """

    packet: EodPacket
    text: str
    facts: str
    color: EodColor | None
    model: str | None
    short: str
    html: str
    filename: str


@dataclass(frozen=True)
class Outcome:
    status: Status
    text: str
    model: str | None
    odds: bool


def recap_kind(now: datetime) -> str:
    """``eod:<local date>``: the key one night's post is deduplicated on."""
    return f"eod:{now.astimezone(LOCAL_TZ):%Y-%m-%d}"


def input_version(model: str | None) -> str:
    """What produced the run: the model version, plus the prompt and model when a
    colour was used, so a later regression is traceable to whichever changed."""
    if model is None:
        return MODEL_VERSION
    return f"{MODEL_VERSION}:{PROMPT_VERSION}:{model}"


def facts_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_packet(
    snapshot: EodSnapshot,
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
) -> EodPacket:
    """The snapshot with its odds, or with the reason there are none."""
    coverage = coverage_pct(snapshot.live_teams())
    reason: str | None = None
    if not snapshot.schedule_available:
        reason = NO_SCHEDULE
    elif coverage < COVERAGE_GATE:
        reason = (
            f"projections cover {coverage}% of the starters still to play, "
            f"under the {COVERAGE_GATE}% gate"
        )
    result = None if reason else simulate(snapshot, simulations=simulations, seed=seed)
    return EodPacket(snapshot=snapshot, result=result, coverage_pct=coverage, no_odds_reason=reason)


def compose_summary(
    snapshot: EodSnapshot,
    now: datetime,
    *,
    ai,
    notifier,
    use_ai: bool = True,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
) -> Composed:
    """The message: odds, deterministic text, and the colour when one survives.

    A function rather than only a method so the dry run composes exactly what the
    scheduled run composes, without holding a delivery service, a repository or a
    connection it has promised not to use. ``ai`` may be ``None``; ``notifier``
    hears why a colour was dropped and nothing else.
    """
    packet = build_packet(snapshot, simulations=simulations, seed=seed)
    facts = facts_text(packet)
    color: EodColor | None = None
    model: str | None = None
    if use_ai and ai is not None:
        try:
            answer, usage = write_color(ai, facts, week=snapshot.week, day_state=snapshot.day_state)
            color = verify_color(answer, facts, [t.label for t in snapshot.teams])
            model = usage.model
        except ColorRejected as exc:
            notifier.ops(f"EOD summary colour declined: {exc.reason}")
        except (AIUnavailable, AIInvalidOutput) as exc:
            notifier.ops(f"EOD summary colour unavailable: {exc.__class__.__name__}")
    return Composed(
        packet,
        render(packet, color, now),
        facts,
        color,
        model,
        short_text(packet, color, now),
        render_html(packet, color, now),
        artifact_filename(now),
    )


class EodSummaryAgent:
    """Compose and post one night's summary.

    ``conn`` may be ``None`` for a dry run, in which case nothing is committed.
    ``ai`` may be ``None``, in which case there is no colour. ``repo`` is a
    :class:`~ultimate_guillotine.summary.store.SummaryRepository` or a stand-in.
    """

    def __init__(
        self,
        settings,
        conn,
        ai,
        delivery,
        notifier,
        repo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._conn = conn
        self._ai = ai
        self._delivery = delivery
        self._notifier = notifier
        self._repo = repo
        self._clock = clock

    def compose(
        self,
        snapshot: EodSnapshot,
        now: datetime,
        *,
        use_ai: bool = True,
        simulations: int = DEFAULT_SIMULATIONS,
        seed: int | None = None,
    ) -> Composed:
        return compose_summary(
            snapshot,
            now,
            ai=self._ai,
            notifier=self._notifier,
            use_ai=use_ai,
            simulations=simulations,
            seed=seed,
        )

    def run(
        self,
        snapshot: EodSnapshot,
        now: datetime,
        *,
        run_id: int,
        use_ai: bool = True,
        force: bool = False,
        simulations: int = DEFAULT_SIMULATIONS,
        seed: int | None = None,
    ) -> Outcome:
        """The scheduled path: compose, record, preview, deliver, settle."""
        kind = recap_kind(now)
        season_id, week = snapshot.season_id, snapshot.week
        if not force and self._repo.sent_today(season_id, week, kind):
            return Outcome("already_sent", "", None, False)

        composed = self.compose(snapshot, now, use_ai=use_ai, simulations=simulations, seed=seed)
        packet = composed.packet
        if packet.result is not None:
            self._repo.record_snapshot(season_id, week, kind, snapshot, packet.result, now)
        recap_id = self._repo.record_recap(
            season_id,
            week,
            kind,
            PROMPT_VERSION,
            facts_hash(render(packet, None, now)),
            composed.short,
        )
        self._repo.set_input_version(run_id, input_version(composed.model))
        self._commit()

        odds = packet.result is not None
        mode = self._settings.delivery_mode
        if mode is not DeliveryMode.PRODUCTION:
            self._notifier.drafts(
                f"[{AGENT}] [{mode.value}] preview · {composed.filename}\n{composed.short}"
            )
        if mode is DeliveryMode.DISABLED:
            return Outcome("draft", composed.short, composed.model, odds)

        try:
            self._delivery.deliver_attachment(
                run_id, AGENT, composed.filename, composed.html.encode()
            )
        except TargetMismatch as exc:
            self._notifier.alerts(f"EOD summary could not deliver: {exc}")
            raise
        except Exception as exc:
            self._notifier.ops(
                f"EOD summary attachment failed: {exc.__class__.__name__}"
            )
            raise
        # The attachment is the entire post. Only a successful upload settles it.
        self._repo.mark_sent(recap_id)
        self._commit()
        return Outcome("sent", composed.short, composed.model, odds)

    def _commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()
