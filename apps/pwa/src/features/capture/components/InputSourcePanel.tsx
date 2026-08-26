import { Camera, Square, Upload } from "lucide-react";
import type { ChangeEvent } from "react";

import "./InputSourcePanel.css";
import {
  ButtonControl,
  FileInputControl,
} from "../../../shared/components/FormControls";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import {
  shareModeLabel,
  type InputMode,
  type ShareMode,
} from "../lib/captureSource";

const INPUT_MODES: readonly { value: InputMode; label: string }[] = [
  { value: "live", label: "Live" },
  { value: "upload", label: "Upload" },
];

export const SHARE_MODES: readonly { value: ShareMode; label: string }[] = [
  { value: "browser", label: "Tab" },
  { value: "window", label: "Window" },
  { value: "monitor", label: "Screen" },
];

export function selectedFilesLabel(files: readonly File[]): string {
  if (files.length === 0) {
    return "Choose screenshots";
  }
  if (files.length === 1) {
    return files[0].name;
  }
  return `${files.length} screenshots selected`;
}

export interface InputSourcePanelProps {
  busy: boolean;
  files: readonly File[];
  inputMode: InputMode;
  livePreviewVisible: boolean;
  onCapture: () => void;
  onFilesChange: (files: File[]) => void;
  onInputModeChange: (mode: InputMode) => void;
  onShareModeChange: (mode: ShareMode) => void;
  onStartOrViewShare: () => void;
  onStopShare: () => void;
  onUpload: () => void;
  screenSharing: boolean;
  screenSourceLabel: string | null;
  shareMode: ShareMode;
}

export function InputSourcePanel({
  busy,
  files,
  inputMode,
  livePreviewVisible,
  onCapture,
  onFilesChange,
  onInputModeChange,
  onShareModeChange,
  onStartOrViewShare,
  onStopShare,
  onUpload,
  screenSharing,
  screenSourceLabel,
  shareMode,
}: InputSourcePanelProps) {
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    onFilesChange(Array.from(event.target.files ?? []));
  }

  return (
    <section className="input-panel">
      <div className="input-panel-heading">
        <h2>Input</h2>
        <SegmentedControl
          ariaLabel="Input mode"
          className="input-mode-switch"
          options={INPUT_MODES}
          value={inputMode}
          onChange={onInputModeChange}
          disabled={busy}
        />
      </div>

      <div className="input-source-body">
        {inputMode === "live" ? (
          <>
            <span className="input-label">Capture source</span>
            <SegmentedControl
              ariaLabel="Share source type"
              className="share-mode"
              options={SHARE_MODES}
              value={shareMode}
              onChange={onShareModeChange}
              disabled={screenSharing || busy}
            />
            <div className="screen-capture-actions">
              <ButtonControl
                variant="secondary"
                className="share-source-button"
                onClick={onStartOrViewShare}
                disabled={busy || (screenSharing && livePreviewVisible)}
              >
                <span
                  className={
                    screenSharing
                      ? "source-indicator active"
                      : "source-indicator"
                  }
                  aria-hidden="true"
                />
                {screenSharing
                  ? `View live ${shareModeLabel(shareMode).toLowerCase()}`
                  : `Share ${shareModeLabel(shareMode).toLowerCase()}`}
              </ButtonControl>
              <ButtonControl
                variant="secondary"
                iconOnly
                onClick={onCapture}
                disabled={!screenSharing || busy}
                title="Capture and parse"
                aria-label="Capture and parse"
              >
                <Camera size={15} aria-hidden="true" />
              </ButtonControl>
              <ButtonControl
                variant="secondary"
                iconOnly
                onClick={onStopShare}
                disabled={!screenSharing || busy}
                title="Stop sharing"
                aria-label="Stop sharing"
              >
                <Square size={13} aria-hidden="true" />
              </ButtonControl>
            </div>
            <div className="source-hint">
              {screenSharing
                ? `${screenSourceLabel ?? "Source"} sharing active`
                : "Pick a source and share to read frames."}
            </div>
          </>
        ) : (
          <>
            <span className="input-label">Screenshot files</span>
            <div className="upload-source-row">
              <label className="file-picker">
                <Upload size={15} aria-hidden="true" />
                <span>{selectedFilesLabel(files)}</span>
                <FileInputControl
                  accept="image/*"
                  multiple
                  aria-label="Choose screenshots"
                  onChange={handleFileChange}
                />
              </label>
              <ButtonControl
                variant="secondary"
                iconOnly
                onClick={onUpload}
                disabled={files.length === 0 || busy}
                title="Upload and parse"
                aria-label="Upload and parse"
              >
                <Upload size={15} aria-hidden="true" />
              </ButtonControl>
            </div>
            <div className="source-hint">
              {files.length > 0
                ? `${files.length} selected for upload`
                : "Choose screenshots to add them to the queue."}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
