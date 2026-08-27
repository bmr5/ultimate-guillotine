import { useState } from "react";
import { LayoutGridIcon, TableIcon } from "lucide-react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { LeagueStatus } from "../status/LeagueStatus";
import { MobileLeagueStatus } from "../status/MobileLeagueStatus";
import { HeaderAnalytics } from "./HeaderAnalytics";
import { RosterCard } from "./RosterCard";

export default function HomePage() {
  const [view, setView] = useState<string>("card");

  return (
    <main className="grid flex-1 items-start gap-4  sm:py-0 md:gap-8 lg:grid-cols-3 xl:grid-cols-3">
      <div className="grid auto-rows-max items-start gap-4 md:gap-8 lg:col-span-2">
        <HeaderAnalytics />
        <div className="space-y-2">
          <ToggleGroup
            type="single"
            value={view}
            onValueChange={setView}
            className="hidden justify-end sm:block"
          >
            <ToggleGroupItem value="card" aria-label="Card View">
              <LayoutGridIcon className="h-4 w-4" />
            </ToggleGroupItem>
            <ToggleGroupItem value="table" aria-label="Table View">
              <TableIcon className=" h-4 w-4" />
            </ToggleGroupItem>
          </ToggleGroup>
          {view === "table" ? <LeagueStatus /> : <MobileLeagueStatus />}
        </div>
      </div>
      <RosterCard />
    </main>
  );
}
