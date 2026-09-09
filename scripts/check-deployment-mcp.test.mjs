import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import test from "node:test";

import { checkMcpDeployment } from "./check-mcp-deployment.mjs";

const MCP_TOKEN = `phmcp_ABCDEFGHIJKL.${"a".repeat(43)}`;

async function withServer(handler, exercise) {
  const server = createServer((request, response) => {
    Promise.resolve(handler(request, response)).catch(() => {
      response.writeHead(500).end();
    });
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");
  try {
    await exercise(`http://127.0.0.1:${address.port}`);
  } finally {
    server.close();
    await once(server, "close");
  }
}

async function readJsonRequest(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function respondToBaseCheck(request, response, mcpConfig) {
  if (request.url === "/") {
    response
      .writeHead(200)
      .end('<meta name="application-name" content="Poker Hero">');
    return true;
  }
  if (request.url === "/api/mcp/principals") {
    response.writeHead(401).end();
    return true;
  }
  if (request.url === "/api/health") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ status: "ok" }));
    return true;
  }
  if (request.url === "/api/mcp/config") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify(mcpConfig));
    return true;
  }
  if (request.url === "/api/jobs?limit=1") {
    response.writeHead(404).end();
    return true;
  }
  return false;
}

test("initializes MCP and calls the bound environment with an agent token", async () => {
  const authenticatedMethods = [];
  let mcpUrl = "";
  await withServer(
    async (request, response) => {
      assert.equal(request.headers["cf-access-client-id"], "client-id");
      assert.equal(request.headers["cf-access-client-secret"], "client-secret");
      if (
        respondToBaseCheck(request, response, {
          enabled: true,
          endpoint: mcpUrl,
          environment: "staging",
        })
      ) {
        return;
      }
      assert.equal(request.url, "/mcp");
      if (!request.headers.authorization) {
        response.writeHead(401).end();
        return;
      }
      assert.equal(request.headers.authorization, `Bearer ${MCP_TOKEN}`);
      const payload = await readJsonRequest(request);
      authenticatedMethods.push(payload.method);
      if (payload.method === "initialize") {
        response.writeHead(200, { "Content-Type": "text/event-stream" });
        response.end(
          `event: message\ndata: ${JSON.stringify({
            jsonrpc: "2.0",
            id: payload.id,
            result: {
              protocolVersion: "2025-06-18",
              capabilities: {},
              serverInfo: { name: "Poker Hero staging", version: "1.0" },
            },
          })}\n\n`,
        );
        return;
      }
      assert.equal(payload.method, "tools/call");
      assert.equal(payload.params.name, "get_environment_status");
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          jsonrpc: "2.0",
          id: payload.id,
          result: {
            content: [{ type: "text", text: "staging" }],
            isError: false,
            structuredContent: { environment: "staging" },
          },
        }),
      );
    },
    async (baseUrl) => {
      mcpUrl = `${baseUrl}/mcp`;
      const result = await checkMcpDeployment(mcpUrl, "staging", {
        accessClientId: "client-id",
        accessClientSecret: "client-secret",
        allowHttp: true,
        attempts: 1,
        configUrl: `${baseUrl}/api/mcp/config`,
        token: MCP_TOKEN,
        timeoutMs: 1_000,
      });
      assert.equal(result.environment, "staging");
    },
  );
  assert.deepEqual(authenticatedMethods, ["initialize", "tools/call"]);
});

test("honors Retry-After without repeating MCP initialization", async () => {
  const authenticatedMethods = [];
  const waits = [];
  let environmentChecks = 0;
  let mcpUrl = "";
  await withServer(
    async (request, response) => {
      if (
        respondToBaseCheck(request, response, {
          enabled: true,
          endpoint: mcpUrl,
          environment: "staging",
        })
      ) {
        return;
      }
      const payload = await readJsonRequest(request);
      authenticatedMethods.push(payload.method);
      if (payload.method === "initialize") {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(
          JSON.stringify({
            jsonrpc: "2.0",
            id: payload.id,
            result: { serverInfo: { name: "Poker Hero staging" } },
          }),
        );
        return;
      }
      environmentChecks += 1;
      if (environmentChecks === 1) {
        response.writeHead(429, { "Retry-After": "61" }).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          jsonrpc: "2.0",
          id: payload.id,
          result: {
            isError: false,
            structuredContent: { environment: "staging" },
          },
        }),
      );
    },
    async (baseUrl) => {
      mcpUrl = `${baseUrl}/mcp`;
      const result = await checkMcpDeployment(mcpUrl, "staging", {
        allowHttp: true,
        attempts: 1,
        configUrl: `${baseUrl}/api/mcp/config`,
        token: MCP_TOKEN,
        timeoutMs: 1_000,
        wait: async (milliseconds) => {
          waits.push(milliseconds);
        },
      });
      assert.equal(result.environment, "staging");
    },
  );
  assert.deepEqual(authenticatedMethods, [
    "initialize",
    "tools/call",
    "tools/call",
  ]);
  assert.deepEqual(waits, [61_000]);
});

