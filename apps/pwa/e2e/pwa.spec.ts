import { expect, test, type Page } from "@playwright/test";

const BACKEND_URL = "http://127.0.0.1:8010";
const ADMINISTRATOR_TOKEN = "e2e-administrative-ocr-test-token-0123456789";
const ADMINISTRATOR_HEADERS = {
  Authorization: `Bearer ${ADMINISTRATOR_TOKEN}`,
};
const VALID_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" +
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==",
  "base64",
);

// The specs do not share modules today, so the administrative helpers are
// duplicated from `analyzer.spec.ts`.
async function unlockAdministrativeAccess(page: Page): Promise<void> {
  const banner = page.getByRole("note", {
    name: "Administrative OCR test mode",
  });
  if (await banner.isVisible()) {
    return;
  }
  const dialog = page.getByRole("dialog", { name: "Administrator tools" });
  await dialog
    .getByLabel("Administrative OCR test token")
    .fill(ADMINISTRATOR_TOKEN);
  await dialog.getByRole("button", { name: "Unlock" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(banner).toBeVisible();
}

async function expectOperatorWorkspace(page: Page): Promise<void> {
  await unlockAdministrativeAccess(page);
  await expect(
    page.getByRole("region", { name: "Administrator OCR controls" }),
  ).toBeVisible();
}

async function openControlledApp(page: Page): Promise<string> {
  await page.goto("/");
  return page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      await new Promise<void>((resolve) => {
        navigator.serviceWorker.addEventListener(
          "controllerchange",
          () => resolve(),
          { once: true },
        );
      });
    }
    return registration.scope;
  });
}

async function installWaitingUpdate(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.register(
      "/sw-e2e-update.js",
      { scope: "/", updateViaCache: "none" },
    );
    if (registration.waiting) return;

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error("E2E update worker did not enter waiting")),
        10_000,
      );
      const inspect = () => {
        if (!registration.waiting) return;
        window.clearTimeout(timeout);
        resolve();
      };
      registration.addEventListener("updatefound", () => {
        registration.installing?.addEventListener("statechange", inspect);
        inspect();
      });
      registration.installing?.addEventListener("statechange", inspect);
      inspect();
    });
    window.dispatchEvent(new Event("focus"));
  });
}

async function expireUncertainProcessingRecovery(page: Page): Promise<void> {
  await page.evaluate(() => {
    const key = "poker-training-processing-mutation-v1";
    const value = sessionStorage.getItem(key);
    if (value === null) throw new Error("Expected a processing recovery lease");
    const lease = JSON.parse(value) as { expiresAt: number };
    lease.expiresAt = Date.now() - 1;
    sessionStorage.setItem(key, JSON.stringify(lease));
  });
}

async function expectProcessingRecoverySettled(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() =>
        sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    )
    .toBeNull();
}

test("is installable with root-scoped metadata and correctly sized icons", async ({
  page,
}) => {
  const scope = await openControlledApp(page);
  const metadata = await page.evaluate(async () => {
    const manifest = (await fetch("/manifest.webmanifest").then((response) =>
      response.json(),
    )) as {
      display: string;
      icons: Array<{ purpose: string; sizes: string; src: string }>;
      id: string;
      scope: string;
      start_url: string;
    };
    const icons = await Promise.all(
      manifest.icons.map(
        (icon) =>
          new Promise<{ height: number; src: string; width: number }>(
            (resolve, reject) => {
              const image = new Image();
              image.onload = () =>
                resolve({
                  height: image.naturalHeight,
                  src: icon.src,
                  width: image.naturalWidth,
                });
              image.onerror = () =>
                reject(new Error(`Could not load ${icon.src}`));
              image.src = icon.src;
            },
          ),
      ),
    );
    return { icons, manifest };
  });

  expect(scope).toBe("http://127.0.0.1:4174/");
  expect(metadata.manifest).toMatchObject({
    display: "standalone",
    id: "/",
    scope: "/",
    start_url: "/",
  });
  expect(new Set(metadata.manifest.icons.map((icon) => icon.purpose))).toEqual(
    new Set(["any", "maskable"]),
  );
  for (const icon of metadata.icons) {
    const declared = metadata.manifest.icons.find(
      (candidate) => candidate.src === icon.src,
    );
    const size = Number.parseInt(declared?.sizes ?? "0", 10);
    expect([icon.width, icon.height]).toEqual([size, size]);
  }
});

test("opens the cached shell offline without caching private routes", async ({
  context,
  page,
}) => {
  await openControlledApp(page);
  const cachedPaths = await page.evaluate(async () => {
    await fetch("/api/health").catch(() => undefined);
    await fetch("/mcp", { method: "POST" }).catch(() => undefined);
    const paths: string[] = [];
    for (const cacheName of await caches.keys()) {
      for (const request of await (await caches.open(cacheName)).keys()) {
        paths.push(new URL(request.url).pathname);
      }
    }
    return paths.sort();
  });

  expect(cachedPaths).toContain("/");
  expect(
    cachedPaths.some((path) => path === "/api" || path.startsWith("/api/")),
  ).toBe(false);
  expect(cachedPaths).not.toContain("/mcp");
  expect(
    cachedPaths.every(
      (path) =>
        path === "/" || /^\/assets\/.+-[A-Za-z0-9_-]{8,}\.[^/]+$/.test(path),
    ),
  ).toBe(true);

  // A direct navigation to a successful non-HTML resource must never replace
  // the cached document shell stored under `/`.
  await page.goto("/manifest.webmanifest");

  // Put a foreign root response ahead of the recreated Poker Hero cache. The
  // service worker must match only within its own versioned cache.
  await page.evaluate(async () => {
    const ownedCacheName = (await caches.keys()).find((name) =>
      name.startsWith("poker-hero-shell-"),
    );
    if (!ownedCacheName) throw new Error("Poker Hero cache was not installed");
    const ownedCache = await caches.open(ownedCacheName);
    const ownedEntries = await Promise.all(
      (await ownedCache.keys()).map(async (request) => {
        const response = await ownedCache.match(request);
        if (!response) throw new Error(`Missing ${request.url} cache entry`);
        return [request, response] as const;
      }),
    );
    await caches.delete(ownedCacheName);
    const foreignCache = await caches.open("foreign-origin-cache");
    await foreignCache.put(
      "/",
      new Response("foreign cache response", {
        headers: { "content-type": "text/html" },
      }),
    );
    const recreatedOwnedCache = await caches.open(ownedCacheName);
    await Promise.all(
      ownedEntries.map(([request, response]) =>
        recreatedOwnedCache.put(request, response),
      ),
    );
  });

  await context.setOffline(true);
  try {
    await page.goto("/admin/ocr");
    await expect(
      page.getByRole("dialog", { name: "Administrator tools" }),
    ).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByText(/Offline — the shell/i)).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
});

