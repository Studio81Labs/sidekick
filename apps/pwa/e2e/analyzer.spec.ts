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
const ADMINISTRATIVE_REVIEW_NOTICE =
  "Administrative test inputs never request recommendations or enter training.";

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

// Records persisted before #413 deserialize as `legacy_player`, so the provider
// stub drops the `input_context` key to produce a player-owned hand without
// adding a test switch to the product.
async function markLegacyJobs(
  page: Page,
  jobIds: readonly string[],
): Promise<void> {
  const response = await page.request.post(
    `${PROVIDER_URL}/control/legacy-jobs`,
    { data: { job_ids: jobIds } },
  );
  expect(response.ok()).toBe(true);
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
  await expect(
    queueItem.getByLabel("Administrative OCR test input"),
  ).toContainText("Admin test");
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

// The workspace serves its cached processing snapshot while the session is
// marked synced, so a record the provider stub rewrote behind the app's back is
// only read again once those markers are gone. A document init script clears
// them so the workspace cannot re-mark the session between the removal and the
// navigation.
const QUEUE_REVALIDATION_FLAG = "poker-hero-e2e-force-queue-revalidation";
const queueRevalidationPages = new WeakSet<Page>();

async function forceQueueRevalidation(page: Page): Promise<void> {
  if (!queueRevalidationPages.has(page)) {
    queueRevalidationPages.add(page);
    await page.addInitScript((flag) => {
      if (sessionStorage.getItem(flag) === null) {
        return;
      }
      sessionStorage.removeItem(flag);
      sessionStorage.removeItem("poker-training-processing-synced");
      sessionStorage.removeItem("poker-training-history-synced");
    }, QUEUE_REVALIDATION_FLAG);
  }
  await page.evaluate((flag) => {
    sessionStorage.setItem(flag, "1");
  }, QUEUE_REVALIDATION_FLAG);
}

// Administrative test inputs never reach recommendations or training, so a
// scenario that needs a player-owned hand uploads through the administrative
// surface and then reloads the record as a legacy one.
async function uploadLegacyScreenshot(
  page: Page,
  filename: string,
): Promise<{ id: string; queueItem: Locator }> {
  await prepareUploadInput(page);
  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);
  await markLegacyJobs(page, [uploadedJob.id]);
  await forceQueueRevalidation(page);
  await page.goto(`/analyzer/jobs/${uploadedJob.id}`);
  await expectAnalyzerReady(page);
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${uploadedJob.id}/image`);
  await expect(
    uploadedJob.queueItem.getByLabel("Administrative OCR test input"),
  ).toHaveCount(0);
  return uploadedJob;
}

async function createReviewedLesson(
  page: Page,
  filename: string,
  note: string,
  options: { boardCards?: string; street?: "flop" | "turn" } = {},
): Promise<{ id: string }> {
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  if (options.boardCards !== undefined) {
    await page.getByLabel("Board cards").fill(options.boardCards);
  }
  if (options.street !== undefined) {
    await page.getByLabel("Street").selectOption(options.street);
  }
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", { name: "fold", exact: true })
    .click();
  await decisionPanel
    .getByRole("button", { name: "high", exact: true })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");
  await page.getByLabel("Training review note").fill(note);
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed" })
    .click();
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "Reviewed",
  );
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();
  return { id: uploadedJob.id };
}

async function createPendingTrainingReview(
  page: Page,
  filename: string,
  options: {
    boardCards?: string;
    certainty?: "high" | "medium" | "low";
    decisionAction?: "fold" | "check" | "call" | "bet" | "raise";
    decisionSizing?: number;
    heroPosition?: string;
    recommendationControl?: string;
    street: "flop" | "turn" | "river";
  },
): Promise<{ id: string }> {
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  const handReview = page.getByRole("region", { name: "Hand review" });
  if (options.boardCards !== undefined) {
    await handReview.getByLabel("Board cards").fill(options.boardCards);
  }
  if (options.heroPosition !== undefined) {
    await handReview.getByLabel("Hero position").fill(options.heroPosition);
  }
  await handReview
    .getByRole("combobox", { name: /^Street/ })
    .selectOption(options.street);
  await handReview.getByRole("button", { name: "Approve state" }).click();

  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: options.decisionAction ?? "fold",
      exact: true,
    })
    .click();
  if (options.decisionSizing !== undefined) {
    await decisionPanel
      .getByLabel("Decision sizing in BB")
      .fill(String(options.decisionSizing));
  }
  if (options.certainty !== undefined) {
    await decisionPanel
      .getByRole("button", {
        name: options.certainty,
        exact: true,
      })
      .click();
  }
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  if (options.recommendationControl !== undefined) {
    const armResponse = await page.request.post(
      `${PROVIDER_URL}/control/${options.recommendationControl}`,
    );
    expect(armResponse.ok()).toBe(true);
  }
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();
  return { id: uploadedJob.id };
}

async function completeStaleTrainingReviews(
  page: Page,
  fixturePrefix: string,
): Promise<void> {
  const staleProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(staleProgressResponse.ok()).toBe(true);
  const staleProgress = (await staleProgressResponse.json()) as {
    recent_hands: Array<{
      job_id: string;
      original_filename: string;
      reviewed_at: string | null;
    }>;
  };
  for (const staleHand of staleProgress.recent_hands) {
    if (
      staleHand.reviewed_at !== null ||
      !staleHand.original_filename.startsWith(fixturePrefix)
    ) {
      continue;
    }
    const cleanupResponse = await page.request.put(
      `${BACKEND_URL}/api/jobs/${staleHand.job_id}/training-review`,
      { data: { note: null } },
    );
    expect(cleanupResponse.ok()).toBe(true);
  }
}

async function expectDetailedSolverEvidence(page: Page): Promise<void> {
  const evidence = page.getByLabel("Decision evidence");
  await expect(evidence).toContainText("e2e provider stub");
  await expect(evidence.getByText("Range equity").locator("..")).toContainText(
    "61%",
  );
  await expect(evidence.getByText("Realized").locator("..")).toContainText(
    "55%",
  );
  await expect(evidence.getByText("Call price").locator("..")).toContainText(
    "20%",
  );
  const comparedActions = evidence.getByRole("list", {
    name: "Compared actions",
  });
  await expect(comparedActions.getByRole("listitem")).toHaveCount(3);
  const chosenAction = comparedActions.getByRole("listitem").filter({
    hasText: "Chosen",
  });
  await expect(chosenAction).toContainText("call");
  await expect(chosenAction).toContainText("EV 1.4 BB");
  await expect(chosenAction).toContainText("78% frequency");
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
  await markLegacyJobs(page, [uploadedJob.id]);
  return { id: uploadedJob.id };
}

async function expectAnalyzerReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("region", { name: "Analyzer controls" }),
  ).toBeVisible();
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

test("marks an administrative upload and withholds its recommendation", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("administrative-upload", testInfo);
  const uploadedJob = await uploadAdministrativeScreenshot(page, filename);

  await expect(
    uploadedJob.queueItem.getByLabel("Administrative OCR test input"),
  ).toContainText("Admin test");
  const handReview = page.getByRole("region", { name: "Hand review" });
  await expect(
    handReview.getByLabel("Administrative OCR test input"),
  ).toContainText("Admin test");
  await expect(handReview).toContainText(ADMINISTRATIVE_REVIEW_NOTICE);
  const recommendButton = page.getByRole("button", {
    name: "Request recommendation",
  });
  await expect(recommendButton).toBeDisabled();

  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(uploadedJob.queueItem).toContainText("approved");
  await expect(recommendButton).toBeDisabled();
  await expect(
    page.getByRole("region", { name: "Your training decision" }),
  ).toHaveCount(0);

  const refusedRecommendation = await page.request.post(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}/recommend`,
  );
  expect(refusedRecommendation.status()).toBe(403);
  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  expect(await persistedResponse.json()).toMatchObject({
    input_context: "administrative_test",
    recommendation: null,
    status: "approved",
  });

  const progressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(progressResponse.ok()).toBe(true);
  const progress = (await progressResponse.json()) as {
    recent_hands: Array<{ job_id: string }>;
    review_queue: Array<{ job_id: string }>;
  };
  expect(
    [...progress.recent_hands, ...progress.review_queue].some(
      (hand) => hand.job_id === uploadedJob.id,
    ),
  ).toBe(false);

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();
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
    input_context: "administrative_test",
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
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Request recommendation" }),
  ).toBeDisabled();
  await expect(page.getByRole("region", { name: "Hand review" })).toContainText(
    ADMINISTRATIVE_REVIEW_NOTICE,
  );
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
    input_context: string;
    recommendation: { raw: Record<string, string> } | null;
    status: string;
    upload_request_id: string | null;
  };
  expect(persistedJob).toMatchObject({
    approved_state: null,
    archived_at: null,
    input_context: "administrative_test",
    recommendation: null,
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

  // Administrative captures never reach `recommended`, so each frame is
  // approved by hand before it can leave the queue.
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
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toHaveCount(0);
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
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toHaveCount(0);
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

  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  const queueItem = uploadedJob.queueItem;
  await expect(page.getByLabel("Hero cards")).toHaveValue("Ah Kd");
  await expect(page.getByLabel("Board cards")).toHaveValue("Qs Jc 2h");

  await page.getByLabel("Pot").fill("13");
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(
    page.getByRole("region", { name: "Your training decision" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toBeVisible();
  await expect(queueItem).toContainText("recommended");

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
  await expect(
    dialog.getByLabel("Administrative OCR test input"),
  ).toContainText("Admin test");
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

test("completes and reopens a training review from persisted progress", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("training-review", testInfo);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    lesson_count: number;
    needs_review_hands: number;
    reviewed_hands: number;
  };

  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await expect(decisionPanel).toBeVisible();
  await decisionPanel.getByRole("button", { name: "fold" }).click();
  await decisionPanel.getByRole("button", { name: "high" }).click();

  const decisionResponsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${BACKEND_URL}/api/jobs/${uploadedJob.id}/decision` &&
      response.request().method() === "PUT",
  );
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  expect((await decisionResponsePromise).ok()).toBe(true);
  await expect(decisionPanel).toContainText("Answer locked");
  await expect(decisionPanel).toContainText("Saved before reveal");

  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");
  const recommendation = page.getByRole("region", { name: "Recommendation" });
  await expect(recommendation).toBeVisible();
  await expect(recommendation).toContainText("call");
  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Fold");
  await expect(comparison).toContainText("High certainty");
  await expect(comparison).toContainText("Different action");

  const lessonNote = "Compare pot odds before folding to a single bet.";
  await page.getByLabel("Training review note").fill(lessonNote);
  const completeResponsePromise = page.waitForResponse(
    (response) =>
      response.url() ===
        `${BACKEND_URL}/api/jobs/${uploadedJob.id}/training-review` &&
      response.request().method() === "PUT",
  );
  await comparison.getByRole("button", { name: "Mark reviewed" }).click();
  expect((await completeResponsePromise).ok()).toBe(true);
  await expect(comparison).toContainText("Reviewed");
  await expect(page.getByLabel("Saved training review note")).toContainText(
    lessonNote,
  );

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  await expect(progressDialog).toBeVisible();
  const progressSummary = progressDialog.getByLabel(
    "Training progress summary",
  );
  await expect(progressSummary).toContainText(
    String(initialProgress.reviewed_hands + 1),
  );
  const trainingRow = progressDialog.getByRole("button", {
    name: `Open ${filename} training review`,
    exact: true,
  });
  await expect(trainingRow).toContainText("Fold");
  await expect(trainingRow).toContainText("Call");
  await expect(trainingRow).toContainText(lessonNote);
  await expect(trainingRow).toContainText("Reviewed");

  await trainingRow.click();
  await expect(progressDialog).toBeHidden();
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "Reviewed",
  );
  await expect(page.getByLabel("Saved training review note")).toContainText(
    lessonNote,
  );

  const reopenResponsePromise = page.waitForResponse(
    (response) =>
      response.url() ===
        `${BACKEND_URL}/api/jobs/${uploadedJob.id}/training-review` &&
      response.request().method() === "DELETE",
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Reopen review" })
    .click();
  expect((await reopenResponsePromise).ok()).toBe(true);
  await expect(page.getByText("Training review reopened")).toBeVisible();
  await expect(page.getByLabel("Training review note")).toHaveValue(lessonNote);

  const recompleteResponsePromise = page.waitForResponse(
    (response) =>
      response.url() ===
        `${BACKEND_URL}/api/jobs/${uploadedJob.id}/training-review` &&
      response.request().method() === "PUT",
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed" })
    .click();
  expect((await recompleteResponsePromise).ok()).toBe(true);
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "Reviewed",
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    recommendation: { action: string } | null;
    training_decision: { action: string; certainty: string | null } | null;
    training_review_note: string | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    recommendation: { action: "call" },
    training_decision: { action: "fold", certainty: "high" },
    training_review_note: lessonNote,
    training_reviewed_at: expect.any(String),
  });

  const finalProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(finalProgressResponse.ok()).toBe(true);
  const finalProgress = (await finalProgressResponse.json()) as {
    lesson_count: number;
    needs_review_hands: number;
    reviewed_hands: number;
  };
  expect(finalProgress).toMatchObject({
    lesson_count: initialProgress.lesson_count + 1,
    needs_review_hands: initialProgress.needs_review_hands,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
});

test("continues through a filtered persisted training review queue", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const staleProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(staleProgressResponse.ok()).toBe(true);
  const staleProgress = (await staleProgressResponse.json()) as {
    review_queue: Array<{ job_id: string; original_filename: string }>;
  };
  const attemptMarker = [
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
  ].join("-");
  const staleFixturePrefixes = [
    "review-control-flop-",
    "review-turn-older-",
    "review-turn-newer-",
  ];
  for (const staleHand of staleProgress.review_queue) {
    if (
      !staleHand.original_filename.includes(attemptMarker) ||
      !staleFixturePrefixes.some((prefix) =>
        staleHand.original_filename.startsWith(prefix),
      )
    ) {
      continue;
    }
    const cleanupResponse = await page.request.put(
      `${BACKEND_URL}/api/jobs/${staleHand.job_id}/training-review`,
      { data: { note: null } },
    );
    expect(cleanupResponse.ok()).toBe(true);
  }

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const controlFilename = attemptFilename("review-control-flop", testInfo);
  const olderTurnFilename = attemptFilename("review-turn-older", testInfo);
  const newerTurnFilename = attemptFilename("review-turn-newer", testInfo);
  const controlJob = await createPendingTrainingReview(page, controlFilename, {
    certainty: "low",
    street: "flop",
  });
  const olderTurnJob = await createPendingTrainingReview(
    page,
    olderTurnFilename,
    {
      boardCards: "Qs Jc 2h 9d",
      certainty: "high",
      street: "turn",
    },
  );
  const newerTurnJob = await createPendingTrainingReview(
    page,
    newerTurnFilename,
    {
      boardCards: "Qs Jc 2h 8s",
      certainty: "high",
      street: "turn",
    },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const expectedPendingCount = initialProgress.needs_review_hands + 3;
  await progressDialog
    .getByRole("button", {
      name: `Needs review ${expectedPendingCount}`,
      exact: true,
    })
    .click();
  await progressDialog.getByLabel("Review street").selectOption("turn");
  await progressDialog.getByLabel("Review certainty").selectOption("high");

  const olderTurnReview = progressDialog.getByRole("button", {
    name: `Open ${olderTurnFilename} training review`,
    exact: true,
  });
  const newerTurnReview = progressDialog.getByRole("button", {
    name: `Open ${newerTurnFilename} training review`,
    exact: true,
  });
  await expect(newerTurnReview).toBeVisible();
  await expect(olderTurnReview).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${controlFilename} training review`,
      exact: true,
    }),
  ).toBeHidden();

  await progressDialog.getByRole("button", { name: "Review next" }).click();
  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${newerTurnJob.id}/image`);
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${olderTurnJob.id}/image`);
  await expect(
    page.getByText("Training review completed. Next hand ready"),
  ).toBeVisible();
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(progressDialog.getByLabel("Review street")).toHaveValue("turn");
  await expect(progressDialog.getByLabel("Review certainty")).toHaveValue(
    "high",
  );
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 1}`,
      exact: true,
    }),
  ).toBeVisible();

  for (const reviewedJob of [newerTurnJob, olderTurnJob]) {
    const persistedResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${reviewedJob.id}`,
    );
    expect(persistedResponse.ok()).toBe(true);
    const persistedJob = (await persistedResponse.json()) as {
      training_reviewed_at: string | null;
    };
    expect(persistedJob.training_reviewed_at).toEqual(expect.any(String));
  }
  const controlResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${controlJob.id}`,
  );
  expect(controlResponse.ok()).toBe(true);
  const persistedControl = (await controlResponse.json()) as {
    training_reviewed_at: string | null;
  };
  expect(persistedControl.training_reviewed_at).toBeNull();

  const cleanupResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${controlJob.id}/training-review`,
    { data: { note: null } },
  );
  expect(cleanupResponse.ok()).toBe(true);
});

