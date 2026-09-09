import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { appAliases } from "./aliases";

export default defineConfig({
  resolve: {
    alias: appAliases(__dirname),
  },

  plugins: [react()],
});