test("announces an origin outage while the browser link remains online", async ({
  page,
}) => {
  await openControlledApp(page);
  await expect(page.getByText(/Offline — the shell/i)).toHaveCount(0);
  expect(await page.evaluate(() => navigator.onLine)).toBe(true);

  await page.route("**/manifest.webmanifest", (route) => route.abort("failed"));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));

  await expect(page.getByText(/Offline — the shell/i)).toBeVisible();
  expect(await page.evaluate(() => navigator.onLine)).toBe(true);

  await page.unroute("**/manifest.webmanifest");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText(/Offline — the shell/i)).toHaveCount(0);
});

test("keeps uploads network-only and retryable", async ({ context, page }) => {
  await openControlledApp(page);
  await unlockAdministrativeAccess(page);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  const file = {
    name: "offline-retry.png",
    mimeType: "image/png",
    buffer: VALID_PNG,
  };
  await page.getByLabel("Choose screenshots").setInputFiles(file);

  await context.setOffline(true);
  try {
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByRole("button", { name: "Upload and parse" }).click();
    await expect(page.getByText(/Failed to fetch/i).first()).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
  await expireUncertainProcessingRecovery(page);
  await page.reload();
  await expectOperatorWorkspace(page);
  await expectProcessingRecoverySettled(page);

  await unlockAdministrativeAccess(page);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await page.getByLabel("Choose screenshots").setInputFiles(file);
  const uploaded = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/admin/ocr/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  const uploadedJob = (await (await uploaded).json()) as { id: string };
  await page.goto(`/admin/ocr/jobs/${uploadedJob.id}`);
  await expectOperatorWorkspace(page);
  await expect(
    page.getByRole("button", { name: "Approve state" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect
    .poll(async () => {
      const response = await page.request.get(
        `${BACKEND_URL}/api/admin/ocr/jobs/${uploadedJob.id}`,
        { headers: ADMINISTRATOR_HEADERS },
      );
      if (!response.ok()) {
        return null;
      }
      const job = (await response.json()) as { status: string };
      return job.status;
    })
    .toBe("approved");
});

test("keeps a waiting update blocked while an upload is active", async ({
  page,
}) => {
  await openControlledApp(page);
  await unlockAdministrativeAccess(page);
  await installWaitingUpdate(page);
  await expect(
    page.getByRole("button", { name: "Reload update" }),
  ).toBeVisible();
  let releaseUpload: (() => void) | undefined;
  const uploadGate = new Promise<void>((resolve) => {
    releaseUpload = resolve;
  });
  await page.route(`${BACKEND_URL}/api/admin/ocr/jobs`, async (route) => {
    if (route.request().method() === "POST") await uploadGate;
    await route.continue();
  });

  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await page.getByLabel("Choose screenshots").setInputFiles({
    name: "busy-update.png",
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  const uploaded = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/admin/ocr/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  await expect(
    page.getByRole("dialog", { name: "Processing queue" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Upload and parse" }),
  ).toBeDisabled();

  await expect(page.getByText(/wait for active work to finish/i)).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /^(Discard and reload|Reload update)$/,
    }),
  ).toHaveCount(0);

  releaseUpload?.();
  await uploaded;
  await expect(
    page.getByRole("button", { name: "Reload update" }),
  ).toBeVisible();
});

test("requires fresh confirmation when a draft changes during activation", async ({
  page,
}) => {
  await openControlledApp(page);
  await unlockAdministrativeAccess(page);
  const filename = "dirty-update.png";
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  const fileInput = page.getByLabel("Choose screenshots");
  await fileInput.setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  await expect(fileInput).toHaveValue(new RegExp(`${filename}$`));

  await installWaitingUpdate(page);
  await expect(
    page.getByText(/Save your drafts or explicitly discard/i),
  ).toBeVisible();
  await expect(fileInput).toHaveValue(new RegExp(`${filename}$`));

  const dialogs: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.type());
    await dialog.accept();
  });
  await page.getByRole("button", { name: "Discard and reload" }).click();

  const newerFilename = "new-dirty-update.png";
  await fileInput.setInputFiles({
    name: newerFilename,
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  await expect(page.getByText(/Poker Hero has updated/i)).toBeVisible();
  await expect(fileInput).toHaveValue(new RegExp(`${newerFilename}$`));
  expect(dialogs).toEqual(["confirm"]);

  await page.getByRole("button", { name: "Discard and reload" }).click();

  await expect(page).toHaveURL(/\/admin\/ocr$/);
  await unlockAdministrativeAccess(page);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByLabel("Choose screenshots")).toHaveValue("");
  expect(dialogs).toEqual(["confirm", "confirm"]);
});
