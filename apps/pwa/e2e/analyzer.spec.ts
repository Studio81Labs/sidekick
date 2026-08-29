import { readFile } from "node:fs/promises";

import {
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";

const VALID_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" +
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==",
  "base64",
);
const BACKEND_URL = "http://127.0.0.1:8010";
const PROVIDER_URL = "http://127.0.0.1:8011";
const ADMINISTRATOR_TOKEN = "e2e-administrative-ocr-test-token-0123456789";
const ADMINISTRATOR_HEADERS = {
  Authorization: `Bearer ${ADMINISTRATOR_TOKEN}`,
};
const IMPORT_FIRST_NOTICE =
  "Screenshot upload and live capture are administrator-only parser test tools";
const CONSOLE_SUBTITLE =
  "Administrator OCR test console for Texas Hold'em screenshots";
const ADMINISTRATIVE_BANNER_NOTICE =
  "Uploads and captures produce administrative OCR test data, not player analysis.";

async function unlockAdministrativeAccess(page: Page): Promise<void> {
  const banner = page.getByRole("note", {
    name: "Administrative OCR test mode",
  });
  if (await banner.isVisible()) {
    return;
  }
  await page.getByRole("button", { name: "Administrator tools" }).click();
  const dialog = page.getByRole("dialog", { name: "Administrator tools" });
  await dialog
    .getByLabel("Administrative OCR test token")
    .fill(ADMINISTRATOR_TOKEN);
  await dialog.getByRole("button", { name: "Unlock" }).click();
  // The deployment verifies the credential before any capture control appears,
  // so the dialog only reports the unlocked state once that round trip lands.
  await expect(
    dialog.getByRole("button", { name: "Lock administrator tools" }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Close administrator tools" })
    .click();
  await expect(banner).toBeVisible();
}

function attemptFilename(base: string, testInfo: TestInfo): string {
  return [
    base,
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
    `r${testInfo.retry}.png`,
  ].join("-");
}

function filenamePattern(filename: string): RegExp {
  return new RegExp(
    `^Open screenshot \\d+: ${filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
  );
}

function expectPixelClose(
  actual: number[],
  expected: readonly [number, number, number, number],
): void {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((channel, index) => {
    const tolerance = index === 3 ? 0 : 12;
    expect(Math.abs(actual[index] - channel)).toBeLessThanOrEqual(tolerance);
  });
}

async function samplePngPixels(
  page: Page,
  imageBytes: Buffer,
): Promise<{ background: number[]; table: number[] }> {
  return page.evaluate(async (pngBase64) => {
    const binary = window.atob(pngBase64);
    const bytes = Uint8Array.from(binary, (character) =>
      character.charCodeAt(0),
    );
    const bitmap = await createImageBitmap(
      new Blob([bytes], { type: "image/png" }),
    );
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d");
    if (context === null) {
      throw new Error("Canvas is unavailable");
    }
    context.drawImage(bitmap, 0, 0);
    const pixelAt = (x: number, y: number) =>
      Array.from(context.getImageData(x, y, 1, 1).data);
    const samples = {
      background: pixelAt(20, 20),
      table: pixelAt(320, 100),
    };
    bitmap.close();
    return samples;
  }, imageBytes.toString("base64"));
}

async function captureAdministrativeFrame(page: Page): Promise<{
  id: string;
  original_filename: string;
  queueItem: Locator;
}> {
  const uploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Capture and parse" }).click();
  const uploadedJob = await uploadResponsePromise.then(
    (response) =>
      response.json() as Promise<{
        id: string;
        original_filename: string;
      }>,
  );
  expect(uploadedJob.original_filename).toMatch(
    /^screen-capture-\d{4}-\d{2}-\d{2}T.*Z\.png$/,
  );
  const queueItem = page.getByRole("button", {
    name: filenamePattern(uploadedJob.original_filename),
  });
  await expect(queueItem).toContainText("parsed");
  return { ...uploadedJob, queueItem };
}

async function uploadAdministrativeScreenshot(
  page: Page,
  filename: string,
): Promise<{ id: string; queueItem: Locator }> {
  await page.getByLabel("Choose screenshots").setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  const uploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  const uploadedJob = await uploadResponsePromise.then(
    (response) => response.json() as Promise<{ id: string }>,
  );
  const queueItem = page.getByRole("button", {
    name: filenamePattern(filename),
  });
  await expect(queueItem).toContainText("parsed");
  return { id: uploadedJob.id, queueItem };
}

async function createApprovedScreenshot(
  page: Page,
  filename: string,
  potSize: number,
): Promise<{ id: string }> {
  const uploadResponse = await page.request.post(`${BACKEND_URL}/api/jobs`, {
    headers: ADMINISTRATOR_HEADERS,
    multipart: {
      file: {
        name: filename,
        mimeType: "image/png",
        buffer: VALID_PNG,
      },
    },
  });
  expect(uploadResponse.ok()).toBe(true);
  const uploadedJob = (await uploadResponse.json()) as {
    id: string;
    parser_result: { state: Record<string, unknown> } | null;
  };
  if (uploadedJob.parser_result === null) {
    throw new Error(`History fixture ${filename} was not parsed`);
  }
  const approveResponse = await page.request.post(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}/approve`,
    {
      data: {
        ...uploadedJob.parser_result.state,
        pot_size: potSize,
        user_approved: true,
      },
    },
  );
  expect(approveResponse.ok()).toBe(true);
  return { id: uploadedJob.id };
}

async function expectAnalyzerReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("region", { name: "Analyzer controls" }),
  ).toBeVisible();
}

// The console reviews parser output only, so the retired learning surface must
// leave no button, panel or per-row marker behind.
async function expectNoLearningControls(page: Page): Promise<void> {
  await expect(
    page.getByRole("button", { name: "Request recommendation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Your training decision" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Training progress" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Administrative OCR test input")).toHaveCount(0);
}

async function prepareUploadInput(page: Page): Promise<void> {
  await unlockAdministrativeAccess(page);
  await page
    .getByRole("group", { name: "Input mode" })
    .getByRole("button", { name: "Upload" })
    .click();
}

async function openUploadInput(page: Page): Promise<void> {
  await page.goto("/");
  await expectAnalyzerReady(page);
  await prepareUploadInput(page);
}

type CaptureSurface = "browser" | "monitor" | "window";
type CaptureOutcome = CaptureSurface | "cancel";

async function installCaptureStreams(
  page: Page,
  outcomes: readonly CaptureOutcome[] = ["window"],
): Promise<void> {
  await page.addInitScript(
    (configuredOutcomes) => {
      Object.defineProperty(navigator.mediaDevices, "getDisplayMedia", {
        configurable: true,
        value: async (requestedOptions: DisplayMediaStreamOptions) => {
          const fixtureWindow = window as typeof window & {
            __pokerHeroCaptureFixtures?: Array<{
              stream: MediaStream;
              surface: CaptureSurface;
            }>;
            __pokerHeroDisplayMediaCalls?: number;
            __pokerHeroDisplayMediaOptions?: DisplayMediaStreamOptions[];
          };
          const callIndex = fixtureWindow.__pokerHeroDisplayMediaCalls ?? 0;
          fixtureWindow.__pokerHeroDisplayMediaCalls = callIndex + 1;
          const displayMediaOptions =
            fixtureWindow.__pokerHeroDisplayMediaOptions ?? [];
          displayMediaOptions.push(requestedOptions);
          fixtureWindow.__pokerHeroDisplayMediaOptions = displayMediaOptions;
          const outcome =
            configuredOutcomes[
              Math.min(callIndex, configuredOutcomes.length - 1)
            ] ?? "window";
          if (outcome === "cancel") {
            throw new DOMException(
              "Screen sharing was cancelled",
              "NotAllowedError",
            );
          }
          const displaySurface = outcome;
          const canvas = document.createElement("canvas");
          canvas.width = 640;
          canvas.height = 360;
          const context = canvas.getContext("2d");
          if (context === null) {
            throw new Error("Canvas is unavailable");
          }

          let frame = 0;
          let tableColor = "#991b3f";
          const paintFrame = () => {
            context.fillStyle = "#1f2937";
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = tableColor;
            context.beginPath();
            context.ellipse(320, 180, 250, 125, 0, 0, Math.PI * 2);
            context.fill();
            context.fillStyle = "#ffffff";
            context.font = "bold 28px sans-serif";
            context.fillText("Poker Hero capture fixture", 145, 188);
            context.fillStyle = frame % 2 === 0 ? "#22c55e" : "#16a34a";
            context.fillRect(510, 300, 90, 18);
            frame += 1;
          };
          paintFrame();

          const stream = canvas.captureStream(8);
          const track = stream.getVideoTracks()[0];
          const nativeGetSettings = track.getSettings.bind(track);
          track.getSettings = () => ({
            ...nativeGetSettings(),
            displaySurface,
          });
          const interval = window.setInterval(paintFrame, 125);
          const clearPaintInterval = () => window.clearInterval(interval);
          const nativeStop = track.stop.bind(track);
          track.stop = () => {
            clearPaintInterval();
            nativeStop();
          };
          track.addEventListener("ended", clearPaintInterval, {
            once: true,
          });

          const fixture = {
            canvas,
            setTableColor(color: string) {
              tableColor = color;
              paintFrame();
            },
            stream,
            surface: displaySurface,
          };
          const fixtures = fixtureWindow.__pokerHeroCaptureFixtures ?? [];
          fixtures.push(fixture);
          Object.assign(fixtureWindow, {
            __pokerHeroCaptureFixture: fixture,
            __pokerHeroCaptureFixtures: fixtures,
          });
          return stream;
        },
      });
    },
    [...outcomes],
  );
}

test("keeps screenshot upload and live capture locked for players", async ({
  page,
}) => {
  await page.goto("/");
  await expectAnalyzerReady(page);

  await expect(page.getByRole("region", { name: "Input" })).toContainText(
    IMPORT_FIRST_NOTICE,
  );
  await expect(
    page.getByRole("note", { name: "Administrative OCR test mode" }),
  ).toHaveCount(0);
  await expect(page.getByRole("group", { name: "Input mode" })).toHaveCount(0);
  await expect(page.getByLabel("Choose screenshots")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Upload and parse" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Capture and parse" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Automation/ })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Configure automation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Administrator tools" }),
  ).toBeVisible();
});

