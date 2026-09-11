"""`ug agent`: the League Agent's tool server, dry run, and answer log."""

import argparse
import sys
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from ultimate_guillotine.agent.records import AgentAnswerRepository, Session
from ultimate_guillotine.agent.session import HermesAgentClient
from ultimate_guillotine.agent.tools.source import DatabaseSource, FixtureSource
from ultimate_guillotine.agent.worker import AgentWorker, Job
from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import chat_guid_hash
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

DEFAULT_LEAGUE_PROFILE_HOME = Settings.model_fields["hermes_league_profile_home"].default
FIXTURE_ENV = "UG_AGENT_FIXTURE"


class _ProfileSettings(BaseSettings):
    """Read just the profile settings, without database or delivery requirements."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    hermes_league_profile_home: str = DEFAULT_LEAGUE_PROFILE_HOME
    hermes_model: str | None = None


def register(subparsers) -> None:
    parser = subparsers.add_parser("agent", help="League Agent commands")
    agent_sub = parser.add_subparsers(dest="command", required=True)
    mcp = agent_sub.add_parser(
        "mcp", help="serve the league's read-only tools over stdio for the Hermes profile"
    )
    mcp.add_argument(
        "--fixture", action="store_true",
        help="serve the fixture league instead of the database (also UG_AGENT_FIXTURE=1)",
    )
    mcp.set_defaults(handler=cmd_mcp)

    ask = agent_sub.add_parser("ask", help="dry-run a question; prints, never sends")
    ask.add_argument("--text", required=True, help="the message, as it would be sent")
    ask.add_argument("--as", dest="member", required=True, help="member label or alias")
    ask.add_argument("--resume", default=None, help="a Hermes session id to continue")
    ask.add_argument("--fixture", action="store_true", help="answer about the fixture league")
    ask.add_argument("--out", default=".", help="artifact directory (default: here)")
    ask.set_defaults(handler=cmd_ask)

    answers = agent_sub.add_parser("answers", help="list the newest recorded answers")
    answers.add_argument("--last", type=int, default=5)
    answers.set_defaults(handler=cmd_answers)


def cmd_mcp(args: argparse.Namespace) -> int:
    # Imported here rather than at the top: `ug` runs from cron all day, and only this
    # command needs the MCP server loaded.
    from ultimate_guillotine.agent.tools.mcp import serve

    return serve(args.fixture)


def matching_members(members, wanted: str) -> list[MemberRef]:
    """Collect all label, join key, and alias matches, ignoring case and spacing."""
    target = normalize_name(wanted).replace(" ", "")
    if not target:
        return []
    return [member for member in members if target in {
        normalize_name(name).replace(" ", "") for name in (
            member.display_name, member.nickname, member.sleeper_display_name, *member.aliases,
        ) if name
    }]


class PrintingDelivery:
    """Print text and save artifacts locally. Has no messaging client."""

    def __init__(self, out_dir: Path) -> None:
        self._out = out_dir
        self.failed = False

    def deliver(self, run_id, agent, content, *, reply_to=None):
        print(content)
        print("---")

    def deliver_attachment(self, run_id, agent, filename, data, *, reply_to=None):
        try:
            self._out.mkdir(parents=True, exist_ok=True)
            path = self._out / filename
            path.write_bytes(data)
            print(f"artifact: {path}")
        except OSError:
            self.failed = True
            raise


class NoRuns:
    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        print(f"run: {status}" + (f" ({error})" if error else ""))

    def set_session(self, run_id, session_id):
        pass

    def running_ids(self, agent):
        return []


class NoSessions:
    def create(self, hermes_session_id, chat_guid_hash):
        print(f"session: {hermes_session_id}")
        return 0


class PrintingAnswers:
    def record(self, answer):
        print(f"model: {answer.model} · prompt {answer.prompt_version} · kind {answer.kind}")
        return 0


class StderrNotifier:
    def ops(self, text: str) -> bool:
        print(text, file=sys.stderr)
        return True

    def alerts(self, text: str) -> bool:
        print(text, file=sys.stderr)
        return True


def cmd_ask(args: argparse.Namespace) -> int:
    with ExitStack() as resources:
        if args.fixture:
            settings = _ProfileSettings()
            source = FixtureSource()
            extra_env = {FIXTURE_ENV: "1"}
        else:
            settings = load_settings()
            conn = resources.enter_context(closing(connect(settings)))
            conn.read_only = True
            http = resources.enter_context(closing(httpx.Client()))
            source = DatabaseSource(conn, SleeperClient(http), settings.sleeper_league_id)
            # Override a fixture flag inherited from the calling shell for real-league asks.
            extra_env = {FIXTURE_ENV: "0"}
        matched = matching_members(source.members(), args.member)
        if len(matched) != 1:
            reason = "unknown" if not matched else "ambiguous"
            print(f"{reason} member", file=sys.stderr)
            return 2
        delivery = PrintingDelivery(Path(args.out))
        worker = AgentWorker(
            client=HermesAgentClient(
                settings.hermes_league_profile_home, model=settings.hermes_model,
                extra_env=extra_env,
            ),
            source=source, delivery=delivery, notifier=StderrNotifier(),
            runs=NoRuns(), sessions=NoSessions(), answers=PrintingAnswers(),
        )
        message = InboundMessage(
            guid="dry-run", chat_guid="dry-run", sender_address=None, text=args.text,
            is_from_me=False, is_group=True, sent_at=datetime.now(UTC),
        )
        session = Session(0, args.resume, chat_guid_hash(message.chat_guid), 1) if args.resume else None
        outcome = worker.run_job(Job(0, message, matched[0], session))
        print(f"outcome: {outcome}")
        return 1 if outcome in {"failed", "rejected"} or delivery.failed else 0


def cmd_answers(args: argparse.Namespace) -> int:
    if args.last < 1:
        print("--last must be positive", file=sys.stderr)
        return 2
    with closing(connect(load_settings())) as conn:
        conn.read_only = True
        for answer in AgentAnswerRepository(conn).recent(args.last):
            print(f"[{answer.kind}] {answer.model} · run {answer.run_id}"
                  f"{' · follow-up' if answer.is_follow_up else ''}")
            print(f"Q: {answer.question}")
            print(f"A: {answer.chat_text}")
            if answer.report_title:
                print(f"   write-up: {answer.report_title}")
            print("---")
    return 0
