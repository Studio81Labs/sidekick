import { useState } from "react";

import { mutationLeaseOwnerId } from "../lib/mutationLeaseFactories";

export function useAnalyzerWorkflowOwnerId(): string {
  const [ownerId] = useState(mutationLeaseOwnerId);
  return ownerId;
}
