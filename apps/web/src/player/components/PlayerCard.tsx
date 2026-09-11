import { injuryTag } from "@/board/derive/availability";
import { draftedHereDescription, formatDraftValue } from "@/board/derive/draft";
import { UNKNOWN_OWNER } from "@/board/derive/join";
import type { DraftPickRow } from "@/board/fetchers";
import type { BoardTeam } from "@/board/types";
import type { BoardQueryError } from "@/board/useBoardData";
import { ExplainedBadge } from "@/components/explained-badge";
import { LoadingState } from "@/components/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { buildPlayerCardView, type PlayerCardView } from "../derive/card";
import { formatDateLine } from "../derive/dateLine";
import type { JourneyEntry, RegisteredLink } from "../derive/journey";
import { rosteredWeeksCaption } from "../derive/points";
import { usePlayerCard } from "../usePlayerCard";

export const PLAYER_LOADING_LABEL = "Loading the player";
export const UNDRAFTED_LABEL = "Undrafted";
export const NOT_ROSTERED_LABEL = "Not rostered this week";
const NO_NUMBER_TEXT = "—";
const DECIMALS = 1;
const TRADE_CODE_DESCRIPTION =
  "The Registrar's code for this trade, as it was recorded from the league chat";
const RESCINDED_DESCRIPTION =
  "The league undid this trade after it was recorded; it is kept for the record";

function figure(value: number | null): string {
  return value === null ? NO_NUMBER_TEXT : value.toFixed(DECIMALS);
}

function Figure({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption?: string;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl leading-none figures text-foreground">{value}</p>
      {caption === undefined ? null : (
        <p className="mt-1 text-xs text-muted-foreground">{caption}</p>
      )}
    </div>
  );
}

/** The trade code chip, the rescinded chip, and the announcement — as the trade cards draw them. */
function Registered({ link }: { link: RegisteredLink }) {
  return (
    <div className="mt-1 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <ExplainedBadge
          description={TRADE_CODE_DESCRIPTION}
          className={badgeVariants({ variant: "default" })}
        >
          {link.tradeCode}
        </ExplainedBadge>
        {link.rescinded ? (
          <ExplainedBadge
            description={RESCINDED_DESCRIPTION}
            className={badgeVariants({ variant: "destructive" })}
          >
            Rescinded
          </ExplainedBadge>
        ) : null}
      </div>
      {link.announcement === null ? null : (
        <blockquote className="line-clamp-4 border-l-2 pl-2 text-xs whitespace-pre-line text-muted-foreground">
          {link.announcement}
        </blockquote>
      )}
    </div>
  );
}

/** One journey entry in words. Owners by the board's label; players by the directory. */
function JourneyItem({
  entry,
  view,
}: {
  entry: JourneyEntry;
  view: PlayerCardView;
}) {
  const owner = (teamId: number | null) =>
    teamId === null
      ? UNKNOWN_OWNER
      : (view.ownerLabelByTeamId.get(teamId) ?? UNKNOWN_OWNER);
  const playerName = (id: string) =>
    view.playerNameById.get(id) ?? `Unknown player ${id}`;
  const rescinded =
    (entry.kind === "traded" && entry.registered?.rescinded === true) ||
    (entry.kind === "announced" && entry.registered.rescinded);
  let sentence: string;
  switch (entry.kind) {
    case "drafted":
      sentence = draftedHereDescription(owner(entry.teamId), entry.amount);
      break;
    case "traded":
      sentence = `Traded from ${owner(entry.fromTeamId)} to ${owner(entry.toTeamId)}`;
      break;
    case "dropped":
      sentence = `Dropped by ${owner(entry.teamId)}`;
      break;
    case "claimed":
      sentence =
        entry.bid === null
          ? `Claimed by ${owner(entry.teamId)}`
          : `Claimed by ${owner(entry.teamId)} for a $${entry.bid} bid`;
      break;
    case "added":
      sentence = `Added by ${owner(entry.teamId)}`;
      break;
    case "commissioner":
      sentence =
        entry.action === "add"
          ? `Commissioner move to ${owner(entry.teamId)}`
          : `Commissioner move from ${owner(entry.teamId)}`;
      break;
    case "announced":
      sentence = "Announced";
      break;
  }
  return (
    <li
      data-journey={entry.kind}
      data-rescinded={rescinded || undefined}
      className="text-sm"
    >
      <p className="text-xs text-muted-foreground">
        {formatDateLine(entry.at, entry.week)}
      </p>
      <p className={cn("font-medium", rescinded && "line-through")}>
        {sentence}
      </p>
      {entry.kind === "traded" && entry.others.length > 0 ? (
        <ul className="text-xs text-muted-foreground">
          {entry.others.map((other) => (
            <li key={other.sleeperPlayerId}>
              {`${playerName(other.sleeperPlayerId)} to ${owner(other.toTeamId)}`}
            </li>
          ))}
        </ul>
      ) : null}
      {entry.kind === "traded" && entry.faab.length > 0 ? (
        <ul className="text-xs text-muted-foreground">
          {entry.faab.map((move, index) => (
            <li key={index}>
              {`$${move.amount} FAAB from ${owner(move.fromTeamId)} to ${owner(move.toTeamId)}`}
            </li>
          ))}
        </ul>
      ) : null}
      {entry.kind === "traded" && entry.registered !== null ? (
        <Registered link={entry.registered} />
      ) : null}
      {entry.kind === "announced" ? (
        <Registered link={entry.registered} />
      ) : null}
    </li>
  );
}

