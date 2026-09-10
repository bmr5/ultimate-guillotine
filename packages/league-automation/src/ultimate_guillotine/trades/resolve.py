"""Deterministic name resolution and validation for extracted trades.

Sits between the model's extraction (``ExtractedTrade``, free-text names) and
persistence (``TradeProposal``, member/player ids): it maps the names people
typed to league members and Sleeper players, settles duplicate first names
using roster evidence, and validates the resulting proposal. The model is
never asked to choose between ambiguous candidates -- every disambiguation
here is deterministic.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import (
    ExtractedTrade,
    MemberRef,
    TradeAsset,
    TradeParty,
    TradeProposal,
)
from ultimate_guillotine.trades.names import normalize_name

__all__ = [
    "MemberRef",
    "RosterIndex",
    "Unresolved",
    "build_roster_index",
    "find_member",
    "normalize_name",
    "resolve_extracted",
    "validate",
]

_DEFENSE_WORDS = {"defense", "defenses", "def", "dst", "d"}
#: The NFL clubs, keyed by the abbreviation Sleeper files a ``DEF`` row under
#: (``SEA``), each listing the words people type for it: city first, nickname
#: second, then everyday alternates. `_build_defense_aliases` expands these.
_NFL_TEAMS: dict[str, tuple[str, ...]] = {
    "ARI": ("Arizona", "Cardinals"),
    "ATL": ("Atlanta", "Falcons"),
    "BAL": ("Baltimore", "Ravens"),
    "BUF": ("Buffalo", "Bills"),
    "CAR": ("Carolina", "Panthers"),
    "CHI": ("Chicago", "Bears"),
    "CIN": ("Cincinnati", "Bengals"),
    "CLE": ("Cleveland", "Browns"),
    "DAL": ("Dallas", "Cowboys"),
    "DEN": ("Denver", "Broncos"),
    "DET": ("Detroit", "Lions"),
    "GB": ("Green Bay", "Packers", "GNB"),
    "HOU": ("Houston", "Texans"),
    "IND": ("Indianapolis", "Colts"),
    "JAX": ("Jacksonville", "Jaguars", "JAC", "Jags"),
    "KC": ("Kansas City", "Chiefs", "KAN"),
    "LAC": ("Los Angeles", "Chargers"),
    "LAR": ("Los Angeles", "Rams"),
    "LV": ("Las Vegas", "Raiders", "LVR"),
    "MIA": ("Miami", "Dolphins"),
    "MIN": ("Minnesota", "Vikings"),
    "NE": ("New England", "Patriots", "NWE", "Pats"),
    "NO": ("New Orleans", "Saints", "NOR"),
    "NYG": ("New York", "Giants"),
    "NYJ": ("New York", "Jets"),
    "PHI": ("Philadelphia", "Eagles"),
    "PIT": ("Pittsburgh", "Steelers"),
    "SEA": ("Seattle", "Seahawks"),
    "SF": ("San Francisco", "49ers", "SFO", "Niners"),
    "TB": ("Tampa Bay", "Buccaneers", "TAM", "Bucs"),
    "TEN": ("Tennessee", "Titans"),
    "WAS": ("Washington", "Commanders", "WSH", "Football Team", "WFT"),
}
#: Asset kinds that carry a number, and are their own unit when none is given.
_MONEY_KINDS = {"faab", "usd", "draft_dollars"}
#: The league's own exchange rate, from the rules document: "Every $1 left
#: unspent in your draft budget becomes $5 FAAB during the season." So a price
#: quoted in draft dollars is a FAAB price divided by five, and the two are the
#: same money written two ways.
DRAFT_DOLLAR_FAAB = 5
#: Asset kinds that are a term rather than a quantity, whatever number the
#: model attached to them.
_TERM_KINDS = {"protection", "other"}
# Generational suffixes, normalized: they are never the name anyone types.
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
#: First-person tokens, normalized. The prompt asks the model to write the
#: announcer's username instead of one of these; this is the guard for when it
#: does not, and it only fires when no member goes by the word.
_FIRST_PERSON = {"me", "i", "my team", "myself", "my"}


class Unresolved(Exception):
    """Raised when a trade can't be resolved or validated without a human."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RosterIndex:
    """Maps a member id to the Sleeper player ids on their current roster."""

    holdings: dict[int, frozenset[str]]

    @classmethod
    def empty(cls) -> "RosterIndex":
        return cls({})

    def holds(self, member_id: int, player_id: str) -> bool:
        return player_id in self.holdings.get(member_id, frozenset())

    def players_for(self, member_id: int | None) -> frozenset[str]:
        """One member's roster, or nothing for a member nobody could place."""
        if member_id is None:
            return frozenset()
        return self.holdings.get(member_id, frozenset())

    def all_players(self) -> frozenset[str]:
        """Every player on every roster in the index.

        A partial name that is on nobody's roster in particular is still worth
        matching league-wide: `Rhamondre` names one man in the NFL, and the
        rostered players are a two-hundred-name haystack rather than the
        directory's several thousand.
        """
        return frozenset().union(*self.holdings.values()) if self.holdings else frozenset()


