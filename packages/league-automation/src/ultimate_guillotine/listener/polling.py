"""Recent inbox recovery through the listener's existing serialized processor."""

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic

from ultimate_guillotine.messages.bluebubbles import InboundMessage

log = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10
OVERLAP = timedelta(minutes=2)
STARTUP_LOOKBACK = timedelta(seconds=30)
PAGE_SIZE = 100
MAX_PAGES_PER_SCAN = 5
SEEN_LIMIT = 2000


@dataclass
class _Scan:
    after: datetime
    before: datetime | None = None
    offset: int = 0
    seen: OrderedDict[str, None] = field(default_factory=OrderedDict)


class InboxRecovery:
    """One HTTP reader per authorized chat, feeding one shared processing callback.

    A fixed upper bound makes offset pages stable against new arrivals. After a
    complete scan, revisit two minutes to catch late inserts; receipts remain the
    durable dedupe authority. Startup only revisits the last thirty seconds. The
    scheduled gap-fill still owns older gaps. A page limit retains the unfinished
    cursor for the next tick rather than dropping messages beyond that limit.
    """

    def __init__(
        self,
        client,
        chat_guids: Iterable[str],
        process: Callable[[InboundMessage, str], str],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_pages: int = MAX_PAGES_PER_SCAN,
    ) -> None:
        self._client = client
        self._process = process
        self._now = now
        self._max_pages = max_pages
        self._floor = now() - STARTUP_LOOKBACK
        self._scans = {chat: _Scan(self._floor) for chat in dict.fromkeys(chat_guids)}
        self.stopped = threading.Event()
        self.threads: list[threading.Thread] = []

    def scan(self, chat: str) -> None:
        state = self._scans[chat]
        if state.before is None:
            state.before = self._now()
        try:
            for _ in range(self._max_pages):
                if self.stopped.is_set():
                    return
                messages, count = self._client.messages_page(
                    chat, after=state.after, before=state.before,
                    offset=state.offset, limit=PAGE_SIZE,
                )
                for msg in messages:
                    if self.stopped.is_set():
                        return
                    if msg.chat_guid != chat or msg.guid in state.seen:
                        continue
                    outcome = self._process(msg, msg.guid)
                    state.seen[msg.guid] = None
                    if len(state.seen) > SEEN_LIMIT:
                        state.seen.popitem(last=False)
                    if outcome.startswith("handled:"):
                        log.info("listener inbox recovered trigger; age_seconds=%.1f",
                                 max(0.0, (self._now() - msg.sent_at).total_seconds()))
                state.offset += count
                if count < PAGE_SIZE:
                    state.after = max(self._floor, state.before - OVERLAP)
                    state.before = None
                    state.offset = 0
                    return
        except Exception as exc:  # noqa: BLE001 - retry this page on the next tick
            log.warning("listener inbox recovery failed: %s", exc.__class__.__name__)

    def _loop(self, chat: str) -> None:
        while not self.stopped.is_set():
            started = monotonic()
            self.scan(chat)
            self.stopped.wait(max(0.0, POLL_INTERVAL_SECONDS - (monotonic() - started)))

    def start(self) -> None:
        for chat in self._scans:
            thread = threading.Thread(target=self._loop, args=(chat,),
                                      name="listener-inbox", daemon=True)
            self.threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self.stopped.set()
        # HTTP and an already-running trade can outlive shutdown. Daemon readers
        # do not hold process exit open, and never begin another operation afterward.
        deadline = monotonic() + 1.0
        for thread in self.threads:
            thread.join(max(0.0, deadline - monotonic()))
