import type { HTMLAttributes } from "react";

type DialogFooterProps = HTMLAttributes<HTMLDivElement>;

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function DialogFooter({ className, ...props }: DialogFooterProps) {
  return (
    <div
      {...props}
      className={joinClassNames("automation-dialog-footer", className)}
    />
  );
}
