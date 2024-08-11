import React from "react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const LeagueScheduleTable = () => {
  const scheduleData = [
    { week: 1, total: 19, gulag: 0, genPool: 19, eliminated: 0, surviving: 19 },
    { week: 2, total: 19, gulag: 2, genPool: 17, eliminated: 1, surviving: 18 },
    { week: 3, total: 18, gulag: 2, genPool: 16, eliminated: 1, surviving: 17 },
    { week: 4, total: 17, gulag: 2, genPool: 15, eliminated: 1, surviving: 16 },
    { week: 5, total: 16, gulag: 2, genPool: 14, eliminated: 1, surviving: 15 },
    { week: 6, total: 15, gulag: 2, genPool: 13, eliminated: 1, surviving: 14 },
    { week: 7, total: 14, gulag: 2, genPool: 12, eliminated: 1, surviving: 13 },
    { week: 8, total: 13, gulag: 2, genPool: 11, eliminated: 1, surviving: 12 },
    { week: 9, total: 12, gulag: 2, genPool: 10, eliminated: 1, surviving: 11 },
    { week: 10, total: 11, gulag: 2, genPool: 9, eliminated: 1, surviving: 10 },
    { week: 11, total: 10, gulag: 2, genPool: 8, eliminated: 1, surviving: 9 },
    { week: 12, total: 9, gulag: 3, genPool: 6, eliminated: 3, surviving: 6 },
    { week: 13, total: 6, gulag: 0, genPool: 6, eliminated: 1, surviving: 5 },
    { week: 14, total: 5, gulag: 0, genPool: 5, eliminated: 1, surviving: 4 },
    { week: 15, total: 4, gulag: 0, genPool: 4, eliminated: 1, surviving: 3 },
    { week: 16, total: 3, gulag: 0, genPool: 3, eliminated: 1, surviving: 2 },
    {
      week: 17,
      total: 2,
      gulag: 0,
      genPool: 2,
      eliminated: 1,
      surviving: "1 (Winner)",
    },
  ];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Week</TableHead>
          <TableHead className="hidden sm:table-cell">Total Teams</TableHead>
          <TableHead className="hidden sm:table-cell">Gulag Teams</TableHead>
          <TableHead className="hidden md:table-cell">Gen Pool Teams</TableHead>
          <TableHead>Teams Eliminated</TableHead>
          <TableHead className="text-right">Surviving Teams</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {scheduleData.map((row) => (
          <TableRow key={row.week}>
            <TableCell>
              <div className="font-medium">Week {row.week}</div>
            </TableCell>
            <TableCell className="hidden sm:table-cell">{row.total}</TableCell>
            <TableCell className="hidden sm:table-cell">
              {row.gulag > 0 && (
                <Badge className="text-xs" variant="secondary">
                  {row.gulag}
                </Badge>
              )}
            </TableCell>
            <TableCell className="hidden md:table-cell">
              {row.genPool}
            </TableCell>
            <TableCell>
              {row.eliminated > 0 && (
                <Badge className="text-xs" variant="destructive">
                  {row.eliminated}
                </Badge>
              )}
            </TableCell>
            <TableCell className="text-right">{row.surviving}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
