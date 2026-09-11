"""Answer queued league questions without acknowledgment or progress texts.

Every path finishes the run. Failures receive a short error in the originating
chat. Repository and delivery calls share a lock for their database connection.
"""

import hashlib
import logging
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ultimate_guillotine.agent.answer import CHAT_TEXT_LIMIT, LeagueAnswer, extract_answer
from ultimate_guillotine.agent.artifact import artifact_filename, render_artifact, text_content
from ultimate_guillotine.agent.envelope import (
    PROMPT_VERSION,
    Turn,
    build_envelope,
    retry_envelope,
)
from ultimate_guillotine.agent.records import AnswerRecord, Session
from ultimate_guillotine.agent.session import AgentReply, SessionNotFound
from ultimate_guillotine.agent.tools.names import PlayerInfo
from ultimate_guillotine.agent.tools.snapshot import LeagueSnapshot, SnapshotUnavailable
from ultimate_guillotine.agent.tools.source import LeagueSource
from ultimate_guillotine.agent.verify import verify
from ultimate_guillotine.ai.structured import AIInvalidOutput
from ultimate_guillotine.data.repositories import chat_guid_hash
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.models import MemberRef

log = logging.getLogger(__name__)

AGENT = "league-agent"
COULD_NOT_FINISH = "Request failed. Try again."
LOST_THREAD = "Previous context unavailable. "
ATTACHMENT_FAILED = "Report attachment failed."
NOT_AN_ANSWER = "your reply did not end with a valid LeagueAnswer JSON block"
FORMER_MEMBER = "a former member"
LOCAL_TZ = ZoneInfo("America/Chicago")
#: Spelled out so the envelope reads the same whatever locale the process runs under.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Job:
    run_id: int
    message: InboundMessage
    asker: MemberRef | None
    #: The session a reply to the bot continues, or ``None`` for a fresh question.
    session: Session | None
    parent_run_id: int | None = None


@dataclass
class _Checked:
    """A reply after extraction and verification: an answer, or what was wrong with it."""

    answer: LeagueAnswer | None
    problems: list[str]
    html: str | None


def local_time_label(at: datetime) -> str:
    """``Thu 7:42pm`` in the league's time zone: no leading zero, no locale in the way."""
    local = at.astimezone(LOCAL_TZ)
    meridiem = "pm" if local.hour >= 12 else "am"
    return f"{_WEEKDAYS[local.weekday()]} {local.hour % 12 or 12}:{local:%M}{meridiem}"


