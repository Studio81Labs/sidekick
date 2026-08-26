import { afterEach, describe, expect, it, vi } from "vitest";

import { networkFirstNavigation } from "./serviceWorkerRuntime";

const REQUEST = new Request("https://poker.example/analyzer");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("service-worker navigation runtime", () => {
  it("returns online HTML without replacing the install-time shell", async () => {
    const deployedHtml = new Response("next deployment");
    const fetchRequest = vi.fn().mockResolvedValue(deployedHtml);
    const cacheStorage = {
      open: vi.fn(),
    } as unknown as CacheStorage;
    vi.stubGlobal("fetch", fetchRequest);
    vi.stubGlobal("caches", cacheStorage);

    await expect(
      networkFirstNavigation(REQUEST, "poker-hero-shell-current"),
    ).resolves.toBe(deployedHtml);
    expect(cacheStorage.open).not.toHaveBeenCalled();
  });

  it("falls back only to the current worker's install-time shell", async () => {
    const installedHtml = new Response("current deployment");
    const cache = { match: vi.fn().mockResolvedValue(installedHtml) };
    const cacheStorage = {
      open: vi.fn().mockResolvedValue(cache),
    } as unknown as CacheStorage;
    const fetchRequest = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchRequest);
    vi.stubGlobal("caches", cacheStorage);

    await expect(
      networkFirstNavigation(REQUEST, "poker-hero-shell-current"),
    ).resolves.toBe(installedHtml);
    expect(cacheStorage.open).toHaveBeenCalledWith("poker-hero-shell-current");
    expect(cache.match).toHaveBeenCalledWith("/");
  });

  it("preserves the network error when no owned shell exists", async () => {
    const networkError = new TypeError("offline");
    const cacheStorage = {
      open: vi
        .fn()
        .mockResolvedValue({ match: vi.fn().mockResolvedValue(null) }),
    } as unknown as CacheStorage;
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(networkError));
    vi.stubGlobal("caches", cacheStorage);

    await expect(
      networkFirstNavigation(REQUEST, "poker-hero-shell-current"),
    ).rejects.toBe(networkError);
  });
});
