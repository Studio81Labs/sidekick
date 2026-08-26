import type { HTMLAttributes, ReactNode } from "react";

import "./StatusBadge.css";

export type StatusBadgeTone = "neutral" | "accent" | "attention";

export type StatusBadgeProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  density?: "default" | "compact";
  tone?: StatusBadgeTone;
  uppercase?: boolean;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function StatusBadge({
  children,
  className,
  density = "default",
  tone = "neutral",
  uppercase = false,
  ...props
}: StatusBadgeProps) {
  return (
    <span
      {...props}
      className={joinClassNames(
        "status-badge",
        `status-badge-${tone}`,
        density === "compact" ? "status-badge-compact" : undefined,
        uppercase ? "status-badge-uppercase" : undefined,
        className,
      )}
    >
      {children}
    </span>
  );
}
