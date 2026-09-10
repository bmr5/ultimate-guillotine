import { resolveOwnerLabel } from "@/board/derive/join";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
          {memberIds.map((id) => (
            <option key={id} value={id}>
              {resolveOwnerLabel(members.find((member) => member.id === id))}
            </option>
          ))}
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
