"""The listener's half of the League Agent: gates, then a hand-off.

Everything here runs under the listener's one lock:
is this the chat, is the bot addressed (by tag or by inline reply), is this an
attempt to overrule it, and who sent it. Then the run is reserved -- the
idempotency guard against a redelivered webhook -- and a receipt is delivered
before the job is queued for the worker. No league data is read and no model
is called on this thread.
"""

import hashlib
import logging
import re
from collections.abc import Callable

from ultimate_guillotine.agent.records import Session
from ultimate_guillotine.agent.worker import AGENT, Job
from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import chat_guid_hash, handle_hash
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage

BOT_TAG = re.compile(r"@\s*(?:bot|guillotinebot|daddy)\b", re.IGNORECASE)
RECEIPT = "Got it, kitten. Daddy's on it."
log = logging.getLogger(__name__)
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
    "favorites, or make a trade. Members announce deals with a 🚨 alert for commissioner approval."
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

    def resolve(self, thread_guid: str | None, chat_guid: str) -> Session | None:
        run_id = self.parent_run_id(thread_guid, chat_guid)
        if run_id is None:
            return None
        session_id = self._runs.session_id_for(run_id)
        session = self._sessions.get(session_id) if session_id else None
        return session if session and session.chat_guid_hash == chat_guid_hash(chat_guid) else None

    def parent_run_id(self, thread_guid: str | None, chat_guid: str) -> int | None:
        """Recognize an agent outbound even while its session is still being created."""
        if not thread_guid:
            return None
        run_id = self._outbound.run_id_for_guid(thread_guid, chat_guid)
        if run_id is None or not self._runs.is_agent_run(run_id, AGENT):
            return None
        return run_id


def league_agent_trigger(
    *, worker, contacts, resolver: FollowUpResolver, runs, delivery, chat_guid: str,
    commissioner_username: str | None = None, members=lambda: (),
    video_matches: Callable[[InboundMessage], bool] | None = None,
) -> Trigger:
    def matches(msg: InboundMessage) -> bool:
        if msg.chat_guid != chat_guid or is_signed(msg.text):
            return False
        # Explicit video requests belong to the registered video workflow, even
        # when they reply to an Agent receipt.
        if video_matches is not None and video_matches(msg):
            return False
        return has_bot_tag(msg.text) or resolver.parent_run_id(
            msg.thread_originator_guid, msg.chat_guid
        ) is not None

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
        if msg.is_from_me and not msg.sender_address:
            wanted = (commissioner_username or "").strip().lower()
            if wanted:
                asker = next((m for m in members() if m.display_name.lower() == wanted), None)
        job = Job(run_id, msg, asker, None,
                  parent_run_id=resolver.parent_run_id(msg.thread_originator_guid, msg.chat_guid))
        try:
            delivery.deliver(run_id, AGENT, RECEIPT, reply_to=msg.chat_guid)
        except Exception as exc:  # noqa: BLE001 - queue the question even if receipt fails
            log.warning("league agent could not acknowledge receipt: %s", exc.__class__.__name__)
        worker.submit(job)

    return Trigger(AGENT, matches, handle)
