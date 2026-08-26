import { readdir, readFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const KIB = 1024;
const BUDGETS = {
  largestJavaScriptGzip: 175 * KIB,
  totalJavaScriptGzip: 350 * KIB,
  totalCssGzip: 24 * KIB,
};

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const assetsDirectory = process.argv[2]
  ? resolve(process.cwd(), process.argv[2])
  : join(repositoryRoot, "apps/pwa/dist/assets");

function kib(bytes) {
  return `${(bytes / KIB).toFixed(2)} KiB`;
}

const assetNames = (await readdir(assetsDirectory))
  .filter((name) => name.endsWith(".js") || name.endsWith(".css"))
  .sort();

if (assetNames.length === 0) {
  throw new Error(`No JavaScript or CSS assets found in ${assetsDirectory}`);
}

const assets = await Promise.all(
  assetNames.map(async (name) => {
    const contents = await readFile(join(assetsDirectory, name));
    return {
      name,
      bytes: contents.byteLength,
      gzipBytes: gzipSync(contents).byteLength,
    };
  }),
);

const javascriptAssets = assets.filter(({ name }) => name.endsWith(".js"));
const cssAssets = assets.filter(({ name }) => name.endsWith(".css"));
const total = (items) => items.reduce((sum, item) => sum + item.gzipBytes, 0);
const largestJavaScript = javascriptAssets.reduce(
  (largest, asset) => (asset.gzipBytes > largest.gzipBytes ? asset : largest),
  { name: "none", gzipBytes: 0 },
);
const totalJavaScriptGzip = total(javascriptAssets);
const totalCssGzip = total(cssAssets);

console.log("PWA production bundle audit:");
for (const asset of assets) {
  console.log(
    `- ${asset.name}: ${kib(asset.bytes)} raw, ${kib(asset.gzipBytes)} gzip`,
  );
}
console.log(`- total JavaScript gzip: ${kib(totalJavaScriptGzip)}`);
console.log(`- total CSS gzip: ${kib(totalCssGzip)}`);

const violations = [];
if (largestJavaScript.gzipBytes > BUDGETS.largestJavaScriptGzip) {
  violations.push(
    `${largestJavaScript.name} is ${kib(largestJavaScript.gzipBytes)} gzip; ` +
      `largest JavaScript budget is ${kib(BUDGETS.largestJavaScriptGzip)}`,
  );
}
if (totalJavaScriptGzip > BUDGETS.totalJavaScriptGzip) {
  violations.push(
    `JavaScript is ${kib(totalJavaScriptGzip)} gzip; total budget is ` +
      kib(BUDGETS.totalJavaScriptGzip),
  );
}
if (totalCssGzip > BUDGETS.totalCssGzip) {
  violations.push(
    `CSS is ${kib(totalCssGzip)} gzip; total budget is ${kib(BUDGETS.totalCssGzip)}`,
  );
}

if (violations.length > 0) {
  console.error("Bundle budget exceeded:");
  for (const violation of violations) {
    console.error(`- ${violation}`);
  }
  process.exitCode = 1;
} else {
  console.log("PWA bundle budgets pass.");
}
