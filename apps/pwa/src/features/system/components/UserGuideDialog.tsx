import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./UserGuideDialog.css";

import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import { ButtonControl } from "../../../shared/components/FormControls";

interface GuideStep {
  title: string;
  description: string;
}

interface GuideTopic {
  id: string;
  label: string;
  title: string;
  introduction: string;
  steps: GuideStep[];
  note?: string;
}

const GUIDE_TOPICS: GuideTopic[] = [
  {
    id: "quick-start",
    label: "Quick start",
    title: "Review your first hand",
    introduction:
      "A complete review moves from a screenshot to a verified table state, then to educational guidance.",
    steps: [
      {
        title: "Add a screenshot",
        description:
          "Choose Upload for saved images or Live to capture a frame from a browser tab, window, or screen.",
      },
      {
        title: "Verify the detected state",
        description:
          "Check the cards, street, pot, wagers, stacks, positions, and action history. Correct any uncertain or missing fields.",
      },
      {
        title: "Approve the hand",
        description:
          "Approve only after the state matches the screenshot. Your corrections become the canonical state used by the solver.",
      },
      {
        title: "Reveal guidance",
        description:
          "Optionally lock your own decision first, then request the recommendation and inspect its sizing, evidence, and assumptions.",
      },
      {
        title: "Finish the review",
        description:
          "Add a lesson note when useful, then clear completed queue items into the searchable History area.",
      },
    ],
    note: "Poker Training Analyzer is for post-hand study. It does not read private table data or act inside a poker client.",
  },
  {
    id: "input-queue",
    label: "Input and queue",
    title: "Capture and process screenshots",
    introduction:
      "Each screenshot is an independent queue item, so a failed image does not discard successful work from the same batch.",
    steps: [
      {
        title: "Upload one or many images",
        description:
          "Open Upload, choose the screenshots, and select Upload and parse. The queue shows progress and the result for every file.",
      },
      {
        title: "Capture a shared source",
        description:
          "Open Live, choose Tab, Window, or Screen, and share through the browser picker. Browser support determines which source types are available.",
      },
      {
        title: "Capture the useful frame",
        description:
          "Once sharing is active, capture a still image when the complete hand state is visible. Only the image is analyzed, not webpage HTML.",
      },
      {
        title: "Manage queue items",
        description:
          "Select any queue row to review it. Open screenshot details with the pencil button to add a title, comment, or tags, or to delete the image.",
      },
    ],
    note: "For large batches, the processing overlay reports progress and can abort the remaining unprocessed items.",
  },
  {
    id: "review-state",
    label: "Detected state",
    title: "Correct what recognition found",
    introduction:
      "Recognition is an assistant, not the source of truth. Confidence and warnings tell you where to concentrate your review.",
    steps: [
      {
        title: "Read confidence indicators",
        description:
          "Each detected field shows its confidence or says that manual review is required. Warnings identify cards or values that could not be read safely.",
      },
      {
        title: "Use total big-blind amounts",
        description:
          "Pot, stack, wager, and action-history amounts are recorded in BB. Raise and call history fields use the total amount reached by that action.",
      },
      {
        title: "Describe the action accurately",
        description:
          "Set the street, players, positions, facing action, and earlier actions. These fields determine which recommendation route is valid.",
      },
      {
        title: "Approve or reset",
        description:
          "Approve saves your reviewed state. Use refresh to return a completed item to review when you need to correct it and request fresh guidance.",
      },
    ],
    note: "Missing context is left visible rather than guessed. A fallback recommendation can be less specific than a fully supported solver tree.",
  },
  {
    id: "automation",
    label: "Automation",
    title: "Automate trusted parts of the workflow",
    introduction:
      "Automation can move high-confidence screenshots through approval and recommendation while leaving uncertain hands for you.",
    steps: [
      {
        title: "Turn on the master control",
        description:
          "Use Automation in the header to enable or pause control-panel automation for new uploads and captured frames. A deployment may independently auto-approve confidence-eligible, warning-free parses even when this browser control is off.",
      },
      {
        title: "Choose automated actions",
        description:
          "Open the gear to configure auto-approval, automatic recommendations, and whether parser warnings may pass without review.",
      },
      {
        title: "Review attention items",
        description:
          "Automation continues through the batch when one hand fails. Items needing attention remain in the queue with their own status.",
      },
      {
        title: "Take manual control again",
        description:
          "Use refresh on a processed hand to unlock its state and recommendation controls before making corrections.",
      },
    ],
    note: "The backend applies its configured confidence requirements before control-panel automation may approve a hand. Automation-only hands are not scored in Training progress because no pre-reveal player decision was recorded.",
  },
  {
    id: "recommendations",
    label: "Recommendations",
    title: "Compare your decision with the solver",
    introduction:
      "The strongest training signal comes from choosing your action before revealing the recommendation.",
    steps: [
      {
        title: "Record your decision",
        description:
          "Choose an action, add sizing when relevant, rate your certainty, and lock the answer before requesting guidance.",
      },
      {
        title: "Read the headline action",
        description:
          "The recommendation shows the preferred action and sizing, confidence, and a concise explanation of the modeled spot.",
      },
      {
        title: "Inspect decision evidence",
        description:
          "Compare candidate EVs or frequencies, equity and call price, range sources, modeled action history, and fallback reasons when available.",
      },
      {
        title: "Treat fallbacks differently",
        description:
          "A postflop solve uses a supported game tree. The local EV fallback uses transparent range and response assumptions for ambiguous or unsupported states.",
      },
    ],
    note: "Recommendations are educational estimates, not guaranteed optimal play. Verify the approved state before using them for study.",
  },
  {
    id: "history-files",
    label: "History and files",
    title: "Organize completed and saved hands",
    introduction:
      "The queue is your active workspace; History is the durable archive for completed reviews.",
    steps: [
      {
        title: "Clear completed work",
        description:
          "Use Clear reviewed to move eligible queue items into History. Automated results stay in the queue until you clear them.",
      },
      {
        title: "Reopen an archived hand",
        description:
          "Select a History row to bring it back into the workspace. Search can find older hands beyond the compact recent list.",
      },
      {
        title: "Describe your files",
        description:
          "Open screenshot details to edit the title, add a comment, and assign tags that make the archive easier to search later.",
      },
      {
        title: "Remove unwanted screenshots",
        description:
          "Delete screenshot permanently removes its image and analysis data after confirmation, whether it is active or archived.",
      },
    ],
    note: "Deletion is permanent. Download an application backup first when the hand may be useful later.",
  },
  {
    id: "progress-lessons",
    label: "Progress and lessons",
    title: "Turn reviewed hands into a study plan",
    introduction:
      "Training progress uses only hands where you locked an answer before revealing guidance.",
    steps: [
      {
        title: "Open Training progress",
        description:
          "Use the target button to review action match, exact sizing-line accuracy, available EV loss, and recent trends.",
      },
      {
        title: "Find a useful focus",
        description:
          "Break results down by street, position, certainty, recommendation engine, fallback reason, or repeated action difference.",
      },
      {
        title: "Work through review queues",
        description:
          "Open a pending group, revisit each hand, and mark the difference reviewed without rewriting the original training result.",
      },
      {
        title: "Keep lesson notes",
        description:
          "Save a short takeaway on a completed review. The Lessons view can filter, order, edit, and export notes as a Markdown study document.",
      },
    ],
  },
  {
    id: "benchmark",
    label: "Parser benchmark",
    title: "Measure recognition accuracy",
    introduction:
      "The parser benchmark reruns recognition against approved hands that you explicitly selected as trusted ground truth.",
    steps: [
      {
        title: "Build the ground-truth set",
        description:
          "Approve a hand, open Parser benchmark, and enable Use current hand as ground truth. Include varied screenshots from the same table layout.",
      },
      {
        title: "Run the selected pipeline",
        description:
          "Choose a compatible parser and layout, then run the benchmark. Original hands and approved labels are not changed.",
      },
      {
        title: "Compare recognition routes",
        description:
          "Run comparison tests to measure every compatible parser pipeline against the same selected corpus.",
      },
      {
        title: "Read regressions by field and case",
        description:
          "Review overall accuracy, cards, money fields, positions, warnings, and per-screenshot changes from the previous compatible report.",
      },
      {
        title: "Move the corpus safely",
        description:
          "Export the benchmark dataset with screenshots and labels, or import a compatible dataset to continue testing another deployment.",
      },
    ],
    note: "Changing selected hands, labels, layout, or parser makes older reports non-comparable until the benchmark is run again.",
  },
  {
    id: "plugins-data",
    label: "Plugins and data",
    title: "Choose tools and protect your data",
    introduction:
      "Recognition and recommendation tools are configurable, while every saved hand retains the pipeline that produced it.",
    steps: [
      {
        title: "Choose analysis plugins",
        description:
          "Use the sliders button to select recognition, table layout, recommendation provider, and local solver engine for new screenshots.",
      },
      {
        title: "Confirm what is active",
        description:
          "Open About to see the active recognition and recommendation route, including automatic-parser fallback details for the selected hand.",
      },
      {
        title: "Back up the application",
        description:
          "About also provides Download backup and Restore backup for screenshots, states, recommendations, lessons, and benchmark reports.",
      },
      {
        title: "Keep deployment secrets outside the browser",
        description:
          "External providers, hosted agent access, and deployment credentials are configured by the backend environment and should never be stored in screenshot metadata.",
      },
    ],
  },
];

