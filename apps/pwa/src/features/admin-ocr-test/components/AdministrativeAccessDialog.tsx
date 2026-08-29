import { useState } from "react";

import "./AdministrativeAccessDialog.css";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import {
  ButtonControl,
  FormField,
  TextInput,
} from "../../../shared/components/FormControls";

export interface AdministrativeAccessDialogProps {
  capabilityEnabled: boolean | null;
  checkingCapability: boolean;
  onCheckCapability: () => void;
  onClose: () => void;
  onLock: () => void;
  onUnlock: (token: string) => boolean;
  unlocked: boolean;
}

function capabilityStatus(enabled: boolean | null): string {
  if (enabled === null) {
    return "Availability is verified by the server on every upload or capture.";
  }
  return enabled
    ? "Enabled on this deployment."
    : "Disabled on this deployment.";
}

export function AdministrativeAccessDialog({
  capabilityEnabled,
  checkingCapability,
  onCheckCapability,
  onClose,
  onLock,
  onUnlock,
  unlocked,
}: AdministrativeAccessDialogProps) {
  const [draft, setDraft] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  function submit() {
    if (!onUnlock(draft)) {
      setValidation("Enter the administrative OCR test token.");
      return;
    }
    setDraft("");
    setValidation(null);
  }

  return (
    <DialogFrame titleId="administrative-access-dialog-title">
      <DialogHeader
        titleId="administrative-access-dialog-title"
        title="Administrator tools"
        subtitle="Parser testing with screenshot upload and live capture"
        closeLabel="Close administrator tools"
        onClose={onClose}
      />

      <div className="administrative-access-body">
        <p>
          Screenshot upload and live window, screen, or tab capture are
          administrator-only OCR test tools. Test inputs are marked as
          administrative data and never request recommendations, create decision
          points, or enter training.
        </p>
        <p className="administrative-access-status">
          {capabilityStatus(capabilityEnabled)}{" "}
          <ButtonControl
            variant="ghost"
            onClick={onCheckCapability}
            disabled={checkingCapability}
          >
            Check deployment
          </ButtonControl>
        </p>
        {unlocked ? (
          <div className="administrative-access-unlocked">
            <p>
              Unlocked for this session. The token stays in memory until you
              lock these tools or reload the page.
            </p>
            <ButtonControl variant="secondary" onClick={onLock}>
              Lock administrator tools
            </ButtonControl>
          </div>
        ) : (
          <form
            className="administrative-access-form"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <FormField label="Administrative OCR test token">
              <TextInput
                autoComplete="off"
                onChange={(event) => setDraft(event.target.value)}
                type="password"
                value={draft}
              />
            </FormField>
            {validation ? (
              <p className="administrative-access-validation" role="alert">
                {validation}
              </p>
            ) : null}
            <ButtonControl type="submit">Unlock</ButtonControl>
          </form>
        )}
      </div>

      <DialogFooter>
        <ButtonControl variant="secondary" onClick={onClose}>
          Close
        </ButtonControl>
      </DialogFooter>
    </DialogFrame>
  );
}
