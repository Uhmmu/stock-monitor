// Pi Agent sidecar for stock-monitor opportunity discovery.
//
// Contract (internal, compose network only):
//   GET  /health        -> {ok:true}
//   POST /run           -> long-running agent research; returns the final
//                          DiscoveryResult JSON + usage + tool_results.
//
// The sidecar authenticates to the backend agent gateway with the shared
// AGENT_GATEWAY_TOKEN. It never touches the database or user credentials.

import http from "node:http";
import { runAgentResearch } from "./agent-runner.mjs";

const PORT = Number(process.env.PORT || 3001);
const AGENT_TOKEN = (process.env.AGENT_GATEWAY_TOKEN || "").trim();
const BACKEND_BASE_URL = (process.env.BACKEND_BASE_URL || "http://api:8000").replace(/\/$/, "");
const MAX_CONCURRENT_RUNS = Number(process.env.MAX_CONCURRENT_RUNS || 2);
const MAX_BODY_BYTES = 8 * 1024 * 1024;

let activeRuns = 0;

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(body) });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error("request body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function handleRun(req, res) {
  if (!AGENT_TOKEN) return json(res, 503, { error: "AGENT_GATEWAY_TOKEN is not configured" });
  if (activeRuns >= MAX_CONCURRENT_RUNS) {
    return json(res, 429, { error: "sidecar busy", retryable: true });
  }
  let payload;
  try {
    payload = JSON.parse(await readBody(req));
  } catch {
    return json(res, 400, { error: "invalid JSON body" });
  }
  if (payload.agent_token && payload.agent_token !== AGENT_TOKEN) {
    return json(res, 401, { error: "invalid agent token" });
  }
  activeRuns += 1;
  try {
    const result = await runAgentResearch({ request: payload, backendBaseUrl: BACKEND_BASE_URL, agentToken: AGENT_TOKEN });
    json(res, 200, result);
  } catch (error) {
    const retryable = Boolean(error.retryable);
    json(res, 500, {
      status: "failed",
      error: String(error && error.message ? error.message : error),
      retryable,
    });
  } finally {
    activeRuns -= 1;
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return json(res, 200, { ok: true, active_runs: activeRuns, backend: BACKEND_BASE_URL });
  }
  if (req.method === "POST" && req.url === "/run") {
    return handleRun(req, res);
  }
  json(res, 404, { error: "not found" });
});

server.requestTimeout = 0; // long research runs
server.headersTimeout = 60_000;
server.listen(PORT, () => {
  console.log(`[pi-agent] listening on :${PORT}, backend=${BACKEND_BASE_URL}`);
});
