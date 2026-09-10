"""``@bot create trade video``: the reply that asks for a video.

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
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.video.jobs import VideoJobRepository

AGENT = "trade-video"
#: What Ben is told to expect: an 8 s voiced clip took about four minutes on
#: 2026-09-10, and Higgsfield's queue adds what it adds.
ETA = "usually takes 5 to 10 minutes"

_TAG = re.compile(r"@bot\b", re.IGNORECASE)
_VIDEO = re.compile(r"\bvideo\b", re.IGNORECASE)
TRADE_CODE = re.compile(r"\b(?:TEST|T)-\d{4}-\d{3}\b")

HELP = (
    "Reply to the trade alert you mean, or include its code (like T-2026-003), "
    "and I'll make the video."
)


def code_in(text: str | None) -> str | None:
    """The trade code named in a message, if any."""
    match = TRADE_CODE.search(text or "")
    return match.group(0) if match else None


def is_video_request(text: str) -> bool:
    """Tagged and about a video; every other ``@bot`` message is someone else's."""
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
    ) -> None:
        self._trades = trades
        self._jobs = jobs
        self._delivery = delivery
        self._conn = conn
        self._code_for_outbound_guid = code_for_outbound_guid
        self._eta = eta

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
            trade = self._trades.find_by_code(code)
            if trade is not None:
                return trade
        if guid:
            code = self._code_for_outbound_guid(guid)
            if code:
                return self._trades.find_by_code(code)
        return None

    def handle(self, msg: InboundMessage) -> None:
        trade = self.resolve(msg)
        if trade is None:
            self._delivery.deliver(None, AGENT, HELP)
            return
        code = trade["trade_code"]
        if trade["status"] != "accepted":
            self._delivery.deliver(None, AGENT, f"{code} was rescinded, so no video for it.")
            return
        _job_id, created = self._jobs.enqueue(trade["trade_id"], code, msg.guid)
        self._conn.commit()
        if created:
            text = f"🎬 On it — the video for {code} {self._eta}."
        else:
            text = f"🎬 The video for {code} is already in the works."
        self._delivery.deliver(None, AGENT, text)


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
