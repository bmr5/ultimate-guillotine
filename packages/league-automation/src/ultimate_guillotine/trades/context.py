"""The context pack the Trade Registrar puts in front of one announcement.

Ben's ruling: *give the model enough context to resolve trades before it tries*.
The prompt used to see the season, a week hint, the member list and the
announcement, which is enough to read `nickgrod sends Ja'Marr Chase to blandon`
and not much else. People do not write alerts that way. They write
`Derek sends a 1 week Rhamondre rental to Charlie`, and a model with no rosters
in front of it has no way to know that `Rhamondre` is the Rhamondre Stevenson on
Derek's roster -- so it copies the fragment through, code cannot find a player by
that name, and the chat gets a question instead of a trade.

So the user message now carries five sections, rendered by
:func:`build_registrar_context`: the current NFL week, every team's roster with
positions, every team's remaining FAAB, this season's trades, and the league's
own rules. The prompt's rules read them: spell each player the way `Rosters`
spells him, resolving a partial name against the *giving* party's roster; name
the trade a rescission refers to out of `Trades this season`; flag an amount a
team cannot pay rather than silently changing it; date a rental's return from
the current week.

`League rules:` is the odd one out and is deliberately last. Every other section
is this league tonight; the rules are the same on every call and are what makes
the numbers mean anything -- that draft dollars are FAAB at five to one, that a
rental and an option are ordinary trades here rather than something strange,
that eliminated teams still hold tradeable players. It is a curated file
(`agents/trade-registrar/league-rules.md`), not the whole document, and the
Advisor appends the same file to its own prompt so the two agents cannot come to
disagree about what the league allows.

Two things this module is careful about.

**It carries terms, never chat text.** A trade line is built from the recorded
parties and assets only. ``evidence_excerpt`` -- the announcement as it was
typed -- is never read here, because the pack is handed to a model along with a
message from a private chat, and re-feeding twenty-five old announcements into
that call would widen what one prompt has seen from one message to a season of
them for no benefit: the terms are what the rules need.

**It is a pure function over plain data.** Nothing here queries. The registrar
and the CLI build :class:`ContextTeam` rows from
:class:`~ultimate_guillotine.advisor.state.LeagueSnapshot` through
:func:`context_from_snapshot` -- the Advisor's existing six-query read, not a
second set of queries against the same tables -- and the case runner builds them
from its synthetic league, so a case exercises the same rendering production
does.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "CONTEXT_CHAR_BUDGET",
    "LEAGUE_RULES_PATH",
    "POSITION_ORDER",
    "TRADE_LIMIT",
    "ContextPlayer",
    "ContextTeam",
    "build_registrar_context",
    "context_from_snapshot",
    "league_rules",
]

#: The curated trade-bearing rules, extracted from
#: `docs/rules/ultimate-guillotine-gulag-league-rules.docx`. A file rather than a
#: string in this module because both agents read it: the Registrar puts it in
#: the pack, the Advisor appends it to its own prompt, and a rule that lived in
#: one of them would eventually disagree with the other.
LEAGUE_RULES_PATH = (
    Path(__file__).resolve().parents[5] / "agents" / "trade-registrar" / "league-rules.md"
)

#: Roster order. Fantasy managers read a roster this way, and a stable order
#: means two runs of the same league produce the same prompt -- which is what
#: makes a disagreement between two runs a model difference rather than an
#: input difference. A position nothing maps to sorts last under its own name.
POSITION_ORDER = ("QB", "RB", "WR", "TE", "K", "DEF")

#: How many trades of the season the pack carries. Enough that a rescission of
#: anything the chat is still talking about can be matched to its code, short
#: enough that the pack stays a fraction of the prompt.
TRADE_LIMIT = 25

#: The pack's size ceiling in characters, roughly 6,000 tokens at four
#: characters a token. An 18-team league at 16 players a team plus 25 trades
#: renders well inside this; the constant exists so a league that grows, or a
#: rendering that starts including something it should not, fails a test rather
#: than quietly tripling what every extraction costs.
CONTEXT_CHAR_BUDGET = 24_000

#: How an asset's amount is spelled in a trade line, by unit.
_UNIT_WORDS = {"faab": "{n} FAAB", "usd": "${n}", "draft_dollars": "{n} draft dollars"}


@dataclass(frozen=True)
class ContextPlayer:
    """One rostered player as the pack names him: the spelling the model copies."""

    full_name: str
    position: str | None = None


@dataclass(frozen=True)
class ContextTeam:
    """One team's line in `Rosters` and in `FAAB remaining`.

    ``username`` is ``public.members.display_name`` -- the Sleeper username the
    `League members` list is keyed by, so a name the model writes out of the
    roster section resolves in code without a second mapping. ``aliases`` are the
    names people actually use for that manager.

    An eliminated team stays in the pack: its players are still tradeable, and a
    trade naming one is a real trade. ``eliminated_week`` is the week it went
    out, which the league's provisional eliminations do not always carry -- so
    ``None`` on an eliminated team means "out, week unrecorded" rather than
    "still in".
    """

    username: str
    aliases: tuple[str, ...] = ()
    faab_remaining: int = 0
    players: tuple[ContextPlayer, ...] = ()
    is_eliminated: bool = False
    eliminated_week: int | None = None


@lru_cache(maxsize=1)
def league_rules() -> str:
    """The league's trade-bearing rules, or ``""`` if the file is missing.

    Read once per process. An empty answer leaves the section out of the pack
    entirely rather than writing `League rules:` over nothing -- the same rule
    every other section follows, and for the same reason: an empty list of facts
    is a claim.
    """
    try:
        return LEAGUE_RULES_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_registrar_context(
    week: int | None,
    teams: Sequence[ContextTeam],
    trades: Sequence[Mapping],
    *,
    trade_limit: int = TRADE_LIMIT,
) -> str:
    """Render the context pack, or ``""`` when there is nothing to say.

    ``trades`` are rows in :meth:`TradeRepository.list_recent` shape -- a
    ``trade_code``, a ``status``, an ``effective_week`` and the current
    revision's ``terms`` -- newest first; only the first ``trade_limit`` are
    rendered. A row whose terms name no assets is skipped rather than rendered
    as a code with nothing after it.

    An empty return is the honest answer for a league the data layer cannot
    describe yet (a fresh season, a stalled sync): the caller leaves the section
    out of the user message entirely rather than writing `Rosters:` over nothing
    and inviting the model to conclude that every roster is empty.
    """
    sections: list[str] = []
    if week is not None:
        sections.append(f"Current NFL week: {week}")
    if teams:
        sections.append("Rosters:\n" + "\n".join(_roster_line(t) for t in teams))
        sections.append(
            "FAAB remaining:\n" + "\n".join(f"{t.username}: ${t.faab_remaining}" for t in teams)
        )
    lines = [line for line in (_trade_line(t) for t in trades[:trade_limit]) if line]
    if lines:
        sections.append("Trades this season:\n" + "\n".join(lines))
    # Last, and only when there is a league to apply them to. The rules are the
    # only section that is the same on every call, so putting them after the
    # facts keeps the changing part of the pack together, and a pack of rules
    # over no rosters would describe a league the model has not been shown.
    rules = league_rules()
    if sections and rules:
        sections.append("League rules:\n" + rules)
    return "\n\n".join(sections)


def context_from_snapshot(snapshot, members, trades: Sequence[Mapping]) -> str:
    """Build the pack from the Advisor's league snapshot and the trade log.

    ``members`` are :class:`~ultimate_guillotine.trades.models.MemberRef` rows,
    which is where the aliases live: the snapshot carries one rendered label per
    team, and the pack wants every name people use, the same list the `League
    members` line already shows. A team whose member has no alias row simply
    renders no nicknames.
    """
    aliases = {m.member_id: tuple(m.aliases) for m in members}
    teams = tuple(
        ContextTeam(
            username=team.display_name,
            aliases=aliases.get(team.member_id, ()),
            faab_remaining=team.faab_remaining,
            players=tuple(ContextPlayer(h.player_name, h.position) for h in team.holdings),
            is_eliminated=team.is_eliminated,
            eliminated_week=team.eliminated_week,
        )
        for team in snapshot.teams
    )
    return build_registrar_context(snapshot.week, teams, trades)


# -- rendering ----------------------------------------------------------


def _roster_line(team: ContextTeam) -> str:
    names = ", ".join(_player_word(p) for p in sorted(team.players, key=_position_key))
    return f"{team.username} ({_aliases(team)}){_elimination(team)}: {names or 'no players'}"


def _aliases(team: ContextTeam) -> str:
    return ", ".join(team.aliases) or "no known nicknames"


def _elimination(team: ContextTeam) -> str:
    if not team.is_eliminated:
        return ""
    return f" (eliminated wk {team.eliminated_week})" if team.eliminated_week else " (eliminated)"


def _player_word(player: ContextPlayer) -> str:
    return f"{player.full_name} {player.position}" if player.position else player.full_name


def _position_key(player: ContextPlayer) -> tuple[int, str]:
    position = (player.position or "").upper()
    rank = POSITION_ORDER.index(position) if position in POSITION_ORDER else len(POSITION_ORDER)
    return rank, player.full_name


def _trade_line(trade: Mapping) -> str:
    """One trade as `<code> wk<n> <status>: <giver> → <receiver>: <assets…>`."""
    terms = trade.get("terms") or {}
    names = {
        p.get("member_id"): p.get("display_name")
        for p in terms.get("parties") or []
        if p.get("member_id") is not None
    }
    legs: dict[tuple[str, str], list[str]] = {}
    for asset in terms.get("assets") or []:
        word = _asset_word(asset)
        if not word:
            continue
        giver = names.get(asset.get("from_member_id")) or "?"
        taker = names.get(asset.get("to_member_id")) or "?"
        legs.setdefault((giver, taker), []).append(word)
    if not legs:
        return ""
    week = trade.get("effective_week")
    body = "; ".join(f"{g} → {t}: {', '.join(a)}" for (g, t), a in legs.items())
    return (
        f"{trade.get('trade_code', '?')} wk{week if week is not None else '?'} "
        f"{trade.get('status', '?')}: {body}"
    )


def _asset_word(asset: Mapping) -> str:
    kind = asset.get("kind")
    if kind == "player":
        return asset.get("player_name") or asset.get("player_id") or "a player"
    amount, unit = asset.get("amount"), asset.get("unit")
    if amount is not None and unit in _UNIT_WORDS:
        return _UNIT_WORDS[unit].format(n=amount)
    return asset.get("description") or (kind or "")