#: Past this, the holdings cache is not trusted for trade resolution and the registrar
#: pays for one live Sleeper call rather than resolving against a stalled roster.
HOLDINGS_MAX_AGE = timedelta(hours=6)


def build_roster_index(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season: int,
    now: datetime | None = None,
) -> RosterIndex:
    """Map each member to the Sleeper player ids they currently hold.

    Reads ``public.roster_holdings``, which the ten-minute sync keeps current: a
    🚨 alert arriving during a Sleeper outage still resolves against the last
    good rows, and no alert costs a Sleeper call. Every slot counts -- starter,
    bench, ir, taxi -- because a traded player is as likely to be on IR.

    The ``client`` remains for one guard: a season with no holdings rows at all
    (a brand-new season the sync has not reached yet), or a newest ``synced_at``
    older than ``HOLDINGS_MAX_AGE``, falls back to one live fetch, so a stalled
    sync never resolves a trade against a roster that has moved on. Partial
    coverage is not staleness: if the freshest row is recent the table is used as
    it stands, and a team with no rows is simply absent from the index.

    ``now`` is injectable for tests only; the registrar and CLI callers pass the
    season and let it default to the wall clock.

    The season is passed in rather than read off the clock: the caller has
    already settled which season it is recording under, and a January trade
    belongs to the season that started the previous September.
    """
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            select max(h.synced_at)
            from public.roster_holdings h
            join public.seasons s on s.id = h.season_id
            where s.year = %s
            """,
            (season,),
        )
        row = cur.fetchone()
    freshest = row[0] if row else None
    if freshest is None or now - freshest > HOLDINGS_MAX_AGE:
        return _index_from_sleeper(client, conn, league_id, season)

    with conn.cursor() as cur:
        cur.execute(
            """
            select t.member_id, h.sleeper_player_id
            from public.roster_holdings h
            join public.teams t on t.id = h.team_id and t.season_id = h.season_id
            join public.seasons s on s.id = h.season_id
            where s.year = %s
            """,
            (season,),
        )
        rows = cur.fetchall()
    holdings: dict[int, set[str]] = {}
    for member_id, player_id in rows:
        holdings.setdefault(member_id, set()).add(player_id)
    return RosterIndex({m: frozenset(ids) for m, ids in holdings.items()})


def _index_from_sleeper(
    client: SleeperClient, conn: psycopg.Connection, league_id: str, season: int
) -> RosterIndex:
    """The pre-holdings path: one live fetch joined to teams by ``sleeper_roster_id``."""
    rosters = client.get_rosters(league_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.sleeper_roster_id, t.member_id
            from public.teams t
            join public.seasons s on s.id = t.season_id
            where s.year = %s
            """,
            (season,),
        )
        roster_to_member = {row[0]: row[1] for row in cur.fetchall()}
    if not roster_to_member:
        return RosterIndex.empty()
    holdings: dict[int, frozenset[str]] = {}
    for roster in rosters:
        member_id = roster_to_member.get(roster.roster_id)
        if member_id is None:
            continue
        holdings[member_id] = frozenset(roster.players)
    return RosterIndex(holdings)


def _build_member_index(members: list[MemberRef]) -> dict[str, list[MemberRef]]:
    index: dict[str, list[MemberRef]] = {}
    for member in members:
        keys = {normalize_name(member.display_name)} | {normalize_name(a) for a in member.aliases}
        for key in keys:
            index.setdefault(key, []).append(member)
    return index


