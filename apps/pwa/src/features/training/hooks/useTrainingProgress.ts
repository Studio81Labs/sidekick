import { useState } from "react";

import { getJob } from "../../../domains/jobs/api/jobsApi";
import type { JobRecord } from "../../../shared/types/jobs";
import { messageFromError } from "../../../shared/lib/errors";
import { useTrainingProgressState } from "./useTrainingProgressState";

interface UseTrainingProgressOptions {
  onError: (message: string | null) => void;
  onOpenJob: (job: JobRecord) => void;
}

export function useTrainingProgress({
  onError,
  onOpenJob,
}: UseTrainingProgressOptions) {
  const [dialogOpen, setDialogOpenState] = useState(false);
  const [reviewJobId, setReviewJobId] = useState<string | null>(null);
  const [reviewQueueJobId, setReviewQueueJobId] = useState<string | null>(null);
  const { cancelLoads, loadInitial, progress, ...progressState } =
    useTrainingProgressState({ onError });

  function setDialogOpen(open: boolean) {
    if (!open) cancelLoads();
    setDialogOpenState(open);
  }

  function openDialog() {
    setReviewQueueJobId(null);
    setDialogOpenState(true);
    loadInitial();
  }

  async function reviewHand(jobId: string, continueReviewQueue = false) {
    setReviewJobId(jobId);
    onError(null);
    try {
      const job = await getJob(jobId);
      onOpenJob(job);
      setReviewQueueJobId(
        continueReviewQueue &&
          progress?.review_queue.some((hand) => hand.job_id === job.id)
          ? job.id
          : null,
      );
      setDialogOpen(false);
    } catch (error) {
      onError(messageFromError(error, "Could not open training hand"));
    } finally {
      setReviewJobId(null);
    }
  }

  return {
    ...progressState,
    dialogOpen,
    openDialog,
    progress,
    reviewHand,
    reviewJobId,
    reviewQueueJobId,
    setDialogOpen,
    setReviewJobId,
    setReviewQueueJobId,
  };
}
