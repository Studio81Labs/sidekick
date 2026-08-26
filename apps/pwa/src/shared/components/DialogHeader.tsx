import { X } from "lucide-react";

import { ButtonControl } from "./FormControls";

export interface DialogHeaderProps {
  closeDisabled?: boolean;
  closeLabel: string;
  onClose: () => void;
  subtitle: string;
  title: string;
  titleId: string;
}

export function DialogHeader({
  closeDisabled = false,
  closeLabel,
  onClose,
  subtitle,
  title,
  titleId,
}: DialogHeaderProps) {
  return (
    <div className="automation-dialog-header">
      <div>
        <h2 id={titleId}>{title}</h2>
        <p>{subtitle}</p>
      </div>
      <ButtonControl
        variant="secondary"
        iconOnly
        onClick={onClose}
        disabled={closeDisabled}
        aria-label={closeLabel}
      >
        <X size={16} aria-hidden="true" />
      </ButtonControl>
    </div>
  );
}
