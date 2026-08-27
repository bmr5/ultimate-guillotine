import React from "react";
import {
  ColumnDef,
  ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowUpDown, ChevronDown } from "lucide-react";

import { getOwnerByRosterId } from "@/components/roster-table/getOwnerByRosterId";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLeagueGulagData } from "@/queries/useLeagueGulagData";

import { CURRENT_WEEK, owners } from "../constants";
import { generateLeagueStatusData } from "./generateLeagueStatusData";

interface LeagueWeekData {
  week: number;
  gulagTeams: number[];
  genPoolTeams: number[];
  teamsEliminated: number[];
}

const columns: ColumnDef<LeagueWeekData>[] = [
  {
    accessorKey: "week",
    header: ({ column }) => {
      return (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        >
          Week
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      );
    },
  },
  {
    accessorKey: "gulagTeams",
    header: "Gulag Teams",
    cell: ({ row }) => (
      <div>
        {row.original.gulagTeams.map((team) => (
          <Badge key={team} className="mr-1 bg-amber-300">
            {getOwnerByRosterId(team)?.name}
          </Badge>
        ))}
      </div>
    ),
  },
  {
    accessorKey: "genPoolTeams",
    header: "Gen Pool Teams",
    cell: ({ row }) => (
      <div>
        {row.original.genPoolTeams.map((team) => (
          <Badge key={team} className="mb-1 mr-1 bg-green-300">
            {getOwnerByRosterId(team)?.name}
          </Badge>
        ))}
      </div>
    ),
  },
  {
    accessorKey: "teamsEliminated",
    header: "Teams Eliminated",
    cell: ({ row }) => {
      return (
        <div>
          {row.original.teamsEliminated.map((team) => {
            const owner = getOwnerByRosterId(team);
            const isEliminatedThisWeek =
              owner?.eliminationWeek === row.original.week;

            console.log({ owner, row });

            return (
              <Badge
                key={team}
                variant={isEliminatedThisWeek ? "destructive" : "secondary"}
                className="mr-1 "
              >
                {getOwnerByRosterId(team)?.name}
              </Badge>
            );
          })}
        </div>
      );
    },
  },
];

export const LeagueStatus = () => {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>(
    [],
  );
  const [columnVisibility, setColumnVisibility] = React.useState({});
  const allGulagData = useLeagueGulagData();

  const data = React.useMemo(
    () => generateLeagueStatusData(owners, CURRENT_WEEK, allGulagData),
    [],
  );
  // const data = React.useMemo(() => generateLeagueStatusData(owners), []);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    onSortingChange: setSorting,
    getSortedRowModel: getSortedRowModel(),
    onColumnFiltersChange: setColumnFilters,
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    state: {
      pagination: {
        pageIndex: 0,
        pageSize: 20,
      },
      sorting,
      columnFilters,
      columnVisibility,
    },
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>League Status</CardTitle>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="ml-auto">
              Columns <ChevronDown className="ml-2 h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {table
              .getAllColumns()
              .filter((column) => column.getCanHide())
              .map((column) => {
                return (
                  <DropdownMenuCheckboxItem
                    key={column.id}
                    className="capitalize"
                    checked={column.getIsVisible()}
                    onCheckedChange={(value) =>
                      column.toggleVisibility(!!value)
                    }
                  >
                    {column.id}
                  </DropdownMenuCheckboxItem>
                );
              })}
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <CardContent>
        <div className="flex items-center"></div>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    return (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows?.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && "selected"}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="h-24 text-center"
                  >
                    No results.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
};
