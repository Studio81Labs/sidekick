import { describe, expect, it } from "vitest";

import {
  isContentAddressedAssetPath,
  isHtmlContentType,
  isNetworkOnlyPath,
} from "./serviceWorkerPolicy";

describe("service-worker route policy", () => {
  it.each([
    "/api",
    "/api/",
    "/api/jobs",
    "/mcp",
    "/%61pi/jobs",
    "/%2561pi/jobs",
    "/%6dcp",
    "/api%2fjobs",
    "/api%252fjobs",
    "/%E0%A4%A",
  ])("keeps private path %s network-only", (pathname) => {
    expect(isNetworkOnlyPath(pathname)).toBe(true);
  });

  it.each(["/", "/app", "/mcpx", "/mcp/status", "/assets/app-A1b2C3d4.js"])(
    "allows non-private path %s to use the shell policy",
    (pathname) => {
      expect(isNetworkOnlyPath(pathname)).toBe(false);
    },
  );

  it.each([
    "/assets/app-A1b2C3d4.js",
    "/assets/chunk-with-name_9-abcdefgh.css",
  ])("recognizes content-addressed asset %s", (pathname) => {
    expect(isContentAddressedAssetPath(pathname)).toBe(true);
  });

  it.each([
    "/assets/app.js",
    "/assets/app-short.js",
    "/manifest.webmanifest",
    "/icons/icon-192.png",
  ])("rejects mutable asset path %s", (pathname) => {
    expect(isContentAddressedAssetPath(pathname)).toBe(false);
  });

  it.each([
    "text/html",
    "text/html; charset=utf-8",
    " TEXT/HTML ; charset=UTF-8",
  ])("accepts HTML shell content type %s", (contentType) => {
    expect(isHtmlContentType(contentType)).toBe(true);
  });

  it.each([null, "application/json", "image/svg+xml", "text/plain"])(
    "rejects non-HTML shell content type %s",
    (contentType) => {
      expect(isHtmlContentType(contentType)).toBe(false);
    },
  );
});
