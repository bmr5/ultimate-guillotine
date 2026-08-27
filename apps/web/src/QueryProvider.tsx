import { QueryClientProvider } from "@tanstack/react-query";

import { queryClient } from "./queryClient";

interface ReactQueryProps {
  children: React.ReactNode;
}

export function QueryProvider({ children }: ReactQueryProps) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
