import path from "path";

/**
 * The single definition of the app's import aliases.
 *
 * `vite.config.ts` and `vitest.config.ts` are deliberately separate configs — Vitest brings its
 * own Vite, and loading the app's Vite 4 config through it is the one thing that can go wrong —
 * but the two must resolve `@/...` identically or a module can behave differently under test
 * than in the build. Both build their `resolve.alias` from here so the list cannot drift.
 *
 * @param rootDir the app directory. Each config passes its own `__dirname`, so the paths resolve
 *   against the config's location rather than the process working directory.
 */
export function appAliases(rootDir: string): Record<string, string> {
  return {
    "@": path.resolve(rootDir, "./src"),
    "@/components": path.resolve(rootDir, "./src/components"),
    "@/ui": path.resolve(rootDir, "./src/components/ui"),
    "@/lib": path.resolve(rootDir, "./src/lib"),
  };
}
