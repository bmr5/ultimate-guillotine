import { QueryClient } from "@tanstack/react-query";

/**
 * `retry: 1`, not the default 3. Every board query is a plain read against one Supabase
 * project: a request that fails twice is failing for a reason a third attempt will not fix, and
 * the default's exponential backoff kept a broken section spinning for the better part of a
 * minute before the board could say which one it was. One retry still absorbs the dropped
 * connection this is actually for.
 */
export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});