def _build_defense_aliases() -> dict[str, str]:
    """Every spelling of a club that names its defense, mapped to its abbreviation.

    A spelling two clubs share -- ``los angeles``, ``new york`` -- names neither
    of them, so it is dropped and ``the New York D`` still asks the chat which.
    """
    aliases: dict[str, str] = {}
    shared: set[str] = set()
    for abbr, words in _NFL_TEAMS.items():
        city, nickname = words[0], words[1]
        keys = {normalize_name(abbr), normalize_name(f"{city} {nickname}")}
        keys.update(normalize_name(word) for word in words)
        # A multi-word alternate is a name the club used to go by, and people
        # type it after the city the same way: `Washington Football Team`.
        keys.update(normalize_name(f"{city} {word}") for word in words[2:] if " " in word)
        for key in keys:
            if aliases.setdefault(key, abbr) != abbr:
                shared.add(key)
    return {key: abbr for key, abbr in aliases.items() if key not in shared}


#: Normalized team wording -> the abbreviation the ``DEF`` row is filed under.
_DEFENSE_ALIASES = _build_defense_aliases()


def _match_defense(norm: str, players: list[Player]) -> Player | None:
    """Resolve a team defense, however it was typed, to its ``DEF`` row.

    ``Buffalo Bills defense``, ``the Bills D/ST``, ``Bills DEF`` and ``BUF`` all
    name one row, and the directory files that row under the club's
    abbreviation, so every spelling is reduced to the abbreviation before the
    lookup. A leading ``the`` is ignored, and the defense word is optional --
    half the league types the abbreviation on its own.
    """
    tokens = [t for t in norm.split(" ") if t]
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    if tokens and tokens[-1] in _DEFENSE_WORDS:
        tokens = tokens[:-1]
    abbr = _DEFENSE_ALIASES.get(" ".join(tokens))
    if abbr is None:
        return None
    matches = [
        p
        for p in players
        if p.position == "DEF" and abbr in {(p.team or "").upper(), p.sleeper_player_id.upper()}
    ]
    return matches[0] if len(matches) == 1 else None


def _without_suffix(norm: str) -> str:
    """An already-normalized name with its generational suffixes removed.

    ``marvin harrison jr`` -> ``marvin harrison``; a name that is nothing but
    suffixes (someone typing ``III``) is left empty and must match nobody.
    """
    tokens = [t for t in norm.split(" ") if t]
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _last_name(norm: str) -> str | None:
    """The last name in an already-normalized name, ignoring generational suffixes.

    ``marvin harrison jr`` -> ``harrison``; a name that is nothing but suffixes
    has no last name and must match nobody.
    """
    base = _without_suffix(norm)
    return base.split(" ")[-1] if base else None


def _money(
    kind: str, amount: int | None, unit: str | None, currency: str = "faab"
) -> tuple[str, int | None, str | None]:
    """Settle an asset's ``(kind, amount, unit)`` before it is recorded.

    The unit is the more specific field and wins: a ``usd`` asset measured in
    ``faab`` is FAAB, whatever the kind said. A money kind with no unit is its
    own unit. ``protection`` and ``other`` are terms rather than quantities, so
    they keep their description and lose any number the model attached -- a bare
    ``1`` next to "gulag protection" reads as nonsense in the chat.

    ``currency`` is the league's second budget. `$13 draft` and `$65 FAAB` are
    one price written two ways, so an amount the model marked ``draft`` is
    multiplied by five and recorded as FAAB: the trade log holds one currency,
    and `13` sitting in a FAAB column would read as a fifth of what was paid.
    The prompt asks the model to convert and write the FAAB figure itself, and
    this is what happens when it writes the draft figure instead -- so it fires
    on ``currency`` alone and never on the *word* draft, which is why an asset
    whose description says `($13 draft)` beside a converted `65` is left as it
    is. It is also why nothing is converted twice.

    ``usd`` is untouched: real money is not either budget, and $13 cash is $13.
    """
    if kind in _TERM_KINDS:
        return kind, None, None
    if kind in _MONEY_KINDS:
        if unit is None:
            unit = kind
        elif unit != kind:
            kind = unit
        if currency == "draft" and unit != "usd" and amount is not None:
            return "faab", amount * DRAFT_DOLLAR_FAAB, "faab"
        return kind, amount, unit
    return kind, amount, unit


