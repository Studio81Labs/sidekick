import { useMemo, useState } from "react";
import { PERSISTED_JOB_ID_PATTERN } from "../../../shared/lib/jobIdentity";
import type { HistoryItem } from "../../../domains/history/model/historyItem";
import { screenshotTags } from "../../../shared/lib/screenshotMetadata";
import type { JobRecord } from "../../../shared/types/jobs";

interface UseScreenshotDetailsOptions {
  history: readonly HistoryItem[];
  historySearchResults: readonly HistoryItem[] | null;
  jobs: readonly JobRecord[];
  onError: (message: string | null) => void;
}

export function useScreenshotDetails({
  history,
  historySearchResults,
  jobs,
  onError,
}: UseScreenshotDetailsOptions) {
  const [managedJobId, setManagedJobId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [tagInput, setTagInput] = useState("");
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);

  const job = useMemo(
    () =>
      managedJobId === null
        ? null
        : (jobs.find((candidate) => candidate.id === managedJobId) ??
          history.find((item) => item.id === managedJobId)?.job ??
          historySearchResults?.find((item) => item.id === managedJobId)?.job ??
          null),
    [history, historySearchResults, jobs, managedJobId],
  );
  const persisted = Boolean(job && PERSISTED_JOB_ID_PATTERN.test(job.id));

  function syncFields(nextJob: JobRecord) {
    setTitle(nextJob.title ?? "");
    setNotes(nextJob.notes ?? "");
    setTagInput(screenshotTags(nextJob).join(", "));
  }

  function open(nextJob: JobRecord) {
    setManagedJobId(nextJob.id);
    syncFields(nextJob);
    setDeleteArmed(false);
    onError(null);
  }

  function close() {
    if (metadataSaving || deleting) {
      return;
    }
    dismiss();
  }

  function dismiss() {
    setManagedJobId(null);
    setDeleteArmed(false);
  }

  return {
    close,
    deleteArmed,
    deleting,
    dismiss,
    job,
    metadataSaving,
    notes,
    open,
    persisted,
    setDeleteArmed,
    setDeleting,
    setMetadataSaving,
    setNotes,
    setTagInput,
    setTitle,
    syncFields,
    tagInput,
    title,
  };
}
