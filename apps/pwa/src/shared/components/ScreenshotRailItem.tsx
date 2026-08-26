import { Pencil } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

import "./ScreenshotRailItem.css";
import { ButtonControl } from "./FormControls";

export type ScreenshotRailItemProps = Omit<
  HTMLAttributes<HTMLDivElement>,
  "children"
> & {
  active?: boolean;
  attention?: boolean;
  children: ReactNode;
  manageDisabled?: boolean;
  manageLabel: string;
  onManage: () => void;
  onOpen: () => void;
  openDisabled?: boolean;
  openClassName?: string;
  openLabel: string;
};

function joinClassNames(...classNames: Array<string | false | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function ScreenshotRailItem({
  active = false,
  attention = false,
  children,
  className,
  manageDisabled = false,
  manageLabel,
  onManage,
  onOpen,
  openClassName,
  openDisabled = false,
  openLabel,
  ...props
}: ScreenshotRailItemProps) {
  return (
    <div
      {...props}
      className={joinClassNames(
        "screenshot-rail-item",
        active && "active",
        attention && "attention",
        className,
      )}
    >
      <ButtonControl
        variant="ghost"
        className={joinClassNames(
          "screenshot-rail-item-open",
          active && "active",
          attention && "attention",
          openClassName,
        )}
        onClick={onOpen}
        disabled={openDisabled}
        aria-label={openLabel}
      >
        {children}
      </ButtonControl>
      <ButtonControl
        variant="ghost"
        className="screenshot-manage-button"
        onClick={onManage}
        disabled={manageDisabled}
        title="Edit details or delete screenshot"
        aria-label={manageLabel}
      >
        <Pencil size={13} aria-hidden="true" />
      </ButtonControl>
    </div>
  );
}
