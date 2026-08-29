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
  expectedMutation: JobMutationExpectation | null;
};

export type ProjectionMutationTarget = "failed" | "parsed" | "approved";

export type ProjectionMutationLease = MutationLeaseBase & {
  kind: "projection";
  baselineJobIds: string[];
  expectedRemovalJobIds: string[];
  benchmarkImportRequestId: string | null;
  benchmarkImportReceiptObserved: boolean;
  expectedUploads: Array<{
    requestId: string;
    target: ProjectionMutationTarget;
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