test("drills into persisted solver attribution", async ({ page }, testInfo) => {
  await openUploadInput(page);

  const fixturePrefix = [
    "solver-attribution",
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
  ].join("-");
  await completeStaleTrainingReviews(page, fixturePrefix);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    solver_coverage: {
      routes: Array<{ engine: string; hands: number }>;
    };
  };
  const initialRouteHands =
    initialProgress.solver_coverage.routes.find(
      (route) => route.engine === "e2e_provider_stub",
    )?.hands ?? 0;

  const filename = attemptFilename("solver-attribution", testInfo);
  const attributedJob = await createPendingTrainingReview(page, filename, {
    certainty: "medium",
    street: "flop",
  });

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  await expect(
    progressDialog.getByRole("heading", {
      name: "Solver coverage",
    }),
  ).toBeVisible();
  const expectedRouteHands = initialRouteHands + 1;
  const routeButton = progressDialog.getByRole("button", {
    name: new RegExp(
      `^Show ${expectedRouteHands} ${expectedRouteHands === 1 ? "hand" : "hands"}` +
        " handled by e2e provider stub\\.",
    ),
  });
  await expect(routeButton).toBeVisible();
  await routeButton.click();

  const activeSolverFilter = progressDialog.getByLabel("Active solver filter");
  await expect(activeSolverFilter).toContainText("e2e provider stub");
  const attributedReview = progressDialog.getByRole("button", {
    name: `Open ${filename} training review`,
    exact: true,
  });
  await expect(attributedReview).toBeVisible();
  await attributedReview.click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${attributedJob.id}/image`);
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed" })
    .click();
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "Reviewed",
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${attributedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: { raw: Record<string, unknown> } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    recommendation: {
      raw: { engine: "e2e_provider_stub" },
    },
    training_reviewed_at: expect.any(String),
  });
});

test("drills into a persisted solver fallback", async ({ page }, testInfo) => {
  await openUploadInput(page);

  const fixturePrefix = [
    "solver-fallback",
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
  ].join("-");
  await completeStaleTrainingReviews(page, fixturePrefix);
  const fallbackReason = "E2E fallback: unsupported postflop tree";
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    solver_coverage: {
      fallback_reasons: Array<{ reason: string; hands: number }>;
    };
  };
  const initialFallbackHands =
    initialProgress.solver_coverage.fallback_reasons.find(
      (fallback) => fallback.reason === fallbackReason,
    )?.hands ?? 0;

  const armResponse = await page.request.post(
    `${PROVIDER_URL}/control/fallback-next-recommendation`,
  );
  expect(armResponse.ok()).toBe(true);
  const filename = attemptFilename("solver-fallback", testInfo);
  const fallbackJob = await createPendingTrainingReview(page, filename, {
    certainty: "medium",
    street: "flop",
  });

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const expectedFallbackHands = initialFallbackHands + 1;
  const fallbackButton = progressDialog.getByRole("button", {
    name: new RegExp(
      `^Show ${expectedFallbackHands} ${expectedFallbackHands === 1 ? "hand" : "hands"}` +
        ` using fallback: ${fallbackReason}\\.`,
    ),
  });
  await expect(fallbackButton).toBeVisible();
  await fallbackButton.click();

  const activeSolverFilter = progressDialog.getByLabel("Active solver filter");
  await expect(activeSolverFilter).toContainText(fallbackReason);
  const fallbackReview = progressDialog.getByRole("button", {
    name: `Open ${filename} training review`,
    exact: true,
  });
  await expect(fallbackReview).toBeVisible();
  await fallbackReview.click();

  await expect(progressDialog).toBeHidden();
  const recommendation = page.getByRole("region", { name: "Recommendation" });
  await expect(recommendation).toContainText(fallbackReason);
  await expect(recommendation).toContainText("Postflop solver fallback");
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed" })
    .click();
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "Reviewed",
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${fallbackJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: { raw: Record<string, unknown> } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    recommendation: {
      raw: {
        engine: "e2e_provider_stub",
        fallback_reason: fallbackReason,
        requested_engine: "postflop_solver",
      },
    },
    training_reviewed_at: expect.any(String),
  });
});

test("renders persisted solver evidence and prioritizes EV loss", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const fixturePrefix = "solver-evidence-";
  await completeStaleTrainingReviews(page, fixturePrefix);
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const filename = attemptFilename("solver-evidence", testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "fold",
      exact: true,
    })
    .click();
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}/control/evidence-next-recommendation`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  await expectDetailedSolverEvidence(page);
  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Different action");
  await expect(comparison).toContainText("1.4 BB EV loss");

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();
  const lowerLossFilename = attemptFilename("solver-evidence-lower", testInfo);
  const lowerLossJob = await createPendingTrainingReview(
    page,
    lowerLossFilename,
    {
      certainty: "medium",
      recommendationControl: "lower-evidence-next-recommendation",
      street: "flop",
    },
  );
  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  await progressDialog
    .getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 2}`,
      exact: true,
    })
    .click();
  await progressDialog.getByLabel("Review order").selectOption("ev_loss");
  const reviewHands = progressDialog.getByRole("button", {
    name: /^Open .* training review$/,
  });
  await expect(reviewHands.first()).toHaveAccessibleName(
    `Open ${filename} training review`,
  );
  await expect(reviewHands.first()).toContainText("EV loss: 1.4 BB");
  await expect(reviewHands.nth(1)).toHaveAccessibleName(
    `Open ${lowerLossFilename} training review`,
  );
  await expect(reviewHands.nth(1)).toContainText("EV loss: 0.4 BB");
  await progressDialog
    .getByRole("button", {
      name: "Review highest loss",
    })
    .click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${uploadedJob.id}/image`);
  await expectDetailedSolverEvidence(page);
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${lowerLossJob.id}/image`);
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "0.4 BB EV loss",
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();
  await expect(progressDialog).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands}`,
      exact: true,
    }),
  ).toBeVisible();

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: { raw: Record<string, unknown> } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    recommendation: {
      raw: {
        candidates: expect.arrayContaining([
          { action: "call", sizing: null, ev: 1.4, frequency: 0.78 },
          { action: "fold", sizing: null, ev: 0, frequency: 0.02 },
        ]),
        engine: "e2e_provider_stub",
        equity: { equity: 0.61 },
      },
    },
    training_reviewed_at: expect.any(String),
  });
  const persistedLowerLossResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${lowerLossJob.id}`,
  );
  expect(persistedLowerLossResponse.ok()).toBe(true);
  const persistedLowerLossJob = (await persistedLowerLossResponse.json()) as {
    training_reviewed_at: string | null;
  };
  expect(persistedLowerLossJob.training_reviewed_at).toEqual(
    expect.any(String),
  );
});

test("opens the suggested highest-loss action pattern", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  await completeStaleTrainingReviews(page, "suggested-pattern-");
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const controlFilename = attemptFilename(
    "suggested-pattern-control",
    testInfo,
  );
  const controlJob = await createPendingTrainingReview(page, controlFilename, {
    certainty: "low",
    recommendationControl: "lower-evidence-next-recommendation",
    street: "flop",
  });
  const olderTargetFilename = attemptFilename(
    "suggested-pattern-target-older",
    testInfo,
  );
  const olderTargetJob = await createPendingTrainingReview(
    page,
    olderTargetFilename,
    {
      certainty: "high",
      decisionAction: "raise",
      decisionSizing: 8,
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "turn",
    },
  );
  const newerTargetFilename = attemptFilename(
    "suggested-pattern-target-newer",
    testInfo,
  );
  const newerTargetJob = await createPendingTrainingReview(
    page,
    newerTargetFilename,
    {
      boardCards: "Qs Jc 2h 8s",
      certainty: "medium",
      decisionAction: "raise",
      decisionSizing: 8,
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "turn",
    },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const suggestedFocus = progressDialog.getByRole("button", {
    name: "Focus Raise to Call differences: Highest average EV loss: 2.2 BB",
  });
  await expect(suggestedFocus).toBeVisible();
  await suggestedFocus.click();

  await expect(progressDialog).toContainText(
    "2 pending review hands for Raise to Call across all streets.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${newerTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${olderTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${controlFilename} training review`,
    }),
  ).toBeHidden();
  await progressDialog.getByRole("button", { name: "Review next" }).click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${newerTargetJob.id}/image`,
  );
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "2.2 BB EV loss",
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${olderTargetJob.id}/image`,
  );
  await expect(
    page.getByText("Training review completed. Next hand ready"),
  ).toBeVisible();
  await expect(page.getByLabel("Training decision comparison")).toContainText(
    "2.2 BB EV loss",
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 1}`,
      exact: true,
    }),
  ).toBeVisible();

  for (const targetJob of [newerTargetJob, olderTargetJob]) {
    const targetResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${targetJob.id}`,
    );
    expect(targetResponse.ok()).toBe(true);
    const persistedTarget = (await targetResponse.json()) as {
      training_reviewed_at: string | null;
    };
    expect(persistedTarget.training_reviewed_at).toEqual(expect.any(String));
  }

  const controlResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${controlJob.id}`,
  );
  expect(controlResponse.ok()).toBe(true);
  const persistedControl = (await controlResponse.json()) as {
    training_reviewed_at: string | null;
  };
  expect(persistedControl.training_reviewed_at).toBeNull();
  const cleanupResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${controlJob.id}/training-review`,
    { data: { note: null } },
  );
  expect(cleanupResponse.ok()).toBe(true);
});

