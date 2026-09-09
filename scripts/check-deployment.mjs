import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const DEFAULT_ATTEMPTS = 3;
const DEFAULT_RETRY_DELAY_MS = 10_000;
const DEFAULT_TIMEOUT_MS = 20_000;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const PWA_APPLICATION_MARKER =
  /<meta\b(?=[^>]*\bname\s*=\s*["']application-name["'])(?=[^>]*\bcontent\s*=\s*["']poker hero["'])[^>]*>/i;

function positiveInteger(value, label) {
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return parsed;
}

function normalizeBaseUrl(value, allowHttp) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Deployment URL must be a valid absolute URL");
  }
  if (url.username || url.password) {
    throw new Error("Deployment URL must not contain credentials");
  }
  if (url.protocol !== "https:" && !(allowHttp && url.protocol === "http:")) {
    throw new Error("Deployment URL must use HTTPS");
  }
  if (url.search || url.hash) {
    throw new Error("Deployment URL must not contain a query or fragment");
  }
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/`;
  return url;
}

function accessHeaders(accessClientId, accessClientSecret) {
  const hasClientId = Boolean(accessClientId);
  const hasClientSecret = Boolean(accessClientSecret);
  if (hasClientId !== hasClientSecret) {
    throw new Error(
      "Cloudflare Access client ID and secret must be configured together",
    );
  }
  if (!hasClientId) {
    return {};
  }
  return {
    "CF-Access-Client-Id": accessClientId,
    "CF-Access-Client-Secret": accessClientSecret,
  };
}

function endpointUrl(baseUrl, endpoint) {
  const url = new URL(baseUrl);
  const basePath = url.pathname.replace(/\/+$/, "");
  const endpointParts = new URL(endpoint, "https://deployment-check.invalid");
  url.pathname =
    endpoint === "/" ? `${basePath}/` : `${basePath}${endpointParts.pathname}`;
  url.search = endpointParts.search;
  return url;
}

async function readBoundedBody(response, label) {
  if (!response.body) {
    return "";
  }
  const reader = response.body.getReader();
  const chunks = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      totalBytes += value.byteLength;
      if (totalBytes > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error(`${label} response exceeded 1 MiB`);
      }
      chunks.push(Buffer.from(value));
    }
  } finally {
    reader.releaseLock();
  }
  return Buffer.concat(chunks, totalBytes).toString("utf8");
}

async function fetchText(baseUrl, endpoint, label, headers, timeoutMs) {
  const target = endpointUrl(baseUrl, endpoint);
  const signal = AbortSignal.timeout(timeoutMs);
  let current = target;
  let response;
  try {
    for (let redirectCount = 0; redirectCount <= 5; redirectCount += 1) {
      response = await fetch(current, {
        headers: {
          Accept: "application/json, text/html;q=0.9",
          "User-Agent": "poker-hero-uptime-monitor/1.0",
          ...headers,
        },
        redirect: "manual",
        signal,
      });
      if (response.status < 300 || response.status >= 400) {
        break;
      }
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location) {
        throw new Error(`${label} redirect did not include a location`);
      }
      const redirected = new URL(location, current);
      if (redirected.origin !== baseUrl.origin) {
        throw new Error(`${label} redirected outside the deployment origin`);
      }
      current = redirected;
      response = undefined;
    }
  } catch (error) {
    if (error?.message?.startsWith(`${label} redirect`)) {
      throw error;
    }
    if (error?.name === "TimeoutError" || error?.name === "AbortError") {
      throw new Error(`${label} timed out after ${timeoutMs} ms`);
    }
    throw new Error(`${label} request failed`);
  }
  if (!response) {
    throw new Error(`${label} exceeded 5 redirects`);
  }
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`${label} returned HTTP ${response.status}`);
  }
  try {
    return await readBoundedBody(response, label);
  } catch (error) {
    if (error?.message === `${label} response exceeded 1 MiB`) {
      throw error;
    }
    if (error?.name === "TimeoutError" || error?.name === "AbortError") {
      throw new Error(`${label} timed out after ${timeoutMs} ms`);
    }
    throw new Error(`${label} response body could not be read`);
  }
}

async function expectStatus(
  baseUrl,
  endpoint,
  label,
  headers,
  timeoutMs,
  expectedStatuses,
  method = "GET",
) {
  const target = endpointUrl(baseUrl, endpoint);
  let response;
  try {
    response = await fetch(target, {
      body: method === "POST" ? "{}" : undefined,
      headers: {
        Accept: "application/json",
        ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
        "User-Agent": "poker-hero-uptime-monitor/1.0",
        ...headers,
      },
      method,
      redirect: "manual",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    if (error?.name === "TimeoutError" || error?.name === "AbortError") {
      throw new Error(`${label} timed out after ${timeoutMs} ms`);
    }
    throw new Error(`${label} request failed`);
  }
  const status = response.status;
  await response.body?.cancel();
  const acceptedStatuses = Array.isArray(expectedStatuses)
    ? expectedStatuses
    : [expectedStatuses];
  if (!acceptedStatuses.includes(status)) {
    throw new Error(
      `${label} returned HTTP ${status}; expected ${acceptedStatuses.join(" or ")}`,
    );
  }
}

function parseJson(body, label) {
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(`${label} returned invalid JSON`);
  }
}

async function checkOnce(baseUrl, headers, timeoutMs) {
  const spa = await fetchText(baseUrl, "/", "PWA", headers, timeoutMs);
  if (!PWA_APPLICATION_MARKER.test(spa)) {
    throw new Error("PWA response did not contain the application marker");
  }

  const health = parseJson(
    await fetchText(baseUrl, "/api/health", "API health", headers, timeoutMs),
    "API health",
  );
  if (health?.status !== "ok") {
    throw new Error("API health response did not report status ok");
  }

  await expectStatus(
    baseUrl,
    "/api/jobs?limit=1",
    "Retired operator API route",
    headers,
    timeoutMs,
    404,
  );

  const mcpConfig = parseJson(
    await fetchText(
      baseUrl,
      "/api/mcp/config",
      "MCP configuration",
      headers,
      timeoutMs,
    ),
    "MCP configuration",
  );
  if (typeof mcpConfig?.enabled !== "boolean") {
    throw new Error("MCP configuration response did not report enabled state");
  }

  await expectStatus(
    baseUrl,
    "/api/mcp/principals",
    "MCP administration boundary",
    headers,
    timeoutMs,
    mcpConfig.enabled ? 401 : [401, 503],
  );
  await expectStatus(
    baseUrl,
    "/mcp",
    "MCP endpoint boundary",
    headers,
    timeoutMs,
    mcpConfig.enabled ? 401 : 404,
    "POST",
  );

  return mcpConfig;
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

export async function checkDeployment(rawUrl, options = {}) {
  const baseUrl = normalizeBaseUrl(rawUrl, options.allowHttp === true);
  const headers = accessHeaders(
    options.accessClientId ?? "",
    options.accessClientSecret ?? "",
  );
  const attempts = positiveInteger(
    options.attempts ?? DEFAULT_ATTEMPTS,
    "Attempts",
  );
  const retryDelayMs = Number(options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS);
  if (!Number.isSafeInteger(retryDelayMs) || retryDelayMs < 0) {
    throw new Error("Retry delay must be a non-negative integer");
  }
  const timeoutMs = positiveInteger(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    "Timeout",
  );

  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const mcpConfig = await checkOnce(baseUrl, headers, timeoutMs);
      return {
        attempts: attempt,
        mcp: {
          enabled: mcpConfig.enabled,
          endpoint: mcpConfig.endpoint ?? null,
          environment: mcpConfig.environment ?? null,
        },
        url: baseUrl.href.replace(/\/$/, ""),
      };
    } catch (error) {
      lastError = error;
      if (attempt < attempts && retryDelayMs > 0) {
        await delay(retryDelayMs);
      }
    }
  }
  throw new Error(
    `Deployment check failed after ${attempts} attempt(s): ${lastError.message}`,
  );
}

function parseArguments(argv) {
  const options = {};
  let json = false;
  let url = "";
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!argument.startsWith("--")) {
      if (url) {
        throw new Error("Only one deployment URL may be provided");
      }
      url = argument;
      continue;
    }
    if (argument === "--json") {
      json = true;
      continue;
    }
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`${argument} requires a value`);
    }
    index += 1;
    if (argument === "--attempts") {
      options.attempts = value;
    } else if (argument === "--retry-delay-ms") {
      options.retryDelayMs = value;
    } else if (argument === "--timeout-ms") {
      options.timeoutMs = value;
    } else {
      throw new Error(`Unknown option: ${argument}`);
    }
  }
  if (!url) {
    throw new Error(
      "Usage: node scripts/check-deployment.mjs <deployment-url>",
    );
  }
  return { json, options, url };
}

async function main() {
  const { json, options, url } = parseArguments(process.argv.slice(2));
  const result = await checkDeployment(url, {
    ...options,
    accessClientId: process.env.CLOUDFLARE_ACCESS_CLIENT_ID,
    accessClientSecret: process.env.CLOUDFLARE_ACCESS_CLIENT_SECRET,
  });
  if (json) {
    process.stdout.write(`${JSON.stringify(result)}\n`);
    return;
  }
  process.stdout.write(
    `Deployment healthy after ${result.attempts} attempt(s): ${result.url}\n`,
  );
}

const invokedPath = process.argv[1]
  ? pathToFileURL(resolve(process.argv[1])).href
  : "";
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    process.stderr.write(`Deployment unhealthy: ${error.message}\n`);
    process.exitCode = 1;
  });
}