test("unlocks and relocks the administrative OCR test tools", async ({
  page,
}) => {
  await page.goto("/");
  await expectAnalyzerReady(page);

  await page.getByRole("button", { name: "Administrator tools" }).click();
  const dialog = page.getByRole("dialog", { name: "Administrator tools" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "The token is verified with the server before any capture control is shown.",
  );
  await dialog
    .getByLabel("Administrative OCR test token")
    .fill(ADMINISTRATOR_TOKEN);
  const sessionResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/admin/ocr-test/session` &&
      response.request().method() === "GET",
  );
  await dialog.getByRole("button", { name: "Unlock" }).click();
  const sessionResponse = await sessionResponsePromise;
  expect(sessionResponse.status()).toBe(200);
  expect(await sessionResponse.request().headerValue("authorization")).toBe(
    `Bearer ${ADMINISTRATOR_TOKEN}`,
  );
  expect(await sessionResponse.json()).toEqual({
    authorized: true,
    enabled: true,
  });
  await expect(
    dialog.getByRole("button", { name: "Lock administrator tools" }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Close administrator tools" })
    .click();
  await expect(dialog).toHaveCount(0);

  const banner = page.getByRole("note", {
    name: "Administrative OCR test mode",
  });
  await expect(banner).toBeVisible();
  const inputMode = page.getByRole("group", { name: "Input mode" });
  await expect(inputMode).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Share window" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Capture and parse" }),
  ).toBeVisible();
  await inputMode.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByLabel("Choose screenshots")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Upload and parse" }),
  ).toBeVisible();

  await banner
    .getByRole("button", { name: "Lock administrator tools" })
    .click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Input" })).toContainText(
    IMPORT_FIRST_NOTICE,
  );
  await expect(page.getByLabel("Choose screenshots")).toHaveCount(0);
});

test("refuses to unlock when the deployment rejects the administrative token", async ({
  page,
}) => {
  const attemptedJobUploads: string[] = [];
  page.on("request", (request) => {
    if (
      request.url() === `${BACKEND_URL}/api/jobs` &&
      request.method() === "POST"
    ) {
      attemptedJobUploads.push(request.url());
    }
  });

  await page.goto("/");
  await expectAnalyzerReady(page);

  await page.getByRole("button", { name: "Administrator tools" }).click();
  const dialog = page.getByRole("dialog", { name: "Administrator tools" });
  await dialog
    .getByLabel("Administrative OCR test token")
    .fill("rejected-administrative-ocr-test-token-98765");
  const rejectedSessionPromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/admin/ocr-test/session` &&
      response.request().method() === "GET",
  );
  await dialog.getByRole("button", { name: "Unlock" }).click();
  const rejectedSession = await rejectedSessionPromise;
  expect(rejectedSession.status()).toBe(401);
  expect(rejectedSession.headers()["www-authenticate"]).toBe("Bearer");
  expect(await rejectedSession.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });

  await expect(dialog.getByRole("alert")).toHaveText(
    "The administrative OCR test token was rejected. Unlock administrator" +
      " tools again with the deployment's token.",
  );
  await expect(
    dialog.getByRole("button", { name: "Lock administrator tools" }),
  ).toHaveCount(0);
  await dialog
    .getByRole("button", { name: "Close administrator tools" })
    .click();

  await expect(
    page.getByRole("note", { name: "Administrative OCR test mode" }),
  ).toHaveCount(0);
  await expect(page.getByRole("group", { name: "Input mode" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Input" })).toContainText(
    IMPORT_FIRST_NOTICE,
  );
  await expect(page.getByLabel("Choose screenshots")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Upload and parse" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Capture and parse" }),
  ).toHaveCount(0);
  expect(attemptedJobUploads).toEqual([]);
});

test("keeps dataset import and backup restore behind administrator tools", async ({
  page,
}) => {
  await page.goto("/");
  await expectAnalyzerReady(page);

  const benchmarkDialog = page.getByRole("dialog", {
    name: "Parser benchmark",
  });
  const importDatasetButton = benchmarkDialog.getByRole("button", {
    name: "Import dataset",
  });
  await page.getByRole("button", { name: "Parser benchmark" }).click();
  await expect(benchmarkDialog).toBeVisible();
  await expect(importDatasetButton).toBeDisabled();
  await expect(benchmarkDialog.getByLabel("Parser dataset ZIP")).toBeDisabled();
  await expect(benchmarkDialog).toContainText(
    "Unlock administrator tools to import datasets.",
  );
  await benchmarkDialog.getByRole("button", { name: "Done" }).click();
  await expect(benchmarkDialog).toHaveCount(0);

  const infoDialog = page.getByRole("dialog", {
    name: "About Poker Training Analyzer",
  });
  const restoreBackupButton = infoDialog.getByRole("button", {
    name: "Restore application backup",
  });
  await page.getByRole("button", { name: "About this app" }).click();
  await expect(infoDialog).toBeVisible();
  await expect(restoreBackupButton).toBeDisabled();
  await expect(infoDialog.getByLabel("Application backup ZIP")).toBeDisabled();
  await expect(infoDialog).toContainText(
    "Unlock administrator tools to restore a backup.",
  );
  await infoDialog.getByRole("button", { name: "Done" }).click();
  await expect(infoDialog).toHaveCount(0);

  await unlockAdministrativeAccess(page);

  await page.getByRole("button", { name: "Parser benchmark" }).click();
  await expect(importDatasetButton).toBeEnabled();
  await expect(benchmarkDialog.getByLabel("Parser dataset ZIP")).toBeEnabled();
  await expect(benchmarkDialog).not.toContainText(
    "Unlock administrator tools to import datasets.",
  );
  await benchmarkDialog.getByRole("button", { name: "Done" }).click();
  await expect(benchmarkDialog).toHaveCount(0);

  await page.getByRole("button", { name: "About this app" }).click();
  await expect(restoreBackupButton).toBeEnabled();
  await expect(infoDialog.getByLabel("Application backup ZIP")).toBeEnabled();
  await expect(infoDialog).not.toContainText(
    "Unlock administrator tools to restore a backup.",
  );
  await infoDialog.getByRole("button", { name: "Done" }).click();
  await expect(infoDialog).toHaveCount(0);
});

