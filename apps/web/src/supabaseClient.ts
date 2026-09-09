import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

/**
 * The board is read-only and anonymous: nobody ever signs in, so there is no session to
 * persist, refresh or recover from a URL. Left on, supabase-js writes an auth entry to
 * localStorage, starts a refresh timer, and parses every page load's hash looking for tokens
 * this app will never issue.
 */
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: false,
    autoRefreshToken: false,
    detectSessionInUrl: false,
  },
});
