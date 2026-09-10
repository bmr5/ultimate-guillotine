"""``@daddy create trade video``: the reply that asks for a video.

Ben replies to a trade alert (or to the bot's own confirmation) with a tagged
request; the trade is read off the reply thread, a job is queued, and one line
comes back saying the video is on its way. The render itself happens in
``ug video jobs run``, never here: the listener answers in a second and the
twenty-minute render runs on the queue.
"""

import re
from collections.abc import Callable

import psycopg

from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import MemberAliasRepository, SourceMessageRepository
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.trades.format import party_labels
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.video.jobs import VideoJobRepository

AGENT = "trade-video"
#: What Ben is told to expect: an 8 s voiced clip took about four minutes on
#: 2026-09-10, and Higgsfield's queue adds what it adds.
ETA = "usually takes 5 to 10 minutes"

_TAG = re.compile(r"@daddy\b", re.IGNORECASE)
_VIDEO = re.compile(r"\bvideo\b", re.IGNORECASE)
TRADE_CODE = re.compile(r"\b(?:TEST|T)-\d{4}-\d{3}\b")

HELP = (
    "Reply to the trade alert you mean, or include its code (like T-2026-003), "
    "and I'll make the video."
)
#: How many recent trades an alert with no trade behind it is matched against.
RECENT = 20
#: Names of a trade an alert must contain before it is taken as that trade.
MIN_NAME_HITS = 2


def code_in(text: str | None) -> str | None:
    """The trade code named in a message, if any."""
    match = TRADE_CODE.search(text or "")
    return match.group(0) if match else None


def code_variants(code: str) -> list[str]:
    """The code as written, then the same number under the other prefix.

    Going live re-codes ``TEST-2026-002`` to ``T-2026-002``, and the bot's old
    confirmation in the chat still names the TEST code; a reply to it should
    still find the trade (Ben hit this on 2026-09-10).
    """
    prefix, _, number = code.partition("-")
    other = "T" if prefix == "TEST" else "TEST"
    return [code, f"{other}-{number}"]


def _identifiers(trade: dict, members) -> set[str]:
    """The names an alert about this trade would use: each party's display
    name, nickname and aliases, and each player's name and its parts."""
    by_id = {m.member_id: m for m in members}
    names: set[str] = set()
    terms = trade.get("terms") or {}
    for party in terms.get("parties") or []:
        names.add(party.get("display_name") or "")
        ref = by_id.get(party.get("member_id"))
        if ref is not None:
            names.update([ref.display_name, ref.nickname or "", ref.sleeper_display_name or ""])
            names.update(ref.aliases)
    for asset in terms.get("assets") or []:
        player = asset.get("player_name") or ""
        names.add(player)
        names.update(part for part in player.split() if len(part) >= 4)
    return {name.strip().lower() for name in names if len(name.strip()) >= 3}


def match_trade(text: str, trades: list[dict], members) -> dict | None:
    """The one accepted trade an alert's wording points at, by the names in it.

    A reposted or reworded alert has no trade behind its message id, but it
    still names the players and the people. Two or more of a trade's names must
    appear, and the trade must beat every other outright: a tie or a lone name
    is no answer, because a wrong guess costs a render.
    """
    haystack = text.lower()
    scored: list[tuple[int, dict]] = []
    for trade in trades:
        if trade.get("status") != "accepted":
            continue
        hits = {
            name
            for name in _identifiers(trade, members)
            if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", haystack)
        }
        scored.append((len(hits), trade))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < MIN_NAME_HITS:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def help_text(recent: list[dict], labels: dict[int, str]) -> str:
    """What to answer when no trade could be tied to the request: the recent
    trades by code and parties, so the next reply can name one."""
    lines = []
    for trade in recent:
        if trade.get("status") != "accepted":
            continue
        parties = (trade.get("terms") or {}).get("parties") or []
        names = " ↔ ".join(
            labels.get(p.get("member_id"), p.get("display_name", "")) for p in parties
        )
        lines.append(f"{trade['trade_code']} ({names})" if names else trade["trade_code"])
        if len(lines) == 3:
            break
    if not lines:
        return HELP
    return (
        "I couldn't tie that to a logged trade. Recent: "
        + "; ".join(lines)
        + ". Reply with the code and I'll make the video."
    )


