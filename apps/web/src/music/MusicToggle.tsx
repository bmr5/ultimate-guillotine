import { Volume2, VolumeX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { TOGGLE_ATTRIBUTE, useMusic } from "./useMusic";

/**
 * One label whichever way the button is: it is a toggle, and `aria-pressed` says which way.
 * Pressed is muted — the button does what it says — and it starts pressed.
 */
export const MUTE_LABEL = "Mute music";

/**
 * The mute button, and the only sign on the page that there is music at all.
 *
 * Ben, 2026-09-10: "just put a mute button somewhere". It sits in the shell so it is on every
 * page, and it is a 44px target like the board's own controls, because muting is the one thing
 * a member may want to do in a hurry on a phone.
 */
export function MusicToggle({ className }: { className?: string }) {
  const { muted, toggle } = useMusic();
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={MUTE_LABEL}
      aria-pressed={muted}
      onClick={toggle}
      {...{ [TOGGLE_ATTRIBUTE]: "" }}
      className={cn(
        "min-h-[44px] min-w-[44px] text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      {muted ? (
        <VolumeX className="size-5" aria-hidden="true" />
      ) : (
        <Volume2 className="size-5" aria-hidden="true" />
      )}
    </Button>
  );
}
