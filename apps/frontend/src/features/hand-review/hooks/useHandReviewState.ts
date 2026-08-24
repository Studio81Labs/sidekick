import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { imageUrl } from "../../../domains/jobs/api/jobsApi";
import { humanReadableMessage } from "../../../shared/api/client";
import { normalizePreflopPosition } from "../lib/preflopPosition";
import {
  EMPTY_STATE,
  PREFLOP_POSITIONS,
  approvalKey,
  formToCanonical,
  stateFromJob,
  stateToForm,
  summarizeConfidences,
} from "../lib/pokerState";
import { recommendationEvidenceFromRaw } from "../../recommendation/lib/recommendationPresentation";
import {
  type TrainingActionOption,
  type TrainingCertaintyOption,
  trainingDecisionComparison,
} from "../../training/lib/trainingPresentation";
import {
  messageFromError,
  VALIDATION_TOAST_ID,
} from "../../workspace/lib/workflow";
import type {
  CompletedPostflopActionForm,
  PostflopActionForm,
  PreflopActionForm,
  StateForm,
} from "../lib/pokerStateForm";
import { requiresOpponentPosition } from "../lib/pokerStateForm";
import type { CompletedPostflopStreet, JobRecord } from "../../../shared/types";

interface UseHandReviewStateOptions {
  activeJobId: string | null;
  jobs: JobRecord[];
  onActiveJobChange: (jobId: string | null) => void;
  onError: (message: string | null) => void;
}

