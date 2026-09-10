import { LoaderCircle } from "lucide-react";

/**
 * The one way the site says it is waiting: a small ember spinner and a plain sentence in ash,
 * on the line above whatever is loading. Every list wears this while its data is on its way,
 * and the shell wears it for a whole page while the page's chunk is on its way.
 *
 * Ben, 2026-09-10: "it does feel like the ui just freezes when switching between things." A grey
 * block with no word on it reads as a page that has stopped; a sentence that names what is
 * coming reads as a page that is working. The status role carries the label to a screen reader
 * for the same reason.
 *
 * The spinner is the one spinning thing on the site, and it stops under reduced motion.
 */
export function LoadingState({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={label}
      className="flex items-center gap-2 text-sm text-muted-foreground"
    >
      <LoaderCircle
        aria-hidden="true"
        className="h-4 w-4 shrink-0 animate-spin text-primary motion-reduce:animate-none"
      />
      <span aria-hidden="true">{`${label}…`}</span>
    </div>
  );
}
