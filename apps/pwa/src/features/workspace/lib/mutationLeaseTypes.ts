import type { RecommendationAction } from "../../../shared/types/recommendations";
import type { TrainingCertainty } from "../../../shared/types/training";

export type PersistedJobMutationScope = "processing" | "history";

export type MutationLeaseBase = {
  ownerId: string;
  expiresAt: number;
};

export type JobMutationExpectation =
  | {
      kind: "approval";
      approvedStateKey: string;
    }
  | {
      kind: "training-decision";
      action: RecommendationAction;
      sizing: number | null;
      certainty: TrainingCertainty | null;
    }
  | {
      kind: "training-review";
      reviewed: boolean;
      note: string | null;
    }
  | {
      kind: "benchmark-inclusion";
      included: boolean;
    }
  | {
      kind: "metadata";
      title: string | null;
      notes: string | null;
      tags: string[];
    };

export type JobMutationLease = MutationLeaseBase & {
  kind: "job";
  jobId: string;
  baselineUpdatedAt: string;
  expectsRemoval: boolean;
  expectedRecommendationRequestId: string | null;
  expectedMutation: JobMutationExpectation | null;
};

export type ProjectionMutationTarget =
  | "failed"
  | "parsed"
  | "approved"
  | "recommended";

export type ProjectionMutationLease = MutationLeaseBase & {
  kind: "projection";
  baselineJobIds: string[];
  expectedRemovalJobIds: string[];
  benchmarkImportRequestId: string | null;
  benchmarkImportReceiptObserved: boolean;
  expectedUploads: Array<{
    requestId: string;
    target: ProjectionMutationTarget;
    recommendationRequestId: string | null;
  }>;
};

export type ArchiveMutationLease = MutationLeaseBase & {
  kind: "archive";
  jobIds: string[];
  baselineUpdatedAt: Record<string, string>;
  confirmationJobIds: string[];
};

export type PersistedMutationLease =
  | JobMutationLease
  | ProjectionMutationLease
  | ArchiveMutationLease;
