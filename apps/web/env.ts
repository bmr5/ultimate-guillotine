import { createEnv } from "@t3-oss/env-core";
import { z } from "zod";
 
export const env = createEnv({
  /**
   * Specify what prefix the client-side variables must have.
   * This is enforced both on type-level and at runtime.
   */
  clientPrefix: "VITE_",
  client: {
    VITE_PUBLIC_APOLLO_API_URL: z.string().min(1).url(),
  },
  /**
   * What object holds the environment variables at runtime.
   * Often `process.env` or `import.meta.env`
   */
  // @ts-ignore
  runtimeEnv: import.meta.env,
});