/** The card's body, given its view: pure, so every state is a fixture in the test. */
export function PlayerCardContent({
  view,
  isPending,
  errors,
  onRetry,
}: {
  view: PlayerCardView;
  isPending: boolean;
  errors: BoardQueryError[];
  onRetry: () => void;
}) {
  const tag = injuryTag(view.injuryStatus);
  const meta = [view.position, view.nflTeam].filter(Boolean).join(" · ");
  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{view.name}</DialogTitle>
        <DialogDescription>
          {meta === "" ? null : <span>{meta}</span>}
          {tag === null ? null : (
            <span
              className={cn(
                "ml-2 rounded border px-1 text-[0.6875rem] font-medium",
                tag.isUnavailable
                  ? "border-destructive/40 text-destructive"
                  : "border-border",
              )}
            >
              {tag.title}
            </span>
          )}
        </DialogDescription>
      </DialogHeader>

      {/* The one child allowed to scroll — see the trade modal for the reasoning. */}
      <div className="min-h-0 space-y-4 overflow-y-auto">
        {errors.map((error) => (
          <Alert key={error.section} variant="destructive">
            <AlertTitle>{error.section} could not load</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center gap-3">
              <span>{error.message}</span>
              <Button size="sm" variant="outline" onClick={onRetry}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ))}

        <section aria-label="Numbers" className="flex flex-wrap gap-6">
          {view.numbers.rostered ? (
            <>
              <Figure
                label="Projected"
                value={figure(view.numbers.projected)}
              />
              <Figure label="Live" value={figure(view.numbers.live)} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {NOT_ROSTERED_LABEL}
            </p>
          )}
          <Figure
            label="Season"
            value={view.numbers.season.total.toFixed(DECIMALS)}
            caption={rosteredWeeksCaption(view.numbers.season.weeks)}
          />
        </section>

        <section aria-label="Draft">
          <h3 className="text-xs font-medium text-muted-foreground">Draft</h3>
          {view.draft === null ? (
            <p className="mt-1 text-sm">{UNDRAFTED_LABEL}</p>
          ) : (
            <>
              <p className="mt-1 text-sm font-medium">
                {`${formatDraftValue(view.draft.amount)} · pick ${view.draft.pickNo} · ${view.draft.ownerName}`}
              </p>
              <p className="text-xs text-muted-foreground">
                {view.draft.contextLine}
              </p>
            </>
          )}
        </section>

        <section aria-label="Journey">
          <h3 className="text-xs font-medium text-muted-foreground">Journey</h3>
          {isPending ? (
            <div className="mt-1">
              <LoadingState label={PLAYER_LOADING_LABEL} />
            </div>
          ) : (
            <ol className="mt-1 space-y-3">
              {view.journey.map((entry) => (
                <JourneyItem key={entry.key} entry={entry} view={view} />
              ))}
            </ol>
          )}
        </section>
      </div>
    </DialogContent>
  );
}

export interface PlayerCardBoard {
  season: number | null;
  seasonId: number | null;
  teams: BoardTeam[];
  draftPicks: DraftPickRow[];
  memberIdByTeamId: ReadonlyMap<number, number>;
}

/**
 * The controlled dialog: open while mounted, and `onClose` when Radix asks to close it. Mounted
 * by the page only while `?player=` names somebody, so the hook inside runs only then.
 */
export function PlayerCard({
  sleeperPlayerId,
  board,
  onClose,
}: {
  sleeperPlayerId: string;
  board: PlayerCardBoard;
  onClose: () => void;
}) {
  const data = usePlayerCard({ seasonId: board.seasonId, sleeperPlayerId });
  const view = buildPlayerCardView({
    sleeperPlayerId,
    season: board.season ?? 0,
    teams: board.teams,
    draftPicks: board.draftPicks,
    memberIdByTeamId: board.memberIdByTeamId,
    directory: data.directory,
    otherPlayers: data.otherPlayers,
    transactions: data.transactions,
    moves: data.moves,
    seasonScores: data.seasonScores,
    registered: data.registered,
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <PlayerCardContent
        view={view}
        isPending={data.isPending}
        errors={data.errors}
        onRetry={data.refetch}
      />
    </Dialog>
  );
}
