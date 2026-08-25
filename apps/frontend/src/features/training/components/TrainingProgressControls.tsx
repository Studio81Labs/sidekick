import { Search } from "lucide-react";

import "./TrainingProgressControls.css";
import {
  ButtonControl,
  FormField,
  SelectControl,
  TextInput,
} from "../../../shared/components/FormControls";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import type { TrainingDecisionListView } from "./TrainingDecisionList";
import type {
  TrainingReviewCertaintyFilter,
  TrainingReviewOrder,
  TrainingReviewStreet,
} from "../../../shared/types/training";

export interface TrainingProgressControlsProps {
  controlsDisabled: boolean;
  lessonCount: number;
  lessonOrder: TrainingReviewOrder;
  lessonQuery: string;
  lessonSearch: string;
  lessonStreet: TrainingReviewStreet;
  needsReviewHands: number;
  onLessonOrderChange: (order: TrainingReviewOrder) => void | Promise<void>;
  onLessonSearchChange: (search: string) => void;
  onLessonSearchSubmit: () => void | Promise<void>;
  onLessonStreetChange: (street: TrainingReviewStreet) => void | Promise<void>;
  onReviewCertaintyChange: (
    certainty: TrainingReviewCertaintyFilter,
  ) => void | Promise<void>;
  onReviewOrderChange: (order: TrainingReviewOrder) => void | Promise<void>;
  onReviewStreetChange: (street: TrainingReviewStreet) => void | Promise<void>;
  onViewChange: (view: TrainingDecisionListView) => void;
  reviewCertainty: TrainingReviewCertaintyFilter;
  reviewOrder: TrainingReviewOrder;
  reviewStreet: TrainingReviewStreet;
  view: TrainingDecisionListView;
}

const STREET_OPTIONS: ReadonlyArray<{
  label: string;
  value: TrainingReviewStreet;
}> = [
  { value: "all", label: "All" },
  { value: "preflop", label: "Preflop" },
  { value: "flop", label: "Flop" },
  { value: "turn", label: "Turn" },
  { value: "river", label: "River" },
];

export function TrainingProgressControls({
  controlsDisabled,
  lessonCount,
  lessonOrder,
  lessonQuery,
  lessonSearch,
  lessonStreet,
  needsReviewHands,
  onLessonOrderChange,
  onLessonSearchChange,
  onLessonSearchSubmit,
  onLessonStreetChange,
  onReviewCertaintyChange,
  onReviewOrderChange,
  onReviewStreetChange,
  onViewChange,
  reviewCertainty,
  reviewOrder,
  reviewStreet,
  view,
}: TrainingProgressControlsProps) {
  return (
    <div className="training-review-heading">
      <h3 id="training-hands-title">
        {view === "review"
          ? "Needs review"
          : view === "lessons"
            ? "Saved lessons"
            : "Recent decisions"}
      </h3>
      <div className="training-review-controls">
        {view === "review" ? (
          <>
            <FormField
              className="training-review-order"
              label="Order"
              labelClassName="training-review-order-label"
            >
              <SelectControl
                aria-label="Review order"
                density="compact"
                value={reviewOrder}
                onChange={(event) =>
                  void onReviewOrderChange(
                    event.target.value as TrainingReviewOrder,
                  )
                }
                disabled={controlsDisabled}
              >
                <option value="recent">Newest</option>
                <option value="ev_loss">EV loss</option>
              </SelectControl>
            </FormField>
            <FormField
              className="training-review-order"
              label="Street"
              labelClassName="training-review-order-label"
            >
              <SelectControl
                aria-label="Review street"
                density="compact"
                value={reviewStreet}
                onChange={(event) =>
                  void onReviewStreetChange(
                    event.target.value as TrainingReviewStreet,
                  )
                }
                disabled={controlsDisabled}
              >
                {STREET_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </SelectControl>
            </FormField>
            <FormField
              className="training-review-order"
              label="Certainty"
              labelClassName="training-review-order-label"
            >
              <SelectControl
                aria-label="Review certainty"
                density="compact"
                value={reviewCertainty}
                onChange={(event) =>
                  void onReviewCertaintyChange(
                    event.target.value as TrainingReviewCertaintyFilter,
                  )
                }
                disabled={controlsDisabled}
              >
                <option value="all">All</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
                <option value="unrated">Unrated</option>
              </SelectControl>
            </FormField>
          </>
        ) : null}
        {view === "lessons" ? (
          <>
            <form
              className="training-lesson-search"
              role="search"
              onSubmit={(event) => {
                event.preventDefault();
                void onLessonSearchSubmit();
              }}
            >
              <TextInput
                appearance="borderless"
                density="compact"
                type="search"
                aria-label="Search saved lesson notes"
                placeholder="Search notes"
                maxLength={120}
                value={lessonSearch}
                onChange={(event) => onLessonSearchChange(event.target.value)}
                disabled={controlsDisabled}
              />
              <ButtonControl
                type="submit"
                variant="ghost"
                className="training-lesson-search-submit"
                aria-label="Apply lesson search"
                title="Search lesson notes"
                disabled={
                  controlsDisabled || lessonSearch.trim() === lessonQuery
                }
              >
                <Search size={13} aria-hidden="true" />
              </ButtonControl>
            </form>
            <FormField
              className="training-review-order"
              label="Order"
              labelClassName="training-review-order-label"
            >
              <SelectControl
                aria-label="Lesson order"
                density="compact"
                value={lessonOrder}
                onChange={(event) =>
                  void onLessonOrderChange(
                    event.target.value as TrainingReviewOrder,
                  )
                }
                disabled={controlsDisabled}
              >
                <option value="recent">Newest</option>
                <option value="ev_loss">EV loss</option>
              </SelectControl>
            </FormField>
            <FormField
              className="training-review-order"
              label="Street"
              labelClassName="training-review-order-label"
            >
              <SelectControl
                aria-label="Lesson street"
                density="compact"
                value={lessonStreet}
                onChange={(event) =>
                  void onLessonStreetChange(
                    event.target.value as TrainingReviewStreet,
                  )
                }
                disabled={controlsDisabled}
              >
                {STREET_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </SelectControl>
            </FormField>
          </>
        ) : null}
        <SegmentedControl
          ariaLabel="Training decision view"
          className="training-view-switch"
          options={[
            { value: "recent", label: "Recent" },
            {
              value: "review",
              label: `Needs review ${needsReviewHands}`,
            },
            {
              value: "lessons",
              label: `Lessons ${lessonCount}`,
            },
          ]}
          value={view}
          onChange={onViewChange}
        />
      </div>
    </div>
  );
}
