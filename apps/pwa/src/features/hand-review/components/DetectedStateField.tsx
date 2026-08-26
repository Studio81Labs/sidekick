import type { ReactNode } from "react";

import "./DetectedStateField.css";

type DetectedStateFieldProps = {
  children: ReactNode;
  confidence?: number;
  confidenceText?: string;
  label: string;
};

function normalizedConfidence(value: number | undefined): number | undefined {
  if (
    value === undefined ||
    !Number.isFinite(value) ||
    value < 0 ||
    value > 1
  ) {
    return undefined;
  }
  return value;
}

export function DetectedStateField({
  children,
  confidence,
  confidenceText,
  label,
}: DetectedStateFieldProps) {
  const normalized = normalizedConfidence(confidence);
  const percent = normalized === undefined ? 0 : Math.round(normalized * 100);
  const tone =
    normalized === undefined
      ? "missing"
      : normalized < 0.7
        ? "low"
        : normalized < 0.85
          ? "medium"
          : "high";

  return (
    <label className={`field field-${tone}`}>
      <span className="field-header">
        <span>{label}</span>
        <small>
          {confidenceText ??
            (normalized === undefined ? "not detected" : `${percent}%`)}
        </small>
      </span>
      {children}
      <span className="confidence-track" aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </span>
    </label>
  );
}
