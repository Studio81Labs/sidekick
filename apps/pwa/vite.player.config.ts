import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vite";

import { generatedServiceWorker } from "./vite.service-worker";

const playerRoot = fileURLToPath(new URL("./player", import.meta.url));
const playerEntry = fileURLToPath(
  new URL("./player/index.html", import.meta.url),
);
const serviceWorkerEntry = fileURLToPath(
  new URL("./player/src/service-worker.ts", import.meta.url),
);
const outputDirectory = fileURLToPath(
  new URL("./dist-player", import.meta.url),
);
const sharedIconDirectory = fileURLToPath(
  new URL("./public/icons", import.meta.url),
);
const playerIcons = [
  "apple-touch-icon.png",
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-192.png",
  "icon-maskable-512.png",
] as const;

function emitPlayerIcons(): Plugin {
  return {
    name: "poker-hero-player-icons",
    apply: "build",
    async buildStart() {
      await Promise.all(
        playerIcons.map(async (filename) => {
          this.emitFile({
            type: "asset",
            fileName: `icons/${filename}`,
            source: await readFile(`${sharedIconDirectory}/${filename}`),
          });
        }),
      );
    },
  };
}

export default defineConfig({
  root: playerRoot,
  publicDir: "public",
  plugins: [
    react(),
    emitPlayerIcons(),
    generatedServiceWorker(serviceWorkerEntry, "poker-hero-player-shell"),
  ],
  build: {
    outDir: outputDirectory,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: playerEntry,
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
});
