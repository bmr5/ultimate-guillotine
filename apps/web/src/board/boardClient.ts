import type { SupabaseClient } from "@supabase/supabase-js";

import { supabase } from "@/supabaseClient";

import type { Database } from "./types";

/**
 * `supabaseClient.ts` exports an untyped client. This is the app's typed view of it, shared by
 * `src/board` and `src/history`; the `Database` type covers every table the public pages read.
 */
export const boardClient = supabase as unknown as SupabaseClient<Database>;
