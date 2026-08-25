import { useState } from "react";

import { mutationLeaseOwnerId } from "../lib/persistence";

export function useAnalyzerWorkflowOwnerId(): string {
  const [ownerId] = useState(mutationLeaseOwnerId);
  return ownerId;
}
