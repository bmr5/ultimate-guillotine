-- Ben's board addendum: an injured starter with no projection was rendering as a coverage
-- hole -- the card said `partial`, as if Sleeper had simply not published a number, when the
-- real answer is that the player is out. The board can only tell "no data" from "not playing"
-- if the directory carries Sleeper's own flag, so it does.
--
-- Nullable, and null is the normal case: on 2026-09-09 the players feed carried a status on
-- 731 of 12,227 records and nothing at all on the other 11,496.
alter table public.players add column if not exists injury_status text;

-- No check constraint on this column, deliberately. Sleeper's vocabulary on 2026-09-09
-- (`curl -s https://api.sleeper.app/v1/players/nfl`) was Questionable 362, IR 198, NA 95,
-- PUP 38, Out 21, Sus 11, COV 2, DNR 2, Doubtful 1 -- plus one record carrying an empty
-- string, which the sync normalises to null rather than storing. But Sleeper can add a
-- tenth value on any Tuesday, and a constraint would turn that into a failed
-- `ug sleeper players`: the whole directory frozen on the last good rows over one string.
-- The vocabulary is enforced in the sync instead (`KNOWN_INJURY_STATUSES` in
-- `sleeper/players.py`), which reads an unknown value as *no flag*, counts it, and says so
-- in `#guillotine-ops`. The comment below is the record of what the column is for.
--
-- Dropped rather than merely omitted: an earlier revision of this migration added the
-- constraint, so a database that applied that revision locally still carries it.
alter table public.players
  drop constraint if exists players_injury_status_check;

-- No grant or policy changes: the column rides the table's existing ones -- select for
-- anon/authenticated, insert/update for automation_worker -- and this is public Sleeper data
-- every league member can already read in the Sleeper app.
comment on column public.players.injury_status is
  'Sleeper''s injury flag, verbatim; null when the feed carries none, or carries a value the sync does not know. Vocabulary as of 2026-09-09: Questionable, Doubtful, Out, IR, PUP, Sus, NA, COV, DNR. Out/IR/PUP/Sus/COV/DNR mean the player is not playing. Not check-constrained: see KNOWN_INJURY_STATUSES in sleeper/players.py.';
