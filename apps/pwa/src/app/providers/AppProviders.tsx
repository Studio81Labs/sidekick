import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { createQueryClient } from "./queryClient";
import { UpdateSafetyProvider } from "../../shared/pwa/updateSafety";

interface AppProvidersProps {
  children: ReactNode;
}

export function AppProviders({ children }: AppProvidersProps) {
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <UpdateSafetyProvider>{children}</UpdateSafetyProvider>
    </QueryClientProvider>
  );
}
