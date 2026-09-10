import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { FORMER_MANAGER, ownerLabelFor } from "../derive/ownerLabel";
import type { HistoryMemberRow } from "../fetchers";
import type { TradeFilters } from "../types";

interface Props {
  filters: TradeFilters;
  seasons: number[];
  types: string[];
  positions: string[];
  members: HistoryMemberRow[];
  memberIds: number[];
  onChange: (next: Partial<TradeFilters>) => void;
  onClear: () => void;
}

/**
 * A `<option>` for a filter value the loaded trades do not offer.
 *
 * The filters live in the URL, so a link can carry a value nothing on screen has — a season the
 * catalog no longer reaches, a position filtered out by the season chip above it. Without this
 * the `<select>` falls back to its first option and silently reads "Any type" while a type
 * filter is in force. Rendered disabled: it says what the filter applies, and the only way out
 * is another value or Clear.
 */
function orphanOption(value: string | null, options: string[]) {
  if (value === null || value === "" || options.includes(value)) return null;
  return (
    <option value={value} disabled>
      {value}
    </option>
  );
}

export function TradeFilterBar(props: Props) {
  const {
    filters,
    seasons,
    types,
    positions,
    members,
    memberIds,
    onChange,
    onClear,
  } = props;
  return (
    <div className="sticky top-0 z-10 space-y-2 bg-muted/40 pb-2 pt-1">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Season">
        {/* The vendored `Badge` is a plain div with no `asChild`, so a chip that must be
            clickable and focusable is a `Button` at `size="sm"`, not a Badge wrapping one. */}
        <Button
          type="button"
          size="sm"
          variant={filters.season === null ? "default" : "outline"}
          aria-pressed={filters.season === null}
          onClick={() => onChange({ season: null })}
        >
          All
        </Button>
        {seasons.map((season) => (
          <Button
            key={season}
            type="button"
            size="sm"
            variant={filters.season === season ? "default" : "outline"}
            aria-pressed={filters.season === season}
            onClick={() => onChange({ season })}
          >
            {season}
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <select
          aria-label="Type"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.type ?? ""}
          onChange={(event) => onChange({ type: event.target.value || null })}
        >
          <option value="">Any type</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
          {orphanOption(filters.type, types)}
        </select>
        <select
          aria-label="Position"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.position ?? ""}
          onChange={(event) =>
            onChange({ position: event.target.value || null })
          }
        >
          <option value="">Any position</option>
          {positions.map((position) => (
            <option key={position} value={position}>
              {position}
            </option>
          ))}
          {orphanOption(filters.position, positions)}
        </select>
        <select
          aria-label="Owner"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.memberId ?? ""}
          onChange={(event) =>
            onChange({
              memberId: event.target.value ? Number(event.target.value) : null,
            })
          }
        >
          <option value="">Any owner</option>
          {/* `memberIds` is only the owners the caller could name — Ben's ruling: the filter
              never lists a former manager, because one such option would stand for every
              unmapped party in the catalog at once. The order is the caller's; `TradesPage`
              sorts these by label. */}
          {memberIds.map((id) => (
            <option key={id} value={id}>
              {ownerLabelFor(id, members) ?? FORMER_MANAGER}
            </option>
          ))}
          {/* A filter the URL carries but this list does not offer, disabled: without it the
              select reads "Any owner" while an owner filter is in force. `FORMER_MANAGER` is
              what an old link pointing at an unmapped party reads as here — it says what the
              filter is doing, which is not the same as offering it. */}
          {filters.memberId !== null &&
            !memberIds.includes(filters.memberId) && (
              <option value={filters.memberId} disabled>
                {ownerLabelFor(filters.memberId, members) ?? FORMER_MANAGER}
              </option>
            )}
        </select>
      </div>

      <div className={cn("flex gap-2")}>
        <Input
          aria-label="Search players"
          placeholder="Search players"
          value={filters.search}
          onChange={(event) => onChange({ search: event.target.value })}
        />
        <Button type="button" variant="outline" onClick={onClear}>
          Clear
        </Button>
      </div>
    </div>
  );
}