test("opens the suggested normalized-position review focus", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  await completeStaleTrainingReviews(page, "suggested-position-");
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const controlFilename = attemptFilename(
    "suggested-position-control",
    testInfo,
  );
  const controlJob = await createPendingTrainingReview(page, controlFilename, {
    certainty: "low",
    recommendationControl: "lower-evidence-next-recommendation",
    street: "flop",
  });
  const olderTargetFilename = attemptFilename(
    "suggested-position-target-older",
    testInfo,
  );
  const olderTargetJob = await createPendingTrainingReview(
    page,
    olderTargetFilename,
    {
      certainty: "high",
      heroPosition: "big blind",
      recommendationControl: "evidence-next-recommendation",
      street: "turn",
    },
  );
  const newerTargetFilename = attemptFilename(
    "suggested-position-target-newer",
    testInfo,
  );
  const newerTargetJob = await createPendingTrainingReview(
    page,
    newerTargetFilename,
    {
      boardCards: "Qs Jc 2h 8s",
      certainty: "medium",
      heroPosition: "bb",
      recommendationControl: "evidence-next-recommendation",
      street: "turn",
    },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const suggestedFocus = progressDialog.getByRole("button", {
    name: "Focus BB position reviews: Highest average EV loss: 1.4 BB",
  });
  await expect(suggestedFocus).toBeVisible();
  await suggestedFocus.click();

  const positionFilter = progressDialog.getByLabel(
    "Active review position filter",
  );
  await expect(positionFilter).toContainText("BB");
  await expect(progressDialog).toContainText(
    "2 pending review hands across all streets at BB.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${newerTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${olderTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${controlFilename} training review`,
    }),
  ).toBeHidden();
  await progressDialog.getByRole("button", { name: "Review next" }).click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${newerTargetJob.id}/image`,
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${olderTargetJob.id}/image`,
  );
  await expect(
    page.getByText("Training review completed. Next hand ready"),
  ).toBeVisible();
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(
    progressDialog.getByLabel("Active review position filter"),
  ).toContainText("BB");
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 1}`,
      exact: true,
    }),
  ).toBeVisible();

  const targetPositions = [
    [newerTargetJob, "bb"],
    [olderTargetJob, "big blind"],
  ] as const;
  for (const [targetJob, expectedPosition] of targetPositions) {
    const targetResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${targetJob.id}`,
    );
    expect(targetResponse.ok()).toBe(true);
    const persistedTarget = (await targetResponse.json()) as {
      approved_state: { hero_position: string | null } | null;
      training_reviewed_at: string | null;
    };
    expect(persistedTarget).toMatchObject({
      approved_state: { hero_position: expectedPosition },
      training_reviewed_at: expect.any(String),
    });
  }

  const controlResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${controlJob.id}`,
  );
  expect(controlResponse.ok()).toBe(true);
  const persistedControl = (await controlResponse.json()) as {
    training_reviewed_at: string | null;
  };
  expect(persistedControl.training_reviewed_at).toBeNull();
  const cleanupResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${controlJob.id}/training-review`,
    { data: { note: null } },
  );
  expect(cleanupResponse.ok()).toBe(true);
});

