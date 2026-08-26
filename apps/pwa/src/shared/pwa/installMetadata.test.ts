import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

interface ManifestIcon {
  purpose: string;
  sizes: string;
  src: string;
  type: string;
}

interface PokerHeroManifest {
  display: string;
  icons: ManifestIcon[];
  id: string;
  name: string;
  scope: string;
  short_name: string;
  start_url: string;
}

const pwaRoot = process.cwd();

async function pngDimensions(pathname: string): Promise<[number, number]> {
  const bytes = await readFile(resolve(pwaRoot, `public${pathname}`));
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

describe("PWA install metadata", () => {
  it("declares a root-scoped standalone application with regular and maskable icons", async () => {
    const manifest = JSON.parse(
      await readFile(resolve(pwaRoot, "public/manifest.webmanifest"), "utf8"),
    ) as PokerHeroManifest;

    expect(manifest).toMatchObject({
      display: "standalone",
      id: "/",
      name: "Poker Hero Post-Hand Trainer",
      scope: "/",
      short_name: "Poker Hero",
      start_url: "/",
    });
    expect(manifest.icons).toEqual([
      {
        purpose: "any",
        sizes: "192x192",
        src: "/icons/icon-192.png",
        type: "image/png",
      },
      {
        purpose: "any",
        sizes: "512x512",
        src: "/icons/icon-512.png",
        type: "image/png",
      },
      {
        purpose: "maskable",
        sizes: "192x192",
        src: "/icons/icon-maskable-192.png",
        type: "image/png",
      },
      {
        purpose: "maskable",
        sizes: "512x512",
        src: "/icons/icon-maskable-512.png",
        type: "image/png",
      },
    ]);

    for (const icon of manifest.icons) {
      const size = Number.parseInt(icon.sizes, 10);
      expect(await pngDimensions(icon.src)).toEqual([size, size]);
    }
    expect(await pngDimensions("/icons/apple-touch-icon.png")).toEqual([
      180, 180,
    ]);
  });

  it("links install metadata and Apple launch metadata from the document shell", async () => {
    const document = new DOMParser().parseFromString(
      await readFile(resolve(pwaRoot, "index.html"), "utf8"),
      "text/html",
    );

    expect(
      document.querySelector('link[rel="manifest"]')?.getAttribute("href"),
    ).toBe("/manifest.webmanifest");
    expect(
      document
        .querySelector('link[rel="apple-touch-icon"]')
        ?.getAttribute("href"),
    ).toBe("/icons/apple-touch-icon.png");
    expect(
      document
        .querySelector('meta[name="apple-mobile-web-app-capable"]')
        ?.getAttribute("content"),
    ).toBe("yes");
    expect(
      document
        .querySelector('meta[name="theme-color"]')
        ?.getAttribute("content"),
    ).toBe("#c52a12");
  });
});
