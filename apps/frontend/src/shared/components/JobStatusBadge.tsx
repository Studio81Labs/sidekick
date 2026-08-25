import { StatusBadge, type StatusBadgeTone } from "./StatusBadge";
import type { JobRecord } from "../types/jobs";

const JOB_STATUS_TONES: Record<JobRecord["status"], StatusBadgeTone> = {
  created: "neutral",
  parsed: "neutral",
  approved: "accent",
  recommended: "accent",
  error: "attention",
};

export function JobStatusBadge({ status }: { status: JobRecord["status"] }) {
  return (
    <StatusBadge tone={JOB_STATUS_TONES[status]} uppercase>
      {status}
    </StatusBadge>
  );
}