test("opens the suggested certainty review focus", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  await completeStaleTrainingReviews(page, "suggested-certainty-");
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const controlFilename = attemptFilename(
    "suggested-certainty-control",
    testInfo,
  );
  const controlJob = await createPendingTrainingReview(page, controlFilename, {
    certainty: "low",
    recommendationControl: "lower-evidence-next-recommendation",
    street: "flop",
  });
  const olderTargetFilename = attemptFilename(
    "suggested-certainty-target-older",
    testInfo,
  );
  const olderTargetJob = await createPendingTrainingReview(
    page,
    olderTargetFilename,
    {
      certainty: "high",
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "turn",
    },
  );
  const newerTargetFilename = attemptFilename(
    "suggested-certainty-target-newer",
    testInfo,
  );
  const newerTargetJob = await createPendingTrainingReview(
    page,
    newerTargetFilename,
    {
      boardCards: "Qs Jc 2h 8s",
      certainty: "high",
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "turn",
    },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const suggestedFocus = progressDialog.getByRole("button", {
    name: /^Focus high certainty reviews: Highest average EV loss: [\d.]+ BB$/,
  });
  await expect(suggestedFocus).toBeVisible();
  await suggestedFocus.click();

  await expect(progressDialog.getByLabel("Review certainty")).toHaveValue(
    "high",
  );
  await expect(progressDialog).toContainText(
    "2 pending review hands across all streets with high certainty.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${newerTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${olderTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${controlFilename} training review`,
    }),
  ).toBeHidden();
  await progressDialog.getByRole("button", { name: "Review next" }).click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${newerTargetJob.id}/image`,
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${olderTargetJob.id}/image`,
  );
  await expect(
    page.getByText("Training review completed. Next hand ready"),
  ).toBeVisible();
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(progressDialog.getByLabel("Review certainty")).toHaveValue(
    "high",
  );
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 1}`,
      exact: true,
    }),
  ).toBeVisible();

  for (const targetJob of [newerTargetJob, olderTargetJob]) {
    const targetResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${targetJob.id}`,
    );
    expect(targetResponse.ok()).toBe(true);
    const persistedTarget = (await targetResponse.json()) as {
      training_decision: { certainty: string | null } | null;
      training_reviewed_at: string | null;
    };
    expect(persistedTarget).toMatchObject({
      training_decision: { certainty: "high" },
      training_reviewed_at: expect.any(String),
    });
  }

  const controlResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${controlJob.id}`,
  );
  expect(controlResponse.ok()).toBe(true);
  const persistedControl = (await controlResponse.json()) as {
    training_decision: { certainty: string | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedControl).toMatchObject({
    training_decision: { certainty: "low" },
    training_reviewed_at: null,
  });
  const cleanupResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${controlJob.id}/training-review`,
    { data: { note: null } },
  );
  expect(cleanupResponse.ok()).toBe(true);
});

test("opens the suggested street review focus", async ({ page }, testInfo) => {
  await openUploadInput(page);

  await completeStaleTrainingReviews(page, "suggested-street-");
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const controlFilename = attemptFilename("suggested-street-control", testInfo);
  const controlJob = await createPendingTrainingReview(page, controlFilename, {
    certainty: "low",
    recommendationControl: "lower-evidence-next-recommendation",
    street: "flop",
  });
  const olderTargetFilename = attemptFilename(
    "suggested-street-target-older",
    testInfo,
  );
  const olderTargetJob = await createPendingTrainingReview(
    page,
    olderTargetFilename,
    {
      boardCards: "Qs Jc 2h 8s 7d",
      certainty: "high",
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "river",
    },
  );
  const newerTargetFilename = attemptFilename(
    "suggested-street-target-newer",
    testInfo,
  );
  const newerTargetJob = await createPendingTrainingReview(
    page,
    newerTargetFilename,
    {
      boardCards: "Qs Jc 2h 8s 6c",
      certainty: "medium",
      recommendationControl: "pattern-evidence-next-recommendation",
      street: "river",
    },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const suggestedFocus = progressDialog.getByRole("button", {
    name: /^Focus river reviews: Highest average EV loss: [\d.]+ BB$/,
  });
  await expect(suggestedFocus).toBeVisible();
  await suggestedFocus.click();

  await expect(progressDialog.getByLabel("Review street")).toHaveValue("river");
  await expect(progressDialog).toContainText(
    "2 pending review hands on river.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${newerTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${olderTargetFilename} training review`,
    }),
  ).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${controlFilename} training review`,
    }),
  ).toBeHidden();
  await progressDialog.getByRole("button", { name: "Review next" }).click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${newerTargetJob.id}/image`,
  );
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute(
    "src",
    `${BACKEND_URL}/api/jobs/${olderTargetJob.id}/image`,
  );
  await expect(
    page.getByText("Training review completed. Next hand ready"),
  ).toBeVisible();
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(progressDialog.getByLabel("Review street")).toHaveValue("river");
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands + 1}`,
      exact: true,
    }),
  ).toBeVisible();

  for (const targetJob of [newerTargetJob, olderTargetJob]) {
    const targetResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${targetJob.id}`,
    );
    expect(targetResponse.ok()).toBe(true);
    const persistedTarget = (await targetResponse.json()) as {
      approved_state: {
        board_cards: Array<{ rank: string; suit: string }>;
        street: string | null;
      } | null;
      training_reviewed_at: string | null;
    };
    expect(persistedTarget).toMatchObject({
      approved_state: {
        board_cards: expect.arrayContaining([{ rank: "8", suit: "spades" }]),
        street: "river",
      },
      training_reviewed_at: expect.any(String),
    });
    expect(persistedTarget.approved_state?.board_cards).toHaveLength(5);
  }

  const controlResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${controlJob.id}`,
  );
  expect(controlResponse.ok()).toBe(true);
  const persistedControl = (await controlResponse.json()) as {
    approved_state: { street: string | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedControl).toMatchObject({
    approved_state: { street: "flop" },
    training_reviewed_at: null,
  });
  const cleanupResponse = await page.request.put(
    `${BACKEND_URL}/api/jobs/${controlJob.id}/training-review`,
    { data: { note: null } },
  );
  expect(cleanupResponse.ok()).toBe(true);
});

test("opens legacy review focus by unrated and unpositioned state", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  await completeStaleTrainingReviews(page, "legacy-focus-");
  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    needs_review_hands: number;
  };

  const filename = attemptFilename("legacy-focus", testInfo);
  const legacyJob = await createPendingTrainingReview(page, filename, {
    heroPosition: "",
    recommendationControl: "evidence-next-recommendation",
    street: "flop",
  });

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  const unratedFocus = progressDialog.getByRole("button", {
    name: "Focus unrated reviews: 1 legacy hand needs review",
  });
  const unpositionedFocus = progressDialog.getByRole("button", {
    name: "Focus unpositioned reviews: 1 unpositioned hand needs review",
  });
  await expect(unratedFocus).toBeVisible();
  await expect(unpositionedFocus).toBeVisible();

  await unratedFocus.click();
  await expect(progressDialog.getByLabel("Review certainty")).toHaveValue(
    "unrated",
  );
  await expect(progressDialog).toContainText(
    "1 pending review hand across all streets without a certainty rating.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${filename} training review`,
    }),
  ).toBeVisible();

  const recentView = progressDialog.getByRole("button", { name: "Recent" });
  await recentView.click();
  await expect(recentView).toHaveAttribute("aria-pressed", "true");
  const refreshedUnpositionedFocus = progressDialog.getByRole("button", {
    name: "Focus unpositioned reviews: 1 unpositioned hand needs review",
  });
  await expect(refreshedUnpositionedFocus).toBeVisible();
  await refreshedUnpositionedFocus.click();

  await expect(progressDialog.getByLabel("Review certainty")).toHaveValue(
    "all",
  );
  await expect(
    progressDialog.getByLabel("Active review position filter"),
  ).toContainText("Unpositioned");
  await expect(progressDialog).toContainText(
    "1 pending review hand across all streets without a recorded position.",
  );
  await progressDialog.getByRole("button", { name: "Review next" }).click();

  await expect(progressDialog).toBeHidden();
  await expect(
    page.getByAltText("Uploaded poker table screenshot"),
  ).toHaveAttribute("src", `${BACKEND_URL}/api/jobs/${legacyJob.id}/image`);
  await page
    .getByLabel("Training decision comparison")
    .getByRole("button", { name: "Mark reviewed & next" })
    .click();

  await expect(progressDialog).toBeVisible();
  await expect(
    progressDialog.getByLabel("Active review position filter"),
  ).toContainText("Unpositioned");
  await expect(progressDialog).toContainText(
    "No action or sizing differences need review.",
  );
  await expect(
    progressDialog.getByRole("button", {
      name: `Needs review ${initialProgress.needs_review_hands}`,
      exact: true,
    }),
  ).toBeVisible();

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${legacyJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    approved_state: { hero_position: string | null } | null;
    training_decision: { certainty: string | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    approved_state: { hero_position: null },
    training_decision: { certainty: null },
    training_reviewed_at: expect.any(String),
  });
});

