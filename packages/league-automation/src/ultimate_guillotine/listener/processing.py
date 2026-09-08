import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable  # noqa: UP035

from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import SourceMessage, chat_guid_hash
from ultimate_guillotine.messages.bluebubbles import InboundMessage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trigger:
    name: str
    matches: Callable[[InboundMessage], bool]
    handle: Callable[[InboundMessage], None]


class TriggerRegistry:
    def __init__(self) -> None:
        self._triggers: list[Trigger] = []

    def register(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def match(self, msg: InboundMessage) -> list[Trigger]:
        return [t for t in self._triggers if t.matches(msg)]


def _fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def _sender_hash(address: str | None) -> str | None:
    return hashlib.sha256(address.encode()).hexdigest() if address else None


class InboundProcessor:
    def __init__(
        self,
        allowed_chat_guids: set[str],
        registry: TriggerRegistry,
        receipts,
        sources,
        on_error=None,
    ) -> None:
        self._allowed = allowed_chat_guids
        self._registry = registry
        self._receipts = receipts
        self._sources = sources
        self._on_error = on_error or (
            lambda name, exc: log.error("trigger %s failed: %s", name, exc.__class__.__name__)
        )

    def process(self, msg: InboundMessage, event_id: str) -> str:
        if not self._receipts.record(event_id, "received"):
            return "duplicate"
        if msg.chat_guid not in self._allowed:
            return "ignored_chat"
        if msg.is_from_me and is_signed(msg.text):
            return "ignored_bot"
        triggers = self._registry.match(msg)
        if not triggers:
            return "no_trigger"
        names = ",".join(t.name for t in triggers)
        self._sources.upsert(SourceMessage(
            source_guid=msg.guid,
            chat_guid_hash=chat_guid_hash(msg.chat_guid),
            sender_hash=_sender_hash(msg.sender_address),
            direction="outbound" if msg.is_from_me else "inbound",
            sent_at=msg.sent_at,
            content_fingerprint=_fingerprint(msg.text),
            excerpt=msg.text[:2000],
            trigger_name=names,
        ))
        for trigger in triggers:
            try:
                trigger.handle(msg)
            except Exception as exc:  # noqa: BLE001
                self._on_error(trigger.name, exc)
        return f"handled:{names}"


def ping_trigger(delivery, test_chat_guid: str) -> Trigger:
    def matches(msg: InboundMessage) -> bool:
        return (
            msg.chat_guid == test_chat_guid
            and msg.text.strip().lower() == "bot: ping"
            and not msg.is_from_me
        )

    def handle(msg: InboundMessage) -> None:
        delivery.deliver(None, "ping", f"pong {datetime.now(UTC).isoformat(timespec='seconds')}")

    return Trigger("ping", matches, handle)
