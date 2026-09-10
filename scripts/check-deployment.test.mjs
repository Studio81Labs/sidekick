import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { once } from "node:events";
import test from "node:test";

import { checkDeployment } from "./check-deployment.mjs";

const VALID_PWA_DOCUMENT =
  '<meta name="application-name" content="Poker Hero">';

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

test("checks the committed app shell, retired route, and MCP security boundaries", async () => {
  const committedPwaDocument = await readFile(
    new URL("../apps/pwa/index.html", import.meta.url),
    "utf8",
  );
  const requestedPaths = [];
  await withServer(
    (request, response) => {
      requestedPaths.push(request.url);
      assert.equal(request.headers["cf-access-client-id"], "client-id");
      assert.equal(request.headers["cf-access-client-secret"], "client-secret");
      if (request.url === "/") {
        response.writeHead(302, { Location: "/app" }).end();
        return;
      }
      if (request.url === "/app") {
        response.writeHead(200, { "Content-Type": "text/html" });
        response.end(committedPwaDocument);
        return;
      }
      if (request.url === "/api/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/admin/ocr/jobs?limit=1") {
        response.writeHead(401).end();
        return;
      }
      if (request.url === "/api/mcp/principals" || request.url === "/mcp") {
        response.writeHead(401, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ detail: "Authentication required" }));
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        request.url === "/api/health"
          ? JSON.stringify({ status: "ok" })
          : request.url === "/api/mcp/config"
            ? JSON.stringify({ enabled: true })
            : JSON.stringify({ jobs: [], total: 0 }),
      );
    },
    async (baseUrl) => {
      const result = await checkDeployment(baseUrl, {
        accessClientId: "client-id",
        accessClientSecret: "client-secret",
        allowHttp: true,
        attempts: 1,
        timeoutMs: 1_000,
      });
      assert.equal(result.attempts, 1);
      assert.equal(result.url, baseUrl);
    },
  );
  assert.deepEqual(requestedPaths, [
    "/",
    "/app",
    "/api/health",
    "/api/jobs?limit=1",
    "/api/admin/ocr/jobs?limit=1",
    "/api/mcp/config",
    "/api/mcp/principals",
    "/mcp",
  ]);
});

test("rejects branding text without the stable application metadata", async () => {
  await withServer(
    (_request, response) => {
      response.writeHead(200).end("<title>Poker Training Analyzer</title>");
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 1,
          timeoutMs: 1_000,
        }),
        /PWA response did not contain the application marker/,
      );
    },
  );
});

test("rejects a publicly exposed MCP administration route", async () => {
  await withServer(
    (request, response) => {
      if (request.url === "/") {
        response.writeHead(200).end(VALID_PWA_DOCUMENT);
        return;
      }
      if (request.url === "/api/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/admin/ocr/jobs?limit=1") {
        response.writeHead(401).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        request.url === "/api/health"
          ? JSON.stringify({ status: "ok" })
          : request.url === "/api/mcp/config"
            ? JSON.stringify({ enabled: true })
            : JSON.stringify({ principals: [] }),
      );
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 1,
          timeoutMs: 1_000,
        }),
        /MCP administration boundary returned HTTP 200; expected 401/,
      );
    },
  );
});

test("accepts an absent MCP endpoint when hosted access is disabled", async () => {
  await withServer(
    (request, response) => {
      if (request.url === "/") {
        response.writeHead(200).end(VALID_PWA_DOCUMENT);
        return;
      }
      if (request.url === "/api/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/admin/ocr/jobs?limit=1") {
        response.writeHead(403).end();
        return;
      }
      if (request.url === "/api/mcp/principals") {
        response.writeHead(503).end();
        return;
      }
      if (request.url === "/mcp") {
        response.writeHead(404).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        request.url === "/api/health"
          ? JSON.stringify({ status: "ok" })
          : request.url === "/api/mcp/config"
            ? JSON.stringify({ enabled: false })
            : JSON.stringify({ jobs: [] }),
      );
    },
    async (baseUrl) => {
      await checkDeployment(baseUrl, {
        allowHttp: true,
        attempts: 1,
        timeoutMs: 1_000,
      });
    },
  );
});