class AgentWorker:
    def __init__(
        self,
        *,
        client,
        source: LeagueSource,
        delivery,
        notifier,
        runs,
        sessions,
        answers,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._source = source
        self._delivery = delivery
        self._notifier = notifier
        self._runs = runs
        self._sessions = sessions
        self._answers = answers
        self._clock = clock
        self._queue: queue.Queue[Job] = queue.Queue()
        #: Around every delivery and repository call: the connection is one thread's at a time.
        self._lock = threading.RLock()

    # -- public ---------------------------------------------------------

    def submit(self, job: Job) -> None:
        """Queue one question without posting a waiting message."""
        self._queue.put(job)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._loop, name="league-agent-worker", daemon=True)
        thread.start()
        return thread

    def wait_until_idle(self) -> None:
        """Wait for submitted jobs to finish. The caller must stop submitting first."""
        self._queue.join()

    def run_job(self, job: Job) -> str:
        """Answer one question end to end. Returns the answer's kind, or the failure."""
        try:
            return self._answer(job)
        except Exception as exc:  # noqa: BLE001 - every failure is reported alike
            self._fail(job, exc.__class__.__name__)
            return "failed"

    def reconcile_startup(self) -> list[int]:
        """Fail orphaned runs and notify ops; their originating chats are unknown."""
        with self._lock:
            orphaned = self._runs.running_ids(AGENT)
            for run_id in orphaned:
                self._runs.finish(run_id, "failed", error="listener restarted")
            if orphaned:
                self._notify(self._notifier.ops, "League Agent orphaned runs marked failed.")
        return orphaned

    # -- internals ------------------------------------------------------

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self.run_job(job)
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                log.error("league agent run %s crashed: %s", job.run_id, exc.__class__.__name__)
            finally:
                self._queue.task_done()

    def _post(self, run_id: int, reply_to: str | None, text: str) -> None:
        """One line to the chat. A line that cannot be sent is a log line, not a lost run."""
        with self._lock:
            try:
                self._delivery.deliver(run_id, AGENT, text, reply_to=reply_to)
            except Exception as exc:  # noqa: BLE001 - the run goes on without the line
                log.warning(
                    "league agent run %s could not post a line: %s",
                    run_id, exc.__class__.__name__,
                )

    def _notify(self, send: Callable[[str], bool], text: str) -> None:
        """An ops or alerts note. A notifier that fails must not fail the run."""
        try:
            send(text)
        except Exception as exc:  # noqa: BLE001 - nothing more can be done about it
            log.warning("league agent could not send a note: %s", exc.__class__.__name__)

    def _fail(self, job: Job, name: str) -> None:
        with self._lock:
            self._post(job.run_id, job.message.chat_guid, COULD_NOT_FINISH)
            try:
                self._runs.finish(job.run_id, "failed", error=name)
            except Exception as exc:  # noqa: BLE001 - the alert below still goes out
                log.warning(
                    "league agent run %s could not be finished: %s",
                    job.run_id, exc.__class__.__name__,
                )
        self._notify(self._notifier.alerts, f"League Agent failed on a question: {name}")

    @staticmethod
    def _label(snapshot: LeagueSnapshot, asker: MemberRef | None) -> str | None:
        if asker is None:
            return None
        team = snapshot.team_for_member(asker.member_id)
        label = team.member_label if team is not None else (asker.nickname or FORMER_MEMBER)
        # One line, whatever the label holds: a newline in it must not add a header line.
        return " ".join(label.split())

    def _turn(self, snapshot: LeagueSnapshot, job: Job) -> Turn:
        return Turn(
            season=snapshot.season,
            week=snapshot.week,
            local_time=local_time_label(self._clock()),
            asker_label=self._label(snapshot, job.asker),
            is_follow_up=job.session is not None,
            message=job.message.text,
        )

    def _checked(
        self,
        reply: AgentReply,
        snapshot: LeagueSnapshot,
        members: Sequence[MemberRef],
        players: Mapping[str, PlayerInfo],
        turn: Turn,
        lost: bool = False,
    ) -> _Checked:
        try:
            answer = extract_answer(reply.text)
        except AIInvalidOutput:
            return _Checked(None, [NOT_AN_ANSWER], None)
        if lost:
            text = LOST_THREAD + answer.chat_text
            if len(text) > CHAT_TEXT_LIMIT:
                return _Checked(None, [
                    (f"chat text including the lost-thread notice must fit {CHAT_TEXT_LIMIT}"
                     f" characters; leave {len(LOST_THREAD)} characters for the notice")
                ], None)
            answer = answer.model_copy(update={"chat_text": text})
        html = None
        if answer.report is not None:
            html = render_artifact(
                answer.report, asker_label=turn.asker_label, season=snapshot.season,
                week=snapshot.week, source_line=answer.source_line, generated_at=self._clock(),
            )
        # ``html`` is the sanitized file, so its text is the only markup the scan ever sees.
        problems = verify(
            answer, snapshot, members, players,
            artifact_text=text_content(html) if html else None,
            artifact_bytes=len(html.encode("utf-8")) if html else None,
        )
        return _Checked(answer, problems, html)

    def _answer(self, job: Job) -> str:
        with self._lock:
            if job.parent_run_id is not None:
                # Resolve on the worker connection after the serial parent job finishes.
                # A failed parent can still have a usable persisted session. Without
                # one, start fresh with the same lost-thread notice as a missing file.
                session_id = self._runs.session_id_for(job.parent_run_id)
                job = replace(job, session=self._sessions.get(session_id) if session_id else None)
            # Check both resolved parents and directly supplied sessions before
            # any model call. A thread reference cannot transfer chat context.
            if job.session and job.session.chat_guid_hash != chat_guid_hash(job.message.chat_guid):
                job = replace(job, session=None)
            try:
                snapshot = self._source.snapshot()
            except SnapshotUnavailable as exc:
                self._fail(job, f"SnapshotUnavailable: {exc.reason}")
                return "failed"
        turn = self._turn(snapshot, job)
        lost = job.parent_run_id is not None and job.session is None
        resume = job.session.hermes_session_id if job.session else None
        try:
            reply = self._client.run(build_envelope(turn), resume=resume)
        except SessionNotFound:
            if resume is None:
                raise
            # The session is gone; the question is not. Start over, and say so.
            lost = True
            turn = replace(turn, is_follow_up=False)
            reply = self._client.run(build_envelope(turn), resume=None)

        def check(reply: AgentReply) -> _Checked:
            nonlocal snapshot
            with self._lock:
                snapshot = self._source.snapshot()
                members = self._source.members()
                players = self._source.players()
                return self._checked(reply, snapshot, members, players, turn, lost)

        checked = check(reply)
        if checked.problems:
            self._notify(
                self._notifier.ops,
                "League Agent answer failed verification: " + "; ".join(checked.problems),
            )
            query = retry_envelope(checked.problems)
            if not reply.session_id:
                # Hermes printed no session id, so there is nothing to resume: the retry
                # opens a fresh session with the whole turn in front of it, or the
                # question would be lost.
                query = build_envelope(turn) + "\n\n" + query
            reply = self._client.run(query, resume=reply.session_id or None)
            checked = check(reply)
            if checked.problems:
                self._notify(
                    self._notifier.ops,
                    "League Agent declined an answer: " + "; ".join(checked.problems),
                )
                self._fail(job, "verification")
                return "rejected"
        answer = checked.answer
        assert answer is not None  # a checked answer with no problems has an answer
        self._deliver(job, answer, checked.html, reply, week=snapshot.week)
        return answer.kind

    def _deliver(
        self,
        job: Job,
        answer: LeagueAnswer,
        html: str | None,
        reply: AgentReply,
        *,
        week: int,
    ) -> None:
        """Record, send, attach and finish under the connection lock."""
        chat_text = answer.chat_text
        report = answer.report
        chat_hash = chat_guid_hash(job.message.chat_guid)
        reply_to = job.message.chat_guid
        with self._lock:
            session_id = (
                self._sessions.create(reply.session_id, chat_hash) if reply.session_id else None
            )
            if session_id is not None:
                self._runs.set_session(job.run_id, session_id)
            self._answers.record(AnswerRecord(
                run_id=job.run_id, session_id=session_id, chat_guid_hash=chat_hash,
                asker_member_id=job.asker.member_id if job.asker else None,
                question=job.message.text, is_follow_up=job.session is not None,
                kind=answer.kind, chat_text=chat_text, source_line=answer.source_line,
                report_title=report.title if report else None, report_html=html,
                facts=answer.facts.model_dump(),
                sources=[s.model_dump() for s in report.sources] if report else [],
                prompt_version=PROMPT_VERSION, model=reply.model,
            ))
            self._delivery.deliver(job.run_id, AGENT, chat_text, reply_to=reply_to)
            error = None
            if html is not None and report is not None:
                try:
                    self._delivery.deliver_attachment(
                        job.run_id, AGENT, artifact_filename(report.title, week),
                        html.encode("utf-8"), reply_to=reply_to,
                    )
                except Exception as exc:  # noqa: BLE001 - the answer already went out
                    error = f"attachment: {exc.__class__.__name__}"
                    self._notify(
                        self._notifier.ops,
                        f"League Agent could not attach the write-up: {error}",
                    )
                    self._post(job.run_id, reply_to, ATTACHMENT_FAILED)
            self._runs.finish(
                job.run_id, "succeeded",
                output_hash=hashlib.sha256(chat_text.encode()).hexdigest(),
                error=error, input_version=f"{PROMPT_VERSION}:{reply.model}",
            )
