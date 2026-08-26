import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { usePipelineSelection } from "./usePipelineSelection";

afterEach(resetApiMocks);

function wrapper({ children }: { children: ReactNode }) {
  return <AppProviders>{children}</AppProviders>;
}

const capabilities = {
  defaults: {
    parser_layout_profile: "fortuna_nations",
    parser_provider: "ocr_cv",
    recommendation_engine: "postflop_solver",
    recommendation_provider: "local_solver",
  },
  parser_layout_compatibility: { ocr_cv: ["fortuna_nations"] },
  parser_layout_profiles: [
    {
      available: true,
      id: "fortuna_nations",
      label: "Fortuna Nations",
      unavailable_reason: null,
    },
  ],
  parser_providers: [
    {
      available: true,
      id: "ocr_cv",
      label: "OCR CV",
      unavailable_reason: null,
    },
  ],
  recommendation_engines: [
    {
      available: true,
      id: "postflop_solver",
      label: "Postflop solver",
      unavailable_reason: null,
    },
  ],
  recommendation_providers: [
    {
      available: true,
      id: "local_solver",
      label: "Local solver",
      unavailable_reason: null,
    },
  ],
};

describe("usePipelineSelection", () => {
  it("loads capabilities through Query and keeps only the editable selection locally", async () => {
    const onError = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(capabilities));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => usePipelineSelection({ onError }), {
      wrapper,
    });

    act(() => result.current.openDialog());

    await waitFor(() =>
      expect(result.current.selection).toEqual(capabilities.defaults),
    );
    expect(result.current.capabilities).toEqual(capabilities);
    expect(onError).not.toHaveBeenCalled();

    act(() => result.current.updateSelection("recommendation_engine", null));
    expect(result.current.selection?.recommendation_engine).toBeNull();

    await result.current.loadCapabilities();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports a human-readable error and lets a later load retry", async () => {
    const onError = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ missing_fields: ["opponent_wager"] }), {
          headers: { "Content-Type": "application/json" },
          status: 422,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(capabilities));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => usePipelineSelection({ onError }), {
      wrapper,
    });

    await expect(result.current.loadCapabilities()).resolves.toBeNull();
    expect(onError).toHaveBeenCalledWith(
      "Complete the required table details before requesting a recommendation: Opponent wager total. Edit the listed fields, then approve the state again.",
    );

    await expect(result.current.loadCapabilities()).resolves.toEqual(
      capabilities,
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("deduplicates concurrent capability loads through the shared Query cache", async () => {
    const onError = vi.fn();
    let resolveResponse: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(
      () =>
        [
          usePipelineSelection({ onError }),
          usePipelineSelection({ onError }),
        ] as const,
      { wrapper },
    );

    let firstLoad: Promise<unknown> | undefined;
    let secondLoad: Promise<unknown> | undefined;
    await act(async () => {
      firstLoad = result.current[0].loadCapabilities();
      secondLoad = result.current[1].loadCapabilities();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveResponse?.(jsonResponse(capabilities));
    await expect(firstLoad).resolves.toEqual(capabilities);
    await expect(secondLoad).resolves.toEqual(capabilities);
    expect(onError).not.toHaveBeenCalled();
  });
});
