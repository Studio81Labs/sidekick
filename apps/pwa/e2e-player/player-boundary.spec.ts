import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { expect, test, type Request } from "@playwright/test";

const PLAYER_ORIGIN = "http://127.0.0.1:8765";
const WORKER_ORIGIN = "http://127.0.0.1:8787";
const WORKER_BACKEND_ORIGIN = "http://127.0.0.1:8788";
const LAUNCH_FILE = fileURLToPath(
  new URL("../.player-e2e-launch-url", import.meta.url),
);

interface ObservedRequest {
  hasAuthorization: boolean;
  hasCsrf: boolean;
  method: string;
  origin: string | undefined;
  url: string;
}

async function readLaunchUrl(): Promise<string> {
  await expect
    .poll(
      async () => {
        try {
          return (await readFile(LAUNCH_FILE, "utf8")).trim();
        } catch {
          return "";
        }
      },
      { timeout: 10_000 },
    )
    .toMatch(/^http:\/\/127\.0\.0\.1:8765\/#ticket=[A-Za-z0-9_-]+$/);
  expect((await stat(LAUNCH_FILE)).mode & 0o777).toBe(0o600);
  return (await readFile(LAUNCH_FILE, "utf8")).trim();
}

async function observeRequest(request: Request): Promise<ObservedRequest> {
  const headers = await request.allHeaders();
  return {
    hasAuthorization: /^Bearer \S+$/.test(headers.authorization ?? ""),
    hasCsrf: Boolean(headers["x-poker-csrf-token"]),
    method: request.method(),
    origin: headers.origin,
    url: request.url(),
  };
}

test("runs the authenticated player recovery flow only on loopback", async ({
  context,
  page,
}) => {
  const observedRequestPromises: Array<Promise<ObservedRequest>> = [];
  context.on("request", (request) => {
    observedRequestPromises.push(observeRequest(request));
  });

  const launchUrl = await readLaunchUrl();
  await page.goto(launchUrl);
  await expect(page.getByText("Ready on this machine")).toBeVisible();
  expect(new URL(page.url()).origin).toBe(PLAYER_ORIGIN);
  expect(new URL(page.url()).hash).toBe("");

  const launchTicket = new URLSearchParams(
    new URL(launchUrl).hash.slice(1),
  ).get("ticket");
  expect(launchTicket).not.toBeNull();
  const replayResponse = await page.evaluate(async (ticket) => {
    const response = await fetch("/api/player/session", {
      method: "POST",
      cache: "no-store",
      headers: { Authorization: `Bearer ${ticket}` },
    });
    return {
      cacheControl: response.headers.get("cache-control"),
      status: response.status,
    };
  }, launchTicket!);
  expect(replayResponse).toEqual({ cacheControl: "no-store", status: 401 });

  const handListResponse = await page.evaluate(async () => {
    const session = sessionStorage.getItem("poker-hero-player-session-v1");
    const response = await fetch("/api/player/hands?limit=1", {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session}` },
    });
    return {
      body: await response.json(),
      cacheControl: response.headers.get("cache-control"),
      status: response.status,
    };
  });
  expect(handListResponse).toEqual({
    body: { items: [], next_cursor: null },
    cacheControl: "no-store",
    status: 200,
  });

  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (navigator.serviceWorker.controller) return;
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error("Player service worker did not take control")),
        10_000,
      );
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => {
          window.clearTimeout(timeout);
          resolve();
        },
        { once: true },
      );
    });
  });

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download backup" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^poker-hero-player-backup-\d{8}T\d{6}Z\.zip$/,
  );
  const backupPath = await download.path();
  expect(backupPath).not.toBeNull();

  await page.getByLabel("Player backup ZIP").setInputFiles(backupPath!);
  await page.getByRole("button", { name: "Restore backup" }).click();
  await expect(page.getByText("Restore committed.")).toBeVisible();

  const cacheEntries = await page.evaluate(async () => {
    const entries: Array<{ cacheName: string; path: string }> = [];
    for (const cacheName of await caches.keys()) {
      const cache = await caches.open(cacheName);
      for (const request of await cache.keys()) {
        entries.push({ cacheName, path: new URL(request.url).pathname });
      }
    }
    return entries;
  });
  expect(cacheEntries.length).toBeGreaterThan(1);
  expect(
    cacheEntries.every(
      ({ cacheName, path }) =>
        cacheName.startsWith("poker-hero-player-shell-") &&
        (path === "/" || /^\/assets\/.+-[A-Za-z0-9_-]{8,}\.[^/]+$/.test(path)),
    ),
  ).toBe(true);
  expect(
    cacheEntries.some(({ path }) => {
      let candidate = path;
      for (let depth = 0; depth < 8; depth += 1) {
        if (candidate === "/api" || candidate.startsWith("/api/")) return true;
        if (!candidate.includes("%")) return false;
        try {
          candidate = decodeURIComponent(candidate);
        } catch {
          return true;
        }
      }
      return candidate.includes("%");
    }),
  ).toBe(false);

  const onlineObservedRequestPromises = [...observedRequestPromises];

  await context.setOffline(true);
  try {
    expect(
      await page.evaluate(async () => {
        try {
          await fetch("/api/player/hands?limit=1", { cache: "no-store" });
          return "resolved";
        } catch {
          return "rejected";
        }
      }),
    ).toBe("rejected");
  } finally {
    await context.setOffline(false);
  }

  const observedRequests = await Promise.all(onlineObservedRequestPromises);
  const httpRequests = observedRequests.filter(({ url }) =>
    /^https?:/.test(url),
  );
  expect(httpRequests.length).toBeGreaterThan(0);
  expect(
    httpRequests.every(({ url }) => new URL(url).origin === PLAYER_ORIGIN),
  ).toBe(true);

  const playerApiRequests = httpRequests.filter(({ url }) =>
    new URL(url).pathname.startsWith("/api/player/"),
  );
  expect(playerApiRequests.length).toBeGreaterThanOrEqual(5);
  expect(
    playerApiRequests.every(({ hasAuthorization }) => hasAuthorization),
  ).toBe(true);
  expect(
    playerApiRequests
      .filter(({ method }) => method === "POST")
      .some(
        ({ hasCsrf, origin, url }) =>
          new URL(url).pathname === "/api/player/backups/restore" &&
          hasCsrf &&
          origin === PLAYER_ORIGIN,
      ),
  ).toBe(true);
});

test("the hosted Worker denies direct and encoded player paths before proxying", async ({
  request,
}) => {
  const sentinel = "player-private-body-must-not-reach-hosted-backend";
  const paths = [
    "/api/player/imports",
    "/api%2Fplayer%2Fimports",
    "/%61pi/%70layer/imports",
    "/%2561pi%252Fplayer%252Fimports",
  ];

  for (const path of paths) {
    const response = await request.post(`${WORKER_ORIGIN}${path}`, {
      data: sentinel,
      headers: { "Content-Type": "text/plain" },
    });
    expect(response.status(), path).toBe(404);
    expect(response.headers()["cache-control"], path).toBe("no-store");
    expect(await response.json(), path).toEqual({ detail: "Not Found" });
  }

  for (const path of [
    "/api/player/hands",
    "/api%2Fplayer%2Fhands",
    "/%61pi/%70layer/hands",
    "/%2561pi%252Fplayer%252Fhands",
  ]) {
    const response = await request.get(`${WORKER_ORIGIN}${path}`);
    expect(response.status(), path).toBe(404);
    expect(response.headers()["cache-control"], path).toBe("no-store");
    expect(await response.json(), path).toEqual({ detail: "Not Found" });
  }

  const recordingResponse = await request.get(
    `${WORKER_BACKEND_ORIGIN}/__recording`,
  );
  expect(recordingResponse.status()).toBe(200);
  expect(await recordingResponse.json()).toEqual({ requests: [] });
});