def _is_single_token(norm: str) -> bool:
    """Is this normalized name one name, ignoring generational suffixes?

    ``harrison`` and ``harrison jr`` are; ``justin jefferson`` is not.
    """
    return len(_without_suffix(norm).split()) == 1


def find_member(members, name: str) -> MemberRef | None:
    """The member ``name`` refers to, matched the way resolution matches a name.

    Display name or alias, normalized on both sides, so a name typed at a
    terminal or written into a fixture is accepted in exactly the spellings the
    chat is accepted in. ``None`` for a name nobody answers to, which every
    caller has to refuse rather than treat as "no member named": a `--as` or an
    `announcer` that was silently dropped would report the behaviour of a chat
    with no handles loaded and read as a bug somewhere else.

    Deliberately *not* the resolver the pipeline uses. ``resolve_extracted``
    disambiguates duplicate names with roster evidence and raises rather than
    guessing; this answers "which member did the operator mean", where a
    duplicate is the operator's problem and the first match is as good an answer
    as an exception. It lives here so the CLI and the case runner share one
    implementation of the matching rule rather than two that can drift.
    """
    wanted = normalize_name(name)
    for member in members:
        names = {normalize_name(member.display_name)} | {
            normalize_name(alias) for alias in member.aliases
        }
        if wanted in names:
            return member
    return None


def _resolve_player(name: str, players: list[Player]) -> str:
    """Resolve a player name against the whole directory, or say it is unknown.

    The signature the CLI, the replay and the older tests already call. Trade
    resolution goes through :func:`_resolve_player_with_rosters` instead, which
    is this chain with the roster steps spliced in.
    """
    found = _resolve_directly(name, players)
    if found is None:
        raise Unresolved(f"I can't find a player named {name}")
    return found


def _resolve_directly(name: str, players: list[Player]) -> str | None:
    """The whole no-roster chain, answering ``None`` for a name nothing matched.

    ``None`` rather than an exception because the caller may have a roster step
    left to try; an *ambiguous* name still raises, because roster evidence is
    not what settles two players who are both called Mike Williams.
    """
    return _match_exactly(name, players) or _match_by_surname(name, players)


def _match_exactly(name: str, players: list[Player]) -> str | None:
    """Exact name, suffix-blind kin, or a team defense -- the certain matches."""
    norm = normalize_name(name)
    base = _without_suffix(norm)
    exact = [p for p in players if normalize_name(p.full_name) == norm]
    if len(exact) >= 2:
        raise Unresolved(f"Two players named {name}; which team?")
    # A generational suffix is decoration the two sides rarely agree on:
    # `Marvin Harrison Jr.` has to find a row filed as `Marvin Harrison`, and
    # `Kenneth Walker` a row filed as `Kenneth Walker III`.
    kin = (
        [p for p in players if _without_suffix(normalize_name(p.full_name)) == base] if base else []
    )
    if len(kin) >= 2 and not (exact and norm != base):
        # A father and a son are both on file, and the name as typed carries
        # nothing that separates them: `Marvin Harrison` is either of them, so
        # the chat settles it. Only a spelling that carries the suffix *and*
        # matches a row exactly picks one of the two on its own.
        raise Unresolved(f"Two players named {name}; which one?")
    if exact:
        return exact[0].sleeper_player_id
    if len(kin) == 1:
        return kin[0].sleeper_player_id
    defense = _match_defense(norm, players)
    if defense is not None:
        return defense.sleeper_player_id
    return None


def _match_by_surname(name: str, players: list[Player]) -> str | None:
    """The last resort: a bare surname over the whole directory.

    Only a bare surname falls back to matching on surnames. Somebody who typed a
    full name meant that player: "Justin Jefferson" must not quietly resolve to
    the only Jefferson on file.
    """
    norm = normalize_name(name)
    typed_last = _last_name(norm) if _is_single_token(norm) else None
    if typed_last is None:
        return None
    matches = [p for p in players if _last_name(normalize_name(p.full_name)) == typed_last]
    if len(matches) == 1:
        return matches[0].sleeper_player_id
    if len(matches) >= 2:
        raise Unresolved(f"Two players named {name}; which team?")
    return None


