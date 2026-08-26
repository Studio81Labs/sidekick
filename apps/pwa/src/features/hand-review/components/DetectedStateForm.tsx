import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import "./DetectedStateForm.css";
import { DetectedStateField } from "./DetectedStateField";
import {
  SelectControl,
  TextAreaControl,
  TextInput,
} from "../../../shared/components/FormControls";
import {
  type FacingActionOption,
  requiresOpponentPosition,
  type StateForm,
  type StateFormChange,
  type StreetOption,
} from "../../../domains/poker/model/pokerStateForm";

export interface DetectedStateFormProps {
  children?: ReactNode;
  confidences: Readonly<Record<string, number>>;
  disabled: boolean;
  form: StateForm;
  onChange: StateFormChange;
  warnings: readonly string[];
}

export function DetectedStateForm({
  children,
  confidences,
  disabled,
  form,
  onChange,
  warnings,
}: DetectedStateFormProps) {
  const currentBet = Number(form.current_bet);
  const playersInHand = Number(form.players_in_hand);
  const showOpponentCommitments =
    (form.street === "preflop" && currentBet <= 0) ||
    (currentBet > 0 &&
      playersInHand > 2 &&
      (form.street === "preflop" ||
        form.facing_action === "raise" ||
        form.opponent_commitment_total !== ""));
  const showOpponentStack =
    (form.street !== "" &&
      form.street !== "preflop" &&
      form.facing_action === "raise") ||
    form.street === "turn" ||
    form.street === "river";

  return (
    <>
      {warnings.length > 0 ? (
        <div className="parser-warnings">
          <AlertTriangle size={16} aria-hidden="true" />
          <ul>
            {warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="field-grid">
        <DetectedStateField
          label="Hero cards"
          confidence={confidences.hero_cards}
        >
          <TextInput
            disabled={disabled}
            value={form.hero_cards}
            onChange={(event) => onChange("hero_cards", event.target.value)}
          />
        </DetectedStateField>
        <DetectedStateField
          label="Board cards"
          confidence={confidences.board_cards}
        >
          <TextInput
            disabled={disabled}
            value={form.board_cards}
            onChange={(event) => onChange("board_cards", event.target.value)}
          />
        </DetectedStateField>
        <DetectedStateField label="Street" confidence={confidences.street}>
          <SelectControl
            disabled={disabled}
            value={form.street}
            onChange={(event) =>
              onChange("street", event.target.value as StreetOption)
            }
          >
            <option value="">Select street</option>
            <option value="preflop">Preflop</option>
            <option value="flop">Flop</option>
            <option value="turn">Turn</option>
            <option value="river">River</option>
          </SelectControl>
        </DetectedStateField>
        <DetectedStateField label="Pot" confidence={confidences.pot_size}>
          <TextInput
            disabled={disabled}
            inputMode="decimal"
            value={form.pot_size}
            onChange={(event) => onChange("pot_size", event.target.value)}
          />
        </DetectedStateField>
        <DetectedStateField
          label="Current bet"
          confidence={confidences.current_bet}
        >
          <TextInput
            disabled={disabled}
            inputMode="decimal"
            value={form.current_bet}
            onChange={(event) => onChange("current_bet", event.target.value)}
          />
        </DetectedStateField>
        <DetectedStateField
          label="Effective stack"
          confidence={confidences.effective_stack}
        >
          <TextInput
            disabled={disabled}
            inputMode="decimal"
            value={form.effective_stack}
            onChange={(event) =>
              onChange("effective_stack", event.target.value)
            }
          />
        </DetectedStateField>
        <DetectedStateField
          label="Hero stack"
          confidence={confidences.hero_stack}
        >
          <TextInput
            disabled={disabled}
            inputMode="decimal"
            value={form.hero_stack}
            onChange={(event) => onChange("hero_stack", event.target.value)}
          />
        </DetectedStateField>
        <DetectedStateField
          label="Players in hand"
          confidence={confidences.players_in_hand}
        >
          <TextInput
            disabled={disabled}
            inputMode="numeric"
            value={form.players_in_hand}
            onChange={(event) =>
              onChange("players_in_hand", event.target.value)
            }
          />
        </DetectedStateField>
        {currentBet > 0 && playersInHand > 2 ? (
          <DetectedStateField
            label="Opponents at wager"
            confidenceText="manual"
          >
            <TextInput
              disabled={disabled}
              inputMode="numeric"
              min="1"
              max={Math.max(1, playersInHand - 1)}
              value={form.opponents_at_current_bet}
              onChange={(event) =>
                onChange("opponents_at_current_bet", event.target.value)
              }
              placeholder="Already committed"
            />
          </DetectedStateField>
        ) : null}
        {currentBet > 0 ? (
          <DetectedStateField
            label="Opponent wager total"
            confidence={confidences.opponent_wager}
          >
            <TextInput
              disabled={disabled}
              inputMode="decimal"
              min={form.current_bet || "0"}
              value={form.opponent_wager}
              onChange={(event) =>
                onChange("opponent_wager", event.target.value)
              }
              placeholder="Total BB committed"
            />
          </DetectedStateField>
        ) : null}
        {showOpponentCommitments ? (
          <DetectedStateField
            label="Opponent commitments total"
            confidenceText="manual"
          >
            <TextInput
              disabled={disabled}
              inputMode="decimal"
              min="0"
              value={form.opponent_commitment_total}
              onChange={(event) =>
                onChange("opponent_commitment_total", event.target.value)
              }
              placeholder="All opponents, BB"
            />
          </DetectedStateField>
        ) : null}
        <DetectedStateField
          label="Hero position"
          confidence={confidences.hero_position}
        >
          <TextInput
            disabled={disabled}
            value={form.hero_position}
            onChange={(event) => onChange("hero_position", event.target.value)}
          />
        </DetectedStateField>
        {requiresOpponentPosition(form) ? (
          <DetectedStateField
            label="Opponent position"
            confidence={confidences.opponent_position}
          >
            <TextInput
              disabled={disabled}
              value={form.opponent_position}
              onChange={(event) =>
                onChange("opponent_position", event.target.value)
              }
            />
          </DetectedStateField>
        ) : null}
        <DetectedStateField
          label="Facing action"
          confidence={confidences.facing_action}
        >
          <SelectControl
            disabled={disabled}
            value={form.facing_action}
            onChange={(event) =>
              onChange(
                "facing_action",
                event.target.value as FacingActionOption,
              )
            }
          >
            <option value="">Select action</option>
            <option value="bet">Bet</option>
            <option value="raise">Raise or check-raise</option>
          </SelectControl>
        </DetectedStateField>
        {showOpponentStack ? (
          <DetectedStateField label="Opponent stack" confidenceText="manual">
            <TextInput
              disabled={disabled}
              inputMode="decimal"
              value={form.opponent_stack}
              onChange={(event) =>
                onChange("opponent_stack", event.target.value)
              }
              placeholder="BB behind"
            />
          </DetectedStateField>
        ) : null}
        {children}
        <DetectedStateField
          label="Action context"
          confidence={confidences.action_context}
        >
          <TextAreaControl
            disabled={disabled}
            value={form.action_context}
            onChange={(event) => onChange("action_context", event.target.value)}
          />
        </DetectedStateField>
      </div>
    </>
  );
}
