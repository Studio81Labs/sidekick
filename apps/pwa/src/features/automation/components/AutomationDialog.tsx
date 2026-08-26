import "./AutomationDialog.css";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import { ButtonControl } from "../../../shared/components/FormControls";
import { ToggleControl } from "../../../shared/components/ToggleControl";

export interface AutomationDialogProps {
  allowWarnings: boolean;
  autoApprove: boolean;
  autoRecommend: boolean;
  enabled: boolean;
  onAllowWarningsChange: (value: boolean) => void;
  onAutoApproveChange: (value: boolean) => void;
  onAutoRecommendChange: (value: boolean) => void;
  onClose: () => void;
}

export function AutomationDialog({
  allowWarnings,
  autoApprove,
  autoRecommend,
  enabled,
  onAllowWarningsChange,
  onAutoApproveChange,
  onAutoRecommendChange,
  onClose,
}: AutomationDialogProps) {
  return (
    <DialogFrame titleId="automation-dialog-title">
      <DialogHeader
        titleId="automation-dialog-title"
        title="Configure automation"
        subtitle="Applies to every frame you capture or upload"
        closeLabel="Close automation settings"
        onClose={onClose}
      />

      <div className="automation-dialog-body">
        <ToggleControl
          title="Auto-approve parsed state"
          description="Skip manual review when confidence is high"
          checked={autoApprove}
          onClick={() => onAutoApproveChange(!autoApprove)}
        />
        <ToggleControl
          title="Auto-request recommendation"
          description="Generate a play the moment a frame is approved"
          checked={autoRecommend}
          disabled={!autoApprove}
          onClick={() => onAutoRecommendChange(!autoRecommend)}
        />
        <ToggleControl
          title="Allow parser warnings"
          description="Continue automation even when fields are flagged"
          checked={allowWarnings}
          disabled={!autoApprove}
          onClick={() => onAllowWarningsChange(!allowWarnings)}
        />
      </div>

      <DialogFooter>
        <span>
          Master automation is <strong>{enabled ? "On" : "Off"}</strong>
        </span>
        <ButtonControl variant="secondary" onClick={onClose}>
          Done
        </ButtonControl>
      </DialogFooter>
    </DialogFrame>
  );
}
