import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { generatedServiceWorker } from "./vite.service-worker";

const pwaRoot = fileURLToPath(new URL(".", import.meta.url));
const appEntry = fileURLToPath(new URL("./index.html", import.meta.url));
const serviceWorkerEntry = fileURLToPath(
  new URL("./src/app/pwa/service-worker.ts", import.meta.url),
);
export default defineConfig({
  root: pwaRoot,
  plugins: [react(), generatedServiceWorker(serviceWorkerEntry)],
  build: {
    rollupOptions: {
      input: {
        app: appEntry,
        "service-worker": serviceWorkerEntry,
      },
      output: {
        assetFileNames: "assets/[name]-[hash][extname]",
        chunkFileNames: "assets/[name]-[hash].js",
        entryFileNames: (chunk) =>
          chunk.name === "service-worker" ? "sw.js" : "assets/[name]-[hash].js",
      },
    },
  },
  test: {
    environment: "jsdom",
    include: [
      "src/**/*.test.{ts,tsx}",
      "player/src/**/*.test.{ts,tsx}",
      "worker.test.js",
    ],
    setupFiles: ["./src/test/setup.ts"],
  },
});
