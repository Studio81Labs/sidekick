import { afterEach, describe, expect, it, vi } from "vitest";

import worker from "./worker.js";

const MCP_ADMIN_TOKEN = "admin-secret-with-at-least-32-characters";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API Worker proxy", () => {
  it("rejects encoded API paths before they can bypass MCP administration", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    for (const path of [
      "/api/mcp/%70rincipals",
      "/api/mcp/principals%2Fmcp_123",
    ]) {
      const response = await worker.fetch(
        new Request(`https://poker.example${path}`, {
          headers: { Authorization: "Bearer agent-controlled-value" },
        }),
        {
          ASSETS: { fetch: vi.fn() },
          API_PROXY_SECRET: "trusted-worker-value",
          BACKEND_URL: "https://backend.example",
          MCP_ADMIN_TOKEN,
        },
      );

      expect(response.status).toBe(400);
      expect(response.headers.get("Cache-Control")).toBe("no-store");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects MCP credential administration without its bearer token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/mcp/principals"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
        MCP_ADMIN_TOKEN,
      },
    );

    expect(response.status).toBe(401);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("WWW-Authenticate")).toBe("Bearer");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an incorrect MCP administration bearer token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/mcp/principals", {
        headers: { Authorization: "Bearer wrong-secret" },
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
        MCP_ADMIN_TOKEN,
      },
    );

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed when the MCP administration secret is not configured", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/mcp/principals"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed when the MCP administration secret is weak or malformed", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    for (const token of ["short", `${"a".repeat(32)}\n`, "Ā".repeat(32)]) {
      const response = await worker.fetch(
        new Request("https://poker.example/api/mcp/principals"),
        {
          ASSETS: { fetch: vi.fn() },
          API_PROXY_SECRET: "trusted-worker-value",
          BACKEND_URL: "https://backend.example",
          MCP_ADMIN_TOKEN: token,
        },
      );

      expect(response.status).toBe(503);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("authorizes MCP administration without forwarding the admin token", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return Response.json({ principals: [] });
      }),
    );

    const response = await worker.fetch(
      new Request("https://poker.example/api/mcp/principals", {
        headers: { Authorization: `Bearer ${MCP_ADMIN_TOKEN}` },
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
        MCP_ADMIN_TOKEN,
      },
    );

    expect(response.status).toBe(200);
    expect(forwardedRequest.headers.has("Authorization")).toBe(false);
    expect(forwardedRequest.headers.get("X-Poker-Proxy-Secret")).toBe(
      "trusted-worker-value",
    );
  });

  it("proxies MCP with bearer auth and a Worker-signed public host", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(JSON.stringify({ jsonrpc: "2.0", result: {} }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        });
      }),
    );

    const response = await worker.fetch(
      new Request("https://faß.example:443/mcp", {
        body: JSON.stringify({ jsonrpc: "2.0", method: "initialize" }),
        headers: {
          Authorization: "Bearer phmcp_test",
          "Content-Type": "application/json",
          "X-Poker-MCP-Public-Host": "spoofed.example",
        },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(200);
    expect(forwardedRequest.url).toBe("https://backend.example/mcp");
    expect(forwardedRequest.headers.get("Authorization")).toBe(
      "Bearer phmcp_test",
    );
    expect(forwardedRequest.headers.get("X-Poker-MCP-Public-Host")).toBe(
      "xn--fa-hia.example",
    );
    expect(forwardedRequest.headers.get("X-Poker-Proxy-Secret")).toBe(
      "trusted-worker-value",
    );
  });

  it("forwards the browser-canonical IPv6 public host", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(null, { status: 200 });
      }),
    );

    const response = await worker.fetch(
      new Request("https://[2001:0db8:0:0:0:0:0:1]/mcp", {
        body: "{}",
        headers: { Authorization: "Bearer phmcp_test" },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(200);
    expect(forwardedRequest.headers.get("X-Poker-MCP-Public-Host")).toBe(
      "[2001:db8::1]",
    );
  });

  it("forwards the browser-canonical legacy IPv4 public host", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(null, { status: 200 });
      }),
    );

    const response = await worker.fetch(
      new Request("https://0177.0.0.1/mcp", {
        body: "{}",
        headers: { Authorization: "Bearer phmcp_test" },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(200);
    expect(forwardedRequest.headers.get("X-Poker-MCP-Public-Host")).toBe(
      "127.0.0.1",
    );
  });

  it("rejects oversized MCP bodies before proxying them", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const oversizedBody = new Uint8Array(4 * 1024 * 1024 + 1);

    const response = await worker.fetch(
      new Request("https://poker.example/mcp", {
        body: oversizedBody,
        headers: { Authorization: "Bearer phmcp_test" },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(413);
    expect(await response.text()).toBe("MCP request body is too large");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not follow MCP redirects outside the MCP route", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(null, {
            headers: { Location: "/api/jobs" },
            status: 307,
          }),
      ),
    );

    const response = await worker.fetch(
      new Request("https://poker-staging.example/mcp", {
        body: "{}",
        headers: { Authorization: "Bearer phmcp_test" },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(502);
  });

  it("replaces an incoming proxy credential with the Worker secret", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(null, { status: 200 });
      }),
    );

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs", {
        headers: { "X-Poker-Proxy-Secret": "spoofed-browser-value" },
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(response.status).toBe(200);
    expect(forwardedRequest.headers.get("X-Poker-Proxy-Secret")).toBe(
      "trusted-worker-value",
    );
    expect(forwardedRequest.redirect).toBe("manual");
  });

  it("strips Access email while preserving the edge client IP", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(null, { status: 200 });
      }),
    );

    await worker.fetch(
      new Request("https://poker.example/api/jobs", {
        headers: {
          "CF-Access-Authenticated-User-Email": "player@example.com",
          "CF-Connecting-IP": "203.0.113.10",
        },
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(
      forwardedRequest.headers.has("CF-Access-Authenticated-User-Email"),
    ).toBe(false);
    expect(forwardedRequest.headers.get("CF-Connecting-IP")).toBe(
      "203.0.113.10",
    );
  });

  it("strips browser-supplied proxy credentials when no Worker secret is configured", async () => {
    let forwardedRequest;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return new Response(null, { status: 200 });
      }),
    );

    await worker.fetch(
      new Request("https://poker.example/api/jobs", {
        headers: { "X-Poker-Proxy-Secret": "spoofed-browser-value" },
      }),
      {
        ASSETS: { fetch: vi.fn() },
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(forwardedRequest.headers.has("X-Poker-Proxy-Secret")).toBe(false);
  });

  it("requires an HTTPS backend before attaching the Worker secret", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "http://backend.example",
      },
    );

    expect(response.status).toBe(500);
    await expect(response.text()).resolves.toContain("must use HTTPS");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("follows same-origin backend redirects without exposing them to the browser", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(null, {
          headers: { Location: "https://backend.example/api/jobs" },
          status: 307,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ jobs: [] }), {
          headers: { "Content-Type": "application/json" },
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs/"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const redirectedRequest = fetchMock.mock.calls[1][0];
    expect(redirectedRequest.url).toBe("https://backend.example/api/jobs");
    expect(redirectedRequest.headers.get("X-Poker-Proxy-Secret")).toBe(
      "trusted-worker-value",
    );
  });

  it("blocks cross-origin backend redirects", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(null, {
          headers: { Location: "https://other.example/collect" },
          status: 302,
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(response.status).toBe(502);
    expect(response.headers.has("location")).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("blocks redirects outside a configured backend base path", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(null, {
          headers: { Location: "/admin" },
          status: 307,
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs"),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example/api",
      },
    );

    expect(response.status).toBe(502);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("applies fetch method rewriting to followed 303 redirects", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(null, {
          headers: { Location: "/api/jobs/result" },
          status: 303,
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://poker.example/api/jobs", {
        body: "upload",
        headers: { "Content-Type": "text/plain" },
        method: "POST",
      }),
      {
        ASSETS: { fetch: vi.fn() },
        API_PROXY_SECRET: "trusted-worker-value",
        BACKEND_URL: "https://backend.example",
      },
    );

    expect(response.status).toBe(204);
    const redirectedRequest = fetchMock.mock.calls[1][0];
    expect(redirectedRequest.method).toBe("GET");
    expect(redirectedRequest.headers.has("content-type")).toBe(false);
    await expect(redirectedRequest.text()).resolves.toBe("");
  });

  it("forwards a multipart screenshot as the file field", async () => {
    let forwardedRequest;
    const backendResponse = new Response(JSON.stringify({ status: "parsed" }), {
      headers: { "Content-Type": "application/json" },
      status: 201,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (request) => {
        forwardedRequest = request;
        return backendResponse;
      }),
    );

    const boundary = "----poker-hero-test-boundary";
    const multipartBody = [
      `--${boundary}`,
      'Content-Disposition: form-data; name="file"; filename="table.png"',
      "Content-Type: image/png",
      "",
      "png-bytes",
      `--${boundary}--`,
      "",
    ].join("\r\n");
    const request = new Request(
      "https://poker.example/api/jobs?source=upload",
      {
        body: multipartBody,
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
        },
        method: "POST",
      },
    );

    const response = await worker.fetch(request, {
      ASSETS: { fetch: vi.fn() },
      BACKEND_URL: "https://backend.example/api",
    });

    expect(response.status).toBe(201);
    expect(forwardedRequest.url).toBe(
      "https://backend.example/api/jobs?source=upload",
    );
    expect(forwardedRequest.headers.get("content-type")).toContain(
      "multipart/form-data; boundary=",
    );

    const forwardedBody = await forwardedRequest.text();
    expect(forwardedBody).toContain('name="file"; filename="table.png"');
    expect(forwardedBody).toContain("Content-Type: image/png");
    expect(forwardedBody).toContain("png-bytes");
    expect(forwardedBody).toContain(`--${boundary}--`);
  });
});
