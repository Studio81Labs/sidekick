import type { ChangeEvent, Ref } from "react";
import { Download, Play, Upload } from "lucide-react";

import { benchmarkDatasetUrl } from "../../../domains/benchmarks/api/benchmarksApi";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import {
  ButtonControl,
  DownloadLinkControl,
  FileInputControl,
} from "../../../shared/components/FormControls";
import type { PipelineSelection } from "../../../shared/types/pipeline";

export interface BenchmarkDialogActionsProps {
  administrativeUnlocked: boolean;
  closeDisabled: boolean;
  datasetExportDisabled: boolean;
  datasetInputRef: Ref<HTMLInputElement>;
  importInProgress: boolean;
  includedCases: number;
  onChooseDatasetImport: () => void;
  onClose: () => void;
  onDatasetImport: (
    event: ChangeEvent<HTMLInputElement>,
  ) => void | Promise<void>;
  onRun: () => void | Promise<void>;
  operationsLocked: boolean;
  pipelineSelection: PipelineSelection | null;
  running: boolean;
  targetLayoutLabel: string | null;
}

export function BenchmarkDialogActions({
  administrativeUnlocked,
  closeDisabled,
  datasetExportDisabled,
  datasetInputRef,
  importInProgress,
  includedCases,
  onChooseDatasetImport,
  onClose,
  onDatasetImport,
  onRun,
  operationsLocked,
  pipelineSelection,
  running,
  targetLayoutLabel,
}: BenchmarkDialogActionsProps) {
  // Dataset import writes ground truth, so the server requires the same
  // administrator credential the upload path uses.
  const datasetImportDisabled = operationsLocked || !administrativeUnlocked;

  return (
    <DialogFooter className="benchmark-dialog-footer">
      <span>
        <strong>{includedCases}</strong> ground-truth{" "}
        {includedCases === 1 ? "hand" : "hands"}
        {targetLayoutLabel ? ` · ${targetLayoutLabel}` : ""}
      </span>
      <ButtonControl
        variant="secondary"
        className="benchmark-dataset-action"
        onClick={onChooseDatasetImport}
        disabled={datasetImportDisabled}
        aria-label="Import dataset"
        title="Import dataset"
      >
        <Upload size={14} aria-hidden="true" />
        <span>{importInProgress ? "Importing..." : "Import dataset"}</span>
      </ButtonControl>
      <FileInputControl
        ref={datasetInputRef}
        accept=".zip,application/zip"
        aria-label="Parser dataset ZIP"
        disabled={datasetImportDisabled}
        onChange={(event) => void onDatasetImport(event)}
      />
      <DownloadLinkControl
        className="secondary-button benchmark-dataset-action benchmark-export-button"
        href={benchmarkDatasetUrl(pipelineSelection ?? undefined)}
        download
        aria-label="Export dataset"
        title="Export dataset"
        disabled={datasetExportDisabled}
      >
        <Download size={14} aria-hidden="true" />
        <span>Export dataset</span>
      </DownloadLinkControl>
      <ButtonControl
        onClick={() => void onRun()}
        disabled={operationsLocked || includedCases === 0}
      >
        <Play size={14} aria-hidden="true" />
        {running ? "Running..." : "Run benchmark"}
      </ButtonControl>
      <ButtonControl
        variant="secondary"
        onClick={onClose}
        disabled={closeDisabled}
      >
        Done
      </ButtonControl>
      {administrativeUnlocked ? null : (
        <p className="benchmark-dataset-lock-note">
          Unlock administrator tools to import datasets.
        </p>
      )}
    </DialogFooter>
  );
}