test("rejects an absent admin binding when hosted MCP is enabled", async () => {
  await withServer(
    (request, response) => {
      if (request.url === "/") {
        response.writeHead(200).end(VALID_PWA_DOCUMENT);
        return;
      }
      if (request.url === "/api/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/admin/ocr/jobs?limit=1") {
        response.writeHead(401).end();
        return;
      }
      if (request.url === "/api/mcp/principals") {
        response.writeHead(503).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        request.url === "/api/health"
          ? JSON.stringify({ status: "ok" })
          : request.url === "/api/mcp/config"
            ? JSON.stringify({ enabled: true })
            : JSON.stringify({ jobs: [] }),
      );
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 1,
          timeoutMs: 1_000,
        }),
        /MCP administration boundary returned HTTP 503; expected 401/,
      );
    },
  );
});

test("rejects an absent administrator OCR API boundary", async () => {
  await withServer(
    (request, response) => {
      if (request.url === "/") {
        response.writeHead(200).end(VALID_PWA_DOCUMENT);
        return;
      }
      if (request.url === "/api/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/admin/ocr/jobs?limit=1") {
        response.writeHead(404).end();
        return;
      }
      if (request.url === "/api/mcp/principals") {
        response.writeHead(401).end();
        return;
      }
      if (request.url === "/mcp") {
        response.writeHead(401).end();
        return;
      }
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(
        request.url === "/api/health"
          ? JSON.stringify({ status: "ok" })
          : JSON.stringify({ enabled: true }),
      );
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 1,
          timeoutMs: 1_000,
        }),
        /Administrator OCR API boundary returned HTTP 404; expected 401 or 403/,
      );
    },
  );
});

test("retries transient failures and reports only the failed check", async () => {
  let healthRequests = 0;
  await withServer(
    (request, response) => {
      if (request.url === "/") {
        response.writeHead(200).end(VALID_PWA_DOCUMENT);
        return;
      }
      if (request.url === "/api/health") {
        healthRequests += 1;
        response.writeHead(503).end("provider details must stay private");
        return;
      }
      response.writeHead(200).end(JSON.stringify({ jobs: [] }));
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 2,
          retryDelayMs: 0,
          timeoutMs: 1_000,
        }),
        /failed after 2 attempt\(s\): API health returned HTTP 503/,
      );
    },
  );
  assert.equal(healthRequests, 2);
});

test("requires both Cloudflare Access service-token values", async () => {
  await assert.rejects(
    checkDeployment("https://poker.example.com", {
      accessClientId: "client-id",
      attempts: 1,
    }),
    /client ID and secret must be configured together/,
  );
});

test("does not forward Access credentials across redirects", async () => {
  let redirectedRequests = 0;
  await withServer(
    (request, response) => {
      redirectedRequests += 1;
      response.writeHead(200).end(VALID_PWA_DOCUMENT);
    },
    async (redirectTarget) => {
      await withServer(
        (_request, response) => {
          response.writeHead(302, { Location: redirectTarget }).end();
        },
        async (baseUrl) => {
          await assert.rejects(
            checkDeployment(baseUrl, {
              accessClientId: "client-id",
              accessClientSecret: "client-secret",
              allowHttp: true,
              attempts: 1,
              timeoutMs: 1_000,
            }),
            /PWA redirected outside the deployment origin/,
          );
        },
      );
    },
  );
  assert.equal(redirectedRequests, 0);
});

test("rejects oversized deployment responses", async () => {
  await withServer(
    (_request, response) => {
      response.writeHead(200).end("x".repeat(1024 * 1024 + 1));
    },
    async (baseUrl) => {
      await assert.rejects(
        checkDeployment(baseUrl, {
          allowHttp: true,
          attempts: 1,
          timeoutMs: 1_000,
        }),
        /PWA response exceeded 1 MiB/,
      );
    },
  );
});

test("rejects insecure production targets", async () => {
  await assert.rejects(
    checkDeployment("http://poker.example.com", { attempts: 1 }),
    /must use HTTPS/,
  );
});
