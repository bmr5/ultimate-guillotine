import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const HistoryPage = () => {
  const historicalWinners = [
    { year: 2023, winner: "Nick Silviera (Nick Nifty's Team)" },
    { year: 2022, winner: "Ben (Supreme Leader)", note: "*" },
    { year: 2021, winner: "Brandon Scott (Ultimate Guilloteam)" },
    { year: 2020, winner: "Michael Hunter (The Two Time)" },
    { year: 2019, winner: "Michael Hunter (Liberals Worst Nightmare)" },
  ];

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="mb-6 text-4xl font-bold">
        Guillotine Gulag League History
      </h1>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Historical Winners</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Year</TableHead>
              <TableHead>Winner</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {historicalWinners.map((entry) => (
              <TableRow key={entry.year}>
                <TableCell>
                  <div className="font-medium">{entry.year}</div>
                </TableCell>
                <TableCell>
                  <div className="font-medium">
                    {entry.winner}
                    {entry.note && (
                      <Badge className="ml-2 text-xs" variant="secondary">
                        {entry.note}
                      </Badge>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className="mt-8">
        <h3 className="mb-4 text-2xl font-semibold">Notes</h3>
        <p>* Indicates a year in which Damar Hamlin died on the field.</p>
      </section>

      <section className="mt-8">
        <h3 className="mb-4 text-2xl font-semibold">League Stats</h3>
        <ul className="list-disc pl-6">
          <li>Most wins: Michael (2 times)</li>
          <li>First winner: Michael (2019)</li>
          <li>Most recent winner: Nick Silviera (2023)</li>
          <li>{"Most collusive trade: Max & Ryan #Friendship Gate"}</li>
        </ul>
      </section>
    </div>
  );
};