const gradedSupportedMixCases = [
  {
    filename: "supported-mix",
    controlPath: "/control/evidence-next-recommendation",
    unrelatedAction: "fold",
    unrelatedEv: 0,
    unrelatedSizing: null,
  },
  {
    filename: "supported-mix-unrelated-nonnumeric-ev",
    controlPath: "/control/unrelated-nonnumeric-ev-next-recommendation",
    unrelatedAction: "fold",
    unrelatedEv: "99",
    unrelatedSizing: null,
  },
  {
    filename: "supported-mix-unrelated-invalid-sizing",
    controlPath: "/control/unrelated-invalid-sizing-next-recommendation",
    unrelatedAction: "bet",
    unrelatedEv: 99,
    unrelatedSizing: -1,
  },
  {
    filename: "supported-mix-unrelated-invalid-action",
    controlPath: "/control/unrelated-invalid-action-next-recommendation",
    unrelatedAction: "jam",
    unrelatedEv: 99,
    unrelatedSizing: null,
  },
  {
    filename: "supported-mix-ev-candidate-invalid-frequency",
    controlPath: "/control/ev-candidate-invalid-frequency-next-recommendation",
    expectedEvLoss: 0.9,
    unrelatedAction: "bet",
    unrelatedEv: 2,
    unrelatedFrequency: "20%",
    unrelatedSizing: 6,
  },
  {
    filename: "supported-mix-missing-recommended-frequency",
    controlPath: "/control/missing-recommended-frequency-next-recommendation",
    recommendedCandidate: { action: "call", sizing: null, ev: 1.4 },
    unrelatedAction: "fold",
    unrelatedEv: 0,
    unrelatedSizing: null,
  },
  {
    filename: "supported-mix-malformed-recommended-frequency",
    controlPath: "/control/malformed-recommended-frequency-next-recommendation",
    recommendedCandidate: {
      action: "call",
      sizing: null,
      ev: 1.4,
      frequency: "78%",
    },
    unrelatedAction: "fold",
    unrelatedEv: 0,
    unrelatedSizing: null,
  },
  {
    filename: "supported-mix-maximum-frequency-boundary",
    controlPath: "/control/maximum-frequency-boundary-next-recommendation",
    alternateFrequency: 1,
    unrelatedAction: "fold",
    unrelatedEv: 0,
    unrelatedSizing: null,
  },
].map((evidenceCase) => ({
  alternateFrequency: 0.2,
  expectedEvLoss: 0.3,
  recommendedCandidate: {
    action: "call",
    sizing: null,
    ev: 1.4,
    frequency: 0.78,
  },
  unrelatedFrequency: 0.02,
  ...evidenceCase,
}));

async function verifyGradedSupportedMix(
  page: Page,
  testInfo: TestInfo,
  evidenceCase: (typeof gradedSupportedMixCases)[number],
): Promise<void> {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename(evidenceCase.filename, testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}${evidenceCase.controlPath}`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Solver-supported mix");
  await expect(comparison).toContainText(
    `${evidenceCase.expectedEvLoss} BB EV loss`,
  );
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{
      ev_loss_bb: number | null;
      job_id: string;
      outcome: string;
    }>;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    ev_compared_hands: initialProgress.ev_compared_hands + 1,
    exact_matches: initialProgress.exact_matches + 1,
    needs_review_hands: initialProgress.needs_review_hands,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        ev_loss_bb: evidenceCase.expectedEvLoss,
        job_id: uploadedJob.id,
        outcome: "mixed",
      }),
    ]),
  );

  const filteredProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress` +
      "?review_decision_action=raise&review_recommended_action=call",
  );
  expect(filteredProgressResponse.ok()).toBe(true);
  const filteredProgress = (await filteredProgressResponse.json()) as {
    review_queue: Array<{ job_id: string }>;
  };
  expect(filteredProgress.review_queue).not.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ job_id: uploadedJob.id }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    recommendation: { raw: Record<string, unknown> } | null;
    training_decision: { action: string; sizing: number | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    recommendation: {
      raw: {
        candidates: expect.arrayContaining([
          evidenceCase.recommendedCandidate,
          {
            action: "raise",
            sizing: 8,
            ev: 1.1,
            frequency: evidenceCase.alternateFrequency,
          },
          {
            action: evidenceCase.unrelatedAction,
            sizing: evidenceCase.unrelatedSizing,
            ev: evidenceCase.unrelatedEv,
            frequency: evidenceCase.unrelatedFrequency,
          },
        ]),
      },
    },
    training_decision: { action: "raise", sizing: 8 },
    training_reviewed_at: null,
  });
}

test("keeps a solver-supported mixed action out of review", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[0]);
});

test("ignores unrelated nonnumeric EV when grading a supported mix", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[1]);
});

test("ignores unrelated invalid sizing when grading a supported mix", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[2]);
});

test("ignores unrelated invalid action when grading a supported mix", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[3]);
});

test("grades valid EV evidence without candidate frequency metadata", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[4]);
});

test("grades recommended-line EV without frequency metadata", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[5]);
});

test("grades recommended-line EV with malformed frequency metadata", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[6]);
});

test("supports a policy candidate at the maximum frequency boundary", async ({
  page,
}, testInfo) => {
  await verifyGradedSupportedMix(page, testInfo, gradedSupportedMixCases[7]);
});

test("applies the solver policy-support frequency boundary", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  async function processFrequencyCase(
    filename: string,
    controlPath: string,
    expectedLabel: string,
    needsReview: boolean,
  ) {
    const uploadedJob = await uploadLegacyScreenshot(page, filename);
    await page.getByRole("button", { name: "Approve state" }).click();
    const decisionPanel = page.getByRole("region", {
      name: "Your training decision",
    });
    await decisionPanel
      .getByRole("button", {
        name: "raise",
        exact: true,
      })
      .click();
    await decisionPanel.getByLabel("Decision sizing in BB").fill("8");
    await decisionPanel
      .getByRole("button", {
        name: "medium",
        exact: true,
      })
      .click();
    await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
    await expect(decisionPanel).toContainText("Answer locked");

    const armResponse = await page.request.post(
      `${PROVIDER_URL}${controlPath}`,
    );
    expect(armResponse.ok()).toBe(true);
    await page.getByRole("button", { name: "Request recommendation" }).click();
    await expect(uploadedJob.queueItem).toContainText("recommended");

    const comparison = page.getByLabel("Training decision comparison");
    await expect(comparison).toContainText(expectedLabel);
    if (needsReview) {
      await expect(
        comparison.getByRole("button", {
          name: "Mark reviewed",
        }),
      ).toBeVisible();
    } else {
      await expect(
        comparison.getByRole("button", {
          name: "Mark reviewed",
        }),
      ).toBeHidden();
    }

    await page.getByRole("button", { name: "Clear reviewed" }).click();
    await expect(uploadedJob.queueItem).toBeHidden();
    return uploadedJob;
  }

  const boundaryJob = await processFrequencyCase(
    attemptFilename("frequency-boundary-supported", testInfo),
    "/control/frequency-boundary-next-recommendation",
    "Solver-supported mix",
    false,
  );
  const belowBoundaryJob = await processFrequencyCase(
    attemptFilename("frequency-boundary-review", testInfo),
    "/control/below-frequency-boundary-next-recommendation",
    "Different action",
    true,
  );

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{ job_id: string; outcome: string }>;
    review_queue: Array<{ job_id: string; outcome: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions + 1,
    exact_matches: initialProgress.exact_matches + 1,
    needs_review_hands: initialProgress.needs_review_hands + 1,
    review_queue_hands: initialProgress.review_queue_hands + 1,
    reviewed_hands: initialProgress.reviewed_hands + 2,
  });
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: boundaryJob.id,
        outcome: "mixed",
      }),
      expect.objectContaining({
        job_id: belowBoundaryJob.id,
        outcome: "different",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: belowBoundaryJob.id,
        outcome: "different",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).not.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ job_id: boundaryJob.id }),
    ]),
  );

  const boundaryResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${boundaryJob.id}`,
  );
  const belowBoundaryResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${belowBoundaryJob.id}`,
  );
  expect(boundaryResponse.ok()).toBe(true);
  expect(belowBoundaryResponse.ok()).toBe(true);
  const boundaryPersistedJob = (await boundaryResponse.json()) as {
    recommendation: { raw: Record<string, unknown> } | null;
  };
  const belowBoundaryPersistedJob = (await belowBoundaryResponse.json()) as {
    recommendation: { raw: Record<string, unknown> } | null;
  };
  expect(boundaryPersistedJob.recommendation?.raw).toMatchObject({
    candidates: expect.arrayContaining([
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.05 },
    ]),
  });
  expect(belowBoundaryPersistedJob.recommendation?.raw).toMatchObject({
    candidates: expect.arrayContaining([
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.049999 },
    ]),
  });
});

const unsupportedPolicyCases = [
  {
    filename: "malformed-policy-candidate",
    controlPath: "/control/malformed-policy-next-recommendation",
    expectedCandidate: { action: "raise", ev: 1.1, frequency: 0.2 },
    expectedEvLoss: null,
  },
  {
    filename: "malformed-policy-frequency",
    controlPath: "/control/malformed-policy-frequency-next-recommendation",
    expectedCandidate: {
      action: "raise",
      sizing: 8,
      ev: 1.1,
      frequency: "20%",
    },
    expectedEvLoss: 0.3,
  },
  {
    filename: "above-policy-frequency-maximum",
    controlPath: "/control/above-frequency-maximum-next-recommendation",
    expectedCandidate: {
      action: "raise",
      sizing: 8,
      ev: 1.1,
      frequency: 1.000001,
    },
    expectedEvLoss: 0.3,
  },
  {
    filename: "missing-policy-frequency",
    controlPath: "/control/missing-policy-frequency-next-recommendation",
    expectedCandidate: {
      action: "raise",
      sizing: 8,
      ev: 1.1,
    },
    expectedEvLoss: 0.3,
  },
];

