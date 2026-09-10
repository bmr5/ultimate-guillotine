import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { appAliases } from "./aliases.ts";

export default defineConfig({
  resolve: {
    alias: appAliases(import.meta.dirname),
  },

  plugins: [react(), tailwindcss()],
});
