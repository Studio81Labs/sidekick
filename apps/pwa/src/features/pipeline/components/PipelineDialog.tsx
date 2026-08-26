import "./PipelineDialog.css";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import {
  ButtonControl,
  FormField,
  SelectControl,
} from "../../../shared/components/FormControls";
import { StateMessage } from "../../../shared/components/StateMessage";
import type {
  PipelineCapabilities,
  PipelineOption,
  PipelineSelection,
} from "../../../shared/types/pipeline";

export interface PipelineDialogProps {
  capabilities: PipelineCapabilities | null;
  compatibleLayouts: PipelineOption[];
  loading: boolean;
  onClose: () => void;
  onParserChange: (value: string) => void;
  onParserLayoutChange: (value: string) => void;
  onRecommendationChange: (value: string) => void;
  onRecommendationEngineChange: (value: string) => void;
  selection: PipelineSelection | null;
}

interface PipelineSelectProps {
  description: string;
  id: string;
  label: string;
  onChange: (value: string) => void;
  options: PipelineOption[];
  value: string;
}

export function PipelineDialog({
  capabilities,
  compatibleLayouts,
  loading,
  onClose,
  onParserChange,
  onParserLayoutChange,
  onRecommendationChange,
  onRecommendationEngineChange,
  selection,
}: PipelineDialogProps) {
  return (
    <DialogFrame className="pipeline-dialog" titleId="pipeline-dialog-title">
      <DialogHeader
        titleId="pipeline-dialog-title"
        title="Analysis plugins"
        subtitle="Choose the tools used for new uploads and live captures"
        closeLabel="Close analysis plugin settings"
        onClose={onClose}
      />

      <div className="pipeline-dialog-body">
        {loading ? (
          <StateMessage as="p" className="pipeline-loading">
            Reading installed plugins...
          </StateMessage>
        ) : capabilities && selection ? (
          <>
            <PipelineSelect
              id="pipeline-parser"
              label="Recognition"
              description="Reads the table state from the screenshot"
              options={capabilities.parser_providers}
              value={selection.parser_provider}
              onChange={onParserChange}
            />
            <PipelineSelect
              id="pipeline-layout"
              label="Table layout"
              description="Defines where cards, wagers, and player seats are located"
              options={compatibleLayouts}
              value={selection.parser_layout_profile}
              onChange={onParserLayoutChange}
            />
            <PipelineSelect
              id="pipeline-recommendation"
              label="Recommendation"
              description="Analyzes the approved table state"
              options={capabilities.recommendation_providers}
              value={selection.recommendation_provider}
              onChange={onRecommendationChange}
            />
            {selection.recommendation_provider === "local_solver" ? (
              <PipelineSelect
                id="pipeline-engine"
                label="Solver engine"
                description="Runs locally inside the backend deployment"
                options={capabilities.recommendation_engines}
                value={selection.recommendation_engine ?? ""}
                onChange={onRecommendationEngineChange}
              />
            ) : null}
          </>
        ) : (
          <StateMessage as="p" className="pipeline-loading">
            Plugin details are unavailable.
          </StateMessage>
        )}
      </div>

      <DialogFooter className="pipeline-dialog-footer">
        <span>Existing screenshots keep their original pipeline.</span>
        <ButtonControl variant="secondary" onClick={onClose}>
          Done
        </ButtonControl>
      </DialogFooter>
    </DialogFrame>
  );
}

function PipelineSelect({
  description,
  id,
  label,
  onChange,
  options,
  value,
}: PipelineSelectProps) {
  const unavailableOptions = options.filter((option) => !option.available);
  return (
    <div className="pipeline-select-row">
      <FormField
        description={description}
        htmlFor={id}
        label={label}
        labelClassName="pipeline-select-copy"
      >
        <SelectControl
          id={id}
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option
              key={option.id}
              value={option.id}
              disabled={!option.available}
            >
              {option.label}
              {option.available ? "" : " (unavailable)"}
            </option>
          ))}
        </SelectControl>
      </FormField>
      {unavailableOptions.map((option) => (
        <small key={option.id} className="pipeline-unavailable">
          {option.label}: {option.unavailable_reason ?? "Not configured"}
        </small>
      ))}
    </div>
  );
}
