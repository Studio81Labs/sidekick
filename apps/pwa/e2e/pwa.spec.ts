import { expect, test, type Page } from "@playwright/test";

const BACKEND_URL = "http://127.0.0.1:8010";
const VALID_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" +
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==",
  "base64",
);

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

  await context.setOffline(true);
  try {
    await page.goto("/offline-shell-proof");
    await expect(
      page.getByRole("region", { name: "Analyzer controls" }),
    ).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByText(/Offline — the shell/i)).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
});

test("keeps uploads and recommendations network-only and retryable", async ({
  context,
  page,
}) => {
  await openControlledApp(page);
  await page.getByRole("button", { name: "Automation On" }).click();
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
  await expect(
    page.getByRole("region", { name: "Analyzer controls" }),
  ).toBeVisible();
  await expectProcessingRecoverySettled(page);

  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await page.getByLabel("Choose screenshots").setInputFiles(file);
  const uploaded = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  const uploadedJob = (await uploaded).json() as Promise<{ id: string }>;
  await expect(
    page.getByRole("button", { name: "Approve state" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Approve state" }).click();
  const recommendationButton = page.getByRole("button", {
    name: "Request recommendation",
  });
  await expect(recommendationButton).toBeEnabled();

  await context.setOffline(true);
  try {
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await recommendationButton.click();
    await expect(page.getByText(/Failed to fetch/i).first()).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
  await expireUncertainProcessingRecovery(page);
  await page.goto(`/analyzer/jobs/${(await uploadedJob).id}`);

  await expectProcessingRecoverySettled(page);
  await expect(recommendationButton).toBeEnabled({ timeout: 10_000 });
  const recommended = page.waitForResponse(
    (response) =>
      response.url().endsWith("/recommend") &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await recommendationButton.click();
  await recommended;
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toBeVisible();
});

test("keeps a waiting update blocked while an upload is active", async ({
  page,
}) => {
  await openControlledApp(page);
  await installWaitingUpdate(page);
  await expect(
    page.getByRole("button", { name: "Reload update" }),
  ).toBeVisible();
  let releaseUpload: (() => void) | undefined;
  const uploadGate = new Promise<void>((resolve) => {
    releaseUpload = resolve;
  });
  await page.route(`${BACKEND_URL}/api/jobs`, async (route) => {
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
      response.url() === `${BACKEND_URL}/api/jobs` &&
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

test("preserves a dirty draft until discard is confirmed, then reloads once", async ({
  page,
}) => {
  await openControlledApp(page);
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

  await expect(page).toHaveURL(/\/analyzer$/);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByLabel("Choose screenshots")).toHaveValue("");
  expect(dialogs).toEqual(["confirm"]);
});
