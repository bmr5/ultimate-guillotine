-- Ben's board addendum: an injured starter with no projection was rendering as a coverage
-- hole -- the card said `partial`, as if Sleeper had simply not published a number, when the
-- real answer is that the player is out. The board can only tell "no data" from "not playing"
-- if the directory carries Sleeper's own flag, so it does.
--
-- Nullable, and null is the normal case: on 2026-09-09 the players feed carried a status on
-- 731 of 12,227 records and nothing at all on the other 11,496.
alter table public.players add column if not exists injury_status text;

-- Sleeper's own vocabulary, and nothing else. Counted off the live feed on 2026-09-09
-- (`curl -s https://api.sleeper.app/v1/players/nfl`): Questionable 362, IR 198, NA 95,
-- PUP 38, Out 21, Sus 11, COV 2, DNR 2, Doubtful 1 -- plus one record carrying an empty
-- string, which the sync normalises to null rather than storing.
--
-- The constraint is the contract with `ug sleeper players`: a free-text injury note reaching
-- this column would surface on a card as an unreadable tag and, worse, would be silently
-- treated as "not one of the unavailable statuses" by the board. If Sleeper ever adds a tenth
-- value the sync fails loudly inside its own transaction, the last good rows survive, and the
-- value gets added here deliberately.
alter table public.players
  add constraint players_injury_status_check
  check (
    injury_status is null
    or injury_status in ('Questionable', 'Doubtful', 'Out', 'IR', 'PUP', 'Sus', 'NA', 'COV', 'DNR')
  );

-- No grant or policy changes: the column rides the table's existing ones -- select for
-- anon/authenticated, insert/update for automation_worker -- and this is public Sleeper data
-- every league member can already read in the Sleeper app.
comment on column public.players.injury_status is
  'Sleeper''s injury flag, verbatim; null when the feed carries none. Out/IR/PUP/Sus/COV/DNR mean the player is not playing.';