export function useHandReviewState({
  activeJobId,
  jobs,
  onActiveJobChange,
  onError,
}: UseHandReviewStateOptions) {
  const [form, setForm] = useState<StateForm>(() => stateToForm(EMPTY_STATE));
  const [approvedStateKey, setApprovedStateKey] = useState<string | null>(null);
  const [trainingAction, setTrainingAction] =
    useState<TrainingActionOption>("");
  const [trainingSizing, setTrainingSizing] = useState("");
  const [trainingCertainty, setTrainingCertainty] =
    useState<TrainingCertaintyOption>("");
  const [trainingReviewNote, setTrainingReviewNote] = useState("");
  const [trainingReviewNoteEditing, setTrainingReviewNoteEditing] =
    useState(false);
  const activeJobIdRef = useRef(activeJobId);
  activeJobIdRef.current = activeJobId;
  const formBaselineRef = useRef(form);
  const formDirtyRef = useRef(false);

  const job = useMemo(
    () =>
      jobs.find((candidate) => candidate.id === activeJobId) ?? jobs[0] ?? null,
    [activeJobId, jobs],
  );
  const validation = useMemo(() => {
    try {
      return { state: formToCanonical(form), error: null };
    } catch (error) {
      return {
        state: null,
        error: messageFromError(error, "Correct the detected state"),
      };
    }
  }, [form]);
  const confidences: Record<string, number> =
    job?.parser_result?.confidences ?? {};
  const parserWarnings = (job?.parser_result?.warnings ?? []).map((warning) =>
    humanReadableMessage(warning, "The parser reported a warning"),
  );
  const warnings = job?.error
    ? [
        ...parserWarnings,
        humanReadableMessage(job.error, "The screenshot needs attention"),
      ]
    : parserWarnings;
  const currentStateKey = validation.state
    ? approvalKey(validation.state)
    : null;
  const currentStateApproved = Boolean(
    job?.approved_state &&
    currentStateKey &&
    approvedStateKey === currentStateKey,
  );
  const recommendation = currentStateApproved
    ? (job?.recommendation ?? null)
    : null;
  const trainingDecision = currentStateApproved
    ? (job?.training_decision ?? null)
    : null;
  const decisionEvidence = useMemo(
    () =>
      recommendation
        ? recommendationEvidenceFromRaw(recommendation.raw, recommendation)
        : null,
    [recommendation],
  );
  const decisionComparison = useMemo(
    () =>
      recommendation && trainingDecision
        ? trainingDecisionComparison(
            trainingDecision.action,
            trainingDecision.sizing,
            recommendation,
          )
        : null,
    [recommendation, trainingDecision],
  );
  const canApprove = Boolean(
    (job?.parser_result || job?.approved_state) &&
    validation.state &&
    validation.state.hero_cards.length > 0 &&
    validation.state.street &&
    !currentStateApproved,
  );
  const canRecommend =
    currentStateApproved &&
    !job?.recommendation &&
    !job?.recommendation_pending;
  const completedPostflopActionCounts = useMemo(
    () =>
      form.completed_postflop_actions.reduce<
        Record<CompletedPostflopStreet, number>
      >(
        (counts, action) => ({
          ...counts,
          [action.street]: counts[action.street] + 1,
        }),
        { flop: 0, turn: 0 },
      ),
    [form.completed_postflop_actions],
  );
  const completedPostflopActionsAtLimit =
    form.street === "turn"
      ? completedPostflopActionCounts.flop >= 8
      : completedPostflopActionCounts.flop >= 8 &&
        completedPostflopActionCounts.turn >= 8;
  const screenshotUrl = useMemo(
    () => (job && job.image_filename !== "" ? imageUrl(job.id) : null),
    [job],
  );
  const confidenceSummary = useMemo(
    () => summarizeConfidences(confidences, warnings, validation.state),
    [confidences, validation.state, warnings],
  );

  useEffect(() => {
    if (activeJobId !== null || jobs.length === 0) return;
    alignWorkspaceToJob(jobs[0]);
  }, [activeJobId, jobs]);

  useEffect(() => {
    if (!currentStateApproved) {
      setTrainingAction("");
      setTrainingSizing("");
      setTrainingCertainty("");
      return;
    }
    setTrainingAction(job?.training_decision?.action ?? "");
    setTrainingSizing(
      job?.training_decision?.sizing === null ||
        job?.training_decision?.sizing === undefined
        ? ""
        : String(job.training_decision.sizing),
    );
    setTrainingCertainty(job?.training_decision?.certainty ?? "");
  }, [
    currentStateApproved,
    job?.id,
    job?.training_decision?.action,
    job?.training_decision?.certainty,
    job?.training_decision?.sizing,
  ]);

  useEffect(() => {
    setTrainingReviewNote(job?.training_review_note ?? "");
    setTrainingReviewNoteEditing(false);
  }, [job?.id, job?.training_review_note, job?.training_reviewed_at]);

  useEffect(() => {
    if (job && validation.error) {
      toast.warning(validation.error, { id: VALIDATION_TOAST_ID });
      return;
    }
    toast.dismiss(VALIDATION_TOAST_ID);
  }, [job, validation.error]);

  function setActiveJobId(nextActiveJobId: string | null) {
    activeJobIdRef.current = nextActiveJobId;
    onActiveJobChange(nextActiveJobId);
  }

  function alignWorkspaceToJob(nextJob: JobRecord | null) {
    const nextState = nextJob ? stateFromJob(nextJob) : EMPTY_STATE;
    const nextForm = stateToForm(nextState);
    activeJobIdRef.current = nextJob?.id ?? null;
    formBaselineRef.current = nextForm;
    formDirtyRef.current = false;
    setActiveJobId(nextJob?.id ?? null);
    setForm(nextForm);
    setApprovedStateKey(
      nextJob?.approved_state ? approvalKey(nextJob.approved_state) : null,
    );
  }

  function updateForm<K extends keyof StateForm>(
    field: K,
    value: StateForm[K],
  ) {
    setForm((current) => {
      const next = { ...current, [field]: value };
      if (field === "current_bet") {
        next.opponent_wager = "";
        next.action_context = "";
        if (value !== "") next.facing_action = "";
      }
      if (field === "facing_action") {
        next.opponent_wager = "";
        next.action_context = "";
      }
      if (field === "street" && (value === "" || value === "preflop")) {
        next.opponent_wager = "";
        next.facing_action = "";
        next.action_context = "";
      }
      if (
        ((field === "street" && value !== "preflop") ||
          (field === "facing_action" && value !== "raise")) &&
        next.preflop_action_history.length === 0
      ) {
        next.preflop_opener_position = "";
        next.preflop_open_size = "";
      }
      const usesPostflopHistory =
        next.facing_action === "raise" &&
        next.street !== "" &&
        next.street !== "preflop";
      const usesCompletedPostflopHistory =
        next.street === "turn" || next.street === "river";
      if (!usesPostflopHistory) next.postflop_action_history = [];
      if (!usesCompletedPostflopHistory) {
        next.completed_postflop_actions = [];
      } else if (next.street === "turn") {
        next.completed_postflop_actions =
          next.completed_postflop_actions.filter(
            (action) => action.street === "flop",
          );
      }
      if (!usesPostflopHistory && !usesCompletedPostflopHistory) {
        next.opponent_stack = "";
      }
      if (!requiresOpponentPosition(next)) next.opponent_position = "";
      const usesCommittedOpponentCount =
        Number(next.current_bet) > 0 && Number(next.players_in_hand) > 2;
      if (!usesCommittedOpponentCount) {
        next.opponents_at_current_bet = "";
        if (Number(next.current_bet) > 0) {
          next.opponent_commitment_total = "";
        }
      }
      if (Number(next.current_bet) <= 0) {
        next.opponent_wager = "";
        if (next.street !== "preflop") next.opponent_commitment_total = "";
      }
      formDirtyRef.current =
        JSON.stringify(next) !== JSON.stringify(formBaselineRef.current);
      return next;
    });
    setApprovedStateKey(null);
  }

  function addPreflopAction() {
    const previous =
      form.preflop_action_history[form.preflop_action_history.length - 1];
    const previousIndex = previous
      ? PREFLOP_POSITIONS.findIndex(
          (position) => position.value === previous.actor,
        )
      : -1;
    const legacyOpener = normalizePreflopPosition(form.preflop_opener_position);
    const heroPosition = normalizePreflopPosition(form.hero_position);
    const actor =
      form.preflop_action_history.length === 0
        ? (legacyOpener ?? heroPosition ?? "cutoff")
        : (PREFLOP_POSITIONS[previousIndex + 1]?.value ?? "big_blind");
    updateForm("preflop_action_history", [
      ...form.preflop_action_history,
      {
        actor,
        action: "raise",
        amount:
          form.preflop_action_history.length === 0
            ? form.preflop_open_size
            : "",
      },
    ]);
  }

  function updatePreflopAction(
    index: number,
    field: keyof PreflopActionForm,
    value: string,
  ) {
    updateForm(
      "preflop_action_history",
      form.preflop_action_history.map((action, actionIndex) =>
        actionIndex === index
          ? ({ ...action, [field]: value } as PreflopActionForm)
          : action,
      ),
    );
  }

  function removePreflopAction(index: number) {
    updateForm(
      "preflop_action_history",
      form.preflop_action_history.filter(
        (_, actionIndex) => actionIndex !== index,
      ),
    );
  }

  function addPostflopAction() {
    updateForm("postflop_action_history", [
      ...form.postflop_action_history,
      {
        actor: form.postflop_action_history.length % 2 === 0 ? "oop" : "ip",
        action: "check",
        amount: "",
      },
    ]);
  }

  function updatePostflopAction(
    index: number,
    field: keyof PostflopActionForm,
    value: string,
  ) {
    updateForm(
      "postflop_action_history",
      form.postflop_action_history.map((action, actionIndex) => {
        if (actionIndex !== index) return action;
        const updated = { ...action, [field]: value } as PostflopActionForm;
        if (field === "action" && value === "check") updated.amount = "";
        return updated;
      }),
    );
  }

  function removePostflopAction(index: number) {
    updateForm(
      "postflop_action_history",
      form.postflop_action_history.filter(
        (_, actionIndex) => actionIndex !== index,
      ),
    );
  }

  function addCompletedPostflopAction() {
    const previous =
      form.completed_postflop_actions[
        form.completed_postflop_actions.length - 1
      ];
    let street: CompletedPostflopStreet =
      form.street === "river" ? (previous?.street ?? "flop") : "flop";
    if (completedPostflopActionCounts[street] >= 8 && form.street === "river") {
      street = street === "flop" ? "turn" : "flop";
    }
    const streetActionCount = completedPostflopActionCounts[street];
    if (streetActionCount >= 8) return;
    updateForm("completed_postflop_actions", [
      ...form.completed_postflop_actions,
      {
        street,
        actor: streetActionCount % 2 === 0 ? "oop" : "ip",
        action: "check",
        amount: "",
      },
    ]);
  }

  function updateCompletedPostflopAction(
    index: number,
    field: keyof CompletedPostflopActionForm,
    value: string,
  ) {
    updateForm(
      "completed_postflop_actions",
      form.completed_postflop_actions.map((action, actionIndex) => {
        if (actionIndex !== index) return action;
        const updated = {
          ...action,
          [field]: value,
        } as CompletedPostflopActionForm;
        if (field === "action" && value === "check") updated.amount = "";
        return updated;
      }),
    );
  }

  function removeCompletedPostflopAction(index: number) {
    updateForm(
      "completed_postflop_actions",
      form.completed_postflop_actions.filter(
        (_, actionIndex) => actionIndex !== index,
      ),
    );
  }

  function resetToParser() {
    if (!job?.parser_result) return;
    const parserForm = stateToForm(job.parser_result.state);
    formBaselineRef.current = parserForm;
    formDirtyRef.current = false;
    setForm(parserForm);
    onError(null);
    setApprovedStateKey(null);
  }

  function startTrainingReviewNoteEdit() {
    setTrainingReviewNote(job?.training_review_note ?? "");
    setTrainingReviewNoteEditing(true);
  }

  function cancelTrainingReviewNoteEdit() {
    setTrainingReviewNote(job?.training_review_note ?? "");
    setTrainingReviewNoteEditing(false);
  }

  return {
    activeJobId,
    activeJobIdRef,
    addCompletedPostflopAction,
    addPostflopAction,
    addPreflopAction,
    alignWorkspaceToJob,
    approvedStateKey,
    canApprove,
    canRecommend,
    cancelTrainingReviewNoteEdit,
    completedPostflopActionCounts,
    completedPostflopActionsAtLimit,
    confidenceSummary,
    confidences,
    currentStateApproved,
    decisionComparison,
    decisionEvidence,
    form,
    formBaselineRef,
    formDirtyRef,
    job,
    recommendation,
    removeCompletedPostflopAction,
    removePostflopAction,
    removePreflopAction,
    resetToParser,
    screenshotUrl,
    setActiveJobId,
    setApprovedStateKey,
    setForm,
    setTrainingAction,
    setTrainingCertainty,
    setTrainingReviewNote,
    setTrainingReviewNoteEditing,
    setTrainingSizing,
    startTrainingReviewNoteEdit,
    trainingAction,
    trainingCertainty,
    trainingDecision,
    trainingReviewNote,
    trainingReviewNoteEditing,
    trainingSizing,
    updateCompletedPostflopAction,
    updateForm,
    updatePostflopAction,
    updatePreflopAction,
    validation,
    warnings,
  };
}