async function verifyUnsupportedPolicyCandidate(
  page: Page,
  testInfo: TestInfo,
  evidenceCase: (typeof unsupportedPolicyCases)[number],
): Promise<void> {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename(evidenceCase.filename, testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}${evidenceCase.controlPath}`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Different action");
  if (evidenceCase.expectedEvLoss === null) {
    await expect(comparison).not.toContainText("BB EV loss");
  } else {
    await expect(comparison).toContainText(
      `${evidenceCase.expectedEvLoss} BB EV loss`,
    );
  }
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{
      ev_loss_bb: number | null;
      job_id: string;
      outcome: string;
    }>;
    review_queue: Array<{ job_id: string; outcome: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches,
    different_actions: initialProgress.different_actions + 1,
    ev_compared_hands:
      initialProgress.ev_compared_hands +
      (evidenceCase.expectedEvLoss === null ? 0 : 1),
    exact_matches: initialProgress.exact_matches,
    needs_review_hands: initialProgress.needs_review_hands + 1,
    review_queue_hands: initialProgress.review_queue_hands + 1,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        ev_loss_bb: evidenceCase.expectedEvLoss,
        job_id: uploadedJob.id,
        outcome: "different",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "different",
      }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: {
      raw: { candidates: Array<Record<string, unknown>> };
    } | null;
  };
  expect(persistedJob.recommendation?.raw.candidates).toEqual(
    expect.arrayContaining([evidenceCase.expectedCandidate]),
  );
}

test("keeps a malformed solver candidate out of policy support", async ({
  page,
}, testInfo) => {
  await verifyUnsupportedPolicyCandidate(
    page,
    testInfo,
    unsupportedPolicyCases[0],
  );
});

test("grades EV without granting support to malformed frequency", async ({
  page,
}, testInfo) => {
  await verifyUnsupportedPolicyCandidate(
    page,
    testInfo,
    unsupportedPolicyCases[1],
  );
});

test("rejects policy frequency above one while retaining EV grading", async ({
  page,
}, testInfo) => {
  await verifyUnsupportedPolicyCandidate(
    page,
    testInfo,
    unsupportedPolicyCases[2],
  );
});

test("rejects missing policy frequency while retaining EV grading", async ({
  page,
}, testInfo) => {
  await verifyUnsupportedPolicyCandidate(
    page,
    testInfo,
    unsupportedPolicyCases[3],
  );
});

const supportedUngradedMixCases = [
  {
    filename: "missing-recommended-ev-line",
    controlPath: "/control/missing-recommended-line-next-recommendation",
    candidates: [
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.2 },
      { action: "fold", sizing: null, ev: 0, frequency: 0.8 },
    ],
  },
  {
    filename: "nonnumeric-candidate-ev",
    controlPath: "/control/nonnumeric-ev-next-recommendation",
    candidates: [
      { action: "call", sizing: null, ev: 1.4, frequency: 0.78 },
      { action: "raise", sizing: 8, ev: "1.1", frequency: 0.2 },
      { action: "fold", sizing: null, ev: 0, frequency: 0.02 },
    ],
  },
  {
    filename: "nonnumeric-recommended-ev",
    controlPath: "/control/nonnumeric-recommended-ev-next-recommendation",
    candidates: [
      { action: "call", sizing: null, ev: "1.4", frequency: 0.78 },
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.2 },
      { action: "fold", sizing: null, ev: 0, frequency: 0.02 },
    ],
  },
  {
    filename: "missing-recommended-sizing",
    controlPath: "/control/missing-recommended-sizing-next-recommendation",
    candidates: [
      { action: "call", ev: 1.4, frequency: 0.78 },
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.2 },
      { action: "fold", sizing: null, ev: 0, frequency: 0.02 },
    ],
  },
  {
    filename: "invalid-recommended-sizing",
    controlPath: "/control/invalid-recommended-sizing-next-recommendation",
    candidates: [
      { action: "call", sizing: 2.5, ev: 1.4, frequency: 0.78 },
      { action: "raise", sizing: 8, ev: 1.1, frequency: 0.2 },
      { action: "fold", sizing: null, ev: 0, frequency: 0.02 },
    ],
  },
];

async function verifySupportedUngradedMix(
  page: Page,
  testInfo: TestInfo,
  evidenceCase: (typeof supportedUngradedMixCases)[number],
): Promise<void> {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename(evidenceCase.filename, testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}${evidenceCase.controlPath}`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Solver-supported mix");
  await expect(comparison).not.toContainText("BB EV loss");
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{
      ev_loss_bb: number | null;
      job_id: string;
      outcome: string;
    }>;
    review_queue: Array<{ job_id: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    ev_compared_hands: initialProgress.ev_compared_hands,
    exact_matches: initialProgress.exact_matches + 1,
    needs_review_hands: initialProgress.needs_review_hands,
    review_queue_hands: initialProgress.review_queue_hands,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        ev_loss_bb: null,
        job_id: uploadedJob.id,
        outcome: "mixed",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).not.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ job_id: uploadedJob.id }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: {
      action: string;
      raw: { candidates: Array<Record<string, unknown>> };
    } | null;
  };
  expect(persistedJob.recommendation?.action).toBe("call");
  expect(persistedJob.recommendation?.raw.candidates).toEqual(
    evidenceCase.candidates,
  );
}

test("leaves EV loss ungraded without the recommended candidate line", async ({
  page,
}, testInfo) => {
  await verifySupportedUngradedMix(
    page,
    testInfo,
    supportedUngradedMixCases[0],
  );
});

test("keeps a supported mix with nonnumeric candidate EV ungraded", async ({
  page,
}, testInfo) => {
  await verifySupportedUngradedMix(
    page,
    testInfo,
    supportedUngradedMixCases[1],
  );
});

test("keeps a supported mix with nonnumeric recommended EV ungraded", async ({
  page,
}, testInfo) => {
  await verifySupportedUngradedMix(
    page,
    testInfo,
    supportedUngradedMixCases[2],
  );
});

test("keeps a supported mix with missing recommended sizing ungraded", async ({
  page,
}, testInfo) => {
  await verifySupportedUngradedMix(
    page,
    testInfo,
    supportedUngradedMixCases[3],
  );
});

test("keeps a supported mix with invalid recommended sizing ungraded", async ({
  page,
}, testInfo) => {
  await verifySupportedUngradedMix(
    page,
    testInfo,
    supportedUngradedMixCases[4],
  );
});

const nonDistinctEvidenceCases = [
  {
    label: "one candidate",
    filename: "single-line-ev-evidence",
    controlPath: "/control/single-line-evidence-next-recommendation",
    candidates: [{ action: "raise", sizing: 8, ev: 1.4, frequency: 1 }],
  },
  {
    label: "duplicate candidate lines",
    filename: "duplicate-line-ev-evidence",
    controlPath: "/control/duplicate-line-evidence-next-recommendation",
    candidates: [
      { action: "raise", sizing: 8, ev: 1.4, frequency: 1 },
      { action: "raise", sizing: 8.001, ev: 1.3, frequency: 0 },
    ],
  },
];

async function verifyNonDistinctEvidence(
  page: Page,
  testInfo: TestInfo,
  evidenceCase: (typeof nonDistinctEvidenceCases)[number],
): Promise<void> {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename(evidenceCase.filename, testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}${evidenceCase.controlPath}`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Matched solver");
  await expect(comparison).not.toContainText("BB EV loss");
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_matches: number;
    different_actions: number;
    ev_compared_hands: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{
      ev_loss_bb: number | null;
      job_id: string;
      outcome: string;
    }>;
    review_queue: Array<{ job_id: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    ev_compared_hands: initialProgress.ev_compared_hands,
    exact_matches: initialProgress.exact_matches + 1,
    needs_review_hands: initialProgress.needs_review_hands,
    review_queue_hands: initialProgress.review_queue_hands,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        ev_loss_bb: null,
        job_id: uploadedJob.id,
        outcome: "match",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).not.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ job_id: uploadedJob.id }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    recommendation: {
      action: string;
      raw: { candidates: Array<Record<string, unknown>> };
      sizing: number | null;
    } | null;
  };
  expect(persistedJob.recommendation).toMatchObject({
    action: "raise",
    sizing: 8,
  });
  expect(persistedJob.recommendation?.raw.candidates).toEqual(
    evidenceCase.candidates,
  );
}

test("leaves EV loss ungraded with one candidate", async ({
  page,
}, testInfo) => {
  await verifyNonDistinctEvidence(page, testInfo, nonDistinctEvidenceCases[0]);
});

test("leaves EV loss ungraded with duplicate candidate lines", async ({
  page,
}, testInfo) => {
  await verifyNonDistinctEvidence(page, testInfo, nonDistinctEvidenceCases[1]);
});

test("reviews a sizing difference at the tolerance boundary", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename("sizing-boundary-review", testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8.01");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}/control/sizing-evidence-next-recommendation`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Same action, different size");
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{ job_id: string; outcome: string }>;
    review_queue: Array<{ job_id: string; outcome: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    exact_matches: initialProgress.exact_matches,
    needs_review_hands: initialProgress.needs_review_hands + 1,
    review_queue_hands: initialProgress.review_queue_hands + 1,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.action_differences).toEqual(
    initialProgress.action_differences,
  );
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "same_action",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "same_action",
      }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    recommendation: { action: string; sizing: number | null } | null;
    training_decision: { action: string; sizing: number | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    recommendation: { action: "raise", sizing: 8 },
    training_decision: { action: "raise", sizing: 8.01 },
    training_reviewed_at: null,
  });
});