test("approves an administrative upload in a console without learning controls", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("administrative-upload", testInfo);
  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);

  await expect(
    page.getByRole("region", { name: "Analyzer controls" }),
  ).toContainText(CONSOLE_SUBTITLE);
  await expect(
    page.getByRole("note", { name: "Administrative OCR test mode" }),
  ).toContainText(ADMINISTRATIVE_BANNER_NOTICE);
  await expectNoLearningControls(page);

  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(uploadedJob.queueItem).toContainText("approved");
  await expectNoLearningControls(page);

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  expect(await persistedResponse.json()).toMatchObject({
    archived_at: null,
    status: "approved",
  });

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  // The retired learning surface has no route of its own any more: the deep
  // link lands on the analyzer workspace instead of a training page.
  await page.goto("/analyzer/training");
  await expectAnalyzerReady(page);
  await expect(page).toHaveURL(/\/analyzer$/);
  await expect(
    page.getByRole("region", { name: "Analyzer controls" }),
  ).toContainText(CONSOLE_SUBTITLE);
  await expect(page.getByRole("region", { name: "Input" })).toContainText(
    IMPORT_FIRST_NOTICE,
  );
  await expectNoLearningControls(page);
});

test("requires an administrator credential for the screenshot upload API", async ({
  page,
}, testInfo) => {
  const filename = attemptFilename("administrative-api", testInfo);
  const multipart = {
    file: {
      name: filename,
      mimeType: "image/png",
      buffer: VALID_PNG,
    },
  };

  const anonymousUpload = await page.request.post(`${BACKEND_URL}/api/jobs`, {
    multipart,
  });
  expect(anonymousUpload.status()).toBe(401);
  expect(anonymousUpload.headers()["www-authenticate"]).toBe("Bearer");
  expect(await anonymousUpload.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });

  const rejectedUpload = await page.request.post(`${BACKEND_URL}/api/jobs`, {
    headers: { Authorization: "Bearer not-the-deployment-token" },
    multipart,
  });
  expect(rejectedUpload.status()).toBe(401);

  const authorizedUpload = await page.request.post(`${BACKEND_URL}/api/jobs`, {
    headers: ADMINISTRATOR_HEADERS,
    multipart,
  });
  expect(authorizedUpload.status()).toBe(201);
  const authorizedJob = (await authorizedUpload.json()) as { id: string };
  expect(authorizedJob).toMatchObject({
    original_filename: filename,
    status: "parsed",
  });
  const cleanupResponse = await page.request.delete(
    `${BACKEND_URL}/api/jobs/${authorizedJob.id}`,
  );
  expect(cleanupResponse.status()).toBe(204);

  const capabilitiesResponse = await page.request.get(
    `${BACKEND_URL}/api/pipeline`,
  );
  expect(capabilitiesResponse.ok()).toBe(true);
  expect(await capabilitiesResponse.json()).toMatchObject({
    administrative_ocr_test: { enabled: true },
  });
});

test("confirms the administrator credential through the session check API", async ({
  page,
}) => {
  const sessionUrl = `${BACKEND_URL}/api/admin/ocr-test/session`;

  const anonymousSession = await page.request.get(sessionUrl);
  expect(anonymousSession.status()).toBe(401);
  expect(anonymousSession.headers()["www-authenticate"]).toBe("Bearer");
  expect(await anonymousSession.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });

  const rejectedSession = await page.request.get(sessionUrl, {
    headers: { Authorization: "Bearer not-the-deployment-token" },
  });
  expect(rejectedSession.status()).toBe(401);
  expect(rejectedSession.headers()["www-authenticate"]).toBe("Bearer");
  expect(await rejectedSession.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });

  const authorizedSession = await page.request.get(sessionUrl, {
    headers: ADMINISTRATOR_HEADERS,
  });
  expect(authorizedSession.status()).toBe(200);
  expect(authorizedSession.headers()["cache-control"]).toBe("no-store");
  expect(await authorizedSession.json()).toEqual({
    authorized: true,
    enabled: true,
  });
});

test("captures repeated shared-window frames into persisted history", async ({
  page,
}) => {
  await installCaptureStreams(page);
  await page.goto("/");
  await expectAnalyzerReady(page);
  await unlockAdministrativeAccess(page);

  await page.getByRole("button", { name: "Share window" }).click();
  await expect(page.getByText("Window sharing active")).toBeVisible();
  const preview = page.getByLabel("Shared screen preview");
  await expect(preview).toHaveClass(/active/);
  await expect
    .poll(() =>
      preview.evaluate((element: HTMLVideoElement) => ({
        height: element.videoHeight,
        width: element.videoWidth,
      })),
    )
    .toEqual({ height: 360, width: 640 });

  const firstCapture = await captureAdministrativeFrame(page);
  await expectNoLearningControls(page);
  await expect(
    page.getByRole("note", { name: "Administrative OCR test mode" }),
  ).toContainText(ADMINISTRATIVE_BANNER_NOTICE);
  await expect(preview).not.toHaveClass(/active/);
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toBeVisible();

  const imageResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${firstCapture.id}/image`,
  );
  expect(imageResponse.ok()).toBe(true);
  expect(imageResponse.headers()["content-type"]).toContain("image/png");
  const imageBytes = await imageResponse.body();
  expect(imageBytes.subarray(0, 8)).toEqual(
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
  );
  expect(imageBytes.readUInt32BE(16)).toBe(640);
  expect(imageBytes.readUInt32BE(20)).toBe(360);
  const sampledPixels = await samplePngPixels(page, imageBytes);
  expectPixelClose(sampledPixels.background, [31, 41, 55, 255]);
  expectPixelClose(sampledPixels.table, [153, 27, 63, 255]);

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${firstCapture.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    approved_state: unknown;
    archived_at: string | null;
    status: string;
    upload_request_id: string | null;
  };
  expect(persistedJob).toMatchObject({
    approved_state: null,
    archived_at: null,
    status: "parsed",
    upload_request_id: expect.any(String),
  });

  await page.getByRole("button", { name: "View live window" }).click();
  await expect(preview).toHaveClass(/active/);
  await page.evaluate(() => {
    const fixture = (
      window as typeof window & {
        __pokerHeroCaptureFixture: {
          setTableColor: (color: string) => void;
        };
      }
    ).__pokerHeroCaptureFixture;
    fixture.setTableColor("#0e7490");
  });
  await expect
    .poll(() =>
      preview.evaluate((video: HTMLVideoElement) => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d");
        if (context === null) {
          return false;
        }
        context.drawImage(video, 0, 0);
        const [red, green, blue, alpha] = context.getImageData(
          320,
          100,
          1,
          1,
        ).data;
        return (
          Math.abs(red - 14) <= 12 &&
          Math.abs(green - 116) <= 12 &&
          Math.abs(blue - 144) <= 12 &&
          alpha === 255
        );
      }),
    )
    .toBe(true);

  const secondCapture = await captureAdministrativeFrame(page);
  expect(secondCapture.original_filename).not.toBe(
    firstCapture.original_filename,
  );
  await expect(firstCapture.queueItem).toContainText("parsed");
  await expect(secondCapture.queueItem).toContainText("parsed");
  const secondImageResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${secondCapture.id}/image`,
  );
  expect(secondImageResponse.ok()).toBe(true);
  const secondImageBytes = await secondImageResponse.body();
  const secondSampledPixels = await samplePngPixels(page, secondImageBytes);
  expectPixelClose(secondSampledPixels.background, [31, 41, 55, 255]);
  expectPixelClose(secondSampledPixels.table, [14, 116, 144, 255]);
  expect(secondImageBytes).not.toEqual(imageBytes);

  const displayMediaCalls = await page.evaluate(
    () =>
      (
        window as typeof window & {
          __pokerHeroDisplayMediaCalls?: number;
        }
      ).__pokerHeroDisplayMediaCalls,
  );
  expect(displayMediaCalls).toBe(1);

  // Only approved ground truth leaves the queue, so each frame is approved by
  // hand before it can be archived.
  for (const capture of [firstCapture, secondCapture]) {
    await capture.queueItem.click();
    await page.getByRole("button", { name: "Approve state" }).click();
    await expect(capture.queueItem).toContainText("approved");
  }

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(firstCapture.queueItem).toBeHidden();
  await expect(secondCapture.queueItem).toBeHidden();
  await expect(
    page.getByRole("button", { name: /Reopen history item/ }).first(),
  ).toBeVisible();

  const archivedResponses = await Promise.all([
    page.request.get(`${BACKEND_URL}/api/jobs/${firstCapture.id}`),
    page.request.get(`${BACKEND_URL}/api/jobs/${secondCapture.id}`),
  ]);
  for (const archivedResponse of archivedResponses) {
    expect(archivedResponse.ok()).toBe(true);
    const archivedJob = (await archivedResponse.json()) as {
      archived_at: string | null;
    };
    expect(archivedJob.archived_at).not.toBeNull();
  }

  await page.getByRole("button", { name: "Stop sharing" }).click();
  await expect(
    page.getByRole("button", { name: "Share window" }),
  ).toBeEnabled();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const fixture = (
          window as typeof window & {
            __pokerHeroCaptureFixture: { stream: MediaStream };
          }
        ).__pokerHeroCaptureFixture;
        return fixture.stream.getVideoTracks()[0]?.readyState;
      }),
    )
    .toBe("ended");
});

