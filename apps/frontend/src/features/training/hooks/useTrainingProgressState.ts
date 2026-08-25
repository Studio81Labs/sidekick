import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  trainingProgressQueryOptions,
  trainingQueryKeys,
} from "../../../domains/training/api/trainingQueries";
import type { Street } from "../../../shared/types/poker";
import type {
  TrainingCertaintyFilter,
  TrainingPositionFilter,
  TrainingProgress,
  TrainingReviewCertainty,
  TrainingReviewCertaintyFilter,
  TrainingReviewDifference,
  TrainingReviewOrder,
  TrainingReviewStreet,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";
import { messageFromError } from "../../workspace/lib/workflow";
import {
  sameTrainingPositionFilter,
  type TrainingProgressView,
} from "../lib/trainingPresentation";

interface UseTrainingProgressStateOptions {
  onError: (message: string | null) => void;
}

interface TrainingProgressQuery {
  certaintyFilter: TrainingCertaintyFilter | null;
  lessonOrder: TrainingReviewOrder;
  lessonQuery: string;
  lessonStreet: TrainingReviewStreet;
  positionFilter: TrainingPositionFilter | null;
  reviewCertainty: TrainingReviewCertaintyFilter;
  reviewDifference: TrainingReviewDifference | null;
  reviewOrder: TrainingReviewOrder;
  reviewPosition: TrainingPositionFilter | null;
  reviewStreet: TrainingReviewStreet;
  solverFilter: TrainingSolverFilter | null;
  streetFilter: TrainingStreetFilter | null;
}

const INITIAL_QUERY: TrainingProgressQuery = {
  certaintyFilter: null,
  lessonOrder: "recent",
  lessonQuery: "",
  lessonStreet: "all",
  positionFilter: null,
  reviewCertainty: "all",
  reviewDifference: null,
  reviewOrder: "recent",
  reviewPosition: null,
  reviewStreet: "all",
  solverFilter: null,
  streetFilter: null,
};

function readProgress(
  queryClient: QueryClient,
  query: TrainingProgressQuery,
): Promise<TrainingProgress> {
  return queryClient.fetchQuery(
    trainingProgressQueryOptions(
      {
        certaintyFilter: query.certaintyFilter,
        lessonOrder: query.lessonOrder,
        lessonQuery: query.lessonQuery,
        lessonStreet: query.lessonStreet,
        positionFilter: query.positionFilter,
        reviewCertainty: query.reviewCertainty,
        reviewDifference: query.reviewDifference,
        reviewOrder: query.reviewOrder,
        reviewPositionFilter: query.reviewPosition,
        reviewStreet: query.reviewStreet,
        solverFilter: query.solverFilter,
        streetFilter: query.streetFilter,
      },
      false,
    ),
  );
}

function sameReviewDifference(
  left: TrainingReviewDifference | null,
  right: TrainingReviewDifference | null,
): boolean {
  return (
    left?.decision_action === right?.decision_action &&
    left?.recommended_action === right?.recommended_action
  );
}

function sameSolverFilter(
  left: TrainingSolverFilter | null,
  right: TrainingSolverFilter | null,
): boolean {
  if (left?.kind !== right?.kind) return false;
  if (!left || !right || left.kind === "unattributed") return true;
  return right.kind !== "unattributed" && left.key === right.key;
}

export function useTrainingProgressState({
  onError,
}: UseTrainingProgressStateOptions) {
  const queryClient = useQueryClient();
  const [progress, setProgressState] = useState<TrainingProgress | null>(null);
  const [query, setQuery] = useState<TrainingProgressQuery>(INITIAL_QUERY);
  const [lessonSearch, setLessonSearch] = useState("");
  const [view, setView] = useState<TrainingProgressView>("recent");
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);
  const loadingRef = useRef(false);
  const requestRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  async function loadQuery(
    nextQuery: TrainingProgressQuery,
    failureMessage: string,
    rollbackQuery?: TrainingProgressQuery,
  ): Promise<TrainingProgress | null> {
    const requestId = ++requestRef.current;
    loadingRef.current = true;
    setLoading(true);
    onError(null);
    try {
      void queryClient.cancelQueries({ queryKey: trainingQueryKeys.all });
      const nextProgress = await readProgress(queryClient, nextQuery);
      if (!mountedRef.current || requestId !== requestRef.current) return null;
      setProgressState(nextProgress);
      return nextProgress;
    } catch (error) {
      if (mountedRef.current && requestId === requestRef.current) {
        if (rollbackQuery) setQuery(rollbackQuery);
        onError(messageFromError(error, failureMessage));
      }
      return null;
    } finally {
      if (mountedRef.current && requestId === requestRef.current) {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }

  function cancelLoads() {
    requestRef.current += 1;
    void queryClient.cancelQueries({ queryKey: trainingQueryKeys.all });
    loadingRef.current = false;
    setLoading(false);
  }

  function loadInitial() {
    setProgressState(null);
    setQuery(INITIAL_QUERY);
    setLessonSearch("");
    setView("recent");
    void loadQuery(
      INITIAL_QUERY,
      "Could not load training progress",
      INITIAL_QUERY,
    );
  }

  function setProgress(nextProgress: TrainingProgress | null) {
    cancelLoads();
    setProgressState(nextProgress);
  }

  async function updateQuery(
    nextQuery: TrainingProgressQuery,
    failureMessage: string,
    optimisticQuery: TrainingProgressQuery = nextQuery,
  ) {
    if (loadingRef.current) return;
    const previousQuery = query;
    setQuery(optimisticQuery);
    if (await loadQuery(nextQuery, failureMessage, previousQuery)) {
      setQuery(nextQuery);
    }
  }

  async function updateReviewQueue(
    nextOrder: TrainingReviewOrder,
    nextStreet: TrainingReviewStreet,
    nextDifference: TrainingReviewDifference | null = query.reviewDifference,
    nextCertainty: TrainingReviewCertaintyFilter = query.reviewCertainty,
    nextPosition: TrainingPositionFilter | null = query.reviewPosition,
  ) {
    if (
      (nextOrder === query.reviewOrder &&
        nextStreet === query.reviewStreet &&
        nextCertainty === query.reviewCertainty &&
        sameTrainingPositionFilter(nextPosition, query.reviewPosition) &&
        sameReviewDifference(nextDifference, query.reviewDifference) &&
        query.solverFilter === null &&
        query.positionFilter === null &&
        query.streetFilter === null &&
        query.certaintyFilter === null) ||
      loadingRef.current
    ) {
      return;
    }
    await updateQuery(
      {
        ...query,
        certaintyFilter: null,
        positionFilter: null,
        reviewCertainty: nextCertainty,
        reviewDifference: nextDifference,
        reviewOrder: nextOrder,
        reviewPosition: nextPosition,
        reviewStreet: nextStreet,
        solverFilter: null,
        streetFilter: null,
      },
      "Could not filter training reviews",
    );
  }

  async function updateLessonFilters(
    nextStreet: TrainingReviewStreet,
    nextSearch: string = lessonSearch,
    nextOrder: TrainingReviewOrder = query.lessonOrder,
  ) {
    const nextQueryText = nextSearch.trim();
    if (
      (nextOrder === query.lessonOrder &&
        nextStreet === query.lessonStreet &&
        nextQueryText === query.lessonQuery) ||
      loadingRef.current
    ) {
      return;
    }
    const nextQuery = {
      ...query,
      lessonOrder: nextOrder,
      lessonQuery: nextQueryText,
      lessonStreet: nextStreet,
    };
    await updateQuery(nextQuery, "Could not filter saved lessons", {
      ...nextQuery,
      lessonQuery: query.lessonQuery,
    });
  }

  async function focusReviewStreet(street: Street) {
    setView("review");
    await updateReviewQueue(query.reviewOrder, street, null, "all", null);
  }

  async function focusReviewCertainty(certainty: TrainingReviewCertainty) {
    setView("review");
    await updateReviewQueue(query.reviewOrder, "all", null, certainty, null);
  }

  async function focusActionDifference(difference: TrainingReviewDifference) {
    setView("review");
    await updateReviewQueue(query.reviewOrder, "all", difference, "all", null);
  }

  async function focusReviewPosition(position: TrainingPositionFilter) {
    setView("review");
    await updateReviewQueue(query.reviewOrder, "all", null, "all", position);
  }

  async function updateSolverFilter(filter: TrainingSolverFilter | null) {
    setView("recent");
    if (sameSolverFilter(filter, query.solverFilter) || loadingRef.current) {
      return;
    }
    await updateQuery(
      {
        ...query,
        certaintyFilter: null,
        positionFilter: null,
        solverFilter: filter,
        streetFilter: null,
      },
      "Could not load solver hands",
    );
  }

  async function updatePositionFilter(filter: TrainingPositionFilter | null) {
    setView("recent");
    if (
      sameTrainingPositionFilter(filter, query.positionFilter) ||
      loadingRef.current
    ) {
      return;
    }
    await updateQuery(
      {
        ...query,
        certaintyFilter: null,
        positionFilter: filter,
        solverFilter: null,
        streetFilter: null,
      },
      "Could not load position hands",
    );
  }

  async function updateStreetFilter(filter: TrainingStreetFilter | null) {
    setView("recent");
    if (filter?.street === query.streetFilter?.street || loadingRef.current) {
      return;
    }
    await updateQuery(
      {
        ...query,
        certaintyFilter: null,
        positionFilter: null,
        solverFilter: null,
        streetFilter: filter,
      },
      "Could not load street hands",
    );
  }

  async function updateCertaintyFilter(filter: TrainingCertaintyFilter | null) {
    setView("recent");
    if (
      filter?.certainty === query.certaintyFilter?.certainty ||
      loadingRef.current
    ) {
      return;
    }
    await updateQuery(
      {
        ...query,
        certaintyFilter: filter,
        positionFilter: null,
        solverFilter: null,
        streetFilter: null,
      },
      "Could not load certainty hands",
    );
  }

  function selectView(nextView: TrainingProgressView) {
    if (nextView === "recent") {
      if (query.solverFilter) void updateSolverFilter(null);
      else if (query.positionFilter) void updatePositionFilter(null);
      else if (query.streetFilter) void updateStreetFilter(null);
      else if (query.certaintyFilter) void updateCertaintyFilter(null);
      else setView("recent");
      return;
    }
    if (nextView === "review") {
      setView("review");
      if (
        query.solverFilter ||
        query.positionFilter ||
        query.streetFilter ||
        query.certaintyFilter
      ) {
        void updateReviewQueue(query.reviewOrder, query.reviewStreet);
      }
      return;
    }
    setView("lessons");
  }

  return {
    cancelLoads,
    certaintyFilter: query.certaintyFilter,
    focusActionDifference,
    focusReviewCertainty,
    focusReviewPosition,
    focusReviewStreet,
    lessonOrder: query.lessonOrder,
    lessonQuery: query.lessonQuery,
    lessonSearch,
    lessonStreet: query.lessonStreet,
    loadInitial,
    loading,
    positionFilter: query.positionFilter,
    progress,
    reviewCertainty: query.reviewCertainty,
    reviewDifference: query.reviewDifference,
    reviewOrder: query.reviewOrder,
    reviewPosition: query.reviewPosition,
    reviewStreet: query.reviewStreet,
    selectView,
    setLessonSearch,
    setProgress,
    setView,
    solverFilter: query.solverFilter,
    streetFilter: query.streetFilter,
    updateCertaintyFilter,
    updateLessonFilters,
    updatePositionFilter,
    updateReviewQueue,
    updateSolverFilter,
    updateStreetFilter,
    view,
  };
}
