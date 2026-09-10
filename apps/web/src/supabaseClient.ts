import { PostgrestClient } from "@supabase/postgrest-js";
import { RealtimeClient } from "@supabase/realtime-js";

const supabaseUrl: string = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey: string = import.meta.env.VITE_SUPABASE_ANON_KEY;
/** The umbrella client normalised this too; without it a trailing slash doubles up in the path. */
const baseUrl = supabaseUrl.replace(/\/+$/, "");

/**
 * The board is read-only and anonymous: nobody ever signs in, so it has no use for auth, storage
 * or edge functions. The umbrella `@supabase/supabase-js` client bundles all of them regardless —
 * `auth-js` alone is the largest module it ships — so the two services the app does use are
 * built directly. Each is wired the way `createClient` would wire it with no session:
 *
 * - PostgREST carries the anon key as both `apikey` and the `Authorization` bearer, which is what
 *   the umbrella client's fetch wrapper sends when `auth.getSession()` has nothing to offer.
 * - Realtime takes the same key as its connection param and as the token in every channel's join
 *   payload, which is where the server evaluates RLS for `postgres_changes`.
 */
export const postgrest = new PostgrestClient(`${baseUrl}/rest/v1`, {
  schema: "public",
  headers: {
    apikey: supabaseAnonKey,
    Authorization: `Bearer ${supabaseAnonKey}`,
  },
});

export const realtime = new RealtimeClient(
  `${baseUrl.replace(/^http/, "ws")}/realtime/v1`,
  {
    params: { apikey: supabaseAnonKey },
    accessToken: async () => supabaseAnonKey,
  },
);
