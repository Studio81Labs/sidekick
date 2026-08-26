import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const documentPath = resolve(
  process.argv[2] ?? resolve(packageRoot, "openapi.json"),
);

let document;
try {
  document = JSON.parse(readFileSync(documentPath, "utf8"));
} catch (error) {
  console.error(`OpenAPI document is not valid JSON: ${documentPath}`);
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}

if (
  typeof document !== "object" ||
  document === null ||
  typeof document.openapi !== "string" ||
  !/^3\.[01]\./.test(document.openapi) ||
  typeof document.info !== "object" ||
  document.info === null ||
  typeof document.paths !== "object" ||
  document.paths === null ||
  Object.keys(document.paths).length === 0
) {
  console.error(
    `OpenAPI document is missing its required structure: ${documentPath}`,
  );
  process.exit(1);
}

console.log(`OpenAPI ${document.openapi} document is valid: ${documentPath}`);
