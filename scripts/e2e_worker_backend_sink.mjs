#!/usr/bin/env node
import { createServer } from "node:http";

const host = "127.0.0.1";
const port = 8788;
const recordedRequests = [];

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(body),
    "Content-Type": "application/json",
  });
  response.end(body);
}

const server = createServer((request, response) => {
  if (request.method === "GET" && request.url === "/__recording") {
    sendJson(response, 200, { requests: recordedRequests });
    return;
  }

  const chunks = [];
  request.on("data", (chunk) => chunks.push(chunk));
  request.on("end", () => {
    recordedRequests.push({
      body: Buffer.concat(chunks).toString("utf8"),
      method: request.method,
      url: request.url,
    });
    sendJson(response, 502, { detail: "Unexpected hosted backend request" });
  });
});

server.listen(port, host);
