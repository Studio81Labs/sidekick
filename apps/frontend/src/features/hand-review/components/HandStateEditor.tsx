import { X } from "lucide-react";

import { ActionHistoryField, ActionHistoryRow } from "./ActionHistoryField";
import { PREFLOP_POSITIONS } from "../../../domains/poker/model/preflopPosition";
import { DetectedStateField } from "./DetectedStateField";
import { DetectedStateForm } from "./DetectedStateForm";
import {
  ButtonControl,
  SelectControl,
  TextInput,
} from "../../../shared/components/FormControls";
import type {
  CompletedPostflopActionForm,
  PostflopActionForm,
  PreflopActionForm,
  StateForm,
} from "../lib/pokerStateForm";
import type { CompletedPostflopStreet } from "../../../shared/types/poker";

export interface HandStateEditorProps {
  completedPostflopActionCounts: Record<CompletedPostflopStreet, number>;
  completedPostflopActionsAtLimit: boolean;
  confidences: Record<string, number>;
  disabled: boolean;
  form: StateForm;
  onAddCompletedPostflopAction: () => void;
  onAddPostflopAction: () => void;
  onAddPreflopAction: () => void;
  onChange: <K extends keyof StateForm>(field: K, value: StateForm[K]) => void;
  onRemoveCompletedPostflopAction: (index: number) => void;
  onRemovePostflopAction: (index: number) => void;
  onRemovePreflopAction: (index: number) => void;
  onUpdateCompletedPostflopAction: (
    index: number,
    field: keyof CompletedPostflopActionForm,
    value: string,
  ) => void;
  onUpdatePostflopAction: (
    index: number,
    field: keyof PostflopActionForm,
    value: string,
  ) => void;
  onUpdatePreflopAction: (
    index: number,
    field: keyof PreflopActionForm,
    value: string,
  ) => void;
  warnings: string[];
}

