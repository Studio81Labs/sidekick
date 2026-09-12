import { readFile, rm } from "node:fs/promises";
import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const PLAYER_ORIGIN = "http://127.0.0.1:8765";

interface RuntimeSpec {
  cwd: string;
  entrypoint: string;
  workerPath: string;
}

interface RunningRuntime {
  launchUrl: string;
  process: ChildProcess;
}

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required for the update rehearsal`);
  return value;
}

function runtimeSpec(name: "BASE" | "CANDIDATE"): RuntimeSpec {
  return {
    cwd: requiredEnvironment(`POKER_PLAYER_UPDATE_${name}_CWD`),
    entrypoint: requiredEnvironment(`POKER_PLAYER_UPDATE_${name}_ENTRYPOINT`),
    workerPath: requiredEnvironment(`POKER_PLAYER_UPDATE_${name}_WORKER`),
  };
}

function launchFile(name: string): string {
  return resolve(requiredEnvironment("POKER_PLAYER_UPDATE_CAPTURE_DIR"), name);
}

async function startRuntime(
  spec: RuntimeSpec,
  {
    dataDir,
    capturePath,
  }: {
    dataDir: string;
    capturePath: string;
  },
): Promise<RunningRuntime> {
  await rm(capturePath, { force: true });
  const runtimeProcess = spawn(spec.entrypoint, [], {
    cwd: spec.cwd,
    env: {
      BROWSER: requiredEnvironment("POKER_PLAYER_UPDATE_LAUNCH_CAPTURE_HELPER"),
      PATH: process.env.PATH ?? "/usr/bin:/bin",
      POKER_DATA_DIR: dataDir,
      POKER_DEPLOYMENT_ENVIRONMENT: "local",
      POKER_HERO_PLAYER_LAUNCH_URL_FILE: capturePath,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const diagnostics: Buffer[] = [];
  runtimeProcess.stdout?.on("data", (chunk: Buffer) => diagnostics.push(chunk));
  runtimeProcess.stderr?.on("data", (chunk: Buffer) => diagnostics.push(chunk));
  try {
    await expect
      .poll(
        async () => {
          if (runtimeProcess.exitCode !== null) {
            throw new Error(
              `Packaged runtime exited during browser rehearsal:\n${Buffer.concat(
                diagnostics,
              ).toString("utf8")}`,
            );
          }
          try {
            return (await fetch(`${PLAYER_ORIGIN}/`)).status;
          } catch {
            return 0;
          }
        },
        { timeout: 20_000 },
      )
      .toBe(200);
    const expectedWorker = await readFile(spec.workerPath);
    const servedWorker = Buffer.from(
      await (await fetch(`${PLAYER_ORIGIN}/sw.js`)).arrayBuffer(),
    );
    expect(servedWorker.equals(expectedWorker)).toBe(true);
    await expect
      .poll(
        async () => {
          try {
            return (await readFile(capturePath, "utf8")).trim();
          } catch {
            return "";
          }
        },
        { timeout: 10_000 },
      )
      .toMatch(/^http:\/\/127\.0\.0\.1:8765\/#ticket=[A-Za-z0-9_-]+$/);
    return {
      launchUrl: (await readFile(capturePath, "utf8")).trim(),
      process: runtimeProcess,
    };
  } catch (error) {
    await stopRuntime(runtimeProcess);
    throw error;
  }
}

async function stopRuntime(process: ChildProcess): Promise<void> {
  if (process.exitCode !== null) return;
  process.kill("SIGTERM");
  await Promise.race([
    once(process, "exit"),
    new Promise((resolveTimeout) => setTimeout(resolveTimeout, 10_000)),
  ]);
  if (process.exitCode === null) {
    process.kill("SIGKILL");
    await once(process, "exit");
  }
}

async function waitForController(page: Page): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(
          () => navigator.serviceWorker.controller?.scriptURL ?? "",
        ),
      { timeout: 15_000 },
    )
    .toContain("/sw.js");
}

async function waitingWorkerState(page: Page): Promise<string | null> {
  return page.evaluate(async () => {
    const registration = await navigator.serviceWorker.getRegistration("/");
    return registration?.waiting?.state ?? null;
  });
}

test("hands a staged player shell to the candidate worker only when safe", async ({
  page,
}) => {
  const base = runtimeSpec("BASE");
  const candidate = runtimeSpec("CANDIDATE");
  const [baseWorker, candidateWorker] = await Promise.all([
    readFile(base.workerPath),
    readFile(candidate.workerPath),
  ]);
  expect(baseWorker.equals(candidateWorker)).toBe(false);

  const dataDir = requiredEnvironment("POKER_PLAYER_UPDATE_DATA_DIR");
  const baseRuntime = await startRuntime(base, {
    dataDir,
    capturePath: launchFile("base-launch-url"),
  });
  let candidateRuntime: RunningRuntime | null = null;
  try {
    await page.goto(baseRuntime.launchUrl);
    await expect(page.getByText("Ready on this machine")).toBeVisible();
    await page.evaluate(async () => navigator.serviceWorker.ready);
    await page.reload();
    await expect(page.getByText("Ready on this machine")).toBeVisible();
    await waitForController(page);

    await stopRuntime(baseRuntime.process);
    candidateRuntime = await startRuntime(candidate, {
      dataDir,
      capturePath: launchFile("candidate-launch-url"),
    });
    await page.goto(candidateRuntime.launchUrl);
    await expect(page.getByText("Ready on this machine")).toBeVisible();
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.getRegistration("/");
      await registration?.update();
    });
    await expect.poll(() => waitingWorkerState(page)).toBe("installed");
    await expect(
      page.getByText("A local player update is ready to reload."),
    ).toBeVisible();

    await page.getByLabel("Player backup ZIP").setInputFiles({
      name: "pending-backup.zip",
      mimeType: "application/zip",
      buffer: Buffer.from("pending backup"),
    });
    await expect(
      page.getByText(
        "A local player update is ready. Finish your drafts or explicitly discard them.",
      ),
    ).toBeVisible();
    page.once("dialog", (dialog) => void dialog.dismiss());
    await page.getByRole("button", { name: "Discard and reload" }).click();
    await expect.poll(() => waitingWorkerState(page)).toBe("installed");
    await page.getByLabel("Player backup ZIP").setInputFiles([]);

    let releaseExport: (() => void) | undefined;
    let resolveExportStarted: (() => void) | undefined;
    const exportStarted = new Promise<void>((resolveStarted) => {
      resolveExportStarted = resolveStarted;
    });
    await page.route("**/api/player/backups/export", async (route) => {
      resolveExportStarted?.();
      await new Promise<void>((resolveExport) => {
        releaseExport = resolveExport;
      });
      await route.continue();
    });
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download backup" }).click();
    await exportStarted;
    await expect(
      page.getByText(
        "A local player update is ready and will wait for active work to finish.",
      ),
    ).toBeVisible();
    expect(await waitingWorkerState(page)).toBe("installed");
    releaseExport?.();
    await download;
    await page.unroute("**/api/player/backups/export");

    const reloaded = page.waitForEvent(
      "framenavigated",
      (frame) => frame === page.mainFrame(),
    );
    await page.getByRole("button", { name: "Reload update" }).click();
    await reloaded;
    await expect(page.getByText("Ready on this machine")).toBeVisible();
    await expect
      .poll(() => waitingWorkerState(page), { timeout: 15_000 })
      .toBeNull();
    await expect
      .poll(() =>
        page.evaluate(async () => {
          const registration =
            await navigator.serviceWorker.getRegistration("/");
          return registration?.active?.state ?? null;
        }),
      )
      .toBe("activated");
  } finally {
    if (candidateRuntime !== null) await stopRuntime(candidateRuntime.process);
    else await stopRuntime(baseRuntime.process);
  }
});
