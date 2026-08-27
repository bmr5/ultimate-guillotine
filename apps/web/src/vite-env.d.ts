/// <reference types="vite/client" />

declare global {
  interface ImportMeta {
    env: Record<string, unknown>;
  }
}
