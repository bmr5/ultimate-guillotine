import hashlib
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
    ) -> None:
        self._settings = settings
        self._client = client
        self._targets = targets
        self._outbound = outbound
        self._notifier = notifier
        self._clock = clock
        self._crash_after_send = crash_after_send

    def _resolve_target(self):
        mode = self._settings.delivery_mode
        if mode is DeliveryMode.DISABLED:
            raise DeliveryDisabled("delivery mode is disabled")
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
            observed = participant_fingerprint(
                self._client.chat_participants(target.chat_guid)
            )
            if (
                observed != self._settings.production_participant_fingerprint
                or observed != target.participant_fingerprint
            ):
                raise TargetMismatch("participant fingerprint changed")
        return target

    def deliver(
        self, run_id: int | None, agent: str, content: str
    ) -> DeliveryResult:
        target = self._resolve_target()
        signed = sign(content)
        digest = content_hash(content)
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if msg.is_from_me and msg.text.strip() == signed.strip():
                    self._outbound.set_state(
                        pending.id, "reconciled", bluebubbles_guid=msg.guid
                    )
                    return DeliveryResult("reconciled", pending.id, msg.guid)
            self._outbound.set_state(
                pending.id, "failed", error="unreconciled send; retrying"
            )
        outbound_id = self._outbound.reserve(run_id, target.id, signed, digest)
        self._outbound.set_state(outbound_id, "sending")
        guid = self._client.send_text(target.chat_guid, signed)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(
            f"[{agent}] [{self._settings.delivery_mode}] "
            f"outbound #{outbound_id}\n{signed}"
        )
        return DeliveryResult("sent", outbound_id, guid)
