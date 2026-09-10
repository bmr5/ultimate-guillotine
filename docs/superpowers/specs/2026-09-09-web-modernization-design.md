# Web Modernization

## Purpose

`apps/web` is a shadcn/ui-shaped Vite app scaffolded in 2023 and never brought current: no
`components.json`, 48 hand-copied primitives of which the three pages use 10, and every major
dependency one or two generations back (Tailwind 3, React 18, Vite 4, thirty separate
`@radix-ui/react-*` packages). This spec brings the toolchain to the current shadcn stack **without
changing what any page renders**, so that the redesign that follows (its own spec) starts from a
toolchain the shadcn CLI can add to and update.

Ben's decision: modernize the existing stack in place rather than replace it. Radix stays as the
primitive layer — the board's focus-ring, reduced-motion and aria work is tuned to it — and the
app stays a Vite SPA on Vercel; Next.js buys a read-only league board nothing.

## Target stack

| Layer | From | To |
|---|---|---|
| React | 18.2 | 19 |
| Vite / plugin-react | 4 / 4 | 8 / 6 |
| Vitest / testing-library | 3 / 16 | 5 / current |
| TypeScript | 5.0 | current 5.x |
| ESLint | 8, `.eslintrc.cjs` | 9, flat `eslint.config.js`, `typescript-eslint` 8 |
| Tailwind | 3.3, `tailwind.config.js`, PostCSS + autoprefixer | 4, CSS-first `@theme` in `globals.css`, `@tailwindcss/vite`, no PostCSS |
| `tailwindcss-animate` | plugin | `tw-animate-css` |
| `tailwind-merge` | 1 | 3 |
| shadcn | none (no `components.json`) | CLI v4, `new-york`, `components.json` committed |
| Radix | 30 × `@radix-ui/react-*` | one `radix-ui` package |
| React Router | `react-router-dom` 6 | `react-router` 8, same data-router API |
| `lucide-react` | 0.427 | current |
| TanStack Query | 5.51 | 5 current |

Removed outright (no app code imports them): `react-hook-form`, `@hookform/resolvers`, `zod`,
`cmdk`, `vaul`, `react-day-picker`, `date-fns`, `@tailwindcss/forms`, `autoprefixer`, `postcss`,
and the 38 `components/ui/*` files nothing imports, plus `lib/validations.ts` and
`lib/type-helpers.ts`. A primitive the redesign later needs is one `shadcn add` away.

The 10 primitives that stay — `alert`, `badge`, `button`, `card`, `collapsible`, `dropdown-menu`,
`input`, `skeleton`, `toggle-group`, `tooltip` — are regenerated from the current registry, then
re-patched with the app's own adjustments (the `button-variants.ts` / `toggle-variants.ts` split
that keeps `react-refresh/only-export-components` quiet, and any class the pages' tests assert on).

## Theme tokens

The HSL triplets in `globals.css` (`--background: 0 0% 100%` consumed as `hsl(var(--background))`)
become Tailwind 4 `@theme` colors. The *values* are converted, not redesigned: each light and dark
token is the same color it was, expressed as `oklch()`, so the pages look identical before and
after. The `.dark` class stays the dark-mode switch (`@custom-variant dark (&:is(.dark *))`) so the
existing `ThemeProvider` and `ModeToggle` keep working. The scoped reduced-motion rule for
`.board-team-card`, the `Inter var` font stack, the `100dvh` / `100dvw` display sizes and the
container settings are carried over verbatim into the new CSS.

## Order of work

Each step ends with `pnpm test`, `pnpm lint` and `pnpm build` green and a commit, so a step that
goes wrong is reverted alone.

1. **Runtime and test toolchain** — React 19, Vite 8, Vitest 5, plugin-react, testing-library,
   TypeScript. `vite.config.ts` / `vitest.config.ts` keep their split and the shared `aliases.ts`.
2. **ESLint 9** — flat config with the same three rule sets and the `react-refresh` rule.
3. **Tailwind 4** — `@tailwindcss/upgrade` for the mechanical part, then the theme block by hand,
   `@tailwindcss/vite` in place of PostCSS, `tw-animate-css`, `tailwind-merge` 3, and the Prettier
   plugin pointed at `globals.css` (`tailwindStylesheet`) instead of the deleted config.
4. **shadcn** — `components.json`; regenerate the 10 kept primitives; `migrate radix`; delete the
   38 others and the unused dependencies.
5. **React Router 8** — `react-router-dom` → `react-router`; `createBrowserRouter`,
   `RouterProvider`, loaders, `NavLink`, `useSearchParams` are unchanged in name.
6. **Verification** — the full suite, `pnpm build`, and the three pages in the browser at desktop
   and 375 px, light and dark, compared against main.

## Done means

- `pnpm test:web`, `pnpm lint` and `pnpm build` pass from the repo root.
- Board, `/trades` and `/history` render the same as on main in both themes and both widths.
- `pnpm dlx shadcn@latest add <name>` works from `apps/web` and lands in `src/components/ui`.
- No `@radix-ui/react-*`, `tailwind.config.js`, `postcss.config.js` or `.eslintrc.cjs` remains.

## Out of scope

- Any visual change. The redesign is the next spec and starts from this toolchain.
- Storybook, a component playground, `motion`, or `@tanstack/react-table` — nothing on the three
  pages calls for them.
- Base UI as the primitive layer.
