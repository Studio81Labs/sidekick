import { AlertTriangle, Tag, Trash2 } from "lucide-react";

import "./ScreenshotDetailsDialog.css";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import {
  ButtonControl,
  FormField,
  TextAreaControl,
  TextInput,
} from "../../../shared/components/FormControls";
import { JobStatusBadge } from "../../../shared/components/JobStatusBadge";
import {
  MAX_SCREENSHOT_NOTES_LENGTH,
  MAX_SCREENSHOT_TAG_INPUT_LENGTH,
  MAX_SCREENSHOT_TITLE_LENGTH,
} from "../../../shared/lib/screenshotMetadata";
import type { JobRecord } from "../../../shared/types/jobs";

export interface ScreenshotDetailsDialogProps {
  deleteArmed: boolean;
  deleting: boolean;
  job: JobRecord;
  metadataSaving: boolean;
  notes: string;
  onClose: () => void;
  onDelete: () => void;
  onDeleteArmedChange: (value: boolean) => void;
  onNotesChange: (value: string) => void;
  onSave: () => void;
  onTagsChange: (value: string) => void;
  onTitleChange: (value: string) => void;
  persisted: boolean;
  recoveryPending: boolean;
  tags: string;
  title: string;
}

export function ScreenshotDetailsDialog({
  deleteArmed,
  deleting,
  job,
  metadataSaving,
  notes,
  onClose,
  onDelete,
  onDeleteArmedChange,
  onNotesChange,
  onSave,
  onTagsChange,
  onTitleChange,
  persisted,
  recoveryPending,
  tags,
  title,
}: ScreenshotDetailsDialogProps) {
  const mutationPending = metadataSaving || deleting;
  const formLocked = deleteArmed || mutationPending;

  return (
    <DialogFrame
      className="screenshot-details-dialog"
      titleId="screenshot-details-title"
    >
      <DialogHeader
        titleId="screenshot-details-title"
        title="Screenshot details"
        subtitle={job.archived_at ? "Saved history" : "Processing queue"}
        closeLabel="Close screenshot details"
        closeDisabled={mutationPending}
        onClose={onClose}
      />

      <form
        className="screenshot-details-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!formLocked) {
            onSave();
          }
        }}
      >
        <div className="screenshot-file-summary">
          <span className="screenshot-file-icon" aria-hidden="true">
            <Tag size={15} />
          </span>
          <span>
            <strong>{job.original_filename}</strong>
            <small>
              {job.archived_at ? "History" : "Queue"} · {job.status}
            </small>
          </span>
          <JobStatusBadge status={job.status} />
        </div>

        {persisted ? (
          <div className="screenshot-metadata-fields">
            <FormField label="Title">
              <TextInput
                type="text"
                value={title}
                onChange={(event) => onTitleChange(event.target.value)}
                maxLength={MAX_SCREENSHOT_TITLE_LENGTH}
                disabled={mutationPending}
                placeholder={job.original_filename}
                autoFocus
              />
            </FormField>
            <FormField label="Tags">
              <TextInput
                type="text"
                value={tags}
                onChange={(event) => onTagsChange(event.target.value)}
                maxLength={MAX_SCREENSHOT_TAG_INPUT_LENGTH}
                disabled={mutationPending}
                placeholder="turn, review, bluff"
              />
            </FormField>
            <FormField className="screenshot-notes-field" label="Notes">
              <TextAreaControl
                value={notes}
                onChange={(event) => onNotesChange(event.target.value)}
                maxLength={MAX_SCREENSHOT_NOTES_LENGTH}
                disabled={mutationPending}
                rows={4}
              />
            </FormField>
          </div>
        ) : (
          <p className="local-upload-note">
            {recoveryPending
              ? "Checking whether this upload reached persistent storage before deletion."
              : "This upload did not reach persistent storage and can only be removed."}
          </p>
        )}

        {deleteArmed ? (
          <div className="screenshot-delete-confirmation" role="alert">
            <span className="screenshot-delete-message">
              <AlertTriangle size={17} aria-hidden="true" />
              <span>
                <strong>Delete permanently?</strong>
                <small>
                  The image and all analysis data will be removed
                  {job.benchmark_included
                    ? " from the benchmark corpus too"
                    : ""}
                  .
                </small>
              </span>
            </span>
            <ButtonControl
              variant="secondary"
              onClick={() => onDeleteArmedChange(false)}
              disabled={deleting}
            >
              Cancel
            </ButtonControl>
            <ButtonControl
              variant="danger"
              onClick={onDelete}
              disabled={deleting || recoveryPending}
              aria-label={
                deleting ? "Deleting screenshot" : "Delete permanently"
              }
            >
              <Trash2 size={14} aria-hidden="true" />
              {deleting ? (
                "Deleting..."
              ) : (
                <>
                  <span className="screenshot-delete-label-full">
                    Delete permanently
                  </span>
                  <span className="screenshot-delete-label-compact">
                    Delete
                  </span>
                </>
              )}
            </ButtonControl>
          </div>
        ) : null}

        <div
          className="screenshot-details-footer"
          aria-hidden={deleteArmed || undefined}
        >
          {!deleteArmed ? (
            <ButtonControl
              variant="ghost"
              className="screenshot-delete-button"
              onClick={() => onDeleteArmedChange(true)}
              disabled={mutationPending || recoveryPending}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete screenshot
            </ButtonControl>
          ) : (
            <span />
          )}
          <span className="screenshot-details-actions">
            <ButtonControl
              variant="secondary"
              onClick={onClose}
              disabled={formLocked}
            >
              Close
            </ButtonControl>
            {persisted ? (
              <ButtonControl type="submit" disabled={formLocked}>
                {metadataSaving ? "Saving..." : "Save details"}
              </ButtonControl>
            ) : null}
          </span>
        </div>
      </form>
    </DialogFrame>
  );
}