test("rejects a mismatched share source and recovers with a tab", async ({
  page,
}) => {
  await installCaptureStreams(page, ["browser", "browser"]);
  await page.goto("/");
  await expectAnalyzerReady(page);
  await unlockAdministrativeAccess(page);

  await page.getByRole("button", { name: "Share window" }).click();
  await expect(
    page.getByText(
      "Tab was selected. Choose a window in the browser share picker, or switch the source type before sharing.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Capture and parse" }),
  ).toBeDisabled();
  await expect(
    page.getByText("No screenshots uploaded or captured yet"),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const fixtures = (
          window as typeof window & {
            __pokerHeroCaptureFixtures: Array<{ stream: MediaStream }>;
          }
        ).__pokerHeroCaptureFixtures;
        return fixtures[0]?.stream.getVideoTracks()[0]?.readyState;
      }),
    )
    .toBe("ended");

  await page
    .getByRole("group", { name: "Share source type" })
    .getByRole("button", { name: "Tab" })
    .click();
  await page.getByRole("button", { name: "Share tab" }).click();
  await expect(page.getByText("Tab sharing active")).toBeVisible();
  const preview = page.getByLabel("Shared screen preview");
  await expect(preview).toHaveClass(/active/);
  await expect
    .poll(() =>
      preview.evaluate((element: HTMLVideoElement) => ({
        height: element.videoHeight,
        width: element.videoWidth,
      })),
    )
    .toEqual({ height: 360, width: 640 });
  await expect(
    page.getByText(
      "Tab was selected. Choose a window in the browser share picker, or switch the source type before sharing.",
    ),
  ).toBeHidden();

  const capture = await captureAdministrativeFrame(page);
  await expectNoLearningControls(page);
  const activeShareState = await page.evaluate(() => {
    const fixtureWindow = window as typeof window & {
      __pokerHeroCaptureFixtures: Array<{
        stream: MediaStream;
        surface: CaptureSurface;
      }>;
      __pokerHeroDisplayMediaCalls?: number;
      __pokerHeroDisplayMediaOptions?: DisplayMediaStreamOptions[];
    };
    return {
      calls: fixtureWindow.__pokerHeroDisplayMediaCalls,
      requestedSurfaces: (
        fixtureWindow.__pokerHeroDisplayMediaOptions ?? []
      ).map((options) => {
        const video = options.video;
        return typeof video === "object" && video !== null
          ? video.displaySurface
          : null;
      }),
      streams: fixtureWindow.__pokerHeroCaptureFixtures.map((fixture) => ({
        readyState: fixture.stream.getVideoTracks()[0]?.readyState,
        surface: fixture.surface,
      })),
    };
  });
  expect(activeShareState).toEqual({
    calls: 2,
    requestedSurfaces: ["window", "browser"],
    streams: [
      { readyState: "ended", surface: "browser" },
      { readyState: "live", surface: "browser" },
    ],
  });

  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(capture.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(capture.queueItem).toBeHidden();
  const archivedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${capture.id}`,
  );
  expect(archivedResponse.ok()).toBe(true);
  const archivedJob = (await archivedResponse.json()) as {
    archived_at: string | null;
  };
  expect(archivedJob.archived_at).not.toBeNull();

  await page.getByRole("button", { name: "Stop sharing" }).click();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const fixtures = (
          window as typeof window & {
            __pokerHeroCaptureFixtures: Array<{ stream: MediaStream }>;
          }
        ).__pokerHeroCaptureFixtures;
        return fixtures.map(
          (fixture) => fixture.stream.getVideoTracks()[0]?.readyState,
        );
      }),
    )
    .toEqual(["ended", "ended"]);
});

test("recovers after the browser share picker is cancelled", async ({
  page,
}) => {
  await installCaptureStreams(page, ["cancel", "window"]);
  await page.goto("/");
  await expectAnalyzerReady(page);
  await unlockAdministrativeAccess(page);

  await page.getByRole("button", { name: "Share window" }).click();
  await expect(page.getByText("Screen sharing was cancelled")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Capture and parse" }),
  ).toBeDisabled();
  await expect(
    page.getByText("No screenshots uploaded or captured yet"),
  ).toBeVisible();
  const cancelledState = await page.evaluate(() => {
    const fixtureWindow = window as typeof window & {
      __pokerHeroCaptureFixtures?: Array<{ stream: MediaStream }>;
      __pokerHeroDisplayMediaCalls?: number;
      __pokerHeroDisplayMediaOptions?: DisplayMediaStreamOptions[];
    };
    return {
      calls: fixtureWindow.__pokerHeroDisplayMediaCalls,
      fixtures: fixtureWindow.__pokerHeroCaptureFixtures?.length ?? 0,
      requestedSurfaces: (
        fixtureWindow.__pokerHeroDisplayMediaOptions ?? []
      ).map((options) => {
        const video = options.video;
        return typeof video === "object" && video !== null
          ? video.displaySurface
          : null;
      }),
    };
  });
  expect(cancelledState).toEqual({
    calls: 1,
    fixtures: 0,
    requestedSurfaces: ["window"],
  });

  await page.getByRole("button", { name: "Share window" }).click();
  await expect(page.getByText("Window sharing active")).toBeVisible();
  await expect(page.getByText("Screen sharing was cancelled")).toBeHidden();
  const preview = page.getByLabel("Shared screen preview");
  await expect(preview).toHaveClass(/active/);
  await expect
    .poll(() =>
      preview.evaluate((element: HTMLVideoElement) => ({
        height: element.videoHeight,
        width: element.videoWidth,
      })),
    )
    .toEqual({ height: 360, width: 640 });

  const capture = await captureAdministrativeFrame(page);
  await expectNoLearningControls(page);
  const recoveredState = await page.evaluate(() => {
    const fixtureWindow = window as typeof window & {
      __pokerHeroCaptureFixtures: Array<{
        stream: MediaStream;
        surface: CaptureSurface;
      }>;
      __pokerHeroDisplayMediaCalls?: number;
      __pokerHeroDisplayMediaOptions?: DisplayMediaStreamOptions[];
    };
    return {
      calls: fixtureWindow.__pokerHeroDisplayMediaCalls,
      requestedSurfaces: (
        fixtureWindow.__pokerHeroDisplayMediaOptions ?? []
      ).map((options) => {
        const video = options.video;
        return typeof video === "object" && video !== null
          ? video.displaySurface
          : null;
      }),
      streams: fixtureWindow.__pokerHeroCaptureFixtures.map((fixture) => ({
        readyState: fixture.stream.getVideoTracks()[0]?.readyState,
        surface: fixture.surface,
      })),
    };
  });
  expect(recoveredState).toEqual({
    calls: 2,
    requestedSurfaces: ["window", "window"],
    streams: [{ readyState: "live", surface: "window" }],
  });

  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(capture.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(capture.queueItem).toBeHidden();
  const archivedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${capture.id}`,
  );
  expect(archivedResponse.ok()).toBe(true);
  const archivedJob = (await archivedResponse.json()) as {
    archived_at: string | null;
  };
  expect(archivedJob.archived_at).not.toBeNull();

  await page.getByRole("button", { name: "Stop sharing" }).click();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const fixtures = (
          window as typeof window & {
            __pokerHeroCaptureFixtures: Array<{ stream: MediaStream }>;
          }
        ).__pokerHeroCaptureFixtures;
        return fixtures.map(
          (fixture) => fixture.stream.getVideoTracks()[0]?.readyState,
        );
      }),
    )
    .toEqual(["ended"]);
});

