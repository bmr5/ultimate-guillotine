"""The listener's half of the League Agent: gates, then a hand-off.

Everything here runs under the listener's one lock and takes milliseconds:
is this the chat, is the bot addressed (by tag or by inline reply), is this an
attempt to overrule it, and who sent it. Then the run is reserved -- the
idempotency guard against a redelivered webhook -- and the job is queued for
the worker. No league data is read and no model is called on this thread.
"""

import hashlib
import re

from ultimate_guillotine.agent.records import Session
from ultimate_guillotine.agent.worker import AGENT, Job
from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import handle_hash
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage

BOT_TAG = re.compile(r"@\s*(?:bot|guillotinebot)\b", re.IGNORECASE)
#: An explicit attempt to overwrite the agent's own instructions. Narrow on
#: purpose: "register this trade" is a question the agent answers with the 🚨
#: path, not an attack.
OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\s+"
    r"(?:(?:your|the|all|any|previous|prior|above)\s+){1,3}"
    r"(?:rules?|instructions?|prompts?|guidelines?|constraints?)"
    r"|\bsystem prompt\b",
    re.IGNORECASE,
)
REFUSAL = (
    "I only answer from league data and my own rules — I can't change them, play "
    "favorites, or make a trade. Announce a deal with a 🚨 alert and I'll log it."
)


def has_bot_tag(text: str) -> bool:
    return BOT_TAG.search(text) is not None


def is_override(text: str) -> bool:
    return OVERRIDE.search(text) is not None


class FollowUpResolver:
    """A reply's thread GUID → the bot's outbound → its run → the agent session."""

    def __init__(self, outbound, runs, sessions) -> None:
        self._outbound = outbound
        self._runs = runs
        self._sessions = sessions

    def resolve(self, thread_guid: str | None) -> Session | None:
        if not thread_guid:
            return None
        run_id = self._outbound.run_id_for_guid(thread_guid)
        if run_id is None:
            return None
        session_id = self._runs.session_id_for(run_id)
        if session_id is None:
            return None
        return self._sessions.get(session_id)


def league_agent_trigger(
    *, worker, contacts, resolver: FollowUpResolver, runs, delivery, chat_guid: str
) -> Trigger:
    def matches(msg: InboundMessage) -> bool:
        if msg.chat_guid != chat_guid or is_signed(msg.text):
            return False
        return has_bot_tag(msg.text) or resolver.resolve(msg.thread_originator_guid) is not None

    def handle(msg: InboundMessage) -> None:
        run_id = runs.reserve(AGENT, "webhook", f"agent:{msg.guid}")
        if run_id is None:
            return
        if is_override(msg.text):
            # Back to the chat the attempt came from, like every line the worker posts.
            delivery.deliver(run_id, AGENT, REFUSAL, reply_to=msg.chat_guid)
            runs.finish(
                run_id, "succeeded", output_hash=hashlib.sha256(REFUSAL.encode()).hexdigest()
            )
            return
        asker = (
            contacts.member_for_handle_hash(handle_hash(msg.sender_address))
            if msg.sender_address
            else None
        )
        worker.submit(Job(run_id, msg, asker, resolver.resolve(msg.thread_originator_guid)))

    return Trigger(AGENT, matches, handle)
