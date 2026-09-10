# The Opening and the Reveal

## Purpose

Ben, 2026-09-10: "when the site loads let's have a fun load in animation. something guillotine
themed", and then "look at the rest of the components in our simple site and have them properly
use suspense and animate in so everything just feels smooth."

This supersedes principle 4 of `2026-09-09-web-redesign-design.md` ("Motion is the sky's alone")
and that spec's out-of-scope line on motion. The rest of the redesign stands: the palette, the
type, the layout and the copy are untouched, and no test that pins them changes.

## The opening

A curtain in the sky's own color, up from the first frame, with a guillotine drawn on it and the
league's name on the block. It is the loading screen as much as the show: the page mounts
underneath it from the first render, so Archivo, the route's chunk and the first Supabase reads
all ride under the curtain, and the curtain never waits for any of them beyond a short cap on
the font.

```
        ═══════════════════════════        the beam, then the uprights, draw themselves
       ┃ ┌───────────────────────┐ ┃
       ┃ │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│ ┃       the blade hangs under the beam; its edge is ember
       ┃ └──────────────────────‾┘ ┃
       ┃                           ┃
       ┃          Ultimate         ┃       ash, small
    ───┃───────  Guillotine  ──────┃───    ink, huge — and the cut line runs through it
       ┃                           ┃
        ═══════════════════════════        the base
```

The timeline, in milliseconds from the start of play (`src/intro/timeline.ts` is the single
source; the stylesheet reads every delay from it):

| when | what |
|---|---|
| 0 – 640 | the frame draws itself; the wordmark and the blade come up |
| 700 | the blade lifts a hair — the rope pulled taut |
| 820 – 1050 | the blade falls, accelerating, and lands on the cut line |
| 1050 | impact: the frame jolts, a line of ember runs the width of the screen, sparks fly, and the bottom half of *Guillotine* drops away and tips |
| 1350 | the curtain parts along the cut — the top half hoisted like the blade, the bottom half falling, faster |
| 1910 | the curtain has cleared; the overlay is gone |

**The trick.** The curtain is two panels, each `overflow: hidden`, and each draws the *whole*
picture, anchored so the cut line sits exactly on the panel's seam. They read as one image until
they part. The bottom panel's copy of the word is the severed half: clipped to its lower half on
the element itself (not by the panel, or the hidden half would slide into view as it fell), it
drops on its own before the curtain does. The blade is drawn behind the word so that, landed, the
word is still seen whole with the blade through it — the cut has to be seen.

**Rules.**
- Decorative: `aria-hidden`, nothing focusable, and never mounted for a reader who asked for
  reduced motion — the same call the sky makes.
- A tap or any key cuts straight to the reveal.
- Only `opacity` and `transform` animate, on compositor layers (the blade on a div, not the SVG),
  so the sky's shaders compiling behind the curtain cannot make the fall stutter.
- Night steel, not bright: dark enough that ink reads over it, lit only along the bevel and the
  ember edge. The palette is the site's own; nothing new is introduced but the steel.

## The reveal

One entrance, everywhere (`src/motion/reveal.ts`): whatever mounts settles into place with the
same short drop — six pixels, the direction the blade goes — in one cascade down the page,
forty-five milliseconds a step, capped at ten steps so a long list does not trail in one card at
a time. The shell first, then a page's header strip, then its cards in rank order; the same when
a page's data lands over its skeleton, and the same when the reader moves to another page.

While the curtain is up the cascade is held at its first frame (`[data-intro="playing"]`), so a
page that loaded under the curtain makes its entrance as the curtain parts. It is one vocabulary
applied to every surface rather than a choreography per section — that is what keeps a page of
eighteen cards from reading as eighteen effects. Reduced motion stills it.

## Suspense

The shell renders every page inside one Suspense boundary with a placeholder the shape every
page shares. The trades and history pages arrive in their own chunks (`src/app/lazyPages.ts`);
the board does not, because it is the home page and a round trip for its chunk would sit in
front of its first Supabase read. Navigations are transitions, so moving between pages keeps the
old page on screen until the new one is ready; the placeholder is only ever seen on a cold load,
under the curtain.

Data stays on `useQuery`, not `useSuspenseQuery`: every page renders what loaded alongside an
alert for what did not, and the board's queries are scoped by the ones before them. Suspending on
data would throw away both.

## Done means

- The opening plays on a cold load at desktop and 375 px, is skippable, and is absent under
  reduced motion; the page beneath is already there when the curtain parts.
- Every page and every card cascades in, on load and on navigation, with no layout shift.
- The trades and history pages are separate chunks in the build.
- Every existing test passes; the opening, the gate, the cascade helpers, the timeline and the
  shell's boundary each have tests of their own.
