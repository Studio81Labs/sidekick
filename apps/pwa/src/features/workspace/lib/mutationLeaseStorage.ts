import { decodePersistedMutationLease } from "./mutationLeaseCodec";
import type {
  PersistedJobMutationScope,
  PersistedMutationLease,
} from "./mutationLeaseTypes";

export const HISTORY_MUTATION_LEASE_KEY = "poker-training-history-mutation-v1";
export const PROCESSING_MUTATION_LEASE_KEY =
  "poker-training-processing-mutation-v1";
export const PERSISTED_MUTATION_LEASE_MS = 30 * 1000;

export function mutationLeaseStorageKey(
  scope: PersistedJobMutationScope,
): string {
  return scope === "processing"
    ? PROCESSING_MUTATION_LEASE_KEY
    : HISTORY_MUTATION_LEASE_KEY;
}

function removePersistedMutationLease(scope: PersistedJobMutationScope): void {
  window.sessionStorage.removeItem(mutationLeaseStorageKey(scope));
}

export function readPersistedMutationLease(
  scope: PersistedJobMutationScope,
): PersistedMutationLease | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(mutationLeaseStorageKey(scope));
    if (raw === null) {
      return null;
    }
    const lease = decodePersistedMutationLease(JSON.parse(raw), scope);
    if (lease === null) {
      removePersistedMutationLease(scope);
    }
    return lease;
  } catch {
    try {
      removePersistedMutationLease(scope);
    } catch {
      // An unavailable session store is equivalent to having no durable lease.
    }
    return null;
  }
}

export function writePersistedMutationLease(
  scope: PersistedJobMutationScope,
  lease: PersistedMutationLease,
): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    window.sessionStorage.setItem(
      mutationLeaseStorageKey(scope),
      JSON.stringify(lease),
    );
    return true;
  } catch {
    return false;
  }
}

export function replacePersistedMutationLease(
  scope: PersistedJobMutationScope,
  expectedLease: PersistedMutationLease,
  nextLease: PersistedMutationLease,
): boolean {
  const storedLease = readPersistedMutationLease(scope);
  if (
    storedLease === null ||
    storedLease.ownerId !== expectedLease.ownerId ||
    storedLease.kind !== expectedLease.kind ||
    storedLease.expiresAt !== expectedLease.expiresAt
  ) {
    return false;
  }
  return writePersistedMutationLease(scope, nextLease);
}

export function claimPersistedMutationLease(
  scope: PersistedJobMutationScope,
  ownerId: string,
): PersistedMutationLease | null {
  const lease = readPersistedMutationLease(scope);
  if (lease === null) {
    return null;
  }
  const claimedLease = { ...lease, ownerId };
  return writePersistedMutationLease(scope, claimedLease) ? claimedLease : null;
}

export function clearPersistedMutationLease(
  scope: PersistedJobMutationScope,
  ownerId: string,
): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (readPersistedMutationLease(scope)?.ownerId === ownerId) {
      removePersistedMutationLease(scope);
    }
  } catch {
    // An unavailable session store already forces authoritative reloads.
  }
}