def _name_tokens(name: str) -> set[str]:
    """The words in a name, with generational suffixes dropped.

    ``Marvin Harrison Jr.`` -> ``{marvin, harrison}``, so the suffix is never a
    token a candidate has to carry.
    """
    return {token for token in _without_suffix(normalize_name(name)).split(" ") if token}


def _match_on_roster(name: str, candidates: list[Player], where: str) -> str | None:
    """The one player on ``candidates`` whose name contains every word typed.

    Containment in both directions is the point. `Rhamondre` matches
    `Rhamondre Stevenson`, `Wilson` matches `Michael Wilson`, and
    `Michael Wilson` matches himself -- but `Justin Jefferson` does not match
    `Van Jefferson`, because `justin` is not one of his words. That is the rule
    that keeps this a resolver of *partial* names rather than a fuzzy matcher
    that quietly swaps one full name for another.

    Two matches raise rather than pick: a roster with two Wilsons on it is a
    question for the chat, and ``where`` says which haystack was searched so the
    question names it.
    """
    typed = _name_tokens(name)
    if not typed:
        return None
    matched = {p.sleeper_player_id for p in candidates if typed <= _name_tokens(p.full_name)}
    if len(matched) == 1:
        return next(iter(matched))
    if len(matched) >= 2:
        raise Unresolved(f"Two players named {name}{where}; which one?")
    return None


def _resolve_player_with_rosters(
    name: str,
    players: list[Player],
    rosters: RosterIndex,
    giver_member_id: int | None,
    by_id: dict[str, Player] | None = None,
) -> str:
    """Resolve a player name with roster evidence between the certain matches
    and the surname fallback.

    Order, and why. An exact name, a suffix-blind kin match or a team defense is
    certain, so it wins outright. Otherwise the name is a fragment -- `Rhamondre`,
    `Wilson` -- and the best evidence about a fragment is who was giving the
    player away: it is his roster the player is leaving. Failing that, the
    league's rosters as a whole, which is still a far smaller haystack than the
    directory. Only then the old bare-surname rule over every active player, and
    only then the question.

    ``giver_member_id`` is ``None`` when the asset names no giver, or one nobody
    could place; the giver's-roster step is simply skipped and the rest of the
    chain runs as it always did.

    ``by_id`` is the active directory keyed by Sleeper id, which the roster steps
    look every holding up in. A caller resolving several assets against the same
    directory builds it once and passes it -- it is the whole player table, and
    rebuilding it per asset is the one avoidable cost in this chain. Left
    ``None`` it is built here, so the single-asset callers stay one call.
    """
    found = _match_exactly(name, players)
    if found is not None:
        return found
    if by_id is None:
        by_id = {p.sleeper_player_id: p for p in players}

    def rostered(ids: frozenset[str]) -> list[Player]:
        return [by_id[i] for i in sorted(ids) if i in by_id]

    found = _match_on_roster(
        name, rostered(rosters.players_for(giver_member_id)), " on that roster"
    )
    if found is None:
        found = _match_on_roster(name, rostered(rosters.all_players()), " in the league")
    if found is None:
        found = _match_by_surname(name, players)
    if found is None:
        raise Unresolved(f"I can't find a player named {name}")
    return found


