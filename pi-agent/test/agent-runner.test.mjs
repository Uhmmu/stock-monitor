import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import {
  wrapBackendTool,
  formatToolResult,
  buildUserPrompt,
  BackendGateway,
} from "../agent-runner.mjs";

function startBackend(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

test("formatToolResult renders error envelopes as model-readable text", () => {
  const text = formatToolResult({ error: { code: "HTTP_402", message: "budget exceeded" } });
  assert.match(text, /Tool error \(HTTP_402\): budget exceeded/);
});

test("formatToolResult renders summary + data + sources", () => {
  const text = formatToolResult({
    summary: "Found 3 sources.",
    data: { results: [1, 2, 3] },
    sources: [{ url: "https://example.com" }],
    warnings: [],
  });
  assert.match(text, /Summary: Found 3 sources\./);
  assert.match(text, /Data: /);
  assert.match(text, /Sources: /);
});

test("wrapBackendTool enforces the deep research budget", async () => {
  const calls = [];
  const gateway = {
    async executeTool(name, args) {
      calls.push(name);
      return { summary: "ok" };
    },
  };
  const tool = wrapBackendTool(
    { function: { name: "run_deep_web_research", description: "deep" } },
    gateway,
    { max_web_search_calls: 5 },
    { webSearches: 0, deepResearch: 0 },
  );
  const first = await tool.execute("t1", { query: "a" });
  assert.match(first.content[0].text, /ok/);
  const second = await tool.execute("t2", { query: "b" });
  assert.match(second.content[0].text, /Deep research budget exhausted/);
  assert.equal(calls.length, 1);
});

test("wrapBackendTool enforces the web search budget", async () => {
  const calls = [];
  const gateway = {
    async executeTool(name) {
      calls.push(name);
      return { summary: "ok" };
    },
  };
  const counters = { webSearches: 0, deepResearch: 0 };
  const tool = wrapBackendTool(
    { function: { name: "search_web", description: "search" } },
    gateway,
    { max_web_search_calls: 1 },
    counters,
  );
  await tool.execute("t1", { query: "a" });
  const blocked = await tool.execute("t2", { query: "b" });
  assert.match(blocked.content[0].text, /Web search budget exhausted/);
  assert.equal(calls.length, 1);
  assert.equal(counters.webSearches, 1);
});

test("buildUserPrompt embeds context and budgets", () => {
  const prompt = buildUserPrompt({ context: { base_currency: "USD" } }, { max_turns: 40, max_web_search_calls: 15, deep_effort: "medium" });
  assert.match(prompt, /PORTFOLIO_CONTEXT/);
  assert.match(prompt, /base_currency/);
  assert.match(prompt, /max 15 web searches/);
  assert.match(prompt, /submit_discovery_result/);
});

test("BackendGateway.executeTool posts run-scoped payloads and reports progress best-effort", async () => {
  const seen = { tools: [], progress: [] };
  const { server, port } = await startBackend((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const parsed = body ? JSON.parse(body) : {};
      if (req.url === "/api/agent/v1/execute") {
        seen.tools.push({ auth: req.headers["x-agent-token"], ...parsed });
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "success", summary: "ok", data: {} }));
        return;
      }
      if (req.url === "/api/agent/v1/progress") {
        seen.progress.push(parsed);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end('{"ok":true}');
        return;
      }
      res.writeHead(404);
      res.end("{}");
    });
  });
  try {
    const gateway = new BackendGateway({ baseUrl: `http://127.0.0.1:${port}`, token: "secret", runId: 7, userId: 3 });
    const result = await gateway.executeTool("get_portfolio_summary", {});
    assert.equal(result.summary, "ok");
    assert.equal(seen.tools[0].run_id, 7);
    assert.equal(seen.tools[0].user_id, 3);
    assert.equal(seen.tools[0].tool, "get_portfolio_summary");
    assert.equal(seen.tools[0].auth, "secret");
    await gateway.reportProgress({ event_type: "candidate_discovered", detail: "ANET" });
    assert.equal(seen.progress.length, 1);
    assert.equal(seen.progress[0].event_type, "candidate_discovered");
  } finally {
    server.close();
  }
});

test("BackendGateway.executeTool surfaces HTTP errors without throwing", async () => {
  const { server, port } = await startBackend((req, res) => {
    res.writeHead(402, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: "budget exceeded" }));
  });
  try {
    const gateway = new BackendGateway({ baseUrl: `http://127.0.0.1:${port}`, token: "secret", runId: 1, userId: 1 });
    const result = await gateway.executeTool("search_web", {});
    assert.equal(result.error.code, "HTTP_402");
    assert.match(result.error.message, /budget exceeded/);
  } finally {
    server.close();
  }
});
