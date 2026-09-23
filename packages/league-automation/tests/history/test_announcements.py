from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.data.repositories import OutboundRepository, TargetRepository
from ultimate_guillotine.history.adjudicator import Unresolved
from ultimate_guillotine.history.announcements import (
    LocalDeliveryNotes,
    announce_confirmed,
    cut_message,
)
from ultimate_guillotine.history.archive_jobs import capture_current, tick
from ultimate_guillotine.history.archive_store import digest, rows
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.messages.fingerprint import participant_fingerprint

from . import test_archive_jobs
from .test_archive_jobs import MONDAY, TUESDAY, current, finalize_week_one

archive = test_archive_jobs.archive


class Messages:
    def __init__(self):
        self.sent = []
        self.fail = False

    def chat_participants(self, _):
        return ["+15555550100"]

    def send_text(self, chat_guid, text):
        if self.fail:
            raise RuntimeError("network unavailable")
        message = InboundMessage(
            guid=f"fake-{len(self.sent)}",
            chat_guid=chat_guid,
            sender_address=None,
            text=text,
            is_from_me=True,
            is_group=True,
            sent_at=datetime.now(UTC),
        )
        self.sent.append(message)
        return message.guid

    def messages_after(self, *_):
        return self.sent


@pytest.fixture
def messenger(archive):
    conn, _, _ = archive
    # Tests share a rollback transaction; emulate separate real send transactions'
    # reservation timestamps so the timestamp uniqueness key remains meaningful.
    conn.execute(
        "alter table private.outbound_messages alter column reserved_at set default clock_timestamp()"
    )
    client = Messages()
    fingerprint = participant_fingerprint(client.chat_participants(None))
    conn.execute(
        """insert into private.delivery_targets
        (mode,chat_guid,chat_guid_hash,participant_fingerprint,label,role)
        values ('production','fake-archive-chat','fake',%s,'fake archive target','deliver')
        on conflict (mode) do update set chat_guid=excluded.chat_guid,
        participant_fingerprint=excluded.participant_fingerprint,role='deliver'""",
        (fingerprint,),
    )
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db",
        delivery_mode=DeliveryMode.PRODUCTION,
        production_chat_guid="fake-archive-chat",
        production_participant_fingerprint=fingerprint,
    )
    delivery = DeliveryService(
        settings, client, TargetRepository(conn), OutboundRepository(conn), LocalDeliveryNotes()
    )
    return settings, delivery, client


def announce(archive, messenger):
    conn, _, _ = archive
    settings, delivery, _ = messenger
    return announce_confirmed(conn, settings, delivery, commit=lambda: None)


def test_week_one_sends_only_after_confirmation_and_only_once(archive, messenger):
    conn, league, _ = archive
    assert announce(archive, messenger) == 0
    league.complete.add(1)
    tick(conn, league, MONDAY)
    assert announce(archive, messenger) == 0
    tick(conn, league, TUESDAY)
    assert announce(archive, messenger) == 1
    assert announce(archive, messenger) == 0
    assert [m.text for m in messenger[2].sent] == [
        sign(
            "Week 1: Nobody was cut. All 18 teams remain alive.\nWeek 2 gulag qualifiers: Archive Manager 1 and Archive Manager 2."
        )
    ]


@pytest.mark.parametrize("guard", ["test_mode", "disabled_mode", "test_scope", "disabled_archive"])
def test_nonproduction_and_disabled_archives_are_silent(archive, messenger, guard):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    settings, delivery, client = messenger
    if guard.endswith("mode"):
        settings = SimpleNamespace(
            delivery_mode=(DeliveryMode.TEST if guard == "test_mode" else DeliveryMode.DISABLED)
        )
    elif guard == "test_scope":
        conn.execute("update private.archive_seasons set scope='test'")
    else:
        conn.execute("update private.archive_seasons set enabled=false")
    assert announce_confirmed(conn, settings, delivery, commit=lambda: None) == 0
    assert not client.sent


def test_corrections_only_when_actual_cut_changes_including_reversal(archive, messenger):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    assert announce(archive, messenger) == 1
    league.week = 2
    capture_current(conn, league, MONDAY + timedelta(weeks=1, minutes=-5))
    league.complete.add(2)
    tick(conn, league, MONDAY + timedelta(weeks=1))
    tick(conn, league, TUESDAY + timedelta(weeks=1))
    assert announce(archive, messenger) == 1
    assert messenger[2].sent[-1].text == sign(
        "Week 2 cut: Archive Manager 1.\n17 teams remain.\nWeek 3 gulag qualifiers: Archive Manager 3 and Archive Manager 4."
    )
    # A score revision that leaves the same loser must not text again.
    first_revision = current(conn, 2)["id"]
    for hours, points, expected_sends, loser in [(2, 1.5, 0, 1), (4, 100, 1, 2), (6, 1, 1, 1)]:
        league.points[(2, 1)] = points
        now = TUESDAY + timedelta(weeks=1, hours=hours)
        tick(conn, league, now)
        assert announce(archive, messenger) == 0  # provisional correction
        tick(conn, league, now + timedelta(minutes=30))
        assert current(conn, 2)["id"] != first_revision
        assert announce(archive, messenger) == expected_sends
        if expected_sends:
            assert messenger[2].sent[-1].text == sign(
                f"Correction: Week 2 cut: Archive Manager {loser}.\n17 teams remain.\nWeek 3 gulag qualifiers: Archive Manager 3 and Archive Manager 4."
            )
        assert announce(archive, messenger) == 0


