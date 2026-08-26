import type { HTMLAttributes, ReactNode } from "react";

export type SummaryMetricProps = HTMLAttributes<HTMLDivElement> & {
  attention?: boolean;
  label: ReactNode;
  labelElement?: "small" | "span";
  value: ReactNode;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function SummaryMetric({
  attention = false,
  className,
  label,
  labelElement = "span",
  value,
  ...props
}: SummaryMetricProps) {
  const LabelElement = labelElement;
  return (
    <div {...props} className={joinClassNames("summary-metric", className)}>
      <strong className={attention ? "needs-review" : undefined}>
        {value}
      </strong>
      <LabelElement>{label}</LabelElement>
    </div>
  );
}