def _reconcile_draft_quotes(
    extracted: ExtractedTrade,
    sides: list[tuple[int | None, int | None]],
    assets: list[TradeAsset],
) -> list[TradeAsset]:
    """Collapse one price written twice, or ask which of the two is right.

    An alert that says `$65 FAAB ($13 draft FAAB)` states one payment in both of
    the league's currencies. The prompt asks for one asset carrying the FAAB
    figure, but the plainest thing a model can do with two numbers is write two
    assets -- and two FAAB assets on the same leg are added up, so the same
    trade would be logged as 130 FAAB paid instead of 65.

    So: on any leg where more than one FAAB asset appears and at least one of
    them was quoted in draft dollars, the quotes are the same money if they agree
    once converted, and the leg keeps one of them -- the one the model already
    wrote in FAAB, so the recorded asset is the one whose description carries the
    announcement's own words. If they do not agree, the announcement states two
    different prices and nobody here can pick: that is a question for the chat.

    Every other leg is untouched, and so is a leg with two FAAB assets and no
    draft quote between them -- `50 FAAB now and 50 more after Week 4` is two
    payments, not one written twice, and collapsing it would silently halve it.
    """
    drafted = {i for i, asset in enumerate(extracted.assets) if asset.currency == "draft"}
    if not drafted:
        return assets
    legs: dict[tuple[int | None, int | None], list[int]] = {}
    for i, asset in enumerate(assets):
        if asset.unit == "faab" and asset.amount is not None:
            legs.setdefault(sides[i], []).append(i)
    dropped: set[int] = set()
    for indexes in legs.values():
        if len(indexes) < 2 or not drafted.intersection(indexes):
            continue
        amounts = {assets[i].amount for i in indexes}
        if len(amounts) > 1:
            stated = ", ".join(str(a) for a in sorted(amounts))
            raise Unresolved(f"That says {stated} FAAB for the same thing; which is it?")
        keep = next((i for i in indexes if i not in drafted), indexes[0])
        dropped.update(i for i in indexes if i != keep)
    return [asset for i, asset in enumerate(assets) if i not in dropped]


