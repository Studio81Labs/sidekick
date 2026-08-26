import { forwardRef } from "react";

import "./TablePreview.css";
import { StateMessage } from "../../../shared/components/StateMessage";
import { SummaryMetric } from "../../../shared/components/SummaryMetric";

export interface TablePreviewProps {
  averageConfidence: number;
  detectedFieldCount: number;
  fieldCount: number;
  frameLabel: string;
  frameStreet: string;
  livePreviewVisible: boolean;
  reviewCount: number;
  screenSharing: boolean;
  screenshotUrl: string | null;
}

export const TablePreview = forwardRef<HTMLVideoElement, TablePreviewProps>(
  (
    {
      averageConfidence,
      detectedFieldCount,
      fieldCount,
      frameLabel,
      frameStreet,
      livePreviewVisible,
      reviewCount,
      screenSharing,
      screenshotUrl,
    },
    ref,
  ) => {
    const showLivePreview = screenSharing && livePreviewVisible;
    return (
      <section className="table-column" aria-label="Poker table preview">
        <div className="table-frame-bar">
          <span
            className={screenSharing ? "live-dot active" : "live-dot"}
            aria-hidden="true"
          />
          <span>{frameLabel}</span>
          <strong>{frameStreet}</strong>
        </div>
        <div className="table-frame-body">
          <video
            className={
              showLivePreview ? "shared-preview active" : "shared-preview"
            }
            ref={ref}
            muted
            playsInline
            aria-label="Shared screen preview"
          />
          {screenshotUrl ? (
            <img
              className={
                showLivePreview
                  ? "screenshot-preview hidden"
                  : "screenshot-preview"
              }
              src={screenshotUrl}
              alt="Uploaded poker table screenshot"
            />
          ) : null}
          {!showLivePreview && !screenshotUrl ? (
            <StateMessage centered className="empty-screenshot" tone="inverse">
              No screenshot uploaded
            </StateMessage>
          ) : null}
        </div>
        <div
          className="confidence-summary"
          aria-label="Parser confidence summary"
        >
          <SummaryMetric
            label="fields read"
            labelElement="small"
            value={
              <>
                {detectedFieldCount}
                <span>/{fieldCount}</span>
              </>
            }
          />
          <SummaryMetric
            label="avg confidence"
            labelElement="small"
            value={`${averageConfidence}%`}
          />
          <SummaryMetric
            attention={reviewCount > 0}
            label="need review"
            labelElement="small"
            value={reviewCount}
          />
        </div>
      </section>
    );
  },
);

TablePreview.displayName = "TablePreview";