@pytest.mark.parametrize("after_send", [False, True])
def test_failed_delivery_reuses_run_and_reconciles_a_completed_send(archive, messenger, after_send):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    _, delivery, client = messenger
    client.fail = not after_send
    delivery._crash_after_send = after_send
    with pytest.raises(RuntimeError):
        announce(archive, messenger)
    run = rows(conn, "select id,status from private.agent_runs where agent='archive-cuts'")
    assert len(run) == 1 and run[0]["status"] == "failed"
    client.fail = delivery._crash_after_send = False
    assert announce(archive, messenger) == 1
    assert announce(archive, messenger) == 0
    assert len(client.sent) == 1
    assert rows(conn, "select id,status from private.agent_runs where agent='archive-cuts'") == [
        {"id": run[0]["id"], "status": "succeeded"}
    ]


def test_sent_message_with_unfinished_run_is_not_repeated(archive, messenger):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    announce(archive, messenger)
    conn.execute("update private.agent_runs set status='running' where agent='archive-cuts'")
    assert announce(archive, messenger) == 0
    assert len(messenger[2].sent) == 1
    assert rows(conn, "select status from private.agent_runs where agent='archive-cuts'") == [
        {"status": "succeeded"}
    ]


def test_score_revision_after_ambiguous_send_reuses_original_message(archive, messenger):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    _, delivery, client = messenger
    revision = current(conn)["id"]
    delivery._crash_after_send = True
    with pytest.raises(RuntimeError):
        announce(archive, messenger)
    league.points[(1, 18)] = 25
    tick(conn, league, TUESDAY + timedelta(hours=2))
    tick(conn, league, TUESDAY + timedelta(hours=2, minutes=30))
    assert current(conn)["id"] != revision
    delivery._crash_after_send = False
    assert announce(archive, messenger) == 1
    assert len(client.sent) == 1
    assert (
        conn.execute(
            "select count(*) from private.agent_runs where agent='archive-cuts'"
        ).fetchone()[0]
        == 1
    )


def test_worker_can_announce_confirmed_results(archive, messenger):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    conn.execute("set local role automation_worker")
    assert announce(archive, messenger) == 1
    assert announce(archive, messenger) == 0


def test_changed_gulag_pair_sends_correction_without_a_cut(archive, messenger):
    conn, league, _ = archive
    finalize_week_one(conn, league)
    assert announce(archive, messenger) == 1
    league.points[(1, 1)] = 100
    tick(conn, league, TUESDAY + timedelta(hours=2))
    assert announce(archive, messenger) == 0
    tick(conn, league, TUESDAY + timedelta(hours=2, minutes=30))
    assert announce(archive, messenger) == 1
    assert messenger[2].sent[-1].text == sign(
        "Correction: Week 1: Nobody was cut. All 18 teams remain alive.\n"
        "Week 2 gulag qualifiers: Archive Manager 2 and Archive Manager 3."
    )
    assert announce(archive, messenger) == 0


def test_previous_cuts_only_message_gets_one_complete_correction(archive, messenger):
    conn, league, season = archive
    finalize_week_one(conn, league)
    revision = current(conn)["id"]
    old_hash = digest(([], 18))
    run_id = conn.execute(
        """insert into private.agent_runs (agent,trigger,idempotency_key,status,output_hash)
        values ('archive-cuts','cron',%s,'succeeded',%s) returning id""",
        (f"archive-cuts:{season}:1:{revision}", old_hash),
    ).fetchone()[0]
    messenger[1].deliver(
        run_id, "archive-cuts", "Week 1: Nobody was cut. All 18 teams remain alive."
    )
    assert announce(archive, messenger) == 1
    assert announce(archive, messenger) == 0
    assert len(messenger[2].sent) == 2
    assert messenger[2].sent[-1].text.startswith("Correction:")
    assert "Week 2 gulag qualifiers:" in messenger[2].sent[-1].text
    assert (
        conn.execute(
            "select output_hash from private.agent_runs where id=%s", (run_id,)
        ).fetchone()[0]
        == old_hash
    )


def test_double_cut_and_malformed_bundle():
    cuts = [
        {"team_id": 1, "manager_label": "Ben", "team_label": "Team Ben"},
        {"team_id": 2, "manager_label": "Max", "team_label": "Team Max"},
    ]
    assert (
        cut_message(12, 6, cuts, [], correction=False)
        == "Week 12 cuts: Ben and Max.\n6 teams remain."
    )
    with pytest.raises(Unresolved):
        cut_message(1, 18, cuts, [], correction=False)
    with pytest.raises(Unresolved):
        cut_message(12, 6, cuts[:1], [], correction=False)
    with pytest.raises(Unresolved):
        cut_message(2, 18, cuts[:1], [], correction=False)
