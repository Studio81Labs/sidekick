export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/") || url.pathname === "/mcp") {
      if (url.pathname.includes("%")) {
        return privateJsonResponse(400, "Encoded URL paths are not supported");
      }
      const mcpAdminRequest = isMcpAdminRequest(url.pathname);
      if (mcpAdminRequest) {
        if (!isStrongMcpAdminToken(env.MCP_ADMIN_TOKEN)) {
          return privateJsonResponse(
            503,
            "Agent access administration is unavailable",
          );
        }
        if (!(await bearerTokenMatches(request, env.MCP_ADMIN_TOKEN))) {
          return privateJsonResponse(
            401,
            "Agent access administrator authentication required",
            {
              "WWW-Authenticate": "Bearer",
            },
          );
        }
      }
      return proxyApiRequest(
        request,
        env.BACKEND_URL,
        env.API_PROXY_SECRET,
        mcpAdminRequest,
      );
    }

    return env.ASSETS.fetch(request);
  },
};

const PROXY_SHARED_SECRET_HEADER = "X-Poker-Proxy-Secret";
const MCP_PUBLIC_HOST_HEADER = "X-Poker-MCP-Public-Host";
const ACCESS_USER_HEADER = "CF-Access-Authenticated-User-Email";
const MCP_MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024;
const REQUEST_BODY_TOO_LARGE = Symbol("request-body-too-large");
const MAX_BACKEND_REDIRECTS = 5;
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

function isMcpAdminRequest(pathname) {
  return (
    pathname === "/api/mcp/principals" ||
    pathname.startsWith("/api/mcp/principals/")
  );
}

function isStrongMcpAdminToken(token) {
  return typeof token === "string" && /^[\x21-\x7e]{32,}$/.test(token);
}

async function bearerTokenMatches(request, expectedToken) {
  const authorization = request.headers.get("authorization") ?? "";
  const match = authorization.match(/^Bearer ([^\s]+)$/i);
  const suppliedToken = match?.[1] ?? "";
  const encoder = new TextEncoder();
  const [suppliedDigest, expectedDigest] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(suppliedToken)),
    crypto.subtle.digest("SHA-256", encoder.encode(expectedToken)),
  ]);
  const suppliedBytes = new Uint8Array(suppliedDigest);
  const expectedBytes = new Uint8Array(expectedDigest);
  let difference = suppliedBytes.byteLength ^ expectedBytes.byteLength;
  for (let index = 0; index < suppliedBytes.byteLength; index += 1) {
    difference |= suppliedBytes[index] ^ expectedBytes[index];
  }
  return difference === 0;
}

function privateJsonResponse(status, detail, extraHeaders = {}) {
  return Response.json(
    { detail },
    {
      status,
      headers: { "Cache-Control": "no-store", ...extraHeaders },
    },
  );
}

async function proxyApiRequest(
  request,
  backendUrl,
  proxySharedSecret,
  stripAuthorization = false,
) {
  if (!backendUrl) {
    return new Response("BACKEND_URL is not configured", { status: 500 });
  }

  const incomingUrl = new URL(request.url);
  const backendBase = new URL(backendUrl);
  if (proxySharedSecret && backendBase.protocol !== "https:") {
    return new Response(
      "BACKEND_URL must use HTTPS when API_PROXY_SECRET is configured",
      { status: 500 },
    );
  }

  let targetUrl = new URL(backendBase);
  let basePath = backendBase.pathname.replace(/\/+$/, "");
  let proxiedPath = incomingUrl.pathname;
  let allowedRedirectBasePath = basePath;

  if (basePath.endsWith("/api") && proxiedPath.startsWith("/api/")) {
    proxiedPath = proxiedPath.slice("/api".length);
  } else if (basePath.endsWith("/api") && proxiedPath === "/mcp") {
    basePath = basePath.slice(0, -"/api".length);
    allowedRedirectBasePath = `${basePath}/mcp`;
  } else if (proxiedPath === "/mcp") {
    allowedRedirectBasePath = `${basePath}/mcp`;
  }

  targetUrl.pathname = `${basePath}${proxiedPath}`;
  targetUrl.search = incomingUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.delete(PROXY_SHARED_SECRET_HEADER);
  headers.delete(MCP_PUBLIC_HOST_HEADER);
  if (stripAuthorization) {
    headers.delete("authorization");
  }
  // Access email is not independently verified by the backend and must not
  // become a caller-controlled rate-limit identity.
  headers.delete(ACCESS_USER_HEADER);
  if (proxySharedSecret) {
    headers.set(PROXY_SHARED_SECRET_HEADER, proxySharedSecret);
  }
  if (incomingUrl.pathname === "/mcp") {
    headers.set(MCP_PUBLIC_HOST_HEADER, incomingUrl.host);
  }

  let method = request.method;
  let body;
  if (method !== "GET" && method !== "HEAD") {
    body =
      incomingUrl.pathname === "/mcp"
        ? await readBodyWithLimit(request, MCP_MAX_REQUEST_BODY_BYTES)
        : await request.arrayBuffer();
    if (body === REQUEST_BODY_TOO_LARGE) {
      return new Response("MCP request body is too large", { status: 413 });
    }
  }

  for (let redirectCount = 0; ; redirectCount += 1) {
    const init = {
      method,
      headers,
      // Inspect redirects so the private header never crosses backend origins.
      redirect: "manual",
      signal: request.signal,
    };

    if (body !== undefined) {
      init.body = body;
    }

    const response = await fetch(new Request(targetUrl, init));
    const location = response.headers.get("location");
    if (!REDIRECT_STATUSES.has(response.status) || !location) {
      return response;
    }

    if (redirectCount >= MAX_BACKEND_REDIRECTS) {
      await response.body?.cancel();
      return new Response("Backend redirect limit exceeded", { status: 502 });
    }

    let redirectUrl;
    try {
      redirectUrl = new URL(location, targetUrl);
    } catch {
      await response.body?.cancel();
      return new Response("Backend redirect target is invalid", {
        status: 502,
      });
    }

    if (
      redirectUrl.origin !== backendBase.origin ||
      redirectUrl.username ||
      redirectUrl.password ||
      (allowedRedirectBasePath &&
        redirectUrl.pathname !== allowedRedirectBasePath &&
        !redirectUrl.pathname.startsWith(`${allowedRedirectBasePath}/`))
    ) {
      await response.body?.cancel();
      return new Response("Backend redirect target is not allowed", {
        status: 502,
      });
    }

    await response.body?.cancel();
    if (
      (response.status === 303 && method !== "GET" && method !== "HEAD") ||
      ((response.status === 301 || response.status === 302) &&
        method === "POST")
    ) {
      method = "GET";
      body = undefined;
      headers.delete("content-type");
    }

    targetUrl = redirectUrl;
  }
}

async function readBodyWithLimit(request, maximumBytes) {
  const declaredLength = request.headers.get("content-length");
  if (
    declaredLength !== null &&
    /^\d+$/.test(declaredLength) &&
    Number(declaredLength) > maximumBytes
  ) {
    return REQUEST_BODY_TOO_LARGE;
  }
  if (request.body === null) {
    return new ArrayBuffer(0);
  }

  const reader = request.body.getReader();
  const chunks = [];
  let byteLength = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      byteLength += value.byteLength;
      if (byteLength > maximumBytes) {
        await reader.cancel();
        return REQUEST_BODY_TOO_LARGE;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}
