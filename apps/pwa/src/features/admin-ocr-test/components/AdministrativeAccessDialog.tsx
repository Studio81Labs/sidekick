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
import type { AdministrativeUnlockResult } from "../hooks/useAdministrativeAccess";
import { unlockFailureMessage } from "../lib/administrativeAccess";

export interface AdministrativeAccessDialogProps {
  busy: boolean;
  externalValidation?: string | null;
  onClose: () => void;
  onLock: () => void;
  onUnlock: (token: string) => Promise<AdministrativeUnlockResult>;
  unlocked: boolean;
  verifying: boolean;
}

export function AdministrativeAccessDialog({
  busy,
  externalValidation = null,
  onClose,
  onLock,
  onUnlock,
  unlocked,
  verifying,
}: AdministrativeAccessDialogProps) {
  const [draft, setDraft] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  async function submit() {
    const result = await onUnlock(draft);
    if (result !== "unlocked") {
      // The draft survives so the operator can correct a mistyped token.
      setValidation(unlockFailureMessage(result));
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
          administrator-only OCR test tools. Uploads and captures are
          administrative OCR test data used for parser diagnostics and
          ground-truth approval; they are not player analysis.
        </p>
        <p className="administrative-access-status">
          The token is verified with the server before any capture control is
          shown.
        </p>
        {unlocked ? (
          <div className="administrative-access-unlocked">
            <p>
              Unlocked for this session. The token stays in memory until you
              lock these tools or reload the page.
            </p>
            <ButtonControl variant="secondary" onClick={onLock} disabled={busy}>
              Lock administrator tools
            </ButtonControl>
          </div>
        ) : (
          <form
            className="administrative-access-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
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
            {(validation ?? externalValidation) ? (
              <p className="administrative-access-validation" role="alert">
                {validation ?? externalValidation}
              </p>
            ) : null}
            <ButtonControl type="submit" disabled={verifying}>
              {verifying ? "Verifying…" : "Unlock"}
            </ButtonControl>
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
