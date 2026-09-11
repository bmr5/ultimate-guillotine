import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.messages.bluebubbles import BlueBubblesError, InboundMessage
from ultimate_guillotine.messages.fingerprint import participant_fingerprint

log = logging.getLogger(__name__)


class TargetMismatch(Exception):
    pass


class DeliveryDisabled(Exception):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["sent", "reconciled"]
    outbound_id: int
    message_guid: str | None


def content_hash(text: str, reply_to_message_guid: str | None = None) -> str:
    signed = sign(text)
    if reply_to_message_guid is not None:
        signed += f"\0reply:{reply_to_message_guid}"
    return hashlib.sha256(signed.encode()).hexdigest()


def attachment_hash(data: bytes, reply_to_message_guid: str | None = None) -> str:
    digest = hashlib.sha256(data)
    if reply_to_message_guid is not None:
        digest.update(f"\0reply:{reply_to_message_guid}".encode())
    return digest.hexdigest()


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _thread_guid(guid: str | None) -> str | None:
    # Messages may return the first text part as p:0/<guid>.
    return guid.removeprefix("p:0/") if guid else None


class DeliveryService:
    def __init__(
        self,
        settings: Settings,
        client,
        targets,
        outbound,
        notifier,
        clock=lambda: datetime.now(UTC),
        crash_after_send: bool = False,
        commit: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._targets = targets
        self._outbound = outbound
        self._notifier = notifier
        self._clock = clock
        self._crash_after_send = crash_after_send
        self._commit = commit

    def _persist(self) -> None:
        """Make the writes so far durable, when the caller gave us a commit hook."""
        if self._commit is not None:
            self._commit()

    def _replies_available(self) -> bool:
        try:
            info = self._client.server_info()
        except BlueBubblesError:
            info = {}
        available = bool(info.get("private_api") and info.get("helper_connected"))
        if not available:
            log.info("Private API unavailable")
        return available

    def _resolve_target(self, reply_to: str | None = None):
        """The chat a message goes to.

        ``reply_to`` is the chat the triggering message came from. In production
        the league chat is the target, but a message posted in the registered
        self-test chat is still answered there (Ben, 2026-09-10: "monitoring the
        actual group chat along with the test one so I can still keep testing").
        Anything else -- a listen-only chat, an unknown chat -- gets the mode's
        target, never the chat it came from.
        """
        mode = self._settings.delivery_mode
        if mode is DeliveryMode.DISABLED:
            raise DeliveryDisabled("delivery mode is disabled")
        if (
            reply_to is not None
            and mode is DeliveryMode.PRODUCTION
        ):
            test_target = self._targets.get(DeliveryMode.TEST)
            if test_target is not None and test_target.chat_guid == reply_to:
                if reply_to != self._settings.test_chat_guid:
                    raise TargetMismatch("stored test target does not match configured chat")
                return test_target
            if reply_to == self._settings.test_chat_guid:
                raise TargetMismatch("no matching registered test target for reply")
        target = self._targets.get(mode)
        if target is None:
            raise TargetMismatch(f"no delivery target configured for {mode}")
        expected_guid = (
            self._settings.test_chat_guid
            if mode is DeliveryMode.TEST
            else self._settings.production_chat_guid
        )
        if target.chat_guid != expected_guid:
            raise TargetMismatch("stored target does not match configured chat")
        if mode is DeliveryMode.PRODUCTION:
            observed = participant_fingerprint(self._client.chat_participants(target.chat_guid))
            if (
                observed != self._settings.production_participant_fingerprint
                or observed != target.participant_fingerprint
            ):
                raise TargetMismatch("participant fingerprint changed")
        return target

    def deliver(
        self,
        run_id: int | None,
        agent: str,
        content: str,
        *,
        reply_to: str | None = None,
        reply_to_message: InboundMessage | None = None,
    ) -> DeliveryResult:
        """Deliver signed content to the configured chat, effectively once.

        When a `commit` hook was supplied, the reservation is durable before the
        send: the outbound row and its `sending` state are each committed before
        `send_text` crosses the Messages boundary, so a crash mid-send leaves a
        reservation the next attempt can reconcile instead of double-sending.
        """
        target = self._resolve_target(reply_to)
        # Chat routing and inline replies are separate. Never reference a message
        # from another chat when the configured delivery target redirects a send.
        if reply_to_message is not None and (
            reply_to_message.chat_guid != target.chat_guid or not self._replies_available()
        ):
            reply_to_message = None
        signed = sign(content)
        reply_guid = reply_to_message.guid if reply_to_message else None
        thread_guid = (
            _thread_guid(reply_to_message.thread_originator_guid or reply_guid)
            if reply_to_message
            else None
        )
        digest = content_hash(content, reply_guid)
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if (
                    msg.is_from_me
                    and _normalized(msg.text) == _normalized(signed)
                    and (
                        thread_guid is None
                        or _thread_guid(msg.thread_originator_guid) == thread_guid
                    )
                ):
                    self._outbound.set_state(pending.id, "reconciled", bluebubbles_guid=msg.guid)
                    self._notifier.feed(
                        f"[{agent}] [{self._settings.delivery_mode}] "
                        f"outbound #{pending.id} (reconciled after crash)\n{signed}"
                    )
                    if pending.run_id == run_id:
                        return DeliveryResult("reconciled", pending.id, msg.guid)
                    # Recover the earlier run, then give this run its own outbound
                    # and reply GUID even when both messages have identical text.
                    break
            else:
                self._outbound.set_state(pending.id, "failed", error="unreconciled send; retrying")
        outbound_id = self._outbound.reserve(run_id, target.id, signed, digest)
        self._persist()
        self._outbound.set_state(outbound_id, "sending")
        self._persist()
        if reply_guid:
            guid = self._client.send_text(
                target.chat_guid, signed, reply_to_message_guid=reply_guid
            )
        else:
            guid = self._client.send_text(target.chat_guid, signed)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(
            f"[{agent}] [{self._settings.delivery_mode}] outbound #{outbound_id}\n{signed}"
        )
        return DeliveryResult("sent", outbound_id, guid)

    def react(self, run_id: int | None, message: InboundMessage) -> DeliveryResult | None:
        """Acknowledge in the originating chat, or stay silent if reactions are unavailable.

        The caller reserves the agent run before calling this, so redelivered
        webhooks cannot send a second reaction. Never redirect a reaction to a
        different chat or replace a failed reaction with a text message.
        """
        target = self._resolve_target(message.chat_guid)
        if target.chat_guid != message.chat_guid:
            raise TargetMismatch("reaction target does not match originating chat")
        if not self._replies_available():
            return None
        content = f"reaction:like:{message.guid}"
        digest = hashlib.sha256(content.encode()).hexdigest()
        outbound_id = self._outbound.reserve(run_id, target.id, content, digest)
        self._persist()
        self._outbound.set_state(outbound_id, "sending")
        self._persist()
        try:
            guid = self._client.send_reaction(target.chat_guid, message.guid)
        except BlueBubblesError as exc:
            self._outbound.set_state(outbound_id, "failed", error=exc.__class__.__name__)
            self._persist()
            raise
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._persist()
        return DeliveryResult("sent", outbound_id, guid)

    def deliver_attachment(
        self,
        run_id: int | None,
        agent: str,
        filename: str,
        data: bytes,
        *,
        reply_to: str | None = None,
        reply_to_message_guid: str | None = None,
    ) -> DeliveryResult:
        """Send one file to the configured chat, effectively once.

        ``reply_to`` is the chat the request came from, resolved the same way
        ``deliver`` resolves it: a file asked for in the self-test chat lands there.

        The same reserve → commit → send → mark path as ``deliver``. The outbound
        row's content is ``attachment:<filename>`` and its hash is over the bytes,
        so a redelivery of the same file is the same reservation. A crashed send
        is reconciled by file name among the bot's own recent messages, which is
        the only thing about an attachment that iMessage hands back.
        """
        target = self._resolve_target(reply_to)
        # The queue retains the request GUID. Read its thread before replying,
        # both to confirm the chat and to reconcile replies to nested requests.
        request = None
        if reply_to_message_guid and reply_to == target.chat_guid and self._replies_available():
            try:
                request = self._client.get_message(reply_to_message_guid)
            except BlueBubblesError:
                log.info("Video request unavailable; sending the file normally")
            if request is not None and (
                request.chat_guid != target.chat_guid or request.guid != reply_to_message_guid
            ):
                request = None
        reply_guid = request.guid if request else None
        thread_guid = (
            _thread_guid(request.thread_originator_guid or reply_guid) if request else None
        )
        digest = attachment_hash(data, reply_guid)
        content = f"attachment:{filename}"
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if (
                    msg.is_from_me
                    and filename in msg.attachment_names
                    and (
                        thread_guid is None
                        or _thread_guid(msg.thread_originator_guid) == thread_guid
                    )
                ):
                    self._outbound.set_state(pending.id, "reconciled", bluebubbles_guid=msg.guid)
                    self._notifier.feed(
                        f"[{agent}] [{self._settings.delivery_mode}] "
                        f"outbound #{pending.id} (reconciled after crash) {content}"
                    )
                    return DeliveryResult("reconciled", pending.id, msg.guid)
            self._outbound.set_state(pending.id, "failed", error="unreconciled send; retrying")
        outbound_id = self._outbound.reserve(run_id, target.id, content, digest)
        self._persist()
        self._outbound.set_state(outbound_id, "sending")
        self._persist()
        if reply_guid:
            guid = self._client.send_attachment(
                target.chat_guid, filename, data, reply_to_message_guid=reply_guid
            )
        else:
            guid = self._client.send_attachment(target.chat_guid, filename, data)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(
            f"[{agent}] [{self._settings.delivery_mode}] outbound #{outbound_id} {content}"
        )
        return DeliveryResult("sent", outbound_id, guid)
