import { useId, useState } from "react";

import { cn } from "@/lib/utils";

import { bandTagline } from "../derive/bandTagline";
import {
  curveBands,
  curveHeightAt,
  faabCurve,
  inBand,
  type CurveBand,
} from "../derive/curve";
import { formatFaab } from "../derive/faab";
import type { FaabTiers, TierKey } from "../derive/tiers";

const WIDTH = 600;
const HEIGHT = 220;
const PAD = { top: 16, right: 16, bottom: 44, left: 16 };
const DOT_RADIUS = 5;

/** Tier colours as Tailwind classes, so the chart follows the theme like everything else. */
const TIER_DOT_CLASS: Record<TierKey, string> = {
  rich: "fill-primary",
  medium: "fill-foreground/60",
  poor: "fill-destructive",
};

const bandLabel = (band: CurveBand) =>
  `${formatFaab(band.from)}–${formatFaab(band.to)}`;

/**
 * A bell curve fitted to the league's FAAB, every team a dot on it coloured by tier, on a fixed
 * axis from $0 to the next $100 above the richest team. Hover, tap or focus a $50 band to see
 * who sits in it (Ben, 2026-09-10). Inline SVG, theme tokens only, and a visually hidden table
 * so the picture is also readable.
 */
export function FaabCurveChart({ tiers }: { tiers: FaabTiers }) {
  const titleId = useId();
  const readoutId = useId();
  const [active, setActive] = useState<number | null>(null);
  const teams = tiers.tiers.flatMap((tier) =>
    tier.teams.map((team) => ({ team, tier: tier.key })),
  );
  const values = teams.map(({ team }) => team.faabRemaining as number);
  if (values.length === 0) return null;
  const curve = faabCurve(values);
  const bands = curveBands(curve);
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const xFor = (value: number) =>
    PAD.left +
    ((value - curve.from) / (curve.to - curve.from || 1)) * plotWidth;
  const yFor = (height: number) => PAD.top + (1 - height) * plotHeight;
  const path = curve.points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${xFor(p.x).toFixed(1)},${yFor(p.y).toFixed(1)}`,
    )
    .join(" ");
  const baseline = yFor(0);
  const teamsIn = (index: number) =>
    teams.filter(({ team }) =>
      inBand(
        team.faabRemaining as number,
        bands[index],
        index === bands.length - 1,
      ),
    );
  const activeTeams = active === null ? [] : teamsIn(active);
  const richest = teams[0]?.team ?? null;
  const poorest = teams.length ? teams[teams.length - 1].team : null;

  return (
    <figure className="rounded-xl border bg-card p-4">
      <figcaption id={titleId} className="mb-2 text-xs text-muted-foreground">
        {`The league's FAAB as a bell curve: mean ${formatFaab(Math.round(curve.mean))}, one deviation ${formatFaab(Math.round(curve.sd))}. Every dot is a team; hover a $50 band to see who is in it.`}
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby={titleId}
        className="h-auto w-full"
        onPointerLeave={() => setActive(null)}
      >
        <path
          d={`${path} L${xFor(curve.to).toFixed(1)},${baseline} L${xFor(curve.from).toFixed(1)},${baseline} Z`}
          className="fill-primary/10"
        />
        <path d={path} className="fill-none stroke-primary" strokeWidth={2} />
        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={baseline}
          y2={baseline}
          className="stroke-border"
        />
        {bands.map((band, index) => (
          <g key={band.from}>
            <line
              x1={xFor(band.from)}
              x2={xFor(band.from)}
              y1={baseline}
              y2={baseline + 6}
              className="stroke-border"
            />
            {/* $50 ticks, labels staggered on two rows so they read at phone width. */}
            <text
              x={xFor(band.from)}
              y={baseline + (index % 2 === 0 ? 18 : 30)}
              textAnchor="middle"
              className={cn(
                "text-[10px]",
                index % 2 === 0
                  ? "fill-muted-foreground"
                  : "fill-muted-foreground/70",
              )}
            >
              {formatFaab(band.from)}
            </text>
            {/* The hover / tap / focus target for the band: the whole column of the plot. */}
            <rect
              data-band={band.from}
              role="button"
              tabIndex={0}
              aria-label={`${bandLabel(band)}: ${teamsIn(index).length} ${teamsIn(index).length === 1 ? "team" : "teams"}`}
              aria-describedby={readoutId}
              x={xFor(band.from)}
              y={PAD.top}
              width={xFor(band.to) - xFor(band.from)}
              height={plotHeight}
              className={cn(
                "cursor-pointer fill-transparent outline-none",
                active === index && "fill-accent/40",
              )}
              onPointerEnter={() => setActive(index)}
              onClick={() => setActive(index)}
              onFocus={() => setActive(index)}
              onBlur={() => setActive(null)}
            />
          </g>
        ))}
        <text
          x={WIDTH - PAD.right}
          y={baseline + (bands.length % 2 === 0 ? 18 : 30)}
          textAnchor="end"
          className="fill-muted-foreground text-[10px]"
        >
          {formatFaab(curve.to)}
        </text>
        {teams.map(({ team, tier }) => {
          const value = team.faabRemaining as number;
          const highlighted =
            active !== null &&
            inBand(value, bands[active], active === bands.length - 1);
          return (
            <circle
              key={team.teamId}
              data-team={team.teamId}
              data-tier={tier}
              cx={xFor(value)}
              cy={yFor(curveHeightAt(curve, value))}
              r={highlighted ? DOT_RADIUS + 2 : DOT_RADIUS}
              className={cn(
                TIER_DOT_CLASS[tier],
                "pointer-events-none stroke-background",
              )}
              strokeWidth={1.5}
            >
              <title>{`${team.ownerName} · ${formatFaab(value)}`}</title>
            </circle>
          );
        })}
      </svg>
      <div
        id={readoutId}
        data-readout
        aria-live="polite"
        className="mt-2 min-h-[2.5rem] text-sm"
      >
        {active === null ? (
          <p className="text-muted-foreground">
            Hover or tap a band on the curve.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {bandLabel(bands[active])}
            </p>
            <p data-band-tagline className="italic">
              {bandTagline(
                bands[active],
                curve,
                activeTeams.map(({ team }) => team),
                richest,
                poorest,
              )}
            </p>
            {activeTeams.length === 0 ? (
              <p>Nobody in this band.</p>
            ) : (
              <ul className="flex flex-wrap gap-x-4 gap-y-1">
                {activeTeams.map(({ team }) => (
                  <li key={team.teamId}>
                    <span className="font-medium">{team.ownerName}</span>
                    <span className="text-muted-foreground tabular-nums">{` ${formatFaab(team.faabRemaining as number)}`}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      <table className="sr-only">
        <caption>Teams on the curve</caption>
        <tbody>
          {teams.map(({ team, tier }) => (
            <tr key={team.teamId}>
              <th scope="row">{team.ownerName}</th>
              <td>{formatFaab(team.faabRemaining as number)}</td>
              <td>{tier}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