test("reviews one screenshot from upload through persisted history", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("manual-flow", testInfo);

  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);
  const queueItem = uploadedJob.queueItem;
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${uploadedJob.id}/image`);
  await expect(page.getByLabel("Hero cards")).toHaveValue("Ah Kd");
  await expect(page.getByLabel("Board cards")).toHaveValue("Qs Jc 2h");

  await page.getByLabel("Pot").fill("13");
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(queueItem).toContainText("approved");

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(queueItem).toBeHidden();

  const historyItem = page
    .getByRole("button", {
      name: /Reopen history item/,
    })
    .first();
  await expect(historyItem).toBeVisible();
  await historyItem.click();
  await expect(page.getByLabel("Pot")).toHaveValue("13");

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    approved_state: { pot_size: number };
    archived_at: string | null;
  };
  expect(persistedJob.approved_state.pot_size).toBe(13);
  expect(persistedJob.archived_at).not.toBeNull();
});

test("overlays delete confirmation without resizing screenshot details", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("delete-overlay", testInfo);

  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const includeResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}/benchmark`,
    { data: { included: true } },
  );
  expect(includeResponse.ok()).toBe(true);
  await page.reload();
  await page
    .getByRole("button", {
      name: `Manage screenshot 1: ${filename}`,
    })
    .click();

  const dialog = page.getByRole("dialog", { name: "Screenshot details" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Administrative OCR test input")).toHaveCount(
    0,
  );
  const before = await dialog.boundingBox();
  expect(before).not.toBeNull();

  await dialog.getByRole("button", { name: "Delete screenshot" }).click();
  const confirmation = dialog.getByRole("alert");
  await expect(confirmation).toBeVisible();

  const coveredFooter = dialog.locator(".screenshot-details-footer");
  await expect(coveredFooter).toHaveAttribute("aria-hidden", "true");
  await expect(coveredFooter.locator("button").first()).toBeDisabled();
  await expect(coveredFooter.locator("button").last()).toBeDisabled();

  const after = await dialog.boundingBox();
  const footerBox = await coveredFooter.boundingBox();
  const confirmationBox = await confirmation.boundingBox();
  expect(after).not.toBeNull();
  expect(footerBox).not.toBeNull();
  expect(confirmationBox).not.toBeNull();
  expect(Math.abs(after!.height - before!.height)).toBeLessThanOrEqual(1);
  expect(Math.abs(confirmationBox!.y - footerBox!.y)).toBeLessThanOrEqual(1);
  expect(
    Math.abs(
      confirmationBox!.y + confirmationBox!.height - (after!.y + after!.height),
    ),
  ).toBeLessThanOrEqual(2);

  await confirmation.getByRole("button", { name: "Cancel" }).click();
  await page.setViewportSize({ width: 320, height: 800 });
  const mobileFooterBox = await coveredFooter.boundingBox();
  expect(mobileFooterBox).not.toBeNull();
  await dialog.getByRole("button", { name: "Delete screenshot" }).click();
  const mobileConfirmationBox = await confirmation.boundingBox();
  expect(mobileConfirmationBox).not.toBeNull();
  expect(
    Math.abs(mobileConfirmationBox!.y - mobileFooterBox!.y),
  ).toBeLessThanOrEqual(1);

  await confirmation
    .getByRole("button", {
      name: "Delete permanently",
    })
    .click();
  await expect(dialog).toBeHidden();
});

