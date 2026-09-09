import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { appAliases } from "./aliases";

export default defineConfig({
  resolve: {
    alias: appAliases(__dirname),
  },
  plugins: [react()],
  test: {
    // jsdom is the default because most tests will render components. The pure derive modules
    // opt out per file with a `@vitest-environment node` docblock — they touch no DOM, and the
    // node environment keeps `Intl` behaviour identical to production Node.
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    restoreMocks: true,
  },
});
