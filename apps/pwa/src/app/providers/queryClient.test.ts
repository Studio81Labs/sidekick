import { describe, expect, it } from "vitest";

import { createQueryClient, queryClientDefaults } from "./queryClient";

describe("createQueryClient", () => {
  it("uses conservative defaults for dynamic server reads", () => {
    const client = createQueryClient();
    const options = client.getDefaultOptions();

    expect(options).toEqual(queryClientDefaults);
    expect(options.queries?.retry).toBe(1);
    expect(options.queries?.refetchOnReconnect).toBe(true);
    expect(options.queries?.refetchOnWindowFocus).toBe(true);
    expect(options.queries?.staleTime).toBe(30_000);
  });
});
