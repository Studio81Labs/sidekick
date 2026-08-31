import { createHash } from "node:crypto";
import type { Plugin } from "vite";

const contentAddressedAsset = /^\/assets\/.+-[A-Za-z0-9_-]{8,}\.[^/]+$/;

export function generatedServiceWorker(
  serviceWorkerEntry: string,
  cachePrefix = "poker-hero-shell",
): Plugin {
  return {
    name: "poker-hero-generated-service-worker",
    apply: "build",
    generateBundle(_options, bundle) {
      const worker = Object.values(bundle).find(
        (output) =>
          output.type === "chunk" &&
          output.isEntry &&
          output.facadeModuleId === serviceWorkerEntry,
      );
      if (!worker || worker.type !== "chunk") {
        this.error("The service-worker entry was not emitted.");
      }

      const assetPaths = Object.keys(bundle)
        .filter((fileName) => fileName.startsWith("assets/"))
        .map((fileName) => `/${fileName}`)
        .sort();
      const mutableAsset = assetPaths.find(
        (pathname) => !contentAddressedAsset.test(pathname),
      );
      if (mutableAsset) {
        this.error(
          `Service-worker precache asset is not content-addressed: ${mutableAsset}`,
        );
      }

      const digest = createHash("sha256");
      digest.update(worker.code);
      for (const [fileName, output] of Object.entries(bundle).sort(
        ([left], [right]) => left.localeCompare(right),
      )) {
        if (output === worker) continue;
        digest.update(fileName);
        digest.update(
          output.type === "chunk"
            ? output.code
            : typeof output.source === "string"
              ? output.source
              : output.source,
        );
      }

      const cacheName = `${cachePrefix}-${digest.digest("hex").slice(0, 16)}`;
      const cacheMarker = "__POKER_HERO_CACHE_NAME__";
      const precacheMarker = /(["'`])__POKER_HERO_PRECACHE_URLS__\1/;
      if (
        !worker.code.includes(cacheMarker) ||
        !precacheMarker.test(worker.code)
      ) {
        this.error("Service-worker build markers were not preserved.");
      }
      worker.code = worker.code
        .replace(cacheMarker, cacheName)
        .replace(precacheMarker, JSON.stringify(["/", ...assetPaths]));
    },
  };
}
