import { useId, useRef, useState, type ComponentProps } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * The same ring every bare `<button>` on the site carries, drawn *inside* the badge. A badge
 * often sits in a clipped, fixed-height line, and an offset ring is drawn outside its box —
 * which is outside the line — so the clipping cuts the ring off the one control on the card
 * that is hardest to see. `ring-inset` puts it on the badge's own border, where nothing clips it.
 */
const BADGE_FOCUS_RING_CLASS =
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

export interface ExplainedBadgeProps extends Omit<
  ComponentProps<"button">,
  "type" | "onClick"
> {
  /** The sentence behind the badge: why it is on the card at all. */
  description: string;
  /** A second, quieter line under the sentence — a timestamp, a figure. */
  secondary?: string | undefined;
}

/**
 * A badge that can say why it is there.
 *
 * Ben's ruling of 2026-09-09: "put a tooltip on all the badges that surface. I filtered by TE
 * and a likely bidder showed up but I have no idea why". The native `title` a badge used to
 * carry never opens on a tap, and a phone is where this board is read — so every badge with a
 * reason is a real Radix tooltip trigger, and the reason is also mounted as visually hidden text
 * named by `aria-describedby`, so a screen reader gets it whether or not the tooltip is open.
 *
 * The badge is a `<button>` rather than a `<div>` wrapped in one: a badge lives beside a card's
 * own toggle, and a control inside a `<button>` is invalid HTML. Callers therefore keep it a
 * *sibling* of any toggle, and style it with the badge classes they want.
 *
 * The tooltip is controlled rather than left to Radix's hover-and-focus default, because Radix
 * suppresses tooltips opened by touch. Hover and keyboard focus still open it through
 * `onOpenChange`; the click handler adds tap.
 *
 * The tap toggle reads a latched copy of `open` rather than the current state, because by the
 * time `onClick` runs the state is no longer the one the reader tapped: the open tooltip's
 * dismissable layer closes on the `pointerdown` that starts the second tap, and Radix's own
 * trigger closes again on the click. A plain `!open` therefore resolves against a just-set
 * `false` and re-opens the tooltip the tap was meant to dismiss. `onPointerDownCapture` runs
 * before either close — capture, at the trigger, beats a document-level listener — so it records
 * what the reader actually saw, and the click toggles against that.
 */
export function ExplainedBadge({
  description,
  secondary,
  className,
  children,
  ...rest
}: ExplainedBadgeProps) {
  const [open, setOpen] = useState(false);
  // What the tooltip was doing when the tap began. False is the right resting value: a click with
  // no pointerdown before it is a keyboard activation, and focus has already opened the tooltip.
  const openAtPointerDown = useRef(false);
  const descriptionId = useId();
  // The quieter line is part of the reason: a reader who cannot see the tooltip still gets the
  // figure or the timestamp it carries, after the sentence and one full stop.
  const fullStop = /[.!?]$/.test(description) ? "" : ".";
  const spokenDescription =
    secondary === undefined
      ? description
      : `${description}${fullStop} ${secondary}`;

  return (
    <TooltipProvider>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-describedby={descriptionId}
            onPointerDownCapture={() => {
              openAtPointerDown.current = open;
            }}
            onClick={() => {
              const wasOpen = openAtPointerDown.current;
              openAtPointerDown.current = false;
              setOpen(!wasOpen);
            }}
            className={cn(BADGE_FOCUS_RING_CLASS, className)}
            {...rest}
          >
            {children}
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[16rem] text-left whitespace-pre-line">
          <span className="block">{description}</span>
          {secondary === undefined ? null : (
            <span className="mt-1 block text-xs text-muted-foreground">
              {secondary}
            </span>
          )}
        </TooltipContent>
      </Tooltip>
      <span id={descriptionId} className="sr-only">
        {spokenDescription}
      </span>
    </TooltipProvider>
  );
}
