import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isExpectedPrecacheResponse,
  isHtmlResponse,
  networkFirstNavigation,
  precacheVersion,
} from "./serviceWorkerRuntime";

const REQUEST = new Request("https://poker.example/analyzer");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("service-worker precache response policy", () => {
  it("requires HTML for the shell and rejects HTML for hashed assets", () => {
    const html = new Response("<main>Poker Hero</main>", {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
    const javascript = new Response("export {};", {
      headers: { "content-type": "text/javascript" },
    });

    expect(isHtmlResponse(html)).toBe(true);
    expect(isExpectedPrecacheResponse("/", html)).toBe(true);
    expect(isExpectedPrecacheResponse("/assets/app-A1b2C3d4.js", html)).toBe(
      false,
    );
    expect(
      isExpectedPrecacheResponse("/assets/app-A1b2C3d4.js", javascript),
    ).toBe(true);
  });

  it("rejects unsuccessful or redirected precache responses", () => {
    const missing = new Response("missing", {
      status: 404,
      headers: { "content-type": "text/javascript" },
    });
    const redirected = new Response("export {};", {
      headers: { "content-type": "text/javascript" },
    });
    Object.defineProperty(redirected, "redirected", { value: true });

    expect(isExpectedPrecacheResponse("/assets/app-A1b2C3d4.js", missing)).toBe(
      false,
    );
    expect(
      isExpectedPrecacheResponse("/assets/app-A1b2C3d4.js", redirected),
    ).toBe(false);
  });

  it("writes only a completely validated shell version", async () => {
    const html = new Response("<main>Poker Hero</main>", {
      headers: { "content-type": "text/html" },
    });
    const javascript = new Response("export {};", {
      headers: { "content-type": "text/javascript" },
    });
    const fetchRequest = vi
      .fn()
      .mockResolvedValueOnce(html)
      .mockResolvedValueOnce(javascript);
    const cache = { put: vi.fn().mockResolvedValue(undefined) };
    const cacheStorage = {
      delete: vi.fn(),
      open: vi.fn().mockResolvedValue(cache),
    } as unknown as CacheStorage;
    vi.stubGlobal("fetch", fetchRequest);
    vi.stubGlobal("caches", cacheStorage);

    await precacheVersion("poker-hero-shell-current", [
      "/",
      "/assets/app-A1b2C3d4.js",
    ]);

    expect(fetchRequest).toHaveBeenNthCalledWith(1, "/", { cache: "reload" });
    expect(fetchRequest).toHaveBeenNthCalledWith(2, "/assets/app-A1b2C3d4.js", {
      cache: "reload",
    });
    expect(cache.put).toHaveBeenCalledTimes(2);
    expect(cacheStorage.delete).not.toHaveBeenCalled();
  });

  it("rejects an HTML SPA fallback and removes the failed version cache", async () => {
    const html = new Response("<main>Poker Hero</main>", {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
    const cacheStorage = {
      delete: vi.fn().mockResolvedValue(true),
      open: vi.fn(),
    } as unknown as CacheStorage;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(html));
    vi.stubGlobal("caches", cacheStorage);

    await expect(
      precacheVersion("poker-hero-shell-failed", [
        "/",
        "/assets/missing-A1b2C3d4.js",
      ]),
    ).rejects.toThrow(
      "Invalid precache response for /assets/missing-A1b2C3d4.js",
    );

    expect(cacheStorage.open).not.toHaveBeenCalled();
    expect(cacheStorage.delete).toHaveBeenCalledWith("poker-hero-shell-failed");
  });
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
