import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";

import { BOARD_WIDTH } from "@/board/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DraftListSkeleton } from "@/draft/components/DraftSkeleton";
import {
  draftBudgetPerTeam,
  draftRows,
  draftSummary,
  DRAFT_SORT_LABELS,
  DRAFT_SORT_MODES,
  parseDraftSortMode,
  sortDraftRows,
  teamSpend,
  type DraftRow,
  type DraftSortMode,
} from "@/draft/derive/rows";
import { useDraftPage } from "@/draft/useDraftPage";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

const SORT_PARAM = "sort";
export const NO_DRAFT_LABEL = "No draft yet";
const SORT_LABEL = "Sort picks by";
const META_SEPARATOR = " · ";

/** The board's own touch target for a segmented control. */
const TOUCH_TARGET_CLASS = "min-h-[44px] min-w-[44px]";

function Strip({ rows }: { rows: DraftRow[] }) {
  const summary = draftSummary(rows);
  const cells: [string, string][] = [
    ["Picks", String(summary.pickCount)],
    ["Spent", `$${summary.spent}`],
    ["Average", summary.average === null ? "—" : `$${summary.average}`],
  ];
  return (
    <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-center">
      {cells.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-2xl leading-none figures">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PickRow({ row, showOwner }: { row: DraftRow; showOwner: boolean }) {
  const meta = [row.position, row.nflTeam].filter(Boolean).join(META_SEPARATOR);
  return (
    <li className="flex items-center gap-3 rounded-md border bg-card px-3 py-2 text-sm">
      <span className="w-8 shrink-0 text-right text-muted-foreground figures">
        {row.pickNo}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        {/* The board opens the card for `?player=`; a tap on a name lands there. */}
        <Link
          to={`/?player=${row.sleeperPlayerId}`}
          className="truncate font-medium hover:underline"
        >
          {row.fullName}
        </Link>
        <span className="truncate text-xs text-muted-foreground">
          {meta}
          {showOwner && meta !== "" ? META_SEPARATOR : ""}
          {showOwner ? row.ownerName : ""}
        </span>
      </span>
      <span className="shrink-0 text-lg leading-none figures">{`$${row.amount}`}</span>
    </li>
  );
}

export function DraftPage() {
  const [params, setParams] = useSearchParams();
  const page = useDraftPage();
  const mode = parseDraftSortMode(params.get(SORT_PARAM));

  const rows = useMemo(
    () => draftRows(page.picks, page.teams, page.members, page.players),
    [page.picks, page.teams, page.members, page.players],
  );
  const sorted = useMemo(() => sortDraftRows(rows, mode), [rows, mode]);
  const spends = useMemo(
    () => teamSpend(rows, draftBudgetPerTeam(page.waiverBudget)),
    [rows, page.waiverBudget],
  );

  function changeSort(next: DraftSortMode) {
    const updated = new URLSearchParams(params);
    if (next === "pick") updated.delete(SORT_PARAM);
    else updated.set(SORT_PARAM, next);
    setParams(updated, { replace: true });
  }

  const showList = !page.isPending && rows.length > 0;

  return (
    <main className={`${BOARD_WIDTH} space-y-3 px-4 pb-10 sm:px-0`}>
      <div className={`space-y-2 ${REVEAL_CLASS}`} style={revealStyle(0)}>
        <h2 className="text-lg font-semibold">
          {page.season === null ? "Draft" : `${page.season} draft`}
        </h2>
        <Strip rows={rows} />
      </div>

      <ToggleGroup
        type="single"
        value={mode}
        onValueChange={(value) => {
          // Radix hands back "" when the active item is clicked again: a no-op.
          if (value !== "") changeSort(value as DraftSortMode);
        }}
        aria-label={SORT_LABEL}
        variant="outline"
        size="sm"
        className="flex-wrap justify-start"
      >
        {DRAFT_SORT_MODES.map((option) => (
          <ToggleGroupItem
            key={option}
            value={option}
            aria-label={DRAFT_SORT_LABELS[option]}
            className={TOUCH_TARGET_CLASS}
          >
            {DRAFT_SORT_LABELS[option]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {page.errors.map((error) => (
        <Alert key={error.section} variant="destructive">
          <AlertTitle>{error.section} could not load</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error.message}</span>
            <Button size="sm" variant="outline" onClick={page.refetchAll}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ))}

      {page.isPending ? <DraftListSkeleton revealIndex={1} /> : null}

      {!page.isPending && rows.length === 0 ? (
        <Card>
          <CardContent className="p-6">
            <p className="font-medium">{NO_DRAFT_LABEL}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The auction lands here once it is complete and the draft sync has
              run.
            </p>
          </CardContent>
        </Card>
      ) : null}

      {showList && mode !== "team" ? (
        <ol className="space-y-1" aria-label="Picks">
          {sorted.map((row) => (
            <PickRow key={row.sleeperPlayerId} row={row} showOwner />
          ))}
        </ol>
      ) : null}

      {showList && mode === "team" ? (
        <div className="space-y-4">
          {spends.map((spend) => (
            <section key={spend.teamId} aria-label={spend.ownerName}>
              <h3 className="mb-1 text-sm font-medium">
                {spend.ownerName}
                <span className="text-muted-foreground">
                  {`${META_SEPARATOR}$${spend.spent} spent`}
                  {spend.unspent === null
                    ? ""
                    : `${META_SEPARATOR}$${spend.unspent} unspent → $${spend.faab} FAAB`}
                </span>
              </h3>
              <ol className="space-y-1" aria-label={`${spend.ownerName}'s picks`}>
                {sorted
                  .filter((row) => row.teamId === spend.teamId)
                  .map((row) => (
                    <PickRow
                      key={row.sleeperPlayerId}
                      row={row}
                      showOwner={false}
                    />
                  ))}
              </ol>
            </section>
          ))}
        </div>
      ) : null}
    </main>
  );
}
