import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { expect, test, type Page, type Request } from "@playwright/test";

const PLAYER_ORIGIN = "http://127.0.0.1:8765";
const WORKER_ORIGIN = "http://127.0.0.1:8787";
const WORKER_BACKEND_ORIGIN = "http://127.0.0.1:8788";
const LAUNCH_FILE = fileURLToPath(
  new URL("../.player-e2e-launch-url", import.meta.url),
);
const FLOP_FIXTURE = fileURLToPath(
  new URL(
    "../../backend/tests/fixtures/pokerstars/synthetic-flop.txt",
    import.meta.url,
  ),
);

interface ObservedRequest {
  hasAuthorization: boolean;
  hasCsrf: boolean;
  method: string;
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

function observeRequest(request: Request): ObservedRequest {
  const headers = request.headers();
  return {
    hasAuthorization: /^Bearer \S+$/.test(headers.authorization ?? ""),
    hasCsrf: Boolean(headers["x-poker-csrf-token"]),
    method: request.method(),
    url: request.url(),
  };
}

test("runs the authenticated player recovery flow only on loopback", async ({
  context,
  page,
}) => {
  const observedRequests: ObservedRequest[] = [];
  const restoreOriginPromises: Array<Promise<string | null>> = [];
  context.on("request", (request) => {
    observedRequests.push(observeRequest(request));
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/player/backups/restore"
    ) {
      restoreOriginPromises.push(request.headerValue("origin"));
    }
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
    body: { items: [], unreadable: [], next_cursor: null },
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

  await bindReplacedActionToRetainedSource(page);

  const onlineObservedRequests = [...observedRequests];
  const onlineRestoreOriginPromises = [...restoreOriginPromises];

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

  const httpRequests = onlineObservedRequests.filter(({ url }) =>
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
        ({ hasCsrf, url }) =>
          new URL(url).pathname === "/api/player/backups/restore" && hasCsrf,
      ),
  ).toBe(true);
  expect(await Promise.all(onlineRestoreOriginPromises)).toContain(
    PLAYER_ORIGIN,
  );
});

async function bindReplacedActionToRetainedSource(page: Page): Promise<void> {
  const source = await readFile(FLOP_FIXTURE);
  await page.getByLabel("PokerStars hand-history files").setInputFiles({
    name: "synthetic-flop.txt",
    mimeType: "text/plain",
    buffer: source,
  });
  await page.getByRole("button", { name: "Import for review" }).click();
  await expect(
    page.getByText("Import finished with reviewable outcomes."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Load hand records" }).click();
  await page.getByRole("button", { name: "View audit detail" }).click();
  await expect(
    page.getByRole("heading", { name: "Review and approve canonical state" }),
  ).toBeVisible();

  const detail = await page.evaluate(async () => {
    const session = sessionStorage.getItem("poker-hero-player-session-v1");
    const records = await fetch("/api/player/hands?limit=25", {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session}` },
    });
    const record = (await records.json()).items[0];
    const response = await fetch(`/api/player/hands/${record.record_key}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session}` },
    });
    return response.json();
  });
  const originalActions = detail.detections[0].state.streets[0].actions;
  const replacedAction = originalActions.at(-1);
  expect(replacedAction.action_type).toBe("check");

  const preflop = page
    .locator("article.review-list-item")
    .filter({ has: page.getByRole("heading", { name: "preflop" }) });
  await preflop.getByRole("button", { name: "Remove action" }).last().click();
  await page
    .getByRole("textbox", { name: "Correction reason" })
    .fill("Removed an erroneously recorded checked action.");
  await page.getByRole("button", { name: "Preview changes" }).click();
  await expect(
    page.getByText(
      /The current draft needs correction before it can be approved/,
    ),
  ).toBeVisible();

  await preflop.getByRole("button", { name: "Add action" }).click();
  const addedAction = preflop
    .getByRole("heading", { name: `Action ${originalActions.length}` })
    .locator("..");
  await addedAction
    .getByRole("combobox", { name: "Actor" })
    .selectOption(replacedAction.actor_id);
  await addedAction
    .getByRole("combobox", { name: "Action type" })
    .selectOption(replacedAction.action_type);
  if (replacedAction.amount !== null) {
    await addedAction
      .getByRole("textbox", { name: "Amount" })
      .fill(replacedAction.amount);
  }
  if (replacedAction.total_committed !== null) {
    await addedAction
      .getByRole("textbox", { name: "Total committed" })
      .fill(replacedAction.total_committed);
  }

  await expect(page.getByText("Flop Rival: checks")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Open retained source lines" })
    .click();
  const returnedLine = page
    .locator(".review-source-line-list li")
    .filter({ hasText: "Flop Rival: checks" })
    .first();
  await expect(returnedLine).toBeVisible();
  await returnedLine
    .getByRole("button", { name: /Use source line \d+ for a correction/ })
    .click();
  await expect(
    returnedLine.getByRole("button", {
      name: /selected for review binding/,
    }),
  ).toBeDisabled();

  const binding = addedAction.getByRole("combobox", {
    name: "Bind retained source evidence",
  });
  const sourceLineValue = await binding
    .locator("option")
    .filter({ hasText: "review-source-line/v1" })
    .getAttribute("value");
  expect(sourceLineValue).not.toBeNull();
  await binding.selectOption(sourceLineValue!);
  await page
    .getByRole("textbox", { name: "Correction reason" })
    .fill("Re-added the checked action from the retained source line.");

  await page.getByRole("button", { name: "Preview changes" }).click();
  await expect(page.getByText(/This current draft is valid/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Approve canonical state" }).click();
  await expect(page.getByText(/Canonical revision 1 approved/)).toBeVisible();

  const approved = await page.evaluate(async () => {
    const session = sessionStorage.getItem("poker-hero-player-session-v1");
    const records = await fetch("/api/player/hands?limit=25", {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session}` },
    });
    const record = (await records.json()).items[0];
    const response = await fetch(`/api/player/hands/${record.record_key}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session}` },
    });
    return response.json();
  });
  const approvedActions =
    approved.canonical_revisions[0].state.streets[0].actions;
  expect(approvedActions).toHaveLength(originalActions.length);
  expect(approvedActions.at(-1).evidence[0]).toMatchObject({
    marker: "review-source-line/v1",
  });
}

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
