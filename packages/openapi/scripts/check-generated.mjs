import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const repositoryRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const openapiDocument = resolve(
  repositoryRoot,
  "packages/openapi/openapi.json",
);
const generatedClient = resolve(
  repositoryRoot,
  "packages/openapi-client/src/generated/openapi.ts",
);
const expectedArtifacts = [openapiDocument, generatedClient];

function repositoryPath(path) {
  return relative(repositoryRoot, path).split("\\").join("/");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: repositoryRoot,
    encoding: "utf8",
    ...options,
  });
  if (result.status !== 0) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    throw new Error(`${command} ${args.join(" ")} failed`);
  }
  return result;
}

function requireCleanTrackedArtifacts(stage) {
  for (const artifact of expectedArtifacts) {
    const path = repositoryPath(artifact);
    if (!existsSync(artifact)) {
      throw new Error(
        `${stage}: required generated artifact is missing: ${path}`,
      );
    }
    const tracked = spawnSync(
      "git",
      ["ls-files", "--error-unmatch", "--", path],
      {
        cwd: repositoryRoot,
        encoding: "utf8",
      },
    );
    if (tracked.status !== 0) {
      throw new Error(`${stage}: generated artifact is not tracked: ${path}`);
    }
  }

  const status = run("git", [
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
    "--",
    ...expectedArtifacts.map(repositoryPath),
  ]).stdout.trim();
  if (status) {
    throw new Error(
      `${stage}: generated artifacts contain staged, unstaged, or untracked changes:\n${status}`,
    );
  }
}

function requireSameDocument(generatedDocument) {
  run("node", [
    "packages/openapi/scripts/validate-openapi.mjs",
    generatedDocument,
  ]);
  if (!readFileSync(openapiDocument).equals(readFileSync(generatedDocument))) {
    throw new Error(
      "packages/openapi/openapi.json is stale. Run 'pnpm api:generate' and commit the result.",
    );
  }
}

function generateDocument(output) {
  const virtualEnvironmentPython = resolve(
    repositoryRoot,
    "apps/backend/.venv/bin/python",
  );
  const python = existsSync(virtualEnvironmentPython)
    ? virtualEnvironmentPython
    : (process.env.POKER_OPENAPI_PYTHON ?? "python3");
  run(python, [
    "packages/openapi/scripts/export_openapi.py",
    "--output",
    output,
  ]);
  run("pnpm", ["exec", "prettier", "--write", "--ignore-unknown", output], {
    stdio: "inherit",
  });
}

let temporaryDirectory;
try {
  requireCleanTrackedArtifacts("before generation");
  const suppliedDocument = process.argv[2];
  let generatedDocument;
  if (suppliedDocument) {
    generatedDocument = resolve(suppliedDocument);
    if (!existsSync(generatedDocument)) {
      throw new Error(
        `generated OpenAPI artifact is missing: ${generatedDocument}`,
      );
    }
  } else {
    temporaryDirectory = mkdtempSync(
      resolve(tmpdir(), "poker-hero-openapi-check-"),
    );
    generatedDocument = resolve(temporaryDirectory, "openapi.json");
    generateDocument(generatedDocument);
  }

  requireSameDocument(generatedDocument);
  run("pnpm", ["-C", "packages/openapi-client", "generate"], {
    stdio: "inherit",
  });
  requireCleanTrackedArtifacts("after generation");
  console.log("Committed OpenAPI document and TypeScript client are current.");
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
} finally {
  if (temporaryDirectory) {
    rmSync(temporaryDirectory, { recursive: true, force: true });
  }
}
