import { Plus } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { useId } from "react";

import "./ActionHistoryField.css";
import { ButtonControl } from "../../../shared/components/FormControls";

export type ActionHistoryFieldProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "children"
> & {
  addDisabled?: boolean;
  addLabel: string;
  children: ReactNode;
  emptyMessage: string;
  heading: string;
  itemCount: number;
  onAdd: () => void;
};

export type ActionHistoryRowProps = HTMLAttributes<HTMLDivElement> & {
  index: number;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function ActionHistoryField({
  addDisabled = false,
  addLabel,
  children,
  className,
  emptyMessage,
  heading,
  itemCount,
  onAdd,
  ...props
}: ActionHistoryFieldProps) {
  const headingId = `action-history-${useId()}`;
  return (
    <div
      {...props}
      aria-labelledby={props["aria-labelledby"] ?? headingId}
      className={joinClassNames("action-history-field", className)}
      role={props.role ?? "group"}
    >
      <div className="action-history-header">
        <div>
          <strong id={headingId}>{heading}</strong>
        </div>
        <ButtonControl
          className="action-history-add"
          disabled={addDisabled}
          onClick={onAdd}
        >
          <Plus size={13} aria-hidden="true" />
          {addLabel}
        </ButtonControl>
      </div>
      {itemCount > 0 ? (
        <div className="action-history-list">{children}</div>
      ) : (
        <p>{emptyMessage}</p>
      )}
    </div>
  );
}

export function ActionHistoryRow({
  children,
  className,
  index,
  ...props
}: ActionHistoryRowProps) {
  return (
    <div {...props} className={joinClassNames("action-history-row", className)}>
      <span className="action-history-index">{index + 1}</span>
      {children}
    </div>
  );
}