test("runs a parser benchmark and verifies its exported dataset", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("benchmark-dataset", testInfo);

  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(uploadedJob.queueItem).toContainText("approved");

  const initialOverviewResponse = await page.request.get(
    `${BACKEND_URL}/api/benchmarks`,
  );
  expect(initialOverviewResponse.ok()).toBe(true);
  const initialOverview = (await initialOverviewResponse.json()) as {
    included_cases: number;
  };
  const expectedIncludedCases = initialOverview.included_cases + 1;

  await page.getByRole("button", { name: "Parser benchmark" }).click();
  const benchmarkDialog = page.getByRole("dialog", {
    name: "Parser benchmark",
  });
  await expect(benchmarkDialog).toBeVisible();
  await expect(benchmarkDialog).toContainText(
    `${initialOverview.included_cases} ground-truth ${initialOverview.included_cases === 1 ? "hand" : "hands"}`,
  );
  const importDatasetButton = benchmarkDialog.getByRole("button", {
    name: "Import dataset",
  });
  await expect(importDatasetButton).toHaveCSS("padding-left", "7px");
  await expect(importDatasetButton).toHaveCSS("padding-right", "7px");
  await expect(importDatasetButton.locator("svg")).toHaveCSS("width", "14px");

  const includeResponsePromise = page.waitForResponse(
    (response) =>
      response.url() ===
        `${BACKEND_URL}/api/jobs/${uploadedJob.id}/benchmark` &&
      response.request().method() === "PUT",
  );
  const groundTruthToggle = benchmarkDialog.getByRole("switch", {
    name: /Use current hand as ground truth/,
  });
  await groundTruthToggle.click();
  expect((await includeResponsePromise).ok()).toBe(true);
  await expect(groundTruthToggle).toHaveAttribute("aria-checked", "true");
  await expect(benchmarkDialog).toContainText(
    `${expectedIncludedCases} ground-truth ${expectedIncludedCases === 1 ? "hand" : "hands"}`,
  );

  const runResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/benchmarks/run` &&
      response.request().method() === "POST",
  );
  await benchmarkDialog.getByRole("button", { name: "Run benchmark" }).click();
  const runResponse = await runResponsePromise;
  expect(runResponse.ok()).toBe(true);
  const report = (await runResponse.json()) as {
    accuracy: number;
    cases: Array<{
      accuracy: number;
      job_id: string;
      status: string;
    }>;
    failed_cases: number;
    total_cases: number;
  };
  expect(report).toMatchObject({
    accuracy: 1,
    failed_cases: 0,
    total_cases: expectedIncludedCases,
  });
  expect(report.cases).toContainEqual(
    expect.objectContaining({
      accuracy: 1,
      job_id: uploadedJob.id,
      status: "completed",
    }),
  );
  const benchmarkSummary = benchmarkDialog.getByLabel("Benchmark summary");
  await expect(benchmarkSummary).toContainText(String(expectedIncludedCases));
  await expect(benchmarkSummary).toContainText("100%");
  await expect(
    benchmarkDialog.getByRole("button", {
      name: `Toggle ${filename} benchmark details`,
    }),
  ).toContainText("100%");

  const downloadPromise = page.waitForEvent("download");
  await benchmarkDialog.getByRole("link", { name: "Export dataset" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^poker-hero-parser-dataset-\d{8}T\d{6}Z\.zip$/,
  );
  const datasetPath = await download.path();
  expect(datasetPath).not.toBeNull();
  if (datasetPath === null) {
    throw new Error("Dataset export did not produce a local download");
  }

  const datasetMultipart = {
    file: {
      name: download.suggestedFilename(),
      mimeType: "application/zip",
      buffer: await readFile(datasetPath),
    },
  };
  const anonymousImport = await page.request.post(
    `${BACKEND_URL}/api/benchmarks/import`,
    { multipart: datasetMultipart },
  );
  expect(anonymousImport.status()).toBe(401);
  expect(anonymousImport.headers()["www-authenticate"]).toBe("Bearer");
  expect(await anonymousImport.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });
  const authorizedImport = await page.request.post(
    `${BACKEND_URL}/api/benchmarks/import`,
    { headers: ADMINISTRATOR_HEADERS, multipart: datasetMultipart },
  );
  expect(authorizedImport.status()).toBe(200);
  expect(await authorizedImport.json()).toMatchObject({
    imported_cases: 0,
    included_cases: expectedIncludedCases,
    reused_cases: expectedIncludedCases,
  });

  const importRequestPromise = page.waitForRequest(
    (request) =>
      request.url() === `${BACKEND_URL}/api/benchmarks/import` &&
      request.method() === "POST",
  );
  const importResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/benchmarks/import` &&
      response.request().method() === "POST",
  );
  await benchmarkDialog
    .getByLabel("Parser dataset ZIP")
    .setInputFiles(datasetPath);
  const importRequest = await importRequestPromise;
  expect(await importRequest.headerValue("authorization")).toBe(
    `Bearer ${ADMINISTRATOR_TOKEN}`,
  );
  const importResponse = await importResponsePromise;
  expect(importResponse.ok()).toBe(true);
  const importResult = (await importResponse.json()) as {
    imported_cases: number;
    included_cases: number;
    job_ids: string[];
    reused_cases: number;
  };
  expect(importResult).toMatchObject({
    imported_cases: 0,
    included_cases: expectedIncludedCases,
    reused_cases: expectedIncludedCases,
  });
  expect(importResult.job_ids).toContain(uploadedJob.id);
  await expect(
    page.getByText(
      `Dataset ready: ${expectedIncludedCases} ${expectedIncludedCases === 1 ? "hand" : "hands"}`,
    ),
  ).toBeVisible();

  const excludeResponsePromise = page.waitForResponse(
    (response) =>
      response.url() ===
        `${BACKEND_URL}/api/jobs/${uploadedJob.id}/benchmark` &&
      response.request().method() === "PUT",
  );
  await groundTruthToggle.click();
  expect((await excludeResponsePromise).ok()).toBe(true);
  await expect(groundTruthToggle).toHaveAttribute("aria-checked", "false");
  await expect(benchmarkDialog).toContainText(
    `${initialOverview.included_cases} ground-truth ${initialOverview.included_cases === 1 ? "hand" : "hands"}`,
  );
  await benchmarkDialog.getByRole("button", { name: "Done" }).click();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    benchmark_included: boolean;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    benchmark_included: false,
  });
});

