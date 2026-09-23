"""Recent executed transfers that explain why the seller no longer holds a player."""

from datetime import UTC, datetime, timedelta

TRANSFER_WINDOW = timedelta(hours=24)


def recent_transfers_context(conn, season: int, now: datetime | None = None) -> str:
    """Read the latest move per player, then retain direct trades to the current holder.

    Waivers and drops cannot establish a counterparty. A later move, even a
    non-trade, invalidates an older transfer as evidence for this announcement.
    Only usernames, player names, and execution times enter the prompt.
    """
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            with latest as (
                select distinct on (m.sleeper_player_id)
                    m.sleeper_player_id, x.id, x.kind, x.occurred_at, x.season_id
                from public.transactions x
                join public.transaction_moves m on m.transaction_id = x.id
                join public.seasons s on s.id = x.season_id
                where s.year = %s and x.occurred_at >= %s and x.occurred_at <= %s
                order by m.sleeper_player_id, x.occurred_at desc, x.id desc
            )
            select p.full_name, giver.display_name, receiver.display_name, x.occurred_at
            from latest x
            join public.transaction_moves d on d.transaction_id = x.id
                and d.sleeper_player_id = x.sleeper_player_id and d.action = 'drop'
            join public.transaction_moves a on a.transaction_id = x.id
                and a.sleeper_player_id = x.sleeper_player_id and a.action = 'add'
            join public.teams gt on gt.id = d.team_id
            join public.members giver on giver.id = gt.member_id
            join public.teams rt on rt.id = a.team_id
            join public.members receiver on receiver.id = rt.member_id
            join public.players p on p.sleeper_player_id = x.sleeper_player_id
            join public.roster_holdings h on h.team_id = a.team_id
                and h.sleeper_player_id = x.sleeper_player_id
            where x.kind = 'trade' and d.team_id <> a.team_id
              and (select count(*) from public.transaction_moves m
                   where m.transaction_id = x.id
                     and m.sleeper_player_id = x.sleeper_player_id) = 2
              and not exists (
                  select 1 from public.roster_holdings other
                  join public.teams ot on ot.id = other.team_id
                  where other.sleeper_player_id = x.sleeper_player_id
                    and ot.season_id = x.season_id and other.team_id <> a.team_id
              )
            order by x.occurred_at desc, x.sleeper_player_id
            limit 25
            """,
            (season, now - TRANSFER_WINDOW, now),
        )
        rows = cur.fetchall()
    if not rows:
        return ""
    return "Recent executed player transfers (last 24 hours):\n" + "\n".join(
        f"{at.isoformat()}: {player}: {giver} -> {receiver} (current holder)"
        for player, giver, receiver, at in rows
    )