def is_video_request(text: str) -> bool:
    """Tagged and about a video; every other ``@daddy`` message is someone else's."""
    return bool(_TAG.search(text) and _VIDEO.search(text))


class VideoRequests:
    """Turn a request into a queued job and an acknowledgement.

    ``code_for_outbound_guid`` answers a reply to the bot's *own* confirmation
    ("🚨 Trade T-2026-003 logged"): given that message's GUID it returns the
    trade code the confirmation named, or ``None``.
    """

    def __init__(
        self,
        trades: TradeRepository,
        jobs: VideoJobRepository,
        delivery: DeliveryService,
        conn: psycopg.Connection,
        code_for_outbound_guid: Callable[[str], str | None] = lambda _guid: None,
        eta: str = ETA,
        sources: SourceMessageRepository | None = None,
        members: MemberAliasRepository | None = None,
    ) -> None:
        self._trades = trades
        self._jobs = jobs
        self._delivery = delivery
        self._conn = conn
        self._code_for_outbound_guid = code_for_outbound_guid
        self._eta = eta
        self._sources = sources
        self._members = members

    def resolve(self, msg: InboundMessage) -> dict | None:
        """The trade a request is about: the alert it replies to, a code in the
        text, or the confirmation it replies to -- in that order."""
        guid = msg.thread_originator_guid
        if guid:
            trade = self._trades.find_by_source_guid(guid)
            if trade is not None:
                return trade
        code = code_in(msg.text)
        if code:
            trade = self._by_code(code)
            if trade is not None:
                return trade
        if guid:
            code = self._code_for_outbound_guid(guid)
            if code:
                return self._by_code(code)
            trade = self._by_alert_wording(guid)
            if trade is not None:
                return trade
        return None

    def _by_alert_wording(self, guid: str) -> dict | None:
        """A reply to an alert the registrar recorded but did not log a trade
        from (a repost, a rewording): match the alert's names to a trade."""
        if self._sources is None or self._members is None:
            return None
        source = self._sources.get(guid)
        if source is None or not source.excerpt:
            return None
        return match_trade(
            source.excerpt, self._trades.list_recent(RECENT), self._members.all_members()
        )

    def _help(self) -> str:
        members = self._members.all_members() if self._members is not None else []
        return help_text(self._trades.list_recent(RECENT), party_labels(members))

    def _by_code(self, code: str) -> dict | None:
        for variant in code_variants(code):
            trade = self._trades.find_by_code(variant)
            if trade is not None:
                return trade
        return None

    def handle(self, msg: InboundMessage) -> None:
        # Answers go back to the chat that asked when that is the self-test chat;
        # the delivery service decides, this only says where the request was.
        trade = self.resolve(msg)
        if trade is None:
            self._delivery.deliver(None, AGENT, self._help(), reply_to=msg.chat_guid)
            return
        code = trade["trade_code"]
        if trade["status"] != "accepted":
            self._delivery.deliver(
                None, AGENT, f"{code} was rescinded, so no video for it.", reply_to=msg.chat_guid
            )
            return
        _job_id, created = self._jobs.enqueue(trade["trade_id"], code, msg.guid, msg.chat_guid)
        self._conn.commit()
        if created:
            text = f"🎬 On it — the video for {code} {self._eta}."
        else:
            text = f"🎬 The video for {code} is already in the works."
        self._delivery.deliver(None, AGENT, text, reply_to=msg.chat_guid)


def video_trigger(requests: VideoRequests, chat_guids: frozenset[str]) -> Trigger:
    """Fire on tagged video requests in the chats trade alerts are read in.

    Same gates as the registrar's: the chat set is where alerts are heard, the
    answer goes through ``DeliveryService`` and lands wherever the mode says,
    and the bot's own signed posts never count as requests.
    """

    def matches(msg: InboundMessage) -> bool:
        return (
            msg.chat_guid in chat_guids and is_video_request(msg.text) and not is_signed(msg.text)
        )

    def handle(msg: InboundMessage) -> None:
        requests.handle(msg)

    return Trigger(AGENT, matches, handle)
