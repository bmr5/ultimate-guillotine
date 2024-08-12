import { MobileRosterTable } from "@/components/roster-table/MobileRosterTable";
import { RosterTable } from "@/components/roster-table/RosterTable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIsMobile } from "@/lib/hooks/useIsMobile";

export const RostersPage = () => {
  const isMobile = useIsMobile();

  return isMobile ? (
    <MobileRosterTable type="full" />
  ) : (
    <Card className="">
      <CardHeader className="flex flex-row items-start">
        <div className="grid gap-0.5">
          <CardTitle className="group flex items-center gap-2 text-lg">
            League Rosters
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="p-6 text-sm">
        <RosterTable type="full" />
      </CardContent>
    </Card>
  );
};
