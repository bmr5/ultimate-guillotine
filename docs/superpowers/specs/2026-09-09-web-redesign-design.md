# Web Redesign

## Purpose

The three public pages — the board, `/trades`, `/history` — get one visual identity, built on the
toolchain `2026-09-09-web-modernization-design.md` landed. Ben's brief, in order: modern
component stack (done), the vgpu "adaptive quality" aurora as the background of the whole app, and
**dark only**. This spec is the look; it changes no data, no derivation, no route, and no DOM that
a test or an accessibility decision depends on.

## The subject

An 18-team guillotine league: every week the lowest score is cut and its roster goes to waivers.
The readers are league members on phones on Sunday afternoon, and the page's job is to answer
"where do I project, and who is on the block" in one glance. Everything below serves that.

## Design plan

**The sky.** The one bold element. The vgpu `adaptive-quality` example — a ray-marched aurora with
bloom over a sparse star field, teal into violet into amber — fills the viewport behind every page,
fixed, at the back of the stacking order, pointer-events off and `aria-hidden`. It runs the
example's own quality controller: High to start, one downgrade to Low when the GPU tier, battery
or presented FPS says so, prepared off-screen. Nothing else on the page glows, moves on its own,
or has a shadow.

**Color.** Taken from the shader's palette so the UI and the sky read as one thing.

| Token | Value | Role |
|---|---|---|
| sky | `#05070C` | the shader's horizon; the body ground and what shows when there is no WebGPU |
| glass | sky at 80% (`#0B0E17` / 0.8) | card and panel surfaces — smoked, not frosted, so the aurora shows through faintly without a per-frame backdrop blur |
| glass edge | white at 10% | the one border |
| ink | `#F2F3F8` | text |
| ash | `#A3A9BD` | secondary text |
| ember | `#F0A24A` | the single accent — active filter, focus ring, links, FAAB |
| blade | `#FF6B7A` | out starters, eliminated, destructive, the eliminated divider |

Only the sticky board strip frosts (`backdrop-blur-md`): it is the one surface that sits over
moving content while the reader scrolls, and one blurred layer is affordable where eighteen are
not.

**Type.** One family, **Archivo** (variable; width 62–125, weight 100–900), self-hosted through
`@fontsource-variable/archivo` so nothing loads from a third party. Two voices from one face:

- *figures* — narrow width (`font-stretch: 75%`), weight 700, tabular numerals: projections,
  scores, ranks, the week number, FAAB totals, the stats strip, champion names on the history page.
- *words* — normal width, weight 400–500: everything else.

Scale, on a 16px base: 12 / 14 / 16 / 20 / 24 / 32 / 44. A card's emphasized figure is 32, the
secondary 20, the rank 20 in ash; the wordmark is 24; the stats strip figures 24.

**Layout.** The board's single ranked column (Ben's ruling, landed the same day: the ranked
board is always one column, `max-w-2xl`), the card's two-row summary, the sticky header, the
trade and season cards all keep their structure — they are tested and they carry Ben's rulings.
What changes:

```
Ultimate Guillotine                       ← wordmark, figures voice, 24
Board   Trades   History                  ← plain words; the current one in ink with an ember rule

        ╭ frosted strip (sticky) ─────────────────────╮
        │ Week 1   Scores updated 9:30 PM · 18 min ago │
        │ All QB RB WR TE K DEF                        │
        │ Projection Score FAAB Total        [search]  │
        ╰──────────────────────────────────────────────╯
        ╭──────────────────────────────────────────────╮
        │ 1  Charlie                    34.5   122.2   │   ← glass card, 12px radius, no shadow;
        │    chobes                    Score    Proj   │     figures voice, stepping up at sm
        │    Total 301.5 · 475 FAAB                    │
        ╰──────────────────────────────────────────────╯
        ╭──────────────────────────────────────────────╮
        │ 2  Daniel                     26.2   116.7   │
        ╰──────────────────────────────────────────────╯
        ────────────── Eliminated (3) ──────────────       ← a thin blade rule
```

Left-aligned throughout; figures right-aligned in their own column. Radius encodes the level:
containers 12px, controls 6px, chips 4px. The shell has no bar and no border — the wordmark and
nav sit on the sky.

**Copy and chrome.** The site's ` · ` separator stays: it is a documented convention with tests
behind it. The history page's `CHAMPION 2024` eyebrow and the stats strip's all-caps labels become
sentence case in ash. No new labels, eyebrows, numbering or arrows are added.

**Principles.**
1. The sky is the one bold thing; every surface is smoked glass so it stays in view.
2. Figures are the typography. Words stay quiet.
3. Hierarchy by weight and width, not by borders, caps or dividers.
4. Motion is the sky's alone. The only other motion answers a tap (a card opening).

Checked against the generic defaults before building: the dark ground and single accent are the
brief's own pin, and the accent is the shader's amber rather than a stock green; the card grid is
a prior ruling, so the kit tells around it go instead — no shadows, no gradient washes, no uniform
radius, no caps eyebrows, no mono data labels.

## Implementation

**Sky.** `src/sky/` holds the example's `renderer.ts`, `scene.ts`, `quality*.ts`,
`frame-health.ts` and the four `.wgsl` files, unchanged apart from removing the HUD. `Sky.tsx`
owns a fixed full-viewport `<canvas>` and mounts the renderer only when `navigator.gpu` exists
and `prefers-reduced-motion` is not `reduce`; otherwise it renders nothing and the body's sky
color and a static radial wash in the same palette stand in. The renderer is disposed on unmount;
`frameLoop` already idles in a hidden tab. Errors from the renderer are reported to the console and
leave the fallback in place — the sky is never a reason the board fails to render. Dependencies:
`vgpu`, `@vgpu/wgsl` (its Vite plugin resolves `.wgsl` imports; `src/wgsl-env.d.ts` types them),
`@pmndrs/detect-gpu` (lazy, only on the High tier while signals are armed).

**Dark only.** `<html class="dark">` in `index.html`; `ThemeProvider`, `theme-context`,
`ModeToggle` and `icons.tsx` are deleted; `globals.css` defines the tokens once on `:root` with no
`.dark` block and no dark variant. The `vite-ui-theme` localStorage key is left alone — nothing
reads it any more.

**Primitives.** The ten kept primitives are regenerated from the current shadcn registry now that
their look is meant to change, then given the tokens above; the `*-variants.ts` split stays. The
focus ring is `ring-2 ring-ring` in ember, so the two tests that pin `focus-visible:ring-2` /
`focus-visible:ring-ring` still hold.

**Order of work.** Each slice ends green (`pnpm test:web`, `pnpm lint`, `pnpm build`), is looked
at in the browser at desktop and 375 px, and merges to main:

1. Foundation — tokens, Archivo, the sky, the shell, dark-only, regenerated primitives.
2. The board — header strip, team card, roster panel, position view, states and divider.
3. Trades and history — filter bar, stats strip, trade card, winners strip, season card.

## Done means

- All three pages render over the aurora on a WebGPU browser and over the static wash without
  one, with no console errors in either.
- The quality signals arm after the first High frame (the GPU tier and battery readings show in
  the console); the frame-health downgrade is the example's own, unchanged.
- Every existing test passes; the ones that pinned a class the design changed are updated with
  the design, not deleted.
- Keyboard focus is visible on every control; `prefers-reduced-motion` stills the sky.
- Ben has reviewed the Vercel preview at 375 px.

## Out of scope

- Any change to what the pages say, sort, filter or fetch.
- A light theme.
- Motion beyond the sky and the collapsibles' own open/close.