test("reviews a supported mixed action taken at a different size", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename("mixed-sizing-review", testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("9");
  await decisionPanel
    .getByRole("button", {
      name: "medium",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}/control/evidence-next-recommendation`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText(
    "Solver-supported action, different size",
  );
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{ job_id: string; outcome: string }>;
    review_queue: Array<{ job_id: string; outcome: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    exact_matches: initialProgress.exact_matches,
    needs_review_hands: initialProgress.needs_review_hands + 1,
    review_queue_hands: initialProgress.review_queue_hands + 1,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.action_differences).toEqual(
    initialProgress.action_differences,
  );
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "mixed_action",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "mixed_action",
      }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    recommendation: {
      action: string;
      raw: Record<string, unknown>;
      sizing: number | null;
    } | null;
    training_decision: { action: string; sizing: number | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    recommendation: {
      action: "call",
      raw: {
        candidates: expect.arrayContaining([
          { action: "raise", sizing: 8, ev: 1.1, frequency: 0.2 },
        ]),
      },
      sizing: null,
    },
    training_decision: { action: "raise", sizing: 9 },
    training_reviewed_at: null,
  });
});

test("treats sub-tolerance sizing drift as an exact line", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    review_queue_hands: number;
    reviewed_hands: number;
  };

  const filename = attemptFilename("sizing-tolerance", testInfo);
  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  const decisionPanel = page.getByRole("region", {
    name: "Your training decision",
  });
  await decisionPanel
    .getByRole("button", {
      name: "raise",
      exact: true,
    })
    .click();
  await decisionPanel.getByLabel("Decision sizing in BB").fill("8.005");
  await decisionPanel
    .getByRole("button", {
      name: "high",
      exact: true,
    })
    .click();
  await decisionPanel.getByRole("button", { name: "Lock answer" }).click();
  await expect(decisionPanel).toContainText("Answer locked");

  const armResponse = await page.request.post(
    `${PROVIDER_URL}/control/sizing-evidence-next-recommendation`,
  );
  expect(armResponse.ok()).toBe(true);
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");

  const comparison = page.getByLabel("Training decision comparison");
  await expect(comparison).toContainText("Matched solver");
  await expect(
    comparison.getByRole("button", {
      name: "Mark reviewed",
    }),
  ).toBeHidden();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(uploadedJob.queueItem).toBeHidden();

  const updatedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(updatedProgressResponse.ok()).toBe(true);
  const updatedProgress = (await updatedProgressResponse.json()) as {
    action_differences: Array<{
      decision_action: string;
      recommended_action: string;
    }>;
    action_matches: number;
    different_actions: number;
    exact_matches: number;
    needs_review_hands: number;
    recent_hands: Array<{ job_id: string; outcome: string }>;
    review_queue: Array<{ job_id: string }>;
    review_queue_hands: number;
    reviewed_hands: number;
  };
  expect(updatedProgress).toMatchObject({
    action_matches: initialProgress.action_matches + 1,
    different_actions: initialProgress.different_actions,
    exact_matches: initialProgress.exact_matches + 1,
    needs_review_hands: initialProgress.needs_review_hands,
    review_queue_hands: initialProgress.review_queue_hands,
    reviewed_hands: initialProgress.reviewed_hands + 1,
  });
  expect(updatedProgress.action_differences).toEqual(
    initialProgress.action_differences,
  );
  expect(updatedProgress.recent_hands).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        job_id: uploadedJob.id,
        outcome: "match",
      }),
    ]),
  );
  expect(updatedProgress.review_queue).not.toEqual(
    expect.arrayContaining([
      expect.objectContaining({ job_id: uploadedJob.id }),
    ]),
  );

  const persistedResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
  );
  expect(persistedResponse.ok()).toBe(true);
  const persistedJob = (await persistedResponse.json()) as {
    archived_at: string | null;
    recommendation: { action: string; sizing: number | null } | null;
    training_decision: { action: string; sizing: number | null } | null;
    training_reviewed_at: string | null;
  };
  expect(persistedJob).toMatchObject({
    archived_at: expect.any(String),
    recommendation: { action: "raise", sizing: 8 },
    training_decision: { action: "raise", sizing: 8.005 },
    training_reviewed_at: null,
  });
});

test("filters and exports persisted lesson notes", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);

  const initialProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(initialProgressResponse.ok()).toBe(true);
  const initialProgress = (await initialProgressResponse.json()) as {
    lesson_count: number;
  };
  const flopFilename = attemptFilename("lesson-export-flop", testInfo);
  const turnFilename = attemptFilename("lesson-export-turn", testInfo);
  const turnControlFilename = attemptFilename(
    "lesson-export-turn-control",
    testInfo,
  );
  const lessonFilterToken = [
    "shared-filter",
    `w${testInfo.workerIndex}`,
    `p${testInfo.repeatEachIndex}`,
    `r${testInfo.retry}`,
  ].join("-");
  const flopNote = `${lessonFilterToken}: review the flop continuation bet.`;
  const turnNote = `${lessonFilterToken}: check the turn bluff catcher.`;
  const turnControlNote = `Review turn value bets from ${turnControlFilename}.`;

  const flopJob = await createReviewedLesson(page, flopFilename, flopNote);
  const turnJob = await createReviewedLesson(page, turnFilename, turnNote, {
    boardCards: "Qs Jc 2h 9d",
    street: "turn",
  });
  const turnControlJob = await createReviewedLesson(
    page,
    turnControlFilename,
    turnControlNote,
    { boardCards: "Qs Jc 2h 8s", street: "turn" },
  );

  await page.getByRole("button", { name: "Training progress" }).click();
  const progressDialog = page.getByRole("dialog", {
    name: "Training progress",
  });
  await expect(progressDialog).toBeVisible();
  const expectedLessonCount = initialProgress.lesson_count + 3;
  await progressDialog
    .getByRole("button", {
      name: `Lessons ${expectedLessonCount}`,
      exact: true,
    })
    .click();

  await progressDialog.getByLabel("Lesson street").selectOption("turn");
  const turnLesson = progressDialog.getByRole("button", {
    name: `Open ${turnFilename} training review`,
    exact: true,
  });
  const turnControlLesson = progressDialog.getByRole("button", {
    name: `Open ${turnControlFilename} training review`,
    exact: true,
  });
  await expect(turnLesson).toBeVisible();
  await expect(turnControlLesson).toBeVisible();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${flopFilename} training review`,
      exact: true,
    }),
  ).toBeHidden();

  const lessonSearch = progressDialog.getByLabel("Search saved lesson notes");
  await lessonSearch.fill(lessonFilterToken);
  await progressDialog
    .getByRole("button", {
      name: "Apply lesson search",
    })
    .click();

  await expect(turnLesson).toContainText(turnNote);
  await expect(turnControlLesson).toBeHidden();
  await expect(
    progressDialog.getByRole("button", {
      name: `Open ${flopFilename} training review`,
      exact: true,
    }),
  ).toBeHidden();
  await expect(progressDialog).toContainText(
    "1 lesson note matches these filters.",
  );

  const downloadPromise = page.waitForEvent("download");
  await progressDialog.getByRole("link", { name: "Export lessons" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^poker-hero-lessons-\d{8}T\d{6}Z\.md$/,
  );
  expect(download.url()).toContain("lesson_street=turn");
  expect(decodeURIComponent(download.url())).toContain(
    `lesson_query=${lessonFilterToken}`,
  );
  const lessonPath = await download.path();
  expect(lessonPath).not.toBeNull();
  if (lessonPath === null) {
    throw new Error("Lesson export did not produce a local download");
  }
  const lessonDocument = await readFile(lessonPath, "utf8");
  expect(lessonDocument).toContain("# Poker Hero Lessons");
  expect(lessonDocument).toContain("1 saved lesson note.");
  expect(lessonDocument).toContain(`- Source: \`${turnFilename}\``);
  expect(lessonDocument).toContain(turnNote);
  expect(lessonDocument).not.toContain(flopFilename);
  expect(lessonDocument).not.toContain(flopNote);
  expect(lessonDocument).not.toContain(turnControlFilename);
  expect(lessonDocument).not.toContain(turnControlNote);

  for (const lessonJob of [flopJob, turnJob, turnControlJob]) {
    const cleanupResponse = await page.request.put(
      `${BACKEND_URL}/api/jobs/${lessonJob.id}/training-review`,
      { data: { note: null } },
    );
    expect(cleanupResponse.ok()).toBe(true);
  }
  const cleanedProgressResponse = await page.request.get(
    `${BACKEND_URL}/api/training/progress`,
  );
  expect(cleanedProgressResponse.ok()).toBe(true);
  const cleanedProgress = (await cleanedProgressResponse.json()) as {
    lesson_count: number;
  };
  expect(cleanedProgress.lesson_count).toBe(initialProgress.lesson_count);
});