interface UserGuideDialogProps {
  onClose: () => void;
}

export function UserGuideDialog({ onClose }: UserGuideDialogProps) {
  const [activeTopicId, setActiveTopicId] = useState(GUIDE_TOPICS[0].id);
  const dialogRef = useRef<HTMLDivElement>(null);
  const topicButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const topicRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const activeIndex = Math.max(
    0,
    GUIDE_TOPICS.findIndex((topic) => topic.id === activeTopicId),
  );
  const activeTopic = GUIDE_TOPICS[activeIndex];
  const previousTopic = GUIDE_TOPICS[activeIndex - 1] ?? null;
  const nextTopic = GUIDE_TOPICS[activeIndex + 1] ?? null;

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (topicRef.current) {
      topicRef.current.scrollTop = 0;
    }
    topicButtonRefs.current.get(activeTopicId)?.scrollIntoView?.({
      block: "nearest",
      inline: "nearest",
    });
  }, [activeTopicId]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    if (!dialog) {
      return;
    }

    const focusableElements = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          "a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
        ),
      );
    const initialFocus =
      dialog.querySelector<HTMLElement>("[aria-current='page']") ??
      focusableElements()[0];
    initialFocus?.focus();

    function containFocus(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const focusable = focusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const focusedIndex = focusable.indexOf(
        document.activeElement as HTMLElement,
      );
      if (event.shiftKey && focusedIndex <= 0) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && focusedIndex === focusable.length - 1) {
        event.preventDefault();
        first.focus();
      } else if (focusedIndex === -1) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }

    document.addEventListener("keydown", containFocus, true);
    return () => {
      document.removeEventListener("keydown", containFocus, true);
      if (previousFocus?.isConnected) {
        previousFocus.focus();
      }
    };
  }, []);

  return (
    <DialogFrame
      ref={dialogRef}
      className="help-dialog"
      titleId="help-dialog-title"
    >
      <DialogHeader
        titleId="help-dialog-title"
        title="How to use Poker Training Analyzer"
        subtitle="Workflows and reference for the control panel"
        closeLabel="Close user guide"
        onClose={onClose}
      />

      <div className="help-dialog-body">
        <nav className="help-topic-nav" aria-label="User guide topics">
          {GUIDE_TOPICS.map((topic, index) => (
            <ButtonControl
              key={topic.id}
              ref={(button) => {
                if (button) {
                  topicButtonRefs.current.set(topic.id, button);
                } else {
                  topicButtonRefs.current.delete(topic.id);
                }
              }}
              variant="ghost"
              className={topic.id === activeTopic.id ? "active" : ""}
              onClick={() => setActiveTopicId(topic.id)}
              aria-current={topic.id === activeTopic.id ? "page" : undefined}
            >
              <span aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              {topic.label}
            </ButtonControl>
          ))}
        </nav>

        <article ref={topicRef} className="help-topic" aria-live="polite">
          <span className="help-topic-index">
            Topic {activeIndex + 1} of {GUIDE_TOPICS.length}
          </span>
          <h3>{activeTopic.title}</h3>
          <p className="help-topic-introduction">{activeTopic.introduction}</p>
          <ol className="help-steps">
            {activeTopic.steps.map((step) => (
              <li key={step.title}>
                <strong>{step.title}</strong>
                <p>{step.description}</p>
              </li>
            ))}
          </ol>
          {activeTopic.note ? (
            <p className="help-topic-note">
              <strong>Keep in mind</strong>
              {activeTopic.note}
            </p>
          ) : null}
        </article>
      </div>

      <DialogFooter className="help-dialog-footer">
        <ButtonControl
          variant="secondary"
          disabled={!previousTopic}
          onClick={() => previousTopic && setActiveTopicId(previousTopic.id)}
          aria-label={
            previousTopic
              ? `Previous topic: ${previousTopic.label}`
              : "No previous topic"
          }
        >
          <ChevronLeft size={15} aria-hidden="true" />
          Previous
        </ButtonControl>
        <span>{activeTopic.label}</span>
        {nextTopic ? (
          <ButtonControl
            variant="secondary"
            onClick={() => setActiveTopicId(nextTopic.id)}
            aria-label={`Next topic: ${nextTopic.label}`}
          >
            Next
            <ChevronRight size={15} aria-hidden="true" />
          </ButtonControl>
        ) : (
          <ButtonControl variant="secondary" onClick={onClose}>
            Done
          </ButtonControl>
        )}
      </DialogFooter>
    </DialogFrame>
  );
}
