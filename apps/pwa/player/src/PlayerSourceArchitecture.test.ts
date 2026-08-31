/// <reference types="node" />

import { readFileSync, readdirSync } from "node:fs";
import { extname, join, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";

const PLAYER_ROOT = resolve(process.cwd(), "player/src");
const SOURCE_EXTENSIONS = new Set([".css", ".ts", ".tsx"]);

function filesBelow(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const pathname = join(directory, entry.name);
    return entry.isDirectory() ? filesBelow(pathname) : [pathname];
  });
}

function playerSources(): Array<{ path: string; source: string }> {
  return filesBelow(PLAYER_ROOT)
    .filter(
      (pathname) =>
        SOURCE_EXTENSIONS.has(extname(pathname)) &&
        !pathname.includes(".test."),
    )
    .map((pathname) => ({
      path: relative(PLAYER_ROOT, pathname).split(sep).join("/"),
      source: readFileSync(pathname, "utf8"),
    }));
}

describe("player source architecture", () => {
  it("keeps the hosted application outside the player bundle", () => {
    const allowedSharedImports = new Set([
      "../../src/app/pwa/serviceWorkerRuntime",
      "../../src/shared/pwa/serviceWorkerPolicy",
    ]);
    const violations = playerSources().flatMap(({ path, source }) => {
      const imports = [
        ...source.matchAll(/from\s+["'](\.\.\/\.\.\/src\/[^"']+)["']/g),
      ].map((match) => match[1] ?? "");
      if (path !== "service-worker.ts" && imports.length > 0) return [path];
      return imports
        .filter((candidate) => !allowedSharedImports.has(candidate))
        .map((candidate) => `${path}: ${candidate}`);
    });

    expect(violations).toEqual([]);
  });

  it("keeps raw transport in the player API adapter and service worker", () => {
    const allowed = new Set(["playerApi.ts", "service-worker.ts"]);
    const violations = playerSources()
      .filter(
        ({ path, source }) => source.includes("fetch(") && !allowed.has(path),
      )
      .map(({ path }) => path);

    expect(violations).toEqual([]);
  });

  it("contains no hosted or administrative endpoint", () => {
    const forbidden = [
      "/api/jobs",
      "/api/benchmarks",
      "/api/capture",
      "/mcp",
      "VITE_API_BASE_URL",
    ];
    const violations = playerSources().flatMap(({ path, source }) =>
      forbidden
        .filter((candidate) => source.includes(candidate))
        .map((candidate) => `${path}: ${candidate}`),
    );

    expect(violations).toEqual([]);
  });
});
