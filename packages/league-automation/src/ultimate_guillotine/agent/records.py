"""What the League Agent writes down: the session a thread runs in, and every answer.

Both tables are private. The question is stored verbatim -- it is the
commissioner's record of what the bot was asked and what it said -- and
nothing on the site reads either table.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Session:
    id: int
    hermes_session_id: str
    chat_guid_hash: str
    turns: int


@dataclass(frozen=True)
class AnswerRecord:
    run_id: int
    session_id: int | None
    chat_guid_hash: str
    asker_member_id: int | None
    question: str
    is_follow_up: bool
    kind: str
    chat_text: str
    source_line: str
    report_title: str | None
    report_html: str | None
    facts: dict[str, Any]
    sources: list[dict[str, Any]]
    prompt_version: str
    model: str


class AgentSessionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def create(self, hermes_session_id: str, chat_guid_hash: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.agent_sessions (hermes_session_id, chat_guid_hash)
                values (%s, %s)
                on conflict (hermes_session_id) do update
                    set last_used_at = now(), turns = private.agent_sessions.turns + 1
                returning id
                """,
                (hermes_session_id, chat_guid_hash),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("insert returned no id")
            return row[0]

    def touch(self, session_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "update private.agent_sessions set last_used_at = now(), turns = turns + 1"
                " where id = %s",
                (session_id,),
            )

    def get(self, session_id: int) -> Session | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "select id, hermes_session_id, chat_guid_hash, turns"
                " from private.agent_sessions where id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            return Session(*row) if row else None


class AgentAnswerRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, answer: AnswerRecord) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.agent_answers
                    (run_id, session_id, chat_guid_hash, asker_member_id, question,
                     is_follow_up, kind, chat_text, source_line, report_title, report_html,
                     facts, sources, prompt_version, model)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    answer.run_id, answer.session_id, answer.chat_guid_hash,
                    answer.asker_member_id, answer.question, answer.is_follow_up,
                    answer.kind, answer.chat_text, answer.source_line, answer.report_title,
                    answer.report_html, Jsonb(answer.facts), Jsonb(answer.sources),
                    answer.prompt_version, answer.model,
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("insert returned no id")
            return row[0]

    def recent(self, limit: int = 10) -> list[AnswerRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select run_id, session_id, chat_guid_hash, asker_member_id, question,
                       is_follow_up, kind, chat_text, source_line, report_title, report_html,
                       facts, sources, prompt_version, model
                from private.agent_answers order by id desc limit %s
                """,
                (limit,),
            )
            return [AnswerRecord(*row) for row in cur.fetchall()]
