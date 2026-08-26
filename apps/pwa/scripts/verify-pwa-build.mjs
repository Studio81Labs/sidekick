import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const pwaRoot = resolve(import.meta.dirname, "..");
const dist = resolve(pwaRoot, "dist");
const contentAddressedAsset = /^assets\/.+-[A-Za-z0-9_-]{8,}\.[^/]+$/;

function invariant(condition, message) {
  if (!condition) throw new Error(`PWA build contract: ${message}`);
}

function lifecycleHandlerStart(source, eventName) {
  return source.search(
    new RegExp(`addEventListener\\(\\s*(["'\\x60])${eventName}\\1`),
  );
}

for (const quote of ['"', "'", "`"]) {
  invariant(
    lifecycleHandlerStart(
      `self.addEventListener(${quote}install${quote}, () => undefined)`,
      "install",
    ) >= 0,
    `lifecycle parser does not accept ${quote} string literals`,
  );
}

async function filesBelow(directory, prefix = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      files.push(
        ...(await filesBelow(resolve(directory, entry.name), relative)),
      );
    } else {
      files.push(relative);
    }
  }
  return files;
}

async function pngDimensions(pathname) {
  const bytes = await readFile(resolve(dist, pathname));
  invariant(
    bytes.subarray(1, 4).toString("ascii") === "PNG",
    `${pathname} is not PNG`,
  );
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

const files = (await filesBelow(dist)).sort();
const assets = files.filter((pathname) => pathname.startsWith("assets/"));
invariant(assets.length > 0, "no application assets were emitted");
for (const asset of assets) {
  invariant(
    contentAddressedAsset.test(asset),
    `${asset} is not content-addressed`,
  );
}

const worker = await readFile(resolve(dist, "sw.js"), "utf8");
invariant(!worker.includes("__POKER_HERO_"), "service-worker markers remain");
invariant(
  /poker-hero-shell-[a-f0-9]{16}/.test(worker),
  "service-worker cache name is not build-versioned",
);
const expectedPrecache = JSON.stringify([
  "/",
  ...assets.map((asset) => `/${asset}`),
]);
invariant(
  worker.includes(expectedPrecache),
  "precache is not the exact emitted asset allowlist",
);
const installStart = lifecycleHandlerStart(worker, "install");
const activateStart = lifecycleHandlerStart(worker, "activate");
invariant(
  installStart >= 0 && activateStart > installStart,
  "worker lifecycle handlers are missing",
);
invariant(
  !worker.slice(installStart, activateStart).includes("skipWaiting"),
  "worker activates during install",
);

const manifest = JSON.parse(
  await readFile(resolve(dist, "manifest.webmanifest"), "utf8"),
);
invariant(
  manifest.id === "/" && manifest.scope === "/" && manifest.start_url === "/",
  "manifest scope is not rooted",
);
invariant(manifest.display === "standalone", "manifest is not standalone");
for (const icon of manifest.icons ?? []) {
  const expectedSize = Number.parseInt(icon.sizes, 10);
  const actualSize = await pngDimensions(icon.src.replace(/^\//, ""));
  invariant(
    actualSize[0] === expectedSize && actualSize[1] === expectedSize,
    `${icon.src} dimensions do not match ${icon.sizes}`,
  );
}
const appleSize = await pngDimensions("icons/apple-touch-icon.png");
invariant(
  appleSize[0] === 180 && appleSize[1] === 180,
  "Apple icon is not 180x180",
);

const html = await readFile(resolve(dist, "index.html"), "utf8");
invariant(
  html.includes('rel="manifest"') && html.includes("/manifest.webmanifest"),
  "document does not link the manifest",
);
invariant(
  html.includes('rel="apple-touch-icon"'),
  "document does not link the Apple icon",
);

process.stdout.write(
  `Verified PWA build contract (${assets.length} cached assets).\n`,
);
