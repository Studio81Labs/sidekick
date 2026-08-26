import { forwardRef, type HTMLAttributes } from "react";
import "./DialogFrame.css";

type DialogFrameProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "aria-labelledby" | "role"
> & {
  titleId: string;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export const DialogFrame = forwardRef<HTMLDivElement, DialogFrameProps>(
  ({ className, titleId, ...props }, ref) => (
    <section className="modal-backdrop">
      <div
        {...props}
        ref={ref}
        className={joinClassNames("automation-dialog", className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      />
    </section>
  ),
);

DialogFrame.displayName = "DialogFrame";
