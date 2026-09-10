import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.messages.fingerprint import participant_fingerprint


class TargetMismatch(Exception):
    pass


class DeliveryDisabled(Exception):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["sent", "reconciled"]
    outbound_id: int
    message_guid: str | None


def content_hash(text: str) -> str:
    return hashlib.sha256(sign(text).encode()).hexdigest()


def attachment_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized(text: str) -> str:
    return " ".join(text.split())


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
            and self._settings.test_chat_guid
            and reply_to == self._settings.test_chat_guid
        ):
            test_target = self._targets.get(DeliveryMode.TEST)
            if test_target is not None and test_target.chat_guid == reply_to:
                return test_target
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
    ) -> DeliveryResult:
        """Deliver signed content to the configured chat, effectively once.

        When a `commit` hook was supplied, the reservation is durable before the
        send: the outbound row and its `sending` state are each committed before
        `send_text` crosses the Messages boundary, so a crash mid-send leaves a
        reservation the next attempt can reconcile instead of double-sending.
        """
        target = self._resolve_target(reply_to)
        signed = sign(content)
        digest = content_hash(content)
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if msg.is_from_me and _normalized(msg.text) == _normalized(signed):
                    self._outbound.set_state(pending.id, "reconciled", bluebubbles_guid=msg.guid)
                    self._notifier.feed(
                        f"[{agent}] [{self._settings.delivery_mode}] "
                        f"outbound #{pending.id} (reconciled after crash)\n{signed}"
                    )
                    return DeliveryResult("reconciled", pending.id, msg.guid)
            self._outbound.set_state(pending.id, "failed", error="unreconciled send; retrying")
        outbound_id = self._outbound.reserve(run_id, target.id, signed, digest)
        self._persist()
        self._outbound.set_state(outbound_id, "sending")
        self._persist()
        guid = self._client.send_text(target.chat_guid, signed)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(
            f"[{agent}] [{self._settings.delivery_mode}] outbound #{outbound_id}\n{signed}"
        )
        return DeliveryResult("sent", outbound_id, guid)

    def deliver_attachment(
        self, run_id: int | None, agent: str, filename: str, data: bytes
    ) -> DeliveryResult:
        """Send one file to the configured chat, effectively once.

        The same reserve → commit → send → mark path as ``deliver``. The outbound
        row's content is ``attachment:<filename>`` and its hash is over the bytes,
        so a redelivery of the same file is the same reservation. A crashed send
        is reconciled by file name among the bot's own recent messages, which is
        the only thing about an attachment that iMessage hands back.
        """
        target = self._resolve_target()
        digest = attachment_hash(data)
        content = f"attachment:{filename}"
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if msg.is_from_me and filename in msg.attachment_names:
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
        guid = self._client.send_attachment(target.chat_guid, filename, data)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(
            f"[{agent}] [{self._settings.delivery_mode}] outbound #{outbound_id} {content}"
        )
        return DeliveryResult("sent", outbound_id, guid)