def resolve_extracted(
    extracted: ExtractedTrade,
    members: list[MemberRef],
    players: list[Player],
    rosters: RosterIndex,
    season: int,
    source_guid: str,
    excerpt: str,
    prompt_version: str,
    model: str,
    announcer: MemberRef | None = None,
    week: int | None = None,
) -> TradeProposal:
    """Turn one extraction into a proposal, or raise ``Unresolved``.

    ``announcer`` is the member who posted the announcement, when the sender
    could be placed. The prompt already asks the model to write that member's
    username wherever the announcement said `I` or `me`, so this is only the
    guard for a model that wrote the pronoun through anyway; with no announcer
    known the pronoun is a name nobody has, which is what it was before.
    """
    if extracted.kind == "unclear":
        raise Unresolved(extracted.unclear_reason or "The alert is unclear")

    member_index = _build_member_index(members)

    # Players and parties each want the other resolved first: settling two
    # members who go by one name reads the rosters of the players they are
    # trading, and settling a partial player name reads the roster of the member
    # giving him away. So the players are resolved twice.
    #
    # This first pass is the old no-roster chain, and it exists only to feed
    # member disambiguation below. Nothing it cannot answer is reported from
    # here -- neither a name it cannot find nor one two players share -- because
    # the roster pass further down is the step that exists for both, and a
    # question raised here would be raised about a haystack the caller has not
    # finished narrowing. Every player question the chat ends up being asked
    # comes from the second pass.
    resolved_players: dict[int, str] = {}
    for i, asset in enumerate(extracted.assets):
        # Only player assets carry a name we must resolve; a FAAB asset that
        # mentions a player in passing keeps the free text and no player id.
        if asset.kind == "player" and asset.player_name:
            try:
                found = _resolve_directly(asset.player_name, players)
            except Unresolved:
                continue
            if found is not None:
                resolved_players[i] = found

    def sent_players(norm_name: str) -> set[str]:
        return {
            resolved_players[i]
            for i, asset in enumerate(extracted.assets)
            if asset.kind == "player"
            and asset.from_party
            and normalize_name(asset.from_party) == norm_name
            and i in resolved_players
        }

    def received_players(norm_name: str) -> set[str]:
        return {
            resolved_players[i]
            for i, asset in enumerate(extracted.assets)
            if asset.kind == "player"
            and asset.to_party
            and normalize_name(asset.to_party) == norm_name
            and i in resolved_players
        }

    member_cache: dict[str, MemberRef] = {}

    def resolve_member(name: str) -> MemberRef:
        norm = normalize_name(name)
        if norm in member_cache:
            return member_cache[norm]

        candidates = member_index.get(norm, [])
        if not candidates and norm in _FIRST_PERSON and announcer is not None:
            # The announcement said `me` and the model copied it through. The
            # member index is asked first, so a member who really does go by one
            # of these words still wins the name.
            member_cache[norm] = announcer
            return announcer
        if not candidates:
            raise Unresolved(f"I don't recognize '{name}' as a league member")
        if len(candidates) == 1:
            member_cache[norm] = candidates[0]
            return candidates[0]

        winner: MemberRef | None = None
        if len(candidates) in (2, 3):
            sent = sent_players(norm)
            received = received_players(norm)
            if sent:
                holds_all_sent = [
                    c for c in candidates if all(rosters.holds(c.member_id, p) for p in sent)
                ]
                if len(holds_all_sent) == 1:
                    winner = holds_all_sent[0]
            if winner is None and not sent and received:
                # "Holds none of what it receives" is only evidence when every
                # candidate's roster is known: a candidate missing from the index
                # holds nothing as far as we can see, which proves nothing.
                known = all(c.member_id in rosters.holdings for c in candidates)
                holds_none = [
                    c
                    for c in candidates
                    if not any(rosters.holds(c.member_id, p) for p in received)
                ]
                if known and len(holds_none) == 1:
                    winner = holds_none[0]

        if winner is None:
            raise Unresolved(f"Two members go by '{name}'; which one?")
        member_cache[norm] = winner
        return winner

    trade_parties: list[TradeParty] = []
    seen_member_ids: set[int] = set()
    for party in extracted.parties:
        member = resolve_member(party.name)
        if member.member_id not in seen_member_ids:
            seen_member_ids.add(member.member_id)
            trade_parties.append(TradeParty(member.member_id, member.display_name))

    # Every asset's two sides, settled before the second player pass: it is the
    # giver's member id that the roster step needs.
    sides = [
        (
            resolve_member(a.from_party).member_id if a.from_party else None,
            resolve_member(a.to_party).member_id if a.to_party else None,
        )
        for a in extracted.assets
    ]

    # The second pass, now with rosters. Every player asset is resolved again
    # rather than only the ones the first pass missed, so the answer that gets
    # recorded comes from one chain: `Rhamondre` reaches Rhamondre Stevenson on
    # the giver's roster, and a name the first pass placed by exact match is
    # placed by exact match here too, since that step comes first either way.
    # Best effort, never a question. Ben (2026-09-10): "trade data is incredibly
    # dynamic, it's probably best to just store as text and reparse the context
    # from that original text later on if needed." A player the directory cannot
    # place keeps the name as written and no id; the announcement itself is the
    # record.
    players_by_id = {p.sleeper_player_id: p for p in players}
    for i, asset in enumerate(extracted.assets):
        if asset.kind == "player" and asset.player_name:
            try:
                resolved_players[i] = _resolve_player_with_rosters(
                    asset.player_name, players, rosters, sides[i][0], players_by_id
                )
            except Unresolved:
                resolved_players.pop(i, None)

    trade_assets: list[TradeAsset] = []
    for i, asset in enumerate(extracted.assets):
        from_id, to_id = sides[i]
        kind, amount, unit = _money(asset.kind, asset.amount, asset.unit, asset.currency)
        trade_assets.append(
            TradeAsset(
                kind=kind,
                from_member_id=from_id,
                to_member_id=to_id,
                player_id=resolved_players.get(i),
                player_name=asset.player_name,
                amount=amount,
                unit=unit,
                description=asset.description,
            )
        )

    trade_assets = _reconcile_draft_quotes(extracted, sides, trade_assets)

    return TradeProposal(
        season=season,
        effective_week=week if week is not None else extracted.effective_week,
        kind=extracted.kind,
        parties=trade_parties,
        assets=trade_assets,
        rental_return_condition=extracted.rental_return_condition,
        special_terms=extracted.special_terms,
        referenced_trade_code=extracted.referenced_trade_code,
        source_message_guid=source_guid,
        evidence_excerpt=excerpt,
        prompt_version=prompt_version,
        model=model,
    )


def validate(proposal: TradeProposal) -> None:
    """The one thing a log needs: who traded.

    Everything else -- the assets, their units, a rental's return terms -- is
    the announcement's own wording, stored verbatim and reparsed later if a
    consumer ever needs it (Ben, 2026-09-10). Refusing to log over any of it
    only costs the league a record.
    """
    if len(proposal.parties) < 2:
        raise Unresolved("A trade needs at least two parties")
