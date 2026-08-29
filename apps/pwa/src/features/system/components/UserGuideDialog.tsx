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
    id: "player-workflow",
    label: "Player workflow",
    title: "Analyze imported hand histories",
    introduction:
      "Player analysis is import-first. Hands reach the workspace as imported hand histories, and screenshots are not a player data path.",
    steps: [
      {
        title: "Work from imported hands",
        description:
          "Imported hand histories are the player data path. They carry the table state player analysis reasons about.",
      },
      {
        title: "Screenshots are not a player path",
        description:
          "Screenshot upload and live capture are administrator-only parser test tools. They stay hidden until an administrator unlocks them and are not used for player analysis.",
      },
    ],
    note: "Every stored screenshot is administrative OCR test data. This workspace is the administrator console for that data.",
  },
  {
    id: "quick-start",
    label: "Quick start",
    title: "Run an OCR test end to end",
    introduction:
      "A complete test moves from an unlocked administrator session to an approved ground-truth state you can benchmark against.",
    steps: [
      {
        title: "Unlock administrator tools",
        description:
          "Open Administrator tools in the header and enter the deployment's administrative OCR test token. Upload and live capture stay hidden until the session is unlocked.",
      },
      {
        title: "Upload or capture a screenshot",
        description:
          "Open Upload to choose image files, or open Live to share a tab, window, or screen and capture a still. The queue shows the parse result for every input.",
      },
      {
        title: "Review the detected state",
        description:
          "Check the cards, street, pot, wagers, stacks, positions, and action history against the screenshot. Correct any uncertain or missing fields.",
      },
      {
        title: "Approve the ground truth",
        description:
          "Approve only after the state matches the screenshot. Your corrections become the approved ground truth the parser is measured against.",
      },
      {
        title: "Benchmark and archive",
        description:
          "Include approved hands in the parser benchmark to measure recognition accuracy, then clear finished queue items into the searchable History area.",
      },
    ],
    note: "Poker Training Analyzer is for post-hand study. It does not read private table data or act inside a poker client.",
  },
  {
    id: "input-queue",
    label: "Input and queue",
    title: "Administrator OCR test tools",
    introduction:
      "Screenshot upload and live capture exist only to test the parser. They are hidden until an administrator unlocks them, and the server verifies the credential on every upload or capture. Benchmark dataset import and application backup restore need the same credential.",
    steps: [
      {
        title: "Unlock administrator tools",
        description:
          "Open Administrator tools in the header and enter the deployment's administrative OCR test token. The token is held in memory for this session only and is never stored.",
      },
      {
        title: "Upload one or many images",
        description:
          "Open Upload, choose the screenshots, and select Upload and parse. The queue shows progress and the result for every file.",
      },
      {
        title: "Capture a shared source",
        description:
          "Open Live, choose Tab, Window, or Screen, and share through the browser picker. Capture a still image when the complete hand state is visible; only the image is analyzed, not webpage HTML.",
      },
      {
        title: "Watch the queue",
        description:
          "Each queued frame shows its parse status, a short detail line, and any warning that needs your attention before approval.",
      },
    ],
    note: "Lock the tools again from the banner or the dialog when testing is finished. Locking also stops any active screen share.",
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
          "Set the street, players, positions, facing action, and earlier actions so the approved state describes the same spot as the screenshot.",
      },
      {
        title: "Approve or reset",
        description:
          "Approve saves your reviewed state as ground truth. Use refresh to return the editor to what the parser detected when you need to start over.",
      },
    ],
    note: "Missing context is left visible rather than guessed. Approve only what you can verify in the screenshot.",
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
    id: "history-files",
    label: "History and files",
    title: "Organize completed and saved hands",
    introduction:
      "The queue is your active workspace; History is the durable archive for approved hands.",
    steps: [
      {
        title: "Clear completed work",
        description:
          "Use Clear reviewed to move approved queue items into History. Items stay in the queue until you clear them.",
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
    id: "plugins-data",
    label: "Plugins and data",
    title: "Choose tools and protect your data",
    introduction:
      "Recognition tools are configurable, while every saved hand retains the pipeline that produced it.",
    steps: [
      {
        title: "Choose analysis plugins",
        description:
          "Use the sliders button to select the recognition parser and table layout used for new screenshots.",
      },
      {
        title: "Confirm what is active",
        description:
          "Open About to see the active recognition route, including automatic-parser fallback details for the selected hand.",
      },
      {
        title: "Back up the application",
        description:
          "About also provides Download backup and Restore backup for screenshots, approved ground truth, and benchmark reports.",
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
