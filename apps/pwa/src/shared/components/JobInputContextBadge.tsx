import { isAdministrativeTestJob } from "../lib/jobInputContext";
import type { JobRecord } from "../types/jobs";
import { StatusBadge } from "./StatusBadge";

export function JobInputContextBadge({
  density = "default",
  job,
}: {
  density?: "default" | "compact";
  job: Pick<JobRecord, "input_context">;
}) {
  if (!isAdministrativeTestJob(job)) {
    return null;
  }
  return (
    <StatusBadge
      aria-label="Administrative OCR test input"
      density={density}
      tone="attention"
      uppercase
    >
      Admin test
    </StatusBadge>
  );
}
