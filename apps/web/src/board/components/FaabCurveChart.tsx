import { useId } from "react";

import { curveHeightAt, faabCurve } from "../derive/curve";
import { formatFaab } from "../derive/faab";
import type { FaabTiers, TierKey } from "../derive/tiers";

const WIDTH = 600;
const HEIGHT = 220;
const PAD = { top: 16, right: 16, bottom: 36, left: 16 };
const DOT_RADIUS = 5;

/** Tier colours as Tailwind classes, so the chart follows the theme like everything else. */
const TIER_DOT_CLASS: Record<TierKey, string> = {
  rich: "fill-primary",
  medium: "fill-foreground/60",
  poor: "fill-destructive",
};

/**
 * A bell curve fitted to the league's FAAB, with every team as a dot on it, coloured by tier.
 * Inline SVG, theme tokens only, and a visually hidden table so the picture is also readable.
 */
export function FaabCurveChart({ tiers }: { tiers: FaabTiers }) {
  const titleId = useId();
  const teams = tiers.tiers.flatMap((tier) =>
    tier.teams.map((team) => ({ team, tier: tier.key })),
  );
  const values = teams.map(({ team }) => team.faabRemaining as number);
  if (values.length === 0) return null;
  const curve = faabCurve(values);
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
  const ticks = [
    curve.mean - curve.sd,
    curve.mean,
    curve.mean + curve.sd,
  ].filter((t) => t >= curve.from && t <= curve.to);

  return (
    <figure className="rounded-xl border bg-card p-4">
      <figcaption id={titleId} className="mb-2 text-xs text-muted-foreground">
        {`The league's FAAB as a bell curve: mean ${formatFaab(Math.round(curve.mean))}, one deviation ${formatFaab(Math.round(curve.sd))}. Every dot is a team.`}
      </figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby={titleId}
        className="h-auto w-full"
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
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={xFor(tick)}
              x2={xFor(tick)}
              y1={baseline}
              y2={baseline + 6}
              className="stroke-border"
            />
            <text
              x={xFor(tick)}
              y={baseline + 20}
              textAnchor="middle"
              className="fill-muted-foreground text-[11px]"
            >
              {formatFaab(Math.round(tick))}
            </text>
          </g>
        ))}
        {teams.map(({ team, tier }) => {
          const value = team.faabRemaining as number;
          return (
            <circle
              key={team.teamId}
              data-team={team.teamId}
              data-tier={tier}
              cx={xFor(value)}
              cy={yFor(curveHeightAt(curve, value))}
              r={DOT_RADIUS}
              className={`${TIER_DOT_CLASS[tier]} stroke-background`}
              strokeWidth={1.5}
            >
              <title>{`${team.ownerName} · ${formatFaab(value)}`}</title>
            </circle>
          );
        })}
      </svg>
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
