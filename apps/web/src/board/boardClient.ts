import type { SupabaseClient } from "@supabase/supabase-js";

import { supabase } from "@/supabaseClient";

import type { Database } from "./types";

/**
 * `supabaseClient.ts` exports an untyped client. Board code uses this typed view instead, so
 * the generated `Database` types stay scoped to the board; nothing outside `src/board` should
 * import it.
 */
export const boardClient = supabase as unknown as SupabaseClient<Database>;
