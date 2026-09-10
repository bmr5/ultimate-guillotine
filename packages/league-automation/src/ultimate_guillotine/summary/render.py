"""The message: every section, in the words the league reads on a phone.

Plain text, no markdown -- iMessage renders asterisks as asterisks -- and short
lines, because eighteen teams have to fit under a thumb. The delivery layer
appends the signature; nothing here does.

**Only what the league already says out loud.** Every name is a team's public
label or a player's Sleeper name, every number is a score, a projection or an
estimate this run computed, and the join key never reaches this module at all.
The colour, when there is one, has already been through the verifier.

**A figure that is unknown says so.** Factual mode -- no schedule, coverage below
the gate -- renders no percentage anywhere and names the reason in the footer; a
projected finish built on an estimated starter carries a ``~``; a missing score
row is counted in the footer rather than shown as a zero that reads as a score.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from ultimate_guillotine.summary.color import EodColor
from ultimate_guillotine.summary.lineup import UNAVAILABLE_STATUSES
from ultimate_guillotine.summary.models import LOCAL_TZ, EodPacket, TeamLine, TeamOdds

#: Below this a team is not worth a "sweating" mention.
SWEATING_FLOOR = Decimal("0.10")
ROSTER_WATCH_LINES = 8
MOVES_LINES = 6

_ONE = Decimal(1)
_ZERO = Decimal(0)


def percent(probability: Decimal, *, settled: bool) -> str:
    """A whole percentage, the tails named, and words when nothing is left to play."""
    if settled:
        if probability >= _ONE:
            return "locked"
        if probability <= _ZERO:
            return "safe"
    if probability <= _ZERO:
        return "0%"
    if probability >= _ONE:
        return "100%"
    hundred = probability * 100
    if hundred < 1:
        return "<1%"
    if hundred > 99:
        return ">99%"
    return f"{int(hundred.quantize(Decimal(1), rounding=ROUND_HALF_UP))}%"


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _clock(stamp: datetime) -> str:
    return stamp.astimezone(LOCAL_TZ).strftime("%-I:%M %p") + " CT"


class _View:
    """One packet, pre-digested: who is live, who is in the gulag, how to say a number."""

    def __init__(self, packet: EodPacket) -> None:
        self.packet = packet
        self.snap = packet.snapshot
        self.result = packet.result
        self.live = self.snap.live_teams()
        self.settled = not any(t.pending() for t in self.live)
        pair = tuple(
            t.team_id for t in self.live if t.team_id in self.snap.phase.gulag_team_ids
        )
        self.gulag = pair if len(pair) == 2 and self.snap.phase.kind in ("gulag", "double") else ()
        self.pool = [t for t in self.live if t.team_id not in self.gulag]

    def odds(self, team: TeamLine) -> TeamOdds | None:
        return None if self.result is None else self.result.teams.get(team.team_id)

    def probability(self, team: TeamLine) -> Decimal:
        odds = self.odds(team)
        return _ZERO if odds is None else odds.probability

    def projected(self, team: TeamLine) -> str:
        odds = self.odds(team)
        if odds is None:
            return "—"
        mark = "~" if odds.is_estimated else ""
        return f"{mark}{odds.projected_final.quantize(Decimal(1), rounding=ROUND_HALF_UP)}"

    def risk(self, team: TeamLine) -> str:
        return percent(self.probability(team), settled=self.settled)

    def left(self, team: TeamLine) -> str:
        count = len(team.pending())
        return f"{count} left"

    def team_line(self, team: TeamLine, *, suffix: str | None = None) -> str:
        """A team in the gulag or on the block: label, where it stands, the odds.

        Before kickoff nobody has scored, so ``0.0 · 8 left`` says nothing: the
        projected finish is the number the pairing is judged on until somebody
        plays, and it stands in for the score until then.
        """
        if self.snap.day_state == "outlook":
            parts = [team.label]
            parts.append(f"proj {self.projected(team)}" if self.result else self.left(team))
        else:
            parts = [team.label, f"{team.points:.1f}", self.left(team)]
        if suffix is not None:
            parts.append(suffix)
        return " · ".join(parts)

    def by_risk(self, teams: Sequence[TeamLine]) -> list[TeamLine]:
        if self.result is None:
            return sorted(teams, key=lambda t: (t.points, t.label))
        return sorted(teams, key=lambda t: (-self.probability(t), t.points, t.label))


def _header(view: _View, now: datetime) -> str:
    snap = view.snap
    title = f"🗡️ GUILLOTINE EOD · Week {snap.week} · {now.astimezone(LOCAL_TZ):%A}"
    if snap.day_state == "outlook":
        line = "Nothing has kicked off yet · the projected board"
    elif snap.day_state == "final":
        line = "Every game is in the books · standings pending the commish"
    elif snap.day_state == "unknown":
        line = "Game status unavailable tonight"
    else:
        left = sum(1 for t in view.live if t.pending())
        line = (
            f"{snap.games_final} of {snap.games_total} games final · "
            f"{left} {_plural(left, 'team', 'teams')} still "
            f"{_plural(left, 'has', 'have')} players to go"
        )
    return f"{title}\n{line}"


def _gulag_section(view: _View) -> str | None:
    phase = view.snap.phase
    if phase.kind not in ("gulag", "double"):
        return None
    if phase.gulag_source == "unknown":
        return "⚔️ THE GULAG · pairing unknown (a past week has no scores on file)"
    if not view.gulag:
        return "⚔️ THE GULAG · pairing unresolved (a named team is already out)"
    lines = ["⚔️ THE GULAG · loser is out"]
    pair = [t for t in view.live if t.team_id in view.gulag]
    for team in view.by_risk(pair):
        if view.result is None:
            lines.append(view.team_line(team))
            continue
        risk = view.risk(team)
        lines.append(view.team_line(team, suffix=risk if risk == "safe" else f"{risk} to lose"))
    if phase.gulag_source == "replay":
        lines.append("(pairing inferred from last week's scores)")
    return "\n".join(lines)


def _block_section(view: _View) -> str:
    kind = view.snap.phase.kind
    if kind in ("entry", "gulag"):
        header, count = f"⚰️ ON THE BLOCK · bottom 2 enter the Week {view.snap.week + 1} gulag", 2
    elif kind == "final":
        header, count = "🏆 THE FINAL · lower score is runner-up", 1
    else:
        header, count = "⚰️ ON THE BLOCK · lowest score is cut", 1
    ranked = view.by_risk(view.pool)
    lines = [header]
    for team in ranked[:count]:
        lines.append(
            view.team_line(team, suffix=None if view.result is None else view.risk(team))
        )
    if view.result is not None:
        sweating = [t for t in ranked[count:] if view.probability(t) >= SWEATING_FLOOR]
        if sweating:
            lines.append(
                "Sweating: " + " · ".join(f"{t.label} {view.risk(t)}" for t in sweating)
            )
    return "\n".join(lines)


def _board_section(view: _View) -> str:
    outlook = view.snap.day_state == "outlook"
    if view.result is not None:
        header = "📊 THE BOARD · proj · risk" if outlook else "📊 THE BOARD · score · proj · left · risk"
        ranked = sorted(
            view.live,
            key=lambda t: (-(view.odds(t).projected_final if view.odds(t) else _ZERO),
                           -t.points, t.label),
        )
    else:
        header = "📊 THE BOARD · proj" if outlook else "📊 THE BOARD · score · left"
        ranked = sorted(view.live, key=lambda t: (-t.points, t.label))
    lines = [header]
    for rank, team in enumerate(ranked, start=1):
        parts = [f"{rank}. {team.label}"]
        if not outlook:
            parts.append(f"{team.points:.1f}")
        if view.result is not None:
            parts.append(view.projected(team))
        if not outlook:
            parts.append(str(len(team.pending())))
        if view.result is not None:
            risk = view.risk(team)
            parts.append(f"⚔{risk}" if team.team_id in view.gulag else risk)
        lines.append(" · ".join(parts))
    out = sorted(
        (t for t in view.snap.teams if t.is_eliminated),
        key=lambda t: (t.eliminated_week or 0, t.label),
    )
    if out:
        lines.append(
            "Out: " + ", ".join(
                f"{t.label} (wk {t.eliminated_week})" if t.eliminated_week else t.label
                for t in out
            )
        )
    return "\n".join(lines)


def _watch_section(view: _View) -> str | None:
    notes: list[str] = []
    for team in view.live:
        empties = team.empty_slots()
        if empties:
            notes.append(f"{team.label}: {empties} empty {_plural(empties, 'slot', 'slots')}")
        for starter in team.out_starters():
            if starter.injury_status in UNAVAILABLE_STATUSES:
                notes.append(
                    f"{team.label}: {starter.name} ({starter.injury_status}) still in the lineup"
                )
            else:
                notes.append(
                    f"{team.label}: {starter.name} ({starter.injury_status}, no projection)"
                )
        for starter in team.unprojected_pending():
            notes.append(f"{team.label}: {starter.name} has no projection")
    if not notes:
        return None
    if len(notes) > ROSTER_WATCH_LINES:
        notes = [*notes[:ROSTER_WATCH_LINES], f"+{len(notes) - ROSTER_WATCH_LINES} more"]
    return "\n".join(["🩹 ROSTER WATCH", *notes])


def _move_suffix(kind: str, bid: int | None) -> str:
    if kind == "waiver":
        return f" (waiver ${bid})" if bid is not None else " (waiver)"
    if kind == "trade":
        return " (trade)"
    if kind == "commissioner":
        return " (commish)"
    return ""


def _moves_section(view: _View) -> str | None:
    moves = view.snap.moves
    if not moves:
        return None
    lines = ["🔁 MOVES TODAY"]
    for move in moves[:MOVES_LINES]:
        legs = [f"+{name}" for name in move.adds] + [f"−{name}" for name in move.drops]
        lines.append(f"{move.team_label}: {' '.join(legs)}{_move_suffix(move.kind, move.waiver_bid)}")
    if len(moves) > MOVES_LINES:
        lines.append(f"+{len(moves) - MOVES_LINES} more")
    return "\n".join(lines)


def _footer(view: _View) -> str:
    snap = view.snap
    parts: list[str] = []
    if view.result is not None:
        parts.append(f"{view.result.simulations:,} sims on Sleeper projections")
    else:
        parts.append(f"No odds tonight: {view.packet.no_odds_reason}")
    parts.append(
        f"scores as of {_clock(snap.scores_synced_at)}"
        if snap.scores_synced_at is not None
        else "no scores on file"
    )
    missing = sum(1 for t in view.live if not t.has_score_row)
    if missing:
        parts.append(
            f"{missing} {_plural(missing, 'team', 'teams')} "
            f"{_plural(missing, 'has', 'have')} no score on file"
        )
    parts.append("estimates, not rulings")
    return " · ".join(parts)


def _middle(view: _View) -> list[str]:
    sections = [
        _gulag_section(view),
        _block_section(view),
        _board_section(view),
        _watch_section(view),
        _moves_section(view),
    ]
    return [section for section in sections if section]


def facts_text(packet: EodPacket) -> str:
    """The sections the colour is written over and checked against: no header,
    no footer, no colour."""
    return "\n\n".join(_middle(_View(packet)))


def render(packet: EodPacket, color: EodColor | None, now: datetime) -> str:
    """The whole message, unsigned."""
    view = _View(packet)
    parts = [_header(view, now)]
    if color is not None:
        parts.append(f"🔥 {color.headline}\n{color.blurb}")
    parts.extend(_middle(view))
    parts.append(_footer(view))
    return "\n\n".join(parts)