test("honors Retry-After when an outer retry rate-limits initialization", async () => {
  const authenticatedMethods = [];
  const waits = [];
  let initializationRequests = 0;
  let environmentChecks = 0;
  let mcpUrl = "";
  await withServer(
    async (request, response) => {
      if (
        respondToBaseCheck(request, response, {
          enabled: true,
          endpoint: mcpUrl,
          environment: "staging",
        })
      ) {
        return;
      }
      const payload = await readJsonRequest(request);
      authenticatedMethods.push(payload.method);
      if (payload.method === "initialize") {
        initializationRequests += 1;
        if (initializationRequests === 2) {
          response.writeHead(429, { "Retry-After": "56" }).end();
          return;
        }
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(
          JSON.stringify({
            jsonrpc: "2.0",
            id: payload.id,
            result: { serverInfo: { name: "Poker Hero staging" } },
          }),
        );
        return;
      }
      environmentChecks += 1;
      if (environmentChecks === 1) {
        response.writeHead(503).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          jsonrpc: "2.0",
          id: payload.id,
          result: {
            isError: false,
            structuredContent: { environment: "staging" },
          },
        }),
      );
    },
    async (baseUrl) => {
      mcpUrl = `${baseUrl}/mcp`;
      const result = await checkMcpDeployment(mcpUrl, "staging", {
        allowHttp: true,
        attempts: 2,
        configUrl: `${baseUrl}/api/mcp/config`,
        retryDelayMs: 0,
        token: MCP_TOKEN,
        timeoutMs: 1_000,
        wait: async (milliseconds) => {
          waits.push(milliseconds);
        },
      });
      assert.equal(result.attempts, 2);
    },
  );
  assert.deepEqual(authenticatedMethods, [
    "initialize",
    "tools/call",
    "initialize",
    "initialize",
    "tools/call",
  ]);
  assert.deepEqual(waits, [56_000]);
});

test("requires a Poker Hero agent token", async () => {
  await assert.rejects(
    checkMcpDeployment("https://poker.example.com/mcp", "staging", {
      attempts: 1,
      configUrl: "https://poker.example.com/api/mcp/config",
      token: "admin-token",
    }),
    /MCP smoke token is not a Poker Hero agent credential/,
  );
});

test("requires both Cloudflare Access service-token values", async () => {
  await assert.rejects(
    checkMcpDeployment("https://poker.example.com/mcp", "staging", {
      accessClientId: "client-id",
      attempts: 1,
      configUrl: "https://poker.example.com/api/mcp/config",
      token: MCP_TOKEN,
    }),
    /Cloudflare Access client ID and secret must be configured together/,
  );
});

test("does not send an agent token when the deployment reports another URL", async () => {
  let receivedAuthorization = false;
  await withServer(
    (request, response) => {
      if (
        respondToBaseCheck(request, response, {
          enabled: true,
          endpoint: "https://unexpected.example/mcp",
          environment: "staging",
        })
      ) {
        return;
      }
      assert.equal(request.url, "/mcp");
      receivedAuthorization ||= Boolean(request.headers.authorization);
      response.writeHead(401).end();
    },
    async (baseUrl) => {
      await assert.rejects(
        checkMcpDeployment(`${baseUrl}/mcp`, "staging", {
          allowHttp: true,
          attempts: 1,
          configUrl: `${baseUrl}/api/mcp/config`,
          token: MCP_TOKEN,
          timeoutMs: 1_000,
        }),
        /MCP configuration did not report the expected enabled endpoint and environment/,
      );
    },
  );
  assert.equal(receivedAuthorization, false);
});
