import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import {
  wrapBackendTool,
  formatToolResult,
  buildUserPrompt,
  BackendGateway,
  mapToolProgress,
  ProgressBridge,
  TurnBudget,
  extractToolSymbols,
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

test("mapToolProgress maps tool names to funnel events without exposing content", () => {
  assert.deepEqual(mapToolProgress("run_deep_web_research"), { eventType: "external_search", stats: { deep_searches: 1 } });
  assert.deepEqual(mapToolProgress("search_web"), { eventType: "external_search", stats: { web_searches: 1 } });
  assert.deepEqual(mapToolProgress("get_portfolio_summary"), { eventType: "portfolio_loaded", stats: {} });
  // screening is counted per symbol, not per call (see extractToolSymbols)
  assert.deepEqual(mapToolProgress("get_latest_valuation"), { eventType: "candidate_screened", stats: {} });
  assert.deepEqual(mapToolProgress("get_sec_filings"), { eventType: "evidence_found", stats: {} });
  assert.equal(mapToolProgress("list_research_capabilities"), null);
});

test("extractToolSymbols reads symbol/symbols args and normalizes them", () => {
  assert.deepEqual([...extractToolSymbols({ symbol: " nvda " })], ["NVDA"]);
  assert.deepEqual([...extractToolSymbols({ ticker: "aapl" })], ["AAPL"]);
  assert.deepEqual([...extractToolSymbols({ symbols: ["MU", "mrkd"] })], ["MU", "MRKD"]);
  assert.deepEqual([...extractToolSymbols({ symbol: "ANET", symbols: ["anet", "WM"] })], ["ANET", "WM"]);
  assert.deepEqual([...extractToolSymbols({ query: "no symbols here" })], []);
  assert.deepEqual([...extractToolSymbols(null)], []);
});

test("TurnBudget fires exactly once on the turn_end boundary and can be disabled", () => {
  const budget = new TurnBudget(3);
  assert.equal(budget.note({ type: "message_end" }), false);
  assert.equal(budget.note({ type: "turn_end" }), false); // 1
  assert.equal(budget.note({ type: "turn_end" }), false); // 2
  assert.equal(budget.note({ type: "turn_end" }), true);  // 3 -> exhausted
  assert.equal(budget.note({ type: "turn_end" }), false); // already reached
  assert.equal(budget.turns, 4);
  const disabled = new TurnBudget(0);
  for (let i = 0; i < 5; i += 1) assert.equal(disabled.note({ type: "turn_end" }), false);
  assert.equal(disabled.reached, false);
});

function recordingGateway() {
  const events = [];
  return {
    events,
    reportProgress(event) { events.push(event); },
  };
}

test("ProgressBridge reports portfolio load once and paid searches immediately", () => {
  const gateway = recordingGateway();
  let clock = 1000;
  const bridge = new ProgressBridge(gateway, { now: () => clock });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_portfolio_summary" });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_portfolio_positions" });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "search_web" });
  assert.equal(gateway.events.length, 2); // portfolio once + paid search; second portfolio suppressed
  assert.equal(gateway.events[0].event_type, "portfolio_loaded");
  assert.equal(gateway.events[1].event_type, "external_search");
  assert.equal(gateway.events[1].funnel_stats.web_searches, 1);
});

test("ProgressBridge counts screened candidates per unique symbol, not per call", () => {
  const gateway = recordingGateway();
  let clock = 1000;
  const bridge = new ProgressBridge(gateway, { intervalMs: 4000, now: () => clock });
  // two different tools for the SAME candidate: one screened symbol
  bridge.onAgentEvent({ type: "tool_execution_start", toolName: "get_latest_valuation", args: { symbol: "NVDA" } });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_latest_valuation" });
  bridge.onAgentEvent({ type: "tool_execution_start", toolName: "get_financial_summary", args: { symbol: "nvda" } });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_financial_summary" });
  assert.equal(gateway.events.length, 0); // within interval: only pending
  clock += 4000;
  bridge.onAgentEvent({ type: "tool_execution_start", toolName: "get_mood_overview", args: { symbol: "MU" } });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_mood_overview" });
  assert.equal(gateway.events.length, 1);
  assert.equal(gateway.events[0].event_type, "candidate_screened");
  assert.equal(gateway.events[0].funnel_stats.candidates_screened, 2); // NVDA + MU
  assert.equal(gateway.events[0].funnel_stats.tool_calls, 3);
});

test("ProgressBridge does not count budget-exhausted stubs as real retrieval", () => {
  const gateway = recordingGateway();
  const bridge = new ProgressBridge(gateway);
  bridge.onAgentEvent({
    type: "tool_execution_end", toolName: "search_web",
    result: { details: { budget_exhausted: true } },
  });
  bridge.finalize();
  assert.equal(gateway.events.length, 1); // only finalized
  assert.equal(gateway.events[0].event_type, "finalized");
  assert.equal(gateway.events[0].funnel_stats.tool_calls, 1); // the call still happened
  assert.equal(gateway.events[0].funnel_stats.web_searches, undefined); // but no real search
});

test("ProgressBridge.finalize reports only deltas so the backend never double-counts", () => {
  const gateway = recordingGateway();
  let clock = 1000;
  const bridge = new ProgressBridge(gateway, { now: () => clock });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_portfolio_summary" });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "search_financial_reports_web" });
  bridge.onAgentEvent({ type: "tool_execution_start", toolName: "get_company_snapshot", args: { symbol: "ANET" } });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "get_company_snapshot" });
  bridge.onAgentEvent({ type: "tool_execution_end", toolName: "list_research_capabilities" });
  bridge.finalize();
  const types = gateway.events.map((event) => event.event_type);
  assert.deepEqual(types, ["portfolio_loaded", "external_search", "candidate_screened", "finalized"]);
  // already reported: tool_calls 3, web 1, screened 1 -> finalized tops up tool_calls only
  const finalized = gateway.events.at(-1);
  assert.deepEqual(finalized.funnel_stats, { tool_calls: 1 });
});

test("ProgressBridge ignores non-tool events", () => {
  const gateway = recordingGateway();
  const bridge = new ProgressBridge(gateway);
  bridge.onAgentEvent({ type: "agent_end", messages: [] });
  bridge.finalize();
  assert.equal(gateway.events.length, 1); // only the finalized event
  assert.deepEqual(gateway.events[0].funnel_stats, {});
});

test("BackendGateway threads the tool scope through /tools and /execute", async () => {
  const seen = { toolsUrl: null, executeBody: null };
  const { server, port } = await startBackend((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      if (req.url.startsWith("/api/agent/v1/tools")) {
        seen.toolsUrl = req.url;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ tools: [{ type: "function", function: { name: "get_market_context" } }] }));
        return;
      }
      if (req.url === "/api/agent/v1/execute") {
        seen.executeBody = JSON.parse(body);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "success", summary: "ok" }));
        return;
      }
      res.writeHead(404);
      res.end("{}");
    });
  });
  try {
    const gateway = new BackendGateway({
      baseUrl: `http://127.0.0.1:${port}`, token: "secret", runId: 1, userId: 1,
      scope: "opportunity_research",
    });
    const tools = await gateway.listTools();
    assert.equal(tools.length, 1);
    assert.equal(seen.toolsUrl, "/api/agent/v1/tools?scope=opportunity_research");
    await gateway.executeTool("get_market_context", {});
    assert.equal(seen.executeBody.tool_scope, "opportunity_research");
  } finally {
    server.close();
  }
});