test("downloads and verifies an application backup through recovery", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("application-backup", testInfo);

  const archivedJob = await uploadAdministrativeScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(archivedJob.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(archivedJob.queueItem).toBeHidden();

  const pendingFilename = attemptFilename(
    "application-backup-pending",
    testInfo,
  );
  const pendingJob = await uploadAdministrativeScreenshot(
    page,
    pendingFilename,
  );
  await expect(pendingJob.queueItem).toContainText("parsed");

  await page.getByRole("button", { name: "About this app" }).click();
  const infoDialog = page.getByRole("dialog", {
    name: "About Poker Training Analyzer",
  });
  await expect(infoDialog).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await infoDialog
    .getByRole("link", {
      name: "Download application backup",
    })
    .click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^poker-hero-backup-\d{8}T\d{6}Z\.zip$/,
  );
  const backupPath = await download.path();
  expect(backupPath).not.toBeNull();
  if (backupPath === null) {
    throw new Error("Backup export did not produce a local download");
  }

  const backupMultipart = {
    file: {
      name: download.suggestedFilename(),
      mimeType: "application/zip",
      buffer: await readFile(backupPath),
    },
  };
  const anonymousRestore = await page.request.post(
    `${BACKEND_URL}/api/backups/restore`,
    { multipart: backupMultipart },
  );
  expect(anonymousRestore.status()).toBe(401);
  expect(anonymousRestore.headers()["www-authenticate"]).toBe("Bearer");
  expect(await anonymousRestore.json()).toEqual({
    detail: "Administrative OCR test authorization is required",
  });
  const authorizedRestore = await page.request.post(
    `${BACKEND_URL}/api/backups/restore`,
    { headers: ADMINISTRATOR_HEADERS, multipart: backupMultipart },
  );
  expect(authorizedRestore.status()).toBe(200);
  expect(await authorizedRestore.json()).toMatchObject({
    imported_benchmark_reports: 0,
    imported_jobs: 0,
  });

  const restoreRequestPromise = page.waitForRequest(
    (request) =>
      request.url() === `${BACKEND_URL}/api/backups/restore` &&
      request.method() === "POST",
  );
  const restoreResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/backups/restore` &&
      response.request().method() === "POST",
  );
  await infoDialog
    .getByLabel("Application backup ZIP")
    .setInputFiles(backupPath);
  const restoreRequest = await restoreRequestPromise;
  expect(await restoreRequest.headerValue("authorization")).toBe(
    `Bearer ${ADMINISTRATOR_TOKEN}`,
  );
  const restoreResponse = await restoreResponsePromise;
  expect(restoreResponse.ok()).toBe(true);
  const restoreResult = (await restoreResponse.json()) as {
    imported_jobs: number;
    reused_jobs: number;
    imported_benchmark_reports: number;
    reused_benchmark_reports: number;
  };
  expect(restoreResult.imported_jobs).toBe(0);
  expect(restoreResult.imported_benchmark_reports).toBe(0);
  expect(restoreResult.reused_jobs).toBeGreaterThanOrEqual(2);
  expect(
    restoreResult.reused_jobs + restoreResult.reused_benchmark_reports,
  ).toBeGreaterThanOrEqual(1);

  await expect(
    page.getByText(/Backup already present: \d+ records? verified/),
  ).toBeVisible();
  await expect(archivedJob.queueItem).toBeHidden();
  await expect(pendingJob.queueItem).toContainText("parsed");
  const archivedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${archivedJob.id}`,
  );
  expect(archivedResponse.ok()).toBe(true);
  const archivedRecord = (await archivedResponse.json()) as {
    archived_at: string | null;
    status: string;
  };
  expect(archivedRecord).toMatchObject({
    archived_at: expect.any(String),
    status: "approved",
  });
  const pendingResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${pendingJob.id}`,
  );
  expect(pendingResponse.ok()).toBe(true);
  const pendingRecord = (await pendingResponse.json()) as {
    archived_at: string | null;
    status: string;
  };
  expect(pendingRecord).toMatchObject({
    archived_at: null,
    status: "parsed",
  });

  await infoDialog.getByRole("button", { name: "Done" }).click();
  await pendingJob.queueItem.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(pendingJob.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(pendingJob.queueItem).toBeHidden();
});

test("continues a screenshot batch when one upload is invalid", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const validFilename = attemptFilename("batch-valid", testInfo);
  const invalidFilename = attemptFilename("batch-invalid", testInfo);

  await page.getByLabel("Choose screenshots").setInputFiles([
    {
      name: validFilename,
      mimeType: "image/png",
      buffer: VALID_PNG,
    },
    {
      name: invalidFilename,
      mimeType: "image/png",
      buffer: Buffer.from("not an image"),
    },
  ]);
  await page.getByRole("button", { name: "Upload and parse" }).click();

  await expect(
    page.getByRole("dialog", { name: "Processing queue" }),
  ).toBeHidden();

  const validItem = page.getByRole("button", {
    name: filenamePattern(validFilename),
  });
  const invalidItem = page.getByRole("button", {
    name: filenamePattern(invalidFilename),
  });
  await expect(validItem).toContainText("parsed");
  await expect(invalidItem).toContainText(
    "Upload must contain supported image data",
  );
  await expect(invalidItem).toContainText("error");
  await expect(
    page.getByText(
      "1 screenshot need attention. Check the failed queue items.",
    ),
  ).toBeVisible();

  const batchJobsResponse = await page.request.get(`${BACKEND_URL}/api/jobs`);
  expect(batchJobsResponse.ok()).toBe(true);
  const batchJobs = (await batchJobsResponse.json()) as {
    jobs: Array<{
      original_filename: string;
      status: string;
    }>;
  };
  expect(
    batchJobs.jobs.find(
      (candidate) => candidate.original_filename === validFilename,
    ),
  ).toMatchObject({
    status: "parsed",
  });
  expect(
    batchJobs.jobs.some(
      (candidate) => candidate.original_filename === invalidFilename,
    ),
  ).toBe(false);

  // The surviving upload is administrative OCR test data, so it becomes ground
  // truth only through an explicit approval.
  await validItem.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(validItem).toContainText("approved");
  await expectNoLearningControls(page);

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(validItem).toBeHidden();
  await expect(invalidItem).toBeVisible();
});

test("persists a parser failure and recovers by re-uploading the screenshot", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("parser-retry", testInfo);

  const armFailureResponse = await page.request.post(
    `${PROVIDER_URL}/control/fail-next-parser`,
  );
  expect(armFailureResponse.ok()).toBe(true);

  await page.getByLabel("Choose screenshots").setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  const failedUploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs` &&
      response.request().method() === "POST" &&
      response.status() === 502,
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  const failedUploadResponse = await failedUploadResponsePromise;
  expect(await failedUploadResponse.json()).toEqual({
    detail: "Vision parser request failed with status 503",
  });

  const matchingQueueItems = page.getByRole("button", {
    name: filenamePattern(filename),
  });
  await expect(matchingQueueItems).toHaveCount(1);
  await expect(matchingQueueItems).toContainText("error");
  await expect(matchingQueueItems).toContainText(
    "Vision parser request failed with status 503",
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    )
    .toBeNull();

  const failedJobsResponse = await page.request.get(`${BACKEND_URL}/api/jobs`);
  expect(failedJobsResponse.ok()).toBe(true);
  const failedJobs = (await failedJobsResponse.json()) as {
    jobs: Array<{
      error: string | null;
      id: string;
      original_filename: string;
      parser_provider: string;
      parser_result: unknown;
      status: string;
      upload_request_id: string | null;
    }>;
  };
  const failedJob = failedJobs.jobs.find(
    (candidate) => candidate.original_filename === filename,
  );
  expect(failedJob).toMatchObject({
    error: "Vision parser request failed with status 503",
    parser_provider: "llm_vision",
    parser_result: null,
    status: "error",
  });
  expect(failedJob?.upload_request_id).not.toBeNull();
  const cachedFailedJobs = await page.evaluate(
    () =>
      JSON.parse(
        localStorage.getItem("poker-training-processing-v1") ?? "[]",
      ) as Array<{
        id: string;
        original_filename: string;
        parser_provider: string;
        status: string;
      }>,
  );
  const cachedFailedJob = cachedFailedJobs.find(
    (candidate) => candidate.original_filename === filename,
  );
  expect(cachedFailedJob).toMatchObject({
    id: failedJob?.id,
    parser_provider: "llm_vision",
    status: "error",
  });

  await page.reload();
  await expectAnalyzerReady(page);
  await expect(matchingQueueItems).toHaveCount(1);
  await expect(matchingQueueItems).toContainText(
    "Vision parser request failed with status 503",
  );
  await prepareUploadInput(page);

  await page.getByLabel("Choose screenshots").setInputFiles({
    name: filename,
    mimeType: "image/png",
    buffer: VALID_PNG,
  });
  const recoveredUploadPromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs` &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Upload and parse" }).click();
  const recoveredJob = (await (await recoveredUploadPromise).json()) as {
    id: string;
  };

  await expect(matchingQueueItems).toHaveCount(2);
  const failedQueueItem = matchingQueueItems.filter({ hasText: "error" });
  await expect(failedQueueItem).toContainText(
    "Vision parser request failed with status 503",
  );
  await expect(matchingQueueItems.filter({ hasText: "parsed" })).toHaveCount(1);

  await page.goto(`/analyzer/jobs/${recoveredJob.id}`);
  await expectAnalyzerReady(page);
  await expect(matchingQueueItems).toHaveCount(2);
  await page.getByRole("button", { name: "Approve state" }).click();
  const recoveredQueueItem = matchingQueueItems.filter({
    hasText: "approved",
  });
  await expect(recoveredQueueItem).toHaveCount(1);

  const recoveredJobsResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs`,
  );
  expect(recoveredJobsResponse.ok()).toBe(true);
  const recoveredJobs = (await recoveredJobsResponse.json()) as {
    jobs: Array<{
      approved_state: Record<string, unknown> | null;
      original_filename: string;
      parser_result: { raw: Record<string, string> } | null;
      status: string;
    }>;
  };
  const matchingPersistedJobs = recoveredJobs.jobs.filter(
    (candidate) => candidate.original_filename === filename,
  );
  expect(matchingPersistedJobs).toHaveLength(2);
  expect(matchingPersistedJobs).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        parser_result: null,
        status: "error",
      }),
      expect.objectContaining({
        approved_state: expect.objectContaining({ street: "flop" }),
        parser_result: expect.objectContaining({
          raw: expect.objectContaining({
            engine: "e2e_provider_stub",
            provider: "llm_vision",
          }),
        }),
        status: "approved",
      }),
    ]),
  );

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(matchingQueueItems).toHaveCount(1);
  await expect(matchingQueueItems).toContainText("error");
});

