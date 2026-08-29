import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { imageUrl } from "../../../domains/jobs/api/jobsApi";
import { humanReadableMessage } from "../../../shared/api/core";
import {
  PREFLOP_POSITIONS,
  normalizePreflopPosition,
} from "../../../domains/poker/model/preflopPosition";
import { EMPTY_STATE } from "../../../domains/poker/model/pokerStateConstants";
import {
  approvalKey,
  benchmarkApprovalKey,
  stateFromJob,
} from "../../../domains/poker/model/canonicalPokerState";
import {
  formToCanonical,
  stateToForm,
} from "../../../domains/poker/model/pokerStateConversion";
import { summarizeConfidences } from "../lib/pokerStateConfidence";
import { parserRoutingFromRaw } from "../../../domains/pipeline/model/parserRouting";
import {
  messageFromError,
  VALIDATION_TOAST_ID,
} from "../../../shared/lib/errors";
import type {
  CompletedPostflopActionForm,
  PostflopActionForm,
  PreflopActionForm,
  StateForm,
} from "../../../domains/poker/model/pokerStateForm";
import { requiresOpponentPosition } from "../../../domains/poker/model/pokerStateForm";
import type { CompletedPostflopStreet } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";

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
  const activeJobIdRef = useRef(activeJobId);
  activeJobIdRef.current = activeJobId;
  const formBaselineRef = useRef(form);
  const formDirtyRef = useRef(false);

  const job = useMemo(
    () =>
      activeJobId === null
        ? (jobs[0] ?? null)
        : (jobs.find((candidate) => candidate.id === activeJobId) ?? null),
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
  const canApprove = Boolean(
    (job?.parser_result || job?.approved_state) &&
    validation.state &&
    validation.state.hero_cards.length > 0 &&
    validation.state.street &&
    !currentStateApproved,
  );
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

  return {
    activeJobId,
    activeJobIdRef,
    addCompletedPostflopAction,
    addPostflopAction,
    addPreflopAction,
    alignWorkspaceToJob,
    approvalKey,
    approvedStateKey,
    benchmarkApprovalKey,
    canApprove,
    completedPostflopActionCounts,
    completedPostflopActionsAtLimit,
    confidenceSummary,
    confidences,
    form,
    formBaselineRef,
    formDirtyRef,
    job,
    parserRoutingFromRaw,
    removeCompletedPostflopAction,
    removePostflopAction,
    removePreflopAction,
    resetToParser,
    screenshotUrl,
    setActiveJobId,
    setApprovedStateKey,
    setForm,
    stateToForm,
    updateCompletedPostflopAction,
    updateForm,
    updatePostflopAction,
    updatePreflopAction,
    validation,
    warnings,
  };
}