export function HandStateEditor({
  completedPostflopActionCounts,
  completedPostflopActionsAtLimit,
  confidences,
  disabled,
  form,
  onAddCompletedPostflopAction,
  onAddPostflopAction,
  onAddPreflopAction,
  onChange,
  onRemoveCompletedPostflopAction,
  onRemovePostflopAction,
  onRemovePreflopAction,
  onUpdateCompletedPostflopAction,
  onUpdatePostflopAction,
  onUpdatePreflopAction,
  warnings,
}: HandStateEditorProps) {
  return (
    <DetectedStateForm
      confidences={confidences}
      disabled={disabled}
      form={form}
      onChange={onChange}
      warnings={warnings}
    >
      {form.street === "turn" || form.street === "river" ? (
        <ActionHistoryField
          addDisabled={disabled || completedPostflopActionsAtLimit}
          addLabel="Add action"
          emptyMessage="No completed streets recorded"
          heading="Completed streets (total BB)"
          itemCount={form.completed_postflop_actions.length}
          onAdd={onAddCompletedPostflopAction}
        >
          {form.completed_postflop_actions.map((action, index) => (
            <ActionHistoryRow
              className="completed-action-history-row"
              index={index}
              key={index}
            >
              <SelectControl
                aria-label={`Completed action ${index + 1} street`}
                density="compact"
                disabled={disabled}
                value={action.street}
                onChange={(event) =>
                  onUpdateCompletedPostflopAction(
                    index,
                    "street",
                    event.target.value,
                  )
                }
              >
                <option
                  value="flop"
                  disabled={
                    action.street !== "flop" &&
                    completedPostflopActionCounts.flop >= 8
                  }
                >
                  Flop
                </option>
                {form.street === "river" ? (
                  <option
                    value="turn"
                    disabled={
                      action.street !== "turn" &&
                      completedPostflopActionCounts.turn >= 8
                    }
                  >
                    Turn
                  </option>
                ) : null}
              </SelectControl>
              <SelectControl
                aria-label={`Completed action ${index + 1} actor`}
                density="compact"
                disabled={disabled}
                value={action.actor}
                onChange={(event) =>
                  onUpdateCompletedPostflopAction(
                    index,
                    "actor",
                    event.target.value,
                  )
                }
              >
                <option value="oop">OOP</option>
                <option value="ip">IP</option>
              </SelectControl>
              <SelectControl
                aria-label={`Completed action ${index + 1} type`}
                density="compact"
                disabled={disabled}
                value={action.action}
                onChange={(event) =>
                  onUpdateCompletedPostflopAction(
                    index,
                    "action",
                    event.target.value,
                  )
                }
              >
                <option value="check">Check</option>
                <option value="bet">Bet</option>
                <option value="raise">Raise to</option>
                <option value="call">Call to</option>
              </SelectControl>
              <TextInput
                density="compact"
                aria-label={`Completed action ${index + 1} amount`}
                disabled={disabled || action.action === "check"}
                inputMode="decimal"
                value={action.amount}
                onChange={(event) =>
                  onUpdateCompletedPostflopAction(
                    index,
                    "amount",
                    event.target.value,
                  )
                }
                placeholder={action.action === "check" ? "-" : "BB"}
              />
              <ButtonControl
                iconOnly
                disabled={disabled}
                onClick={() => onRemoveCompletedPostflopAction(index)}
                title={`Remove completed action ${index + 1}`}
                aria-label={`Remove completed action ${index + 1}`}
              >
                <X size={13} aria-hidden="true" />
              </ButtonControl>
            </ActionHistoryRow>
          ))}
        </ActionHistoryField>
      ) : null}

      {form.street !== "" &&
      form.street !== "preflop" &&
      form.facing_action === "raise" ? (
        <ActionHistoryField
          addDisabled={disabled || form.postflop_action_history.length >= 8}
          addLabel="Add action"
          emptyMessage="No current-street actions recorded"
          heading="Current street history (total BB)"
          itemCount={form.postflop_action_history.length}
          onAdd={onAddPostflopAction}
        >
          {form.postflop_action_history.map((action, index) => (
            <ActionHistoryRow index={index} key={index}>
              <SelectControl
                aria-label={`Action ${index + 1} actor`}
                density="compact"
                disabled={disabled}
                value={action.actor}
                onChange={(event) =>
                  onUpdatePostflopAction(index, "actor", event.target.value)
                }
              >
                <option value="oop">OOP</option>
                <option value="ip">IP</option>
              </SelectControl>
              <SelectControl
                aria-label={`Action ${index + 1} type`}
                density="compact"
                disabled={disabled}
                value={action.action}
                onChange={(event) =>
                  onUpdatePostflopAction(index, "action", event.target.value)
                }
              >
                <option value="check">Check</option>
                <option value="bet">Bet</option>
                <option value="raise">Raise to</option>
              </SelectControl>
              <TextInput
                density="compact"
                aria-label={`Action ${index + 1} amount`}
                disabled={disabled || action.action === "check"}
                inputMode="decimal"
                value={action.amount}
                onChange={(event) =>
                  onUpdatePostflopAction(index, "amount", event.target.value)
                }
                placeholder={action.action === "check" ? "-" : "BB"}
              />
              <ButtonControl
                iconOnly
                disabled={disabled}
                onClick={() => onRemovePostflopAction(index)}
                title={`Remove action ${index + 1}`}
                aria-label={`Remove action ${index + 1}`}
              >
                <X size={13} aria-hidden="true" />
              </ButtonControl>
            </ActionHistoryRow>
          ))}
        </ActionHistoryField>
      ) : null}

      {form.street === "preflop" && form.facing_action === "raise" ? (
        <>
          {form.preflop_action_history.length === 0 ? (
            <>
              <DetectedStateField
                label="Opener position"
                confidenceText="manual"
              >
                <SelectControl
                  disabled={disabled}
                  value={form.preflop_opener_position}
                  onChange={(event) =>
                    onChange("preflop_opener_position", event.target.value)
                  }
                >
                  <option value="">Select position</option>
                  {PREFLOP_POSITIONS.map((position) => (
                    <option key={position.value} value={position.value}>
                      {position.label}
                    </option>
                  ))}
                </SelectControl>
              </DetectedStateField>
              <DetectedStateField label="Opening size" confidenceText="manual">
                <TextInput
                  disabled={disabled}
                  inputMode="decimal"
                  value={form.preflop_open_size}
                  onChange={(event) =>
                    onChange("preflop_open_size", event.target.value)
                  }
                  placeholder="BB"
                />
              </DetectedStateField>
            </>
          ) : null}
          <ActionHistoryField
            addDisabled={disabled || form.preflop_action_history.length >= 8}
            addLabel="Add preflop action"
            emptyMessage="No actions recorded"
            heading="Preflop history (total BB)"
            itemCount={form.preflop_action_history.length}
            onAdd={onAddPreflopAction}
          >
            {form.preflop_action_history.map((action, index) => (
              <ActionHistoryRow index={index} key={index}>
                <SelectControl
                  aria-label={`Preflop action ${index + 1} actor`}
                  density="compact"
                  disabled={disabled}
                  value={action.actor}
                  onChange={(event) =>
                    onUpdatePreflopAction(index, "actor", event.target.value)
                  }
                >
                  {PREFLOP_POSITIONS.map((position) => (
                    <option key={position.value} value={position.value}>
                      {position.label}
                    </option>
                  ))}
                </SelectControl>
                <SelectControl
                  aria-label={`Preflop action ${index + 1} type`}
                  density="compact"
                  disabled={disabled}
                  value={action.action}
                  onChange={(event) =>
                    onUpdatePreflopAction(index, "action", event.target.value)
                  }
                >
                  <option value="raise">Raise to</option>
                  <option value="call">Call</option>
                </SelectControl>
                <TextInput
                  density="compact"
                  aria-label={`Preflop action ${index + 1} amount`}
                  disabled={disabled}
                  inputMode="decimal"
                  value={action.amount}
                  onChange={(event) =>
                    onUpdatePreflopAction(index, "amount", event.target.value)
                  }
                  placeholder="BB"
                />
                <ButtonControl
                  iconOnly
                  disabled={disabled}
                  onClick={() => onRemovePreflopAction(index)}
                  title={`Remove preflop action ${index + 1}`}
                  aria-label={`Remove preflop action ${index + 1}`}
                >
                  <X size={13} aria-hidden="true" />
                </ButtonControl>
              </ActionHistoryRow>
            ))}
          </ActionHistoryField>
        </>
      ) : null}
    </DetectedStateForm>
  );
}