test("restores history and processing after browser storage is cleared", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const archivedFilename = attemptFilename("storage-reset-history", testInfo);
  const archivedJob = await uploadAdministrativeScreenshot(
    page,
    archivedFilename,
  );
  await page.getByLabel("Pot").fill("66.75");
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(archivedJob.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(archivedJob.queueItem).toBeHidden();

  const pendingFilename = attemptFilename("storage-reset-pending", testInfo);
  const pendingJob = await uploadAdministrativeScreenshot(
    page,
    pendingFilename,
  );
  await expect(pendingJob.queueItem).toContainText("parsed");
  const historyPanel = page.getByRole("region", { name: "Session history" });
  await expect(
    historyPanel.getByRole("button", {
      name: "Reopen history item 1",
      exact: true,
    }),
  ).toBeVisible();

  const storageCounts = await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
    return {
      local: localStorage.length,
      session: sessionStorage.length,
    };
  });
  expect(storageCounts).toEqual({ local: 0, session: 0 });

  await page.reload();
  await expectAnalyzerReady(page);
  const restoredPendingJob = page.getByRole("button", {
    name: filenamePattern(pendingFilename),
  });
  await expect(restoredPendingJob).toContainText("parsed");
  const restoredHistoryItem = page
    .getByRole("region", {
      name: "Session history",
    })
    .getByRole("button", { name: "Reopen history item 1", exact: true });
  await expect(restoredHistoryItem).toBeVisible();

  await restoredHistoryItem.click();
  await expect(page.getByLabel("Pot")).toHaveValue("66.75");
  await expect(restoredPendingJob).toContainText("parsed");
  const persistedArchivedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${archivedJob.id}`,
  );
  expect(persistedArchivedResponse.ok()).toBe(true);
  const persistedArchivedJob = (await persistedArchivedResponse.json()) as {
    archived_at: string | null;
    approved_state: { pot_size: number } | null;
    status: string;
  };
  expect(persistedArchivedJob).toMatchObject({
    archived_at: expect.any(String),
    approved_state: { pot_size: 66.75 },
    status: "approved",
  });

  await restoredPendingJob.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(restoredPendingJob).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(restoredPendingJob).toBeHidden();
});

test("searches beyond cached history without replacing active work", async ({
  page,
}, testInfo) => {
  const targetFilename = attemptFilename("deep-history-target", testInfo);
  const targetJob = await createApprovedScreenshot(page, targetFilename, 77.25);
  const targetArchiveResponse = await page.request.put(
    `${BACKEND_URL}/api/history`,
    { data: { job_ids: [targetJob.id] } },
  );
  expect(targetArchiveResponse.ok()).toBe(true);

  const newerJobIds: string[] = [];
  for (let index = 0; index < 24; index += 1) {
    const fixture = await createApprovedScreenshot(
      page,
      attemptFilename(`deep-history-newer-${index + 1}`, testInfo),
      12.5 + index,
    );
    newerJobIds.push(fixture.id);
  }
  const newerArchiveResponse = await page.request.put(
    `${BACKEND_URL}/api/history`,
    { data: { job_ids: newerJobIds } },
  );
  expect(newerArchiveResponse.ok()).toBe(true);

  const firstHistoryResponse = await page.request.get(
    `${BACKEND_URL}/api/history`,
  );
  expect(firstHistoryResponse.ok()).toBe(true);
  const firstHistory = (await firstHistoryResponse.json()) as {
    jobs: Array<{ id: string }>;
    total: number;
  };
  expect(firstHistory.jobs).toHaveLength(24);
  expect(firstHistory.total).toBeGreaterThanOrEqual(25);
  expect(firstHistory.jobs.map((job) => job.id)).not.toContain(targetJob.id);

  await openUploadInput(page);
  const pendingFilename = attemptFilename("deep-history-pending", testInfo);
  const pendingJob = await uploadAdministrativeScreenshot(
    page,
    pendingFilename,
  );
  const historyPanel = page.getByRole("region", { name: "Session history" });
  const historyItems = historyPanel.getByRole("button", {
    name: /^Reopen history item /,
  });
  await expect(historyItems).toHaveCount(24);

  await historyPanel
    .getByRole("button", {
      name: "Search saved history",
    })
    .click();
  await historyPanel.getByLabel("History search query").fill(targetFilename);
  const searchResponsePromise = page.waitForResponse((response) => {
    if (response.request().method() !== "GET") {
      return false;
    }
    const url = new URL(response.url());
    return (
      url.origin === BACKEND_URL &&
      url.pathname === "/api/history" &&
      url.searchParams.get("query") === targetFilename
    );
  });
  await historyPanel
    .getByRole("button", {
      name: "Run history search",
    })
    .click();
  const searchResponse = await searchResponsePromise;
  expect(searchResponse.ok()).toBe(true);
  const searchResult = (await searchResponse.json()) as {
    jobs: Array<{ id: string }>;
    total: number;
  };
  expect(searchResult).toMatchObject({
    jobs: [{ id: targetJob.id }],
    total: 1,
  });
  await expect(historyPanel).toContainText("History · 1 match");
  await expect(historyItems).toHaveCount(1);

  await historyItems.first().click();
  await expect(page.getByLabel("Pot")).toHaveValue("77.25");
  await expect(pendingJob.queueItem).toContainText("parsed");

  await historyPanel
    .getByRole("button", {
      name: "Close history search",
    })
    .click();
  await expect(historyPanel).toContainText("History · reopen");
  await expect(historyItems).toHaveCount(24);
  await expect(pendingJob.queueItem).toContainText("parsed");

  await pendingJob.queueItem.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(pendingJob.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(pendingJob.queueItem).toBeHidden();
});

test("loads an older page of matching history results", async ({
  page,
}, testInfo) => {
  const searchToken = [
    "paged-history",
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
    `r${testInfo.retry}`,
  ].join("-");
  const oldestFilename = `${searchToken}-oldest.png`;
  const oldestJob = await createApprovedScreenshot(page, oldestFilename, 88.5);
  const oldestArchiveResponse = await page.request.put(
    `${BACKEND_URL}/api/history`,
    { data: { job_ids: [oldestJob.id] } },
  );
  expect(oldestArchiveResponse.ok()).toBe(true);

  const newerJobIds: string[] = [];
  for (let index = 0; index < 24; index += 1) {
    const fixture = await createApprovedScreenshot(
      page,
      `${searchToken}-newer-${index + 1}.png`,
      20 + index,
    );
    newerJobIds.push(fixture.id);
  }
  const newerArchiveResponse = await page.request.put(
    `${BACKEND_URL}/api/history`,
    { data: { job_ids: newerJobIds } },
  );
  expect(newerArchiveResponse.ok()).toBe(true);

  await openUploadInput(page);
  const pendingFilename = attemptFilename("paged-history-pending", testInfo);
  const pendingJob = await uploadAdministrativeScreenshot(
    page,
    pendingFilename,
  );
  const historyPanel = page.getByRole("region", { name: "Session history" });
  await historyPanel
    .getByRole("button", {
      name: "Search saved history",
    })
    .click();
  await historyPanel.getByLabel("History search query").fill(searchToken);

  const firstSearchResponsePromise = page.waitForResponse((response) => {
    if (response.request().method() !== "GET") {
      return false;
    }
    const url = new URL(response.url());
    return (
      url.origin === BACKEND_URL &&
      url.pathname === "/api/history" &&
      url.searchParams.get("query") === searchToken &&
      url.searchParams.get("offset") === null
    );
  });
  await historyPanel
    .getByRole("button", {
      name: "Run history search",
    })
    .click();
  const firstSearchResponse = await firstSearchResponsePromise;
  expect(firstSearchResponse.ok()).toBe(true);
  const firstSearchPage = (await firstSearchResponse.json()) as {
    jobs: Array<{ id: string }>;
    snapshot_version: string;
    total: number;
  };
  expect(firstSearchPage.jobs).toHaveLength(24);
  expect(firstSearchPage.total).toBe(25);
  expect(firstSearchPage.jobs.map((job) => job.id)).not.toContain(oldestJob.id);

  const historyItems = historyPanel.getByRole("button", {
    name: /^Reopen history item /,
  });
  await expect(historyPanel).toContainText("History · 25 matches");
  await expect(historyItems).toHaveCount(24);
  const loadOlderButton = historyPanel.getByRole("button", {
    name: "Load older history",
  });
  await expect(loadOlderButton).toContainText("Load 1 older");

  const olderPageResponsePromise = page.waitForResponse((response) => {
    if (response.request().method() !== "GET") {
      return false;
    }
    const url = new URL(response.url());
    return (
      url.origin === BACKEND_URL &&
      url.pathname === "/api/history" &&
      url.searchParams.get("query") === searchToken &&
      url.searchParams.get("offset") === "24"
    );
  });
  await loadOlderButton.click();
  const olderPageResponse = await olderPageResponsePromise;
  expect(olderPageResponse.ok()).toBe(true);
  const olderPage = (await olderPageResponse.json()) as {
    jobs: Array<{ id: string }>;
    snapshot_version: string;
    total: number;
  };
  expect(olderPage).toMatchObject({
    jobs: [{ id: oldestJob.id }],
    snapshot_version: firstSearchPage.snapshot_version,
    total: 25,
  });
  await expect(historyItems).toHaveCount(25);
  await expect(loadOlderButton).toBeHidden();

  await historyItems.nth(24).click();
  await expect(page.getByLabel("Pot")).toHaveValue("88.5");
  await expect(pendingJob.queueItem).toContainText("parsed");

  await historyPanel
    .getByRole("button", {
      name: "Close history search",
    })
    .click();
  await expect(historyItems).toHaveCount(24);
  await expect(pendingJob.queueItem).toContainText("parsed");

  await pendingJob.queueItem.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(pendingJob.queueItem).toContainText("approved");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(pendingJob.queueItem).toBeHidden();
});
