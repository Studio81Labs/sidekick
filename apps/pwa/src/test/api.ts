import { vi } from "vitest";

export function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

export function resetApiMocks(): void {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
}
