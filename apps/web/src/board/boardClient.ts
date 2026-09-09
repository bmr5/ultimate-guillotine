import type { SupabaseClient } from "@supabase/supabase-js";

import { supabase } from "@/supabaseClient";

import type { Database } from "./types";

/**
 * The shared client stays untyped because the legacy `usePlayerProjections` hook reads a
 * `player_projections` table with a different, pre-data-layer shape. Board code uses this
 * typed view instead; nothing outside `src/board` should import it.
 */
export const boardClient = supabase as unknown as SupabaseClient<Database>;
