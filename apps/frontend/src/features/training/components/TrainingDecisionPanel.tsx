import { Check } from "lucide-react";
import "./TrainingDecisionPanel.css";

import {
  TRAINING_ACTION_OPTIONS,
  TRAINING_CERTAINTY_OPTIONS,
  type TrainingActionOption,
  type TrainingCertaintyOption,
} from "../lib/trainingPresentation";
import {
  ButtonControl,
  FormField,
  TextInput,
} from "../../../shared/components/FormControls";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import type { TrainingDecision } from "../../../shared/types/training";

export interface TrainingDecisionPanelProps {
  action: TrainingActionOption;
  busy: boolean;
  certainty: TrainingCertaintyOption;
  decision: TrainingDecision | null;
  onActionChange: (action: TrainingActionOption) => void;
  onCertaintyChange: (certainty: TrainingCertaintyOption) => void;
  onSave: () => void | Promise<void>;
  onSizingChange: (sizing: string) => void;
  sizing: string;
}

export function TrainingDecisionPanel({
  action,
  busy,
  certainty,
  decision,
  onActionChange,
  onCertaintyChange,
  onSave,
  onSizingChange,
  sizing,
}: TrainingDecisionPanelProps) {
  return (
    <section className="training-decision" aria-label="Your training decision">
      <div className="training-decision-head">
        <span>Your decision</span>
        <small>{decision ? "Answer locked" : "Optional before reveal"}</small>
      </div>
      <SegmentedControl
        ariaLabel="Choose your action"
        className="training-action-options"
        options={TRAINING_ACTION_OPTIONS}
        value={action}
        onChange={onActionChange}
        disabled={busy}
      />
      <div className="training-certainty">
        <span>How sure?</span>
        <SegmentedControl
          ariaLabel="How sure are you?"
          options={TRAINING_CERTAINTY_OPTIONS}
          value={certainty}
          onChange={onCertaintyChange}
          disabled={busy}
        />
      </div>
      <div className="training-decision-footer">
        {action === "bet" || action === "raise" ? (
          <FormField label="Size">
            <TextInput
              density="compact"
              aria-label="Decision sizing in BB"
              inputMode="decimal"
              value={sizing}
              onChange={(event) => onSizingChange(event.target.value)}
              placeholder="BB"
              disabled={busy}
            />
          </FormField>
        ) : null}
        <span className="training-decision-hint">
          {decision
            ? "Saved before reveal"
            : action
              ? "Ready to lock"
              : "No answer selected"}
        </span>
        <ButtonControl
          variant="secondary"
          onClick={() => void onSave()}
          disabled={!action || busy}
        >
          <Check size={13} aria-hidden="true" />
          {decision ? "Update answer" : "Lock answer"}
        </ButtonControl>
      </div>
    </section>
  );
}