test("runs a parser benchmark and verifies its exported dataset", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("benchmark-dataset", testInfo);

  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();

  const initialOverviewResponse = await page.request.get(
    `${BACKEND_URL}/api/benchmarks`,
  );
  expect(initialOverviewResponse.ok()).toBe(true);
  const initialOverview = (await initialOverviewResponse.json()) as {
    included_cases: number;
  };
  const expectedIncludedCases = initialOverview.included_cases + 1;

  // The legacy reload drops the in-memory credential, so dataset import stays
  // locked until the administrator unlocks the tools again.
  await unlockAdministrativeAccess(page);
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

  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(uploadedJob.queueItem).toContainText("recommended");
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

  const archivedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(archivedJob.queueItem).toContainText("recommended");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(archivedJob.queueItem).toBeHidden();

  const pendingFilename = attemptFilename(
    "application-backup-pending",
    testInfo,
  );
  const pendingJob = await uploadLegacyScreenshot(page, pendingFilename);
  await expect(pendingJob.queueItem).toContainText("parsed");

  // The legacy reload drops the in-memory credential, so backup restore stays
  // locked until the administrator unlocks the tools again.
  await unlockAdministrativeAccess(page);
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
    status: "recommended",
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
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(pendingJob.queueItem).toContainText("recommended");
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
      input_context: string;
      original_filename: string;
      status: string;
    }>;
  };
  expect(
    batchJobs.jobs.find(
      (candidate) => candidate.original_filename === validFilename,
    ),
  ).toMatchObject({
    input_context: "administrative_test",
    status: "parsed",
  });
  expect(
    batchJobs.jobs.some(
      (candidate) => candidate.original_filename === invalidFilename,
    ),
  ).toBe(false);

  // The surviving upload is an administrative test input, so it is approved by
  // hand and never offers a recommendation.
  await validItem.click();
  await expect(
    page.getByRole("button", { name: "Request recommendation" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Approve state" }).click();
  await expect(validItem).toContainText("approved");
  await expect(
    page.getByRole("button", { name: "Request recommendation" }),
  ).toBeDisabled();

  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(validItem).toBeHidden();
  await expect(invalidItem).toBeVisible();
});

const retryableRecommendationFailureCases = [
  {
    title: "recovers from a failed recommendation and retries it",
    filename: "provider-retry",
    controlPath: "/control/fail-next-recommendation",
    expectedError: "external_solver request failed with status 503",
  },
  {
    title: "rejects and retries malformed headline recommendation sizing",
    filename: "invalid-headline-sizing",
    controlPath: "/control/invalid-headline-sizing-next-recommendation",
    expectedError: "external_solver returned invalid payload",
  },
  {
    title: "rejects and retries nonfinite headline recommendation sizing",
    filename: "nonfinite-headline-sizing",
    controlPath: "/control/nonfinite-headline-sizing-next-recommendation",
    expectedError: "external_solver returned invalid payload",
  },
  {
    title: "rejects and retries zero headline recommendation sizing",
    filename: "zero-headline-sizing",
    controlPath: "/control/zero-headline-sizing-next-recommendation",
    expectedError: "external_solver returned invalid payload",
  },
  {
    title: "rejects and retries coerced headline recommendation sizing",
    filename: "coerced-headline-sizing",
    controlPath: "/control/coerced-headline-sizing-next-recommendation",
    expectedError: "external_solver returned invalid payload",
  },
  {
    title: "rejects and retries coerced recommendation confidence",
    filename: "coerced-recommendation-confidence",
    controlPath: "/control/coerced-confidence-next-recommendation",
    expectedError: "external_solver returned invalid payload",
  },
];

for (const failureCase of retryableRecommendationFailureCases) {
  test(failureCase.title, async ({ page }, testInfo) => {
    await openUploadInput(page);
    const filename = attemptFilename(failureCase.filename, testInfo);

    const uploadedJob = await uploadLegacyScreenshot(page, filename);
    await page.getByRole("button", { name: "Approve state" }).click();
    await expect(
      page.getByRole("region", { name: "Your training decision" }),
    ).toBeVisible();

    const armFailureResponse = await page.request.post(
      `${PROVIDER_URL}${failureCase.controlPath}`,
    );
    expect(armFailureResponse.ok()).toBe(true);

    await page.getByRole("button", { name: "Request recommendation" }).click();
    await expect(
      page.getByText(failureCase.expectedError).first(),
    ).toBeVisible();
    await expect(uploadedJob.queueItem).toContainText("error");
    await expect
      .poll(() =>
        page.evaluate(() =>
          sessionStorage.getItem("poker-training-processing-mutation-v1"),
        ),
      )
      .toBeNull();
    const failedJobResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
    );
    expect(failedJobResponse.ok()).toBe(true);
    const failedJob = (await failedJobResponse.json()) as {
      error: string | null;
      recommendation_pending: boolean;
      recommendation_request_id: string | null;
      status: string;
    };
    expect(failedJob).toMatchObject({
      error: failureCase.expectedError,
      recommendation_pending: false,
      status: "error",
    });
    expect(failedJob.recommendation_request_id).not.toBeNull();

    await page.getByRole("button", { name: "Request recommendation" }).click();
    await expect(
      page.getByRole("region", { name: "Recommendation" }),
    ).toBeVisible();
    await expect(uploadedJob.queueItem).toContainText("recommended");
    const recommendedJobResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
    );
    expect(recommendedJobResponse.ok()).toBe(true);
    const recommendedJob = (await recommendedJobResponse.json()) as {
      error: string | null;
      recommendation: { raw: { engine: string } } | null;
      status: string;
    };
    expect(recommendedJob).toMatchObject({
      error: null,
      recommendation: {
        raw: { engine: "e2e_provider_stub" },
      },
      status: "recommended",
    });
  });
}

test("reconciles a recommendation that completes after page reload", async ({
  page,
}, testInfo) => {
  await openUploadInput(page);
  const filename = attemptFilename("recommendation-reload", testInfo);

  const uploadedJob = await uploadLegacyScreenshot(page, filename);
  await page.getByRole("button", { name: "Approve state" }).click();

  const armBlockResponse = await page.request.post(
    `${PROVIDER_URL}/control/block-next-recommendation`,
  );
  expect(armBlockResponse.ok()).toBe(true);

  let recommendationReleased = false;
  try {
    await page.getByRole("button", { name: "Request recommendation" }).click();
    await expect
      .poll(async () => {
        const response = await page.request.get(
          `${PROVIDER_URL}/control/recommendation-state`,
        );
        if (!response.ok()) {
          return false;
        }
        const state = (await response.json()) as { started: boolean };
        return state.started;
      })
      .toBe(true);
    await expect
      .poll(async () => {
        const response = await page.request.get(
          `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
        );
        if (!response.ok()) {
          return false;
        }
        const job = (await response.json()) as {
          recommendation_pending: boolean;
        };
        return job.recommendation_pending;
      })
      .toBe(true);
    const pendingLease = await page.evaluate(
      () =>
        JSON.parse(
          sessionStorage.getItem("poker-training-processing-mutation-v1") ??
            "null",
        ) as {
          expectedRecommendationRequestId: string;
          jobId: string;
          kind: string;
        } | null,
    );
    if (pendingLease === null) {
      throw new Error("Recommendation mutation lease was not persisted");
    }
    expect(pendingLease).toMatchObject({
      expectedRecommendationRequestId: expect.any(String),
      jobId: uploadedJob.id,
      kind: "job",
    });

    await page.reload();
    await expectAnalyzerReady(page);
    const reloadedQueueItem = page.getByRole("button", {
      name: filenamePattern(filename),
    });
    await expect(reloadedQueueItem).toContainText("Recommendation running");
    await reloadedQueueItem.click();
    await expect(
      page.getByRole("region", { name: "Recommendation" }),
    ).toBeHidden();

    const releaseResponse = await page.request.post(
      `${PROVIDER_URL}/control/release-recommendation`,
    );
    expect(releaseResponse.ok()).toBe(true);
    recommendationReleased = true;

    await expect(
      page.getByRole("region", { name: "Recommendation" }),
    ).toBeVisible();
    await expect(reloadedQueueItem).toContainText("recommended");
    await expect
      .poll(() =>
        page.evaluate(() =>
          sessionStorage.getItem("poker-training-processing-mutation-v1"),
        ),
      )
      .toBeNull();

    const completedJobResponse = await page.request.get(
      `${BACKEND_URL}/api/jobs/${uploadedJob.id}`,
    );
    expect(completedJobResponse.ok()).toBe(true);
    const completedJob = (await completedJobResponse.json()) as {
      error: string | null;
      recommendation: { raw: Record<string, string> } | null;
      recommendation_pending: boolean;
      recommendation_request_id: string | null;
      status: string;
    };
    expect(completedJob).toMatchObject({
      error: null,
      recommendation: {
        raw: {
          engine: "e2e_provider_stub",
          provider: "external_solver",
        },
      },
      recommendation_pending: false,
      recommendation_request_id: pendingLease.expectedRecommendationRequestId,
      status: "recommended",
    });
  } finally {
    if (!recommendationReleased) {
      await page.request.post(`${PROVIDER_URL}/control/release-recommendation`);
    }
  }
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

  await markLegacyJobs(page, [recoveredJob.id]);
  await forceQueueRevalidation(page);
  await page.goto(`/analyzer/jobs/${recoveredJob.id}`);
  await expectAnalyzerReady(page);
  await expect(matchingQueueItems).toHaveCount(2);
  await page.getByRole("button", { name: "Approve state" }).click();
  await page.getByRole("button", { name: "Request recommendation" }).click();
  const recoveredQueueItem = matchingQueueItems.filter({
    hasText: "recommended",
  });
  await expect(recoveredQueueItem).toContainText("recommended");
  await expect(
    page.getByRole("region", { name: "Recommendation" }),
  ).toBeVisible();

  const recoveredJobsResponse = await page.request.get(
    `${BACKEND_URL}/api/jobs`,
  );
  expect(recoveredJobsResponse.ok()).toBe(true);
  const recoveredJobs = (await recoveredJobsResponse.json()) as {
    jobs: Array<{
      original_filename: string;
      parser_result: { raw: Record<string, string> } | null;
      recommendation: { raw: Record<string, string> } | null;
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
        parser_result: expect.objectContaining({
          raw: expect.objectContaining({
            engine: "e2e_provider_stub",
            provider: "llm_vision",
          }),
        }),
        recommendation: expect.objectContaining({
          raw: expect.objectContaining({ engine: "e2e_provider_stub" }),
        }),
        status: "recommended",
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
  const archivedJob = await uploadLegacyScreenshot(page, archivedFilename);
  await page.getByLabel("Pot").fill("66.75");
  await page.getByRole("button", { name: "Approve state" }).click();
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(archivedJob.queueItem).toContainText("recommended");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(archivedJob.queueItem).toBeHidden();

  const pendingFilename = attemptFilename("storage-reset-pending", testInfo);
  const pendingJob = await uploadLegacyScreenshot(page, pendingFilename);
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
    status: "recommended",
  });

  await restoredPendingJob.click();
  await page.getByRole("button", { name: "Approve state" }).click();
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(restoredPendingJob).toContainText("recommended");
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
  const pendingJob = await uploadLegacyScreenshot(page, pendingFilename);
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
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(pendingJob.queueItem).toContainText("recommended");
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
  const pendingJob = await uploadLegacyScreenshot(page, pendingFilename);
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
  await page.getByRole("button", { name: "Request recommendation" }).click();
  await expect(pendingJob.queueItem).toContainText("recommended");
  await page.getByRole("button", { name: "Clear reviewed" }).click();
  await expect(pendingJob.queueItem).toBeHidden();
});